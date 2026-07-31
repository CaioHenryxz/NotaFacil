"""Envio da DPS assinada para a API do Emissor Nacional (Sefin Nacional).

So HOMOLOGACAO (Producao Restrita) por enquanto — producao fica pra depois
do beta aprovar (espec-mvp-emissor-nfse.md, secao 5, fluxo de emissao).

Endpoint e formato do corpo confirmados no spike (spike/emitir_nota.py,
ja validado estruturalmente contra o XSD oficial — ver spike/README.md pra
o registro completo do que foi confirmado vs. o que so a resposta real da
API confirma).

As duas excecoes abaixo (ErroRede / ErroValidacao) sao o contrato que
core/fila.py usa para decidir "reagenda com backoff" vs. "marca rejeitada" —
espec, secao 5:
    erro de rede/5xx: mantem pendente, agenda retry
    erro de validacao (4xx): status=rejeitada + motivo legivel na tela
"""
from __future__ import annotations

import base64
import gzip
import os
import tempfile
from dataclasses import dataclass
from typing import List, Optional, Tuple

import httpx
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat

URL_HOMOLOGACAO = "https://sefin.producaorestrita.nfse.gov.br/SefinNacional/nfse"
URL_PRODUCAO = "https://sefin.nfse.gov.br/SefinNacional/nfse"

# DANFSe (PDF) — mesma autenticacao mTLS, host do ADN (nao do Sefin). Endpoint
# citado na documentacao tecnica do Emissor Nacional como GET /danfse/{chave}
# mas relatado por integradores terceiros como instavel (502/503) — por isso
# `buscar_danfse` e sempre chamada como best-effort (ver core/fila.py:
# falha aqui NUNCA impede a nota de ser considerada emitida, o XML ja e o
# documento fiscal valido; o PDF e so uma facilidade visual pro tomador).
#
# ATENCAO — PRAZO CRITICO (confirmado em pesquisa jul/2026, nao estava na
# auditoria original): a NT-008/2026 (SE/CGNFS-e, atualizada p/ v1.02 em
# 14/07/2026) determina que ESTA API de geracao do DANFSe (o endpoint
# `/danfse/{chave}` abaixo) sera SUSPENSA — data ja foi adiada 2x (01/07 ->
# 15/07 -> 03/08/2026, a vigente agora). A partir dessa data, a
# responsabilidade de gerar o PDF do DANFSe passa a ser DO PROPRIO SISTEMA
# EMISSOR, seguindo o novo leiaute nacional obrigatorio (A4, pagina unica,
# QR Code de consulta publica, campos de IBS/CBS, marca d'agua em
# cancelamento/substituicao — tudo definido na propria NT-008). Ou seja: a
# partir de 03/08/2026 esta funcao provavelmente vai comecar a falhar (ou
# pior, se a API ficar no ar mas devolver o PDF no leiaute ANTIGO, o
# DANFSe salvo deixa de ser o layout oficial vigente sem que o app perceba).
# Isso NAO foi implementado nesta sessao (gerar DANFSe localmente e' um
# recurso novo, fora do escopo do pedido que motivou este comentario) — mas
# e' preciso decidir antes de 03/08/2026 como o app vai continuar entregando
# o DANFSe oficial depois desse prazo.
URL_DANFSE_HOMOLOGACAO = "https://adn.producaorestrita.nfse.gov.br/danfse"
URL_DANFSE_PRODUCAO = "https://adn.nfse.gov.br/danfse"


class ErroRede(Exception):
    """Falha de rede/timeout ou 5xx da API — a fila deve reagendar (retry)."""


class ErroValidacao(Exception):
    """Rejeicao 4xx da API — a fila deve marcar a nota como 'rejeitada'.
    str(excecao) e o motivo legivel guardado em notas.motivo_rejeicao."""


@dataclass
class RespostaEmissao:
    chave_acesso: str
    xml_nfse: bytes
    pdf_nfse: Optional[bytes] = None  # DANFSe — preenchido best-effort por emitir_nota_real


def _escrever_pem_temporarios(chave, certificado, extras) -> Tuple[str, str]:
    """mTLS via httpx exige arquivos em disco. Gravados em temp e apagados
    logo apos a chamada — o certificado nunca fica persistido fora do .pfx
    original (mesma logica de "certificado nunca sai da maquina", espec §4)."""
    cert_pem = certificado.public_bytes(Encoding.PEM)
    for extra in extras:
        cert_pem += extra.public_bytes(Encoding.PEM)
    key_pem = chave.private_bytes(Encoding.PEM, PrivateFormat.TraditionalOpenSSL, NoEncryption())

    cert_file = tempfile.NamedTemporaryFile(suffix=".pem", delete=False)
    key_file = tempfile.NamedTemporaryFile(suffix=".pem", delete=False)
    try:
        cert_file.write(cert_pem)
        key_file.write(key_pem)
    finally:
        cert_file.close()
        key_file.close()
    return cert_file.name, key_file.name


def _extrair_mensagem_erro(resposta: httpx.Response) -> str:
    try:
        corpo = resposta.json()
    except ValueError:
        # corpo nao-JSON: normalmente um erro de infraestrutura (pagina de
        # erro do IIS/proxy num 401/403, por exemplo), nunca algo pra mostrar
        # cru pro usuario — vira so o status HTTP, que core.mensagens traduz.
        texto = (resposta.text or "").strip()
        if not texto or "<" in texto[:20] or len(texto) > 200:
            return f"HTTP {resposta.status_code}"
        return texto
    if isinstance(corpo, list):
        return "; ".join(f"{e.get('Codigo', '?')}: {e.get('Descricao', '')}" for e in corpo)
    if isinstance(corpo, dict):
        return f"{corpo.get('Codigo', '?')}: {corpo.get('Descricao', corpo)}"
    return str(corpo)


def enviar_dps(
    xml_assinado: bytes,
    chave_privada,
    certificado,
    certificados_extras: Optional[List] = None,
    *,
    ambiente: str = "homologacao",
    timeout: float = 60.0,
) -> RespostaEmissao:
    """POST da DPS assinada (gzip+base64) via mTLS. Levanta ErroRede (5xx/timeout)
    ou ErroValidacao (4xx) — nunca retorna em caso de erro, sempre uma excecao
    tipada pra quem chama (core/fila.py) decidir o que fazer."""
    url = URL_HOMOLOGACAO if ambiente == "homologacao" else URL_PRODUCAO
    corpo_b64 = base64.b64encode(gzip.compress(xml_assinado)).decode("ascii")

    cert_file, key_file = _escrever_pem_temporarios(chave_privada, certificado, certificados_extras or [])
    try:
        try:
            with httpx.Client(cert=(cert_file, key_file), timeout=timeout) as client:
                resposta = client.post(url, json={"dpsXmlGZipB64": corpo_b64})
        except httpx.TransportError as exc:
            raise ErroRede(str(exc)) from exc
    finally:
        os.unlink(cert_file)
        os.unlink(key_file)

    if resposta.status_code >= 500:
        raise ErroRede(f"HTTP {resposta.status_code}: {resposta.text}")
    if resposta.status_code >= 400:
        raise ErroValidacao(_extrair_mensagem_erro(resposta))

    payload = resposta.json()
    xml_nfse = b""
    if payload.get("nfseXmlGZipB64"):
        xml_nfse = gzip.decompress(base64.b64decode(payload["nfseXmlGZipB64"]))
    return RespostaEmissao(chave_acesso=payload.get("chaveAcesso", ""), xml_nfse=xml_nfse)


@dataclass
class RespostaCancelamento:
    protocolo: str      # infEvento/id, gerado pelo governo — comprovante do cancelamento
    confirmado_em: str  # infEvento/dhProc, gerado pelo governo


def cancelar_nfse(
    chave_nfse: str,
    xml_evento_assinado: bytes,
    chave_privada,
    certificado,
    certificados_extras: Optional[List] = None,
    *,
    ambiente: str = "homologacao",
    timeout: float = 30.0,
) -> RespostaCancelamento:
    """POST do evento de cancelamento (e101101, ja assinado por
    app.fiscal.evento_builder) via mTLS — mesma autenticacao usada em
    enviar_dps. Levanta ErroRede (5xx/timeout, quem chama deve reagendar
    retry) ou ErroValidacao (4xx — inclui prazo de cancelamento expirado
    E0822 e nota que ja tem cancelamento vinculado E0840/E0845, ambos
    traduzidos em app.core.mensagens pra mensagem clara pro usuario).

    ATENCAO (docs/auditoria.md, Bloco 4.4 + pesquisa desta sessao): o nome do
    campo JSON que envelopa o XML gzip+base64 do evento nao foi confirmado
    contra a Swagger oficial (bloqueada por exigir mTLS pra abrir) — segue a
    MESMA convencao ja confirmada em `enviar_dps` (campo "<tipo>XmlGZipB64").
    Se a API rejeitar por nao reconhecer o corpo da requisicao, esse e' o
    primeiro lugar a conferir contra a Swagger real."""
    url_base = URL_HOMOLOGACAO if ambiente == "homologacao" else URL_PRODUCAO
    url = f"{url_base}/{chave_nfse}/eventos"
    corpo_b64 = base64.b64encode(gzip.compress(xml_evento_assinado)).decode("ascii")

    cert_file, key_file = _escrever_pem_temporarios(chave_privada, certificado, certificados_extras or [])
    try:
        try:
            with httpx.Client(cert=(cert_file, key_file), timeout=timeout) as client:
                resposta = client.post(url, json={"pedidoRegistroEventoXmlGZipB64": corpo_b64})
        except httpx.TransportError as exc:
            raise ErroRede(str(exc)) from exc
    finally:
        os.unlink(cert_file)
        os.unlink(key_file)

    if resposta.status_code >= 500:
        raise ErroRede(f"HTTP {resposta.status_code}: {resposta.text}")
    if resposta.status_code >= 400:
        raise ErroValidacao(_extrair_mensagem_erro(resposta))

    payload = resposta.json()
    return RespostaCancelamento(
        protocolo=payload.get("id", ""),
        confirmado_em=payload.get("dhProc", ""),
    )


@dataclass
class RespostaConsultaDps:
    encontrada: bool
    chave_acesso: Optional[str] = None
    xml_nfse: Optional[bytes] = None


def consultar_dps(
    id_dps: str, chave_privada, certificado, certificados_extras: Optional[List] = None,
    *, ambiente: str = "homologacao", timeout: float = 30.0,
) -> RespostaConsultaDps:
    """RECONCILIACAO (docs/auditoria.md, Bloco 6.1 — achado critico): "internet
    cai no meio do envio... reenviar a MESMA DPS de novo sem checar antes se
    ela ja foi aceita" arrisca duplicidade. Esta funcao existe pra responder
    UMA pergunta antes de qualquer reenvio: "essa DPS ja foi processada pelo
    governo?" — usando o Id DETERMINISTICO da propria DPS
    (`dps_builder.montar_id_dps`, calculado so' com dados que o app ja tem:
    municipio + CNPJ/CPF do prestador + serie + numero — nunca depende de
    ter recebido resposta do envio original, que e' exatamente o que se
    perde numa queda de rede).

    ATENCAO (fonte secundaria — nao a Swagger oficial confirmada por mTLS,
    que nao foi possivel abrir nesta pesquisa; mesmo tipo de ressalva ja
    registrada em `cancelar_nfse` acima): o caminho usado abaixo
    (`GET {base}/dps/{idDps}`) e' descrito por integradores terceiros como
    "consulta por Id da DPS, pra idempotencia em caso de timeout" —
    CONFIRMAR contra a resposta real da API antes do primeiro uso em
    producao. A consequencia de o caminho estar errado e' sempre segura:
    vira ErroRede (tratado como "ainda nao sei, tenta de novo depois"),
    NUNCA finge encontrar uma nota que nao existe.
    """
    url_base = URL_HOMOLOGACAO if ambiente == "homologacao" else URL_PRODUCAO
    url = f"{url_base}/dps/{id_dps}"
    cert_file, key_file = _escrever_pem_temporarios(chave_privada, certificado, certificados_extras or [])
    try:
        try:
            with httpx.Client(cert=(cert_file, key_file), timeout=timeout) as client:
                resposta = client.get(url)
        except httpx.TransportError as exc:
            raise ErroRede(str(exc)) from exc
    finally:
        os.unlink(cert_file)
        os.unlink(key_file)

    if resposta.status_code == 404:
        return RespostaConsultaDps(encontrada=False)
    if resposta.status_code >= 500:
        raise ErroRede(f"HTTP {resposta.status_code}: {resposta.text}")
    if resposta.status_code >= 400:
        # Erro diferente de "nao encontrada" -- estado real incerto, nunca
        # decide sozinho que e' seguro reenviar. Trata como rede (retry).
        raise ErroRede(f"HTTP {resposta.status_code} ao consultar DPS: {resposta.text}")

    payload = resposta.json()
    xml_nfse = None
    if payload.get("nfseXmlGZipB64"):
        xml_nfse = gzip.decompress(base64.b64decode(payload["nfseXmlGZipB64"]))
    return RespostaConsultaDps(encontrada=True, chave_acesso=payload.get("chaveAcesso", ""), xml_nfse=xml_nfse)


def buscar_danfse(
    chave_acesso: str, chave_privada, certificado, certificados_extras: Optional[List] = None,
    *, ambiente: str = "homologacao", timeout: float = 30.0,
) -> bytes:
    """Busca o PDF (DANFSe) pela chave de acesso da NFS-e ja gerada. Levanta
    ErroRede em qualquer falha (rede, TLS, HTTP != 200) — quem chama deve
    tratar isso como nao-fatal (ver docstring da URL_DANFSE_* acima)."""
    url_base = URL_DANFSE_HOMOLOGACAO if ambiente == "homologacao" else URL_DANFSE_PRODUCAO
    url = f"{url_base}/{chave_acesso}"
    cert_file, key_file = _escrever_pem_temporarios(chave_privada, certificado, certificados_extras or [])
    try:
        try:
            with httpx.Client(cert=(cert_file, key_file), timeout=timeout) as client:
                resposta = client.get(url)
        except httpx.TransportError as exc:
            raise ErroRede(str(exc)) from exc
    finally:
        os.unlink(cert_file)
        os.unlink(key_file)

    if resposta.status_code != 200:
        raise ErroRede(f"DANFSe indisponivel (HTTP {resposta.status_code})")
    return resposta.content


def testar_conexao(
    chave_privada, certificado, certificados_extras: Optional[List] = None,
    *, ambiente: str = "homologacao", timeout: float = 20.0,
) -> None:
    """Testa se o certificado e aceito pela Sefin Nacional (handshake mTLS),
    sem emitir nada. Usado pelo botao "Testar conexao" do cadastro de
    prestador (core/onboarding.py).

    Faz uma consulta GET por uma chave de acesso inexistente: qualquer
    resposta HTTP (mesmo 404/erro de negocio) prova que o certificado foi
    aceito na camada TLS — so uma falha de rede/TLS deve contar como "nao
    conectou". Nao valida se o CNPJ do certificado esta credenciado no
    municipio; isso so a primeira emissao real confirma."""
    url = (URL_HOMOLOGACAO if ambiente == "homologacao" else URL_PRODUCAO)
    url += "/00000000000000000000000000000000000000000000000000"
    cert_file, key_file = _escrever_pem_temporarios(chave_privada, certificado, certificados_extras or [])
    try:
        try:
            with httpx.Client(cert=(cert_file, key_file), timeout=timeout) as client:
                client.get(url)
        except httpx.TransportError as exc:
            raise ErroRede(str(exc)) from exc
    finally:
        os.unlink(cert_file)
        os.unlink(key_file)
