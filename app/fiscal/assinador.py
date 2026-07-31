"""Carregamento do certificado A1 e assinatura da DPS.

A senha do certificado NUNCA e gravada em arquivo nem no banco — fica so no
keyring do Windows (DPAPI por baixo), uma entrada por prestador. Ver
espec-mvp-emissor-nfse.md, secao 4: "Certificado A1 nunca sai da maquina...
Nosso servidor nunca ve certificado nem senha."

O .pfx em si (o arquivo) fica no caminho gravado em prestadores.caminho_pfx
(repo.py) — so a senha e sensivel o bastante pra exigir o keyring.
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

import keyring
import keyring.errors
from cryptography import x509
from cryptography.hazmat.primitives.serialization import pkcs12

from app.fiscal import dps_builder as db

SERVICO_KEYRING = "emissor-nfse"

# OIDs do padrao ICP-Brasil (DOC-ICP-04/05) que carregam o CPF/CNPJ do titular
# dentro do Subject do certificado — mais confiavel que tentar ler do CN.
_OID_CPF_ICP_BRASIL = "2.16.76.1.3.1"
_OID_CNPJ_ICP_BRASIL = "2.16.76.1.3.3"


class CertificadoNaoConfigurado(Exception):
    """Sem senha no keyring para o prestador — precisa rodar salvar_senha() antes."""


class CertificadoExpirado(Exception):
    """Certificado A1 com validade ja vencida — detectado localmente ANTES
    de assinar/enviar qualquer coisa (docs/auditoria.md, Bloco 6.2/8.8):
    certificado vencido nao e' erro de rede nem de senha errada, e a
    biblioteca de PKCS12 nao valida isso sozinha (carrega um certificado
    vencido normalmente) -- sem essa checagem explicita, o usuario so
    descobriria via uma rejeicao imprevisivel (e possivelmente tecnica) da
    Receita ou de um handshake TLS."""


def _usuario_keyring(prestador_id: int) -> str:
    return f"prestador:{prestador_id}"


def salvar_senha(prestador_id: int, senha: str) -> None:
    keyring.set_password(SERVICO_KEYRING, _usuario_keyring(prestador_id), senha)


def obter_senha(prestador_id: int) -> Optional[str]:
    return keyring.get_password(SERVICO_KEYRING, _usuario_keyring(prestador_id))


def remover_senha(prestador_id: int) -> None:
    try:
        keyring.delete_password(SERVICO_KEYRING, _usuario_keyring(prestador_id))
    except keyring.errors.PasswordDeleteError:
        pass


def carregar_pfx_com_senha(caminho_pfx: str, senha: str) -> Tuple[object, object, List[object]]:
    """Abre o .pfx com a senha informada diretamente (sem keyring) — usado no
    cadastro do prestador, ANTES de existir um prestador_id pra guardar a
    senha. Depois de criar o prestador, a tela de cadastro deve chamar
    `salvar_senha(prestador_id, senha)` pra persistir no keyring."""
    with open(caminho_pfx, "rb") as f:
        pfx_bytes = f.read()
    chave, certificado, extras = pkcs12.load_key_and_certificates(pfx_bytes, senha.encode("utf-8"))
    if chave is None or certificado is None:
        raise ValueError(
            "Nao foi possivel extrair chave/certificado do .pfx — confira o arquivo e a senha."
        )
    return chave, certificado, list(extras or [])


def carregar_certificado(prestador_id: int, caminho_pfx: str) -> Tuple[object, object, List[object]]:
    """Le a senha do keyring, abre o .pfx e retorna (chave_privada, certificado, extras).
    Bloqueia ANTES de assinar/enviar se o certificado ja estiver vencido —
    ver `CertificadoExpirado`."""
    senha = obter_senha(prestador_id)
    if senha is None:
        raise CertificadoNaoConfigurado(
            f"Sem senha no keyring para o prestador {prestador_id}. "
            "Rode assinador.salvar_senha(prestador_id, senha) no cadastro do prestador."
        )
    chave, certificado, extras = carregar_pfx_com_senha(caminho_pfx, senha)
    validade = (
        certificado.not_valid_after_utc.date()
        if hasattr(certificado, "not_valid_after_utc") else certificado.not_valid_after.date()
    )
    if validade < dt.date.today():
        raise CertificadoExpirado(
            f"Este certificado venceu em {validade.strftime('%d/%m/%Y')}. "
            "Renove o certificado A1 (ou importe um novo) antes de emitir."
        )
    return chave, certificado, extras


@dataclass
class InfoCertificado:
    documento: Optional[str]      # CNPJ (14) ou CPF (11) extraido do certificado, so digitos
    tipo_documento: Optional[str]  # "CNPJ", "CPF" ou None se nao foi possivel identificar
    nome_titular: str              # Subject Common Name, como veio no certificado
    valido_ate: dt.date


def _somente_digitos(texto: str) -> str:
    return re.sub(r"\D", "", texto)


def _extrair_documento_por_oid(certificado: x509.Certificate) -> Tuple[Optional[str], Optional[str]]:
    for oid_str, tipo in ((_OID_CNPJ_ICP_BRASIL, "CNPJ"), (_OID_CPF_ICP_BRASIL, "CPF")):
        for atributo in certificado.subject:
            if atributo.oid.dotted_string == oid_str:
                digitos = _somente_digitos(str(atributo.value))
                tamanho_esperado = 14 if tipo == "CNPJ" else 11
                if len(digitos) >= tamanho_esperado:
                    return digitos[:tamanho_esperado], tipo
    return None, None


def _extrair_documento_do_cn(cn: str) -> Tuple[Optional[str], Optional[str]]:
    """Convencao comum em certificados e-CNPJ/e-CPF: CN = 'NOME:DOCUMENTO'.
    Usado como fallback quando o certificado nao tem os OIDs ICP-Brasil
    (ex.: certificados de teste autoassinados, como o do demo.py)."""
    partes = cn.rsplit(":", 1)
    candidato = _somente_digitos(partes[-1]) if len(partes) == 2 else ""
    if len(candidato) == 14:
        return candidato, "CNPJ"
    if len(candidato) == 11:
        return candidato, "CPF"
    return None, None


def inspecionar_certificado(certificado: x509.Certificate) -> InfoCertificado:
    """Extrai do certificado o que o cadastro de prestador precisa pra
    pre-preencher a tela: documento (CNPJ/CPF), nome do titular e validade.
    Nunca levanta excecao por nao achar o documento — a tela sempre permite
    digitar/corrigir manualmente (ver core/onboarding.py)."""
    cn_attrs = certificado.subject.get_attributes_for_oid(x509.oid.NameOID.COMMON_NAME)
    nome_titular = str(cn_attrs[0].value) if cn_attrs else ""

    documento, tipo = _extrair_documento_por_oid(certificado)
    if documento is None:
        documento, tipo = _extrair_documento_do_cn(nome_titular)

    valido_ate = certificado.not_valid_after_utc.date() if hasattr(certificado, "not_valid_after_utc") else certificado.not_valid_after.date()

    return InfoCertificado(
        documento=documento, tipo_documento=tipo, nome_titular=nome_titular, valido_ate=valido_ate
    )


def assinar(dados: db.DadosDPS, chave_privada, certificado, certificados_extras: Optional[list] = None) -> bytes:
    """Monta a DPS e assina. Retorna o XML assinado (bytes), pronto pra
    enviar via app.fiscal.api_nacional.enviar_dps."""
    return db.montar_e_assinar(dados, chave_privada, certificado, certificados_extras)
