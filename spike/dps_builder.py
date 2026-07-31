"""Montagem e assinatura do XML da DPS (Declaracao de Prestacao de Servico).

Layout de referencia: Sistema Nacional NFS-e, XSD v1.01
(namespace "http://www.sped.fazenda.gov.br/nfse", elemento raiz <DPS versao="1.01">).
Testado offline: montagem + assinatura validadas contra o schema_v101.xsd oficial.

Isolado neste unico modulo (espec-mvp-emissor-nfse.md, secao 8, risco 2) para que uma
mudanca de layout (ex.: NT da Reforma Tributaria / IBS-CBS) custe editar 1 arquivo.

Este builder cobre o subconjunto MINIMO de campos para uma DPS de prestador de
servico comum, tributado por ISSQN, emitida pelo proprio prestador (tpEmit=1),
sem substituicao, sem intermediario, sem IBS/CBS. Campos fora desse recorte
(grupos "subst", "interm", "comExt", "obra", "atvEvento", "IBSCBS" etc.) sao
opcionais no XSD e foram deliberadamente omitidos aqui.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import List, Optional

from cryptography.hazmat.primitives.serialization import Encoding
from lxml import etree
from signxml import XMLSigner, methods

NS = "http://www.sped.fazenda.gov.br/nfse"
NSMAP = {None: NS}


# --------------------------------------------------------------------------
# Modelo de dados de entrada (o que o app precisa coletar do usuario)
# --------------------------------------------------------------------------


@dataclass
class Prestador:
    documento: str  # CNPJ (14 digitos) ou CPF (11 digitos), so numeros
    inscricao_municipal: str
    codigo_municipio: str  # codigo IBGE (7 digitos) do municipio emissor
    # regTrib / opSimpNac (Situacao perante o Simples Nacional):
    #   1 = Nao optante | 2 = Optante MEI | 3 = Optante ME/EPP
    opcao_simples_nacional: str = "1"
    # regTrib / regEspTrib (Regime Especial de Tributacao):
    #   0 Nenhum | 1 Cooperativa | 2 Estimativa | 3 Microempresa Municipal
    #   4 Notario/Registrador | 5 Profissional Autonomo | 6 Sociedade de Profissionais
    regime_especial_tributacao: str = "0"


@dataclass
class Tomador:
    documento: str  # CNPJ (14) ou CPF (11), so numeros
    nome: str
    email: Optional[str] = None


@dataclass
class Servico:
    # cTribNac (LC 116/2003): 6 digitos = Item(2) + Subitem(2) + Desdobro Nacional(2)
    codigo_tributacao_nacional: str
    # cTribMun: 10 digitos, especifico do municipio. Obter via API de Parametros
    # Municipais (GET /parametros_municipais/{codigoMunicipio}/{codigoServico}).
    codigo_tributacao_municipal: str
    # cNBS: 9 digitos, Nomenclatura Brasileira de Servicos v2.0 (Anexo B)
    codigo_nbs: str
    descricao: str
    codigo_municipio_prestacao: str  # cLocPrestacao, codigo IBGE (7 digitos)
    valor: str  # vServ — aceita "1234.5" / "1234.56" / Decimal-like
    # pAliq — alíquota do ISS (%). Deixar None se o municipio de incidencia
    # ja estiver parametrizado no Sistema Nacional (a aliquota vem do sistema).
    aliquota_iss: Optional[str] = None
    # tpRetISSQN: 1 Nao retido | 2 Retido pelo tomador | 3 Retido pelo intermediario
    tipo_retencao_issqn: str = "1"


@dataclass
class Numeracao:
    serie: str = "1"
    numero_dps: str = "1"


@dataclass
class DadosDPS:
    ambiente: str  # "homologacao" ou "producao"
    prestador: Prestador
    tomador: Tomador
    servico: Servico
    numeracao: Numeracao = field(default_factory=Numeracao)
    data_competencia: Optional[str] = None  # "AAAA-MM-DD"; default = hoje
    versao_aplicativo: str = "spike-sprint0-0.1"


# --------------------------------------------------------------------------
# Helpers de formatacao (o XSD e estrito quanto a padrao de string)
# --------------------------------------------------------------------------


def _valor_monetario(x) -> str:
    """Formata para o padrao TSDec15V2/TSDec1V2: '0', '0.00' ou '[1-9]\\d*(\\.\\d{2})?'."""
    d = Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return str(d)


def _tipo_inscricao(documento: str) -> str:
    """1=CPF, 2=CNPJ (regra do DPS/NFS-e Nacional; invertida em relacao a NF-e)."""
    return "1" if len(documento) == 11 else "2"


def _formatar_dhemi(agora: dt.datetime) -> str:
    """AAAA-MM-DDThh:mm:ssTZD, com TZD em horas cheias (ex.: -03:00)."""
    offset = agora.utcoffset() or dt.timedelta(0)
    total_minutos = int(offset.total_seconds() // 60)
    sinal = "+" if total_minutos >= 0 else "-"
    total_minutos = abs(total_minutos)
    tz = f"{sinal}{total_minutos // 60:02d}:{total_minutos % 60:02d}"
    return agora.strftime("%Y-%m-%dT%H:%M:%S") + tz


def montar_id_dps(cod_municipio: str, documento_prestador: str, serie: str, numero_dps: str) -> str:
    """'DPS' + Cod.Mun(7) + TipoInscricao(1) + InscricaoFederal(14) + Serie(5) + NumDPS(15) = 45 chars."""
    tp_insc = _tipo_inscricao(documento_prestador)
    insc_federal = documento_prestador.zfill(14)
    return (
        f"DPS{cod_municipio.zfill(7)}{tp_insc}{insc_federal}"
        f"{serie.zfill(5)}{numero_dps.zfill(15)}"
    )


def _el(parent: etree._Element, tag: str, text: Optional[str] = None) -> etree._Element:
    e = etree.SubElement(parent, f"{{{NS}}}{tag}")
    if text is not None:
        e.text = str(text)
    return e


# --------------------------------------------------------------------------
# Montagem do XML (ordem dos elementos segue estritamente o xsd:sequence)
# --------------------------------------------------------------------------


def montar_dps_xml(dados: DadosDPS) -> etree._Element:
    """Monta o XML da DPS (ainda sem assinatura)."""
    tp_amb = "2" if dados.ambiente == "homologacao" else "1"
    agora = dt.datetime.now().astimezone()
    dcompet = dados.data_competencia or agora.strftime("%Y-%m-%d")

    dps = etree.Element(f"{{{NS}}}DPS", nsmap=NSMAP)
    dps.set("versao", "1.01")

    inf = etree.SubElement(dps, f"{{{NS}}}infDPS")
    inf.set(
        "Id",
        montar_id_dps(
            dados.prestador.codigo_municipio,
            dados.prestador.documento,
            dados.numeracao.serie,
            dados.numeracao.numero_dps,
        ),
    )

    _el(inf, "tpAmb", tp_amb)
    _el(inf, "dhEmi", _formatar_dhemi(agora))
    _el(inf, "verAplic", dados.versao_aplicativo)
    _el(inf, "serie", dados.numeracao.serie)
    _el(inf, "nDPS", dados.numeracao.numero_dps)
    _el(inf, "dCompet", dcompet)
    _el(inf, "tpEmit", "1")  # 1 = Prestador
    _el(inf, "cLocEmi", dados.prestador.codigo_municipio)

    # --- prest (TCInfoPrestador) ---
    prest = _el(inf, "prest")
    p = dados.prestador
    if len(p.documento) == 14:
        _el(prest, "CNPJ", p.documento)
    else:
        _el(prest, "CPF", p.documento)
    _el(prest, "IM", p.inscricao_municipal)
    reg_trib = _el(prest, "regTrib")
    _el(reg_trib, "opSimpNac", p.opcao_simples_nacional)
    _el(reg_trib, "regEspTrib", p.regime_especial_tributacao)

    # --- toma (TCInfoPessoa) ---
    toma = _el(inf, "toma")
    t = dados.tomador
    if len(t.documento) == 14:
        _el(toma, "CNPJ", t.documento)
    else:
        _el(toma, "CPF", t.documento)
    _el(toma, "xNome", t.nome)
    if t.email:
        _el(toma, "email", t.email)

    # --- serv (TCServ) ---
    serv = _el(inf, "serv")
    s = dados.servico
    loc_prest = _el(serv, "locPrest")
    _el(loc_prest, "cLocPrestacao", s.codigo_municipio_prestacao)
    c_serv = _el(serv, "cServ")
    _el(c_serv, "cTribNac", s.codigo_tributacao_nacional)
    _el(c_serv, "cTribMun", s.codigo_tributacao_municipal)
    _el(c_serv, "xDescServ", s.descricao)
    _el(c_serv, "cNBS", s.codigo_nbs)

    # --- valores (TCInfoValores) ---
    valores = _el(inf, "valores")
    v_serv_prest = _el(valores, "vServPrest")
    _el(v_serv_prest, "vServ", _valor_monetario(s.valor))
    trib = _el(valores, "trib")
    trib_mun = _el(trib, "tribMun")
    _el(trib_mun, "tribISSQN", "1")  # 1 = Operacao tributavel
    _el(trib_mun, "tpRetISSQN", s.tipo_retencao_issqn)
    if s.aliquota_iss is not None:
        _el(trib_mun, "pAliq", _valor_monetario(s.aliquota_iss))
    tot_trib = _el(trib, "totTrib")
    # indTotTrib=0: nao informar valor estimado de tributos (Decreto 8.264/2014)
    _el(tot_trib, "indTotTrib", "0")

    return dps


# --------------------------------------------------------------------------
# Assinatura (XMLDSig) — <Signature> como IRMAO de <infDPS>, referenciando
# o atributo Id de infDPS. Ver TCDPS no XSD: sequence(infDPS, dsig:Signature).
# --------------------------------------------------------------------------


def assinar_dps(dps: etree._Element, chave_privada, certificado, certificados_extras: Optional[List] = None) -> etree._Element:
    """Assina o elemento <infDPS> e anexa <Signature> como irmao dele, dentro de <DPS>.

    ATENCAO (validar no primeiro teste real): o algoritmo de assinatura/digest e o
    metodo de canonicalizacao abaixo seguem a convencao usada pelos documentos
    fiscais eletronicos brasileiros (NF-e/NFS-e municipal): RSA-SHA256, digest
    SHA-256, C14N (nao exclusivo). O XSD oficial so garante o namespace XMLDSig
    padrao W3C — o algoritmo especifico exigido pelo Sistema Nacional NFS-e deve
    ser confirmado pela resposta da API (rejeicao de assinatura) caso este default
    nao seja aceito.
    """
    inf = dps.find(f"{{{NS}}}infDPS")
    dps_id = inf.get("Id")

    cert_pem = certificado.public_bytes(Encoding.PEM)
    for extra in certificados_extras or []:
        cert_pem += extra.public_bytes(Encoding.PEM)

    signer = XMLSigner(
        method=methods.enveloped,
        signature_algorithm="rsa-sha256",
        digest_algorithm="sha256",
        c14n_algorithm="http://www.w3.org/TR/2001/REC-xml-c14n-20010315",
    )
    dps_assinado = signer.sign(
        dps,
        key=chave_privada,
        cert=cert_pem,
        reference_uri=f"#{dps_id}",
        id_attribute="Id",
    )
    return dps_assinado


def serializar(dps: etree._Element) -> bytes:
    return etree.tostring(dps, xml_declaration=True, encoding="UTF-8", standalone=False)


def montar_e_assinar(dados: DadosDPS, chave_privada, certificado, certificados_extras: Optional[List] = None) -> bytes:
    dps = montar_dps_xml(dados)
    dps_assinado = assinar_dps(dps, chave_privada, certificado, certificados_extras)
    return serializar(dps_assinado)
