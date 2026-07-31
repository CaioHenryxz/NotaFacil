"""Montagem e assinatura do evento de CANCELAMENTO de NFS-e (Sistema Nacional
NFS-e, leiaute de Eventos — ANEXO_II, tipo de evento e101101).

Documento SEPARADO da DPS (dps_builder.py, Anexo I) — isolado aqui pelo mesmo
motivo (espec-mvp-emissor-nfse.md, secao 8, risco 2): uma mudanca no leiaute
de eventos custa editar so' este arquivo.

Contexto (docs/auditoria.md, Bloco 4.4): antes deste modulo existir, o botao
"Cancelar" so movia o arquivo local pra Canceladas/ e mudava o status no
banco — nunca avisava o governo, entao a nota "cancelada" continuava 100%
valida perante a Receita. Este modulo monta e assina o evento de verdade que
precisa ser enviado (ver app/fiscal/api_nacional.cancelar_nfse) pra essa
informacao ser real.

ATENCAO (confirmar contra o Anexo II oficial antes do primeiro cancelamento
real — nao foi possivel abrir a planilha/XSD oficiais, so' arquivos binarios;
a formula abaixo vem de uma amostra real de XML publicada no forum oficial da
comunidade NFS-e + o changelog de dez/2025 que removeu o campo
`nPedRegEvento` do Id): o `Id` de `infPedReg` e' "PRE" + chNFSe(50 digitos) +
tpEvento(6 digitos) = 59 caracteres. Se a API rejeitar por causa do Id
(procurar erro mencionando "Id"/"infPedReg" na resposta), essa e' a primeira
coisa a conferir.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import List, Optional

from cryptography.hazmat.primitives.serialization import Encoding
from lxml import etree
from signxml import XMLSigner, methods

NS = "http://www.sped.fazenda.gov.br/nfse"
NSMAP = {None: NS}

CODIGO_EVENTO_CANCELAMENTO = "101101"

# cMotivo (Anexo II, tabela de motivos do evento e101101)
MOTIVO_ERRO_NA_EMISSAO = "1"
MOTIVO_SERVICO_NAO_PRESTADO = "2"
MOTIVO_OUTROS = "9"


@dataclass
class DadosEventoCancelamento:
    ambiente: str  # "homologacao" ou "producao"
    chave_nfse: str  # chNFSe — chave de acesso da NFS-e (50 digitos), NAO e' o Id da DPS
    documento_autor: str  # CNPJ (14) ou CPF (11) de quem esta cancelando, so' numeros
    codigo_motivo: str = MOTIVO_OUTROS
    descricao_motivo: Optional[str] = None  # obrigatorio (regra E1944) quando codigo_motivo == "9"
    versao_aplicativo: str = "emissor-nfse-0.1"


def _formatar_dhemi(agora: dt.datetime) -> str:
    """AAAA-MM-DDThh:mm:ssTZD, com TZD em horas cheias (ex.: -03:00) — mesma
    formatacao usada em dps_builder.py, duplicada aqui de proposito (os dois
    modulos precisam poder evoluir sem se enroscar um no outro)."""
    offset = agora.utcoffset() or dt.timedelta(0)
    total_minutos = int(offset.total_seconds() // 60)
    sinal = "+" if total_minutos >= 0 else "-"
    total_minutos = abs(total_minutos)
    tz = f"{sinal}{total_minutos // 60:02d}:{total_minutos % 60:02d}"
    return agora.strftime("%Y-%m-%dT%H:%M:%S") + tz


def montar_id_pedido_registro_evento(chave_nfse: str, tipo_evento: str = CODIGO_EVENTO_CANCELAMENTO) -> str:
    """'PRE' + chNFSe(50) + tpEvento(6) = 59 caracteres. Ver ATENCAO no
    docstring do modulo — confirmar contra o Anexo II oficial antes de usar
    em producao de verdade."""
    if len(chave_nfse) != 50:
        raise ValueError(
            f"Chave de acesso da NFS-e precisa ter 50 digitos pra montar o evento, recebi "
            f"{len(chave_nfse)}: {chave_nfse!r}"
        )
    if len(tipo_evento) != 6:
        raise ValueError(f"Codigo do tipo de evento precisa ter 6 digitos, recebi: {tipo_evento!r}")
    return f"PRE{chave_nfse}{tipo_evento}"


def _el(parent: etree._Element, tag: str, text: Optional[str] = None) -> etree._Element:
    e = etree.SubElement(parent, f"{{{NS}}}{tag}")
    if text is not None:
        e.text = str(text)
    return e


def montar_evento_cancelamento_xml(dados: DadosEventoCancelamento) -> etree._Element:
    """Monta o XML do pedido de registro de evento (ainda sem assinatura)."""
    if dados.codigo_motivo == MOTIVO_OUTROS and not dados.descricao_motivo:
        raise ValueError('Motivo "Outros" exige uma descricao (regra E1944 do Anexo II).')

    tp_amb = "2" if dados.ambiente == "homologacao" else "1"
    agora = dt.datetime.now().astimezone()

    pedido = etree.Element(f"{{{NS}}}pedRegEvento", nsmap=NSMAP)
    pedido.set("versao", "1.01")

    inf = etree.SubElement(pedido, f"{{{NS}}}infPedReg")
    inf.set("Id", montar_id_pedido_registro_evento(dados.chave_nfse))

    _el(inf, "tpAmb", tp_amb)
    _el(inf, "verAplic", dados.versao_aplicativo)
    _el(inf, "dhEvento", _formatar_dhemi(agora))
    if len(dados.documento_autor) == 11:
        _el(inf, "CPFAutor", dados.documento_autor)
    else:
        _el(inf, "CNPJAutor", dados.documento_autor)
    _el(inf, "chNFSe", dados.chave_nfse)

    evento_especifico = _el(inf, f"e{CODIGO_EVENTO_CANCELAMENTO}")
    _el(evento_especifico, "xDesc", "Cancelamento de NFS-e")
    _el(evento_especifico, "cMotivo", dados.codigo_motivo)
    if dados.descricao_motivo:
        _el(evento_especifico, "xMotivo", dados.descricao_motivo)

    return pedido


def assinar_evento(
    pedido: etree._Element, chave_privada, certificado, certificados_extras: Optional[List] = None
) -> etree._Element:
    """Assina <infPedReg> — mesmo algoritmo/convencao do dps_builder.assinar_dps
    (RSA-SHA256, C14N nao-exclusivo): validar no primeiro teste real se a API
    aceitar um algoritmo diferente pro evento."""
    inf = pedido.find(f"{{{NS}}}infPedReg")
    evento_id = inf.get("Id")

    cert_pem = certificado.public_bytes(Encoding.PEM)
    for extra in certificados_extras or []:
        cert_pem += extra.public_bytes(Encoding.PEM)

    signer = XMLSigner(
        method=methods.enveloped,
        signature_algorithm="rsa-sha256",
        digest_algorithm="sha256",
        c14n_algorithm="http://www.w3.org/TR/2001/REC-xml-c14n-20010315",
    )
    return signer.sign(
        pedido, key=chave_privada, cert=cert_pem, reference_uri=f"#{evento_id}", id_attribute="Id",
    )


def serializar(pedido: etree._Element) -> bytes:
    return etree.tostring(pedido, xml_declaration=True, encoding="UTF-8", standalone=False)


def montar_e_assinar_evento(
    dados: DadosEventoCancelamento, chave_privada, certificado, certificados_extras: Optional[List] = None
) -> bytes:
    pedido = montar_evento_cancelamento_xml(dados)
    assinado = assinar_evento(pedido, chave_privada, certificado, certificados_extras)
    return serializar(assinado)
