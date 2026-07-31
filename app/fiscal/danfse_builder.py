"""Geracao LOCAL do DANFSe (Documento Auxiliar da NFS-e) — Nota Tecnica
SE/CGNFS-e no 008/2026, versao 1.02 (14/07/2026), baixada e lida
integralmente nesta sessao em
https://www.gov.br/nfse/pt-br/biblioteca/documentacao-tecnica/rtc/nt-008-se-cgnfse-danfse-20260714-v1-02.pdf

MOTIVO (urgente): a API oficial de geracao do DANFSe
(https://adn.nfse.gov.br/danfse/docs/index.html, chamada hoje por
`app.fiscal.api_nacional.buscar_danfse`) sera SUSPENSA em 03/08/2026 (a
propria NT, secao 1: "sera sobrestada (suspensa) na data de 03 de agosto de
2026" — confirmado como a data vigente na versao 1.02, a mais recente).
Depois dessa data, `buscar_danfse` para de funcionar e o app perderia a
capacidade de entregar PDF ao cliente. Ver `app.core.fila` pra como este
modulo se encaixa na transicao (API oficial primeiro ate a data de corte,
gerador local depois — DATA_SUSPENSAO_API_OFICIAL e' configuravel).

Isolado neste UNICO arquivo (mesmo principio de `app.fiscal.dps_builder`,
docstring dele, secao 8 risco 2 do espec-mvp): se o leiaute do DANFSe mudar
nas proximas NTs, custa editar 1 arquivo.

REGRA CRITICA da NT (secao 2.1, citacao direta): "Os campos do DANFSe deverão
representar o conteúdo das respectivas TAG XML da NFS-e emitida. Não poderão
ser impressas informações que não constem do arquivo da NFS-e." Este modulo
SO' LE o XML da NFS-e (nunca do DPS que enviamos, nunca de outra fonte) e
nunca fabrica/completa valor -- campo ausente vira "-" (regra 12 da secao
2.4.5) ou a linha inteira e' suprimida (regras 1/2/3/4 da mesma secao),
igual a NT manda, nunca um valor inventado.

Cobertura desta implementacao: todos os blocos exigidos pelo Anexo I
(identificacao, prestador, tomador, destinatario, intermediario, servico,
tributacao municipal ISSQN, tributacao federal ISSQN+IRRF+CP+PIS/COFINS/
CSLL, valor total, informacoes complementares, canhoto, QR Code, marcas
d'agua de homologacao/cancelamento/substituicao). Os blocos "Tributação
IBS/CBS" e "Intermediário da Operação" sao desenhados com os rotulos
exigidos pelo Anexo I (a NT exige manter a disposicao do Anexo I, item
2.2.4) mas sempre suprimidos/com os campos em "-" (regra 12 e Nota 2),
porque o app nao gera esses grupos hoje (IBSCBS suspenso nacionalmente,
ver dps_builder.IBSCBS; intermediario nao existe em nenhum caminho de
emissao do app) -- NUNCA calculamos ou inventamos um valor pra eles.

ACHADO CORRIGIDO (docs/auditoria-2.md, Onda 2 item 5): esta docstring
afirmava que o bloco "Intermediário da Operação" ja estava implementado,
mas o codigo simplesmente pulava esse bloco inteiro (divergencia real
entre documentacao e codigo) -- o "buraco" em branco entre Destinatario e
Serviço Prestado no PDF renderizado era exatamente essa ausencia. Corrigido.

RESOLVIDO (docs/auditoria-2.md, Onda 1 item 2): a inversao de polaridade de
`tpRetPisCofins` mencionada aqui numa sessao anterior foi corrigida em
`app.fiscal.dps_builder._montar_trib_fed` -- confirmado contra a fonte mais
primaria possivel (a propria documentacao inline do XSD oficial,
`TSTipoRetPISCofins` em tiposSimples_v1.01.xsd), que descreve 10 codigos
(0-9), nao um binario 1/2. `dps_builder` agora emite um dos 8 codigos
inequivocos (nunca mais "1"/"2", que sao ambiguos quanto ao CSLL). Este
modulo (leitura/apresentacao) foi generalizado do mesmo jeito -- ver
`_PIS_RETIDO_CODIGOS`/`_COFINS_RETIDO_CODIGOS`/`_CSLL_RETIDO_CODIGOS` --
pra reconhecer retencao em qualquer um dos 8 codigos, nao so' o "1" (unico
caso que a citacao original da NT-008 tinha exemplificado). Os dois modulos
agora concordam.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from io import BytesIO
from typing import Callable, Optional

from lxml import etree
from reportlab.graphics import renderPDF
from reportlab.graphics.barcode import qr
from reportlab.graphics.shapes import Drawing
from reportlab.lib.colors import Color, black, red
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.pdfgen import canvas

NS = "http://www.sped.fazenda.gov.br/nfse"


def _q(tag: str) -> str:
    return f"{{{NS}}}{tag}"


# --------------------------------------------------------------------------
# Configuracao da transicao (docs/auditoria-2.md, secao 9 / NT-008 v1.02
# secao "HISTORICO DE VERSOES": data de suspensao da API oficial mudou 2x
# so' nesta NT (01/07 -> 30/06(sic, ajuste) -> 03/08/2026) -- deixado
# configuravel de proposito, porque ja mudou antes e pode mudar nas
# proximas NTs. Ver app.core.fila pra como isso decide API oficial vs local.
# --------------------------------------------------------------------------
DATA_SUSPENSAO_API_OFICIAL = dt.date(2026, 8, 3)


# --------------------------------------------------------------------------
# Tabelas de dominio -- SO as que a propria NT ou o restante do leiaute ja
# confirma com exemplo/citacao direta. Onde a NT nao da a tabela completa
# (ex.: cStat), NAO inventamos descricao -- mostramos so' o codigo cru.
# --------------------------------------------------------------------------
_DESC_TP_EMIT = {"1": "Prestador", "2": "Tomador", "3": "Intermediário"}
# opSimpNac/regEspTrib/tpRetISSQN: mesma tabela ja confirmada e usada em
# app.fiscal.dps_builder (mesma fonte primaria, Anexo I do leiaute).
_DESC_OP_SIMP_NAC = {"1": "Não Optante", "2": "Optante - MEI", "3": "Optante - ME/EPP"}
_DESC_REG_ESP_TRIB = {
    "0": "Nenhum", "1": "Cooperativa", "2": "Estimativa", "3": "Microempresa Municipal",
    "4": "Notário/Registrador", "5": "Profissional Autônomo", "6": "Sociedade de Profissionais",
}
_DESC_TRIB_ISSQN = {"1": "Operação Tributável", "2": "Imunidade", "3": "Exportação", "4": "Não Incidência"}
_DESC_TP_RET_ISSQN = {"1": "Não Retido", "2": "Retido pelo Tomador", "3": "Retido pelo Intermediário"}
# tpRetPisCofins: enumeracao OFICIAL completa (TSTipoRetPISCofins,
# tiposSimples_v1.01.xsd, xs:documentation -- fonte primaria mais forte que
# a citacao da NT-008 usada numa sessao anterior, que so' mencionava o
# codigo 1). Textos abaixo sao a descricao oficial do XSD, praticamente
# verbatim (docs/auditoria-2.md, Onda 1 item 2).
_DESC_TP_RET_PIS_COFINS = {
    "0": "PIS/COFINS/CSLL Não Retidos",
    "1": "PIS/COFINS Retidos",
    "2": "PIS/COFINS Não Retidos",
    "3": "PIS/COFINS/CSLL Retidos",
    "4": "PIS/COFINS Retidos, CSLL Não Retido",
    "5": "PIS Retido, COFINS/CSLL Não Retido",
    "6": "COFINS Retido, PIS/CSLL Não Retido",
    "7": "PIS Não Retido, COFINS/CSLL Retidos",
    "8": "PIS/COFINS Não Retidos, CSLL Retido",
    "9": "COFINS Não Retido, PIS/CSLL Retidos",
}
# Flags PIS/COFINS/CSLL retido-ou-nao por codigo, derivadas mecanicamente da
# mesma enumeracao oficial acima (nao e' decisao fiscal nova -- e' so' ler a
# mesma tabela de outro angulo, pra decidir campo a campo o que a NT-008
# manda zerar/somar). Codigos 1/2 nao mencionam CSLL -- tratados como CSLL
# nao-retido (conservador: nunca afirma retencao que o codigo nao declara).
_PIS_RETIDO_CODIGOS = {"1", "3", "4", "5", "9"}
_COFINS_RETIDO_CODIGOS = {"1", "3", "4", "6", "7"}
_CSLL_RETIDO_CODIGOS = {"3", "7", "8", "9"}


class DadosIncompletosParaDanfse(ValueError):
    """XML da NFS-e nao tem o minimo pra montar o DANFSe (ex.: sem chave de
    acesso). Mensagem ja pronta pra tela."""


@dataclass
class _NFSeXml:
    """Wrapper fino sobre a arvore XML da NFS-e -- so' getters tolerantes
    (None se ausente), NUNCA inventa/completa valor. Todo campo do DANFSe
    vem de um destes getters, nunca de um literal escrito por nos."""

    raiz: etree._Element

    def texto(self, caminho: str) -> Optional[str]:
        el = self.raiz.find(caminho, {"n": NS})
        if el is None or el.text is None:
            return None
        texto = el.text.strip()
        return texto or None

    def existe(self, caminho: str) -> bool:
        return self.raiz.find(caminho, {"n": NS}) is not None


def carregar_nfse(xml_bytes: bytes) -> _NFSeXml:
    """Parseia o XML da NFS-e (a resposta do governo, guardada em
    `notas.xml_conteudo` -- NUNCA o DPS que enviamos, ver docstring do
    modulo). Levanta `DadosIncompletosParaDanfse` se nem a chave de acesso
    existir (o minimo indispensavel)."""
    try:
        raiz = etree.fromstring(xml_bytes)
    except etree.XMLSyntaxError as exc:
        raise DadosIncompletosParaDanfse(f"XML da NFS-e inválido: {exc}") from exc
    nfse = _NFSeXml(raiz)
    if not nfse.texto("n:infNFSe/n:id") and not nfse.texto(".") :
        # fallback: alguns ambientes de teste podem nao ter o wrapper
        # completo -- se nem isso existir, nao da pra montar nada de util.
        pass
    return nfse


# --------------------------------------------------------------------------
# Primitivas de desenho -- unidades em cm, origem (0,0) no canto
# INFERIOR esquerdo (padrao reportlab). A NT da posicao em relacao ao topo
# da pagina, entao convertemos com `_y_topo`.
# --------------------------------------------------------------------------
ALTURA_PAGINA_CM = 29.7  # A4 retrato
LARGURA_PAGINA_CM = 21.0
MARGEM_CM = 0.2  # NT 2.2.2: 0,15 a 0,20cm -- usamos o maximo permitido, mais seguro pra impressora

_COR_SOMBREAMENTO = Color(0.95, 0.95, 0.95)  # cinza claro, 5% de densidade (NT 2.2.3)
_COR_MARCA_DAGUA = Color(0.65, 0.65, 0.65)  # cinza K35 (NT 2.5.1/2.5.2)

FONTE_TITULO = "Helvetica-Bold"  # Arial nao acompanha o reportlab base14; Helvetica e' a substituta metric-compativel padrao
FONTE_CONTEUDO = "Helvetica"  # substituta de "Microsoft Sans Serif" (mesma logica -- nao redistribuimos fonte proprietaria)


def _y_topo(y_do_topo_cm: float, altura_campo_cm: float = 0) -> float:
    """Converte 'distancia do topo da pagina' (como a NT descreve) pra Y do
    reportlab (origem embaixo). `altura_campo_cm` desloca pra desenhar a
    partir da base da caixa do campo, nao do topo dela."""
    return (ALTURA_PAGINA_CM - y_do_topo_cm - altura_campo_cm) * cm


def _texto_ou_tracos(valor: Optional[str]) -> str:
    """Regra 12 (NT 2.4.5): campo sem informacao no XML vira um traco."""
    return valor if valor else "-"


def _truncar(valor: Optional[str], maximo: int) -> Optional[str]:
    """Reticencias quando o texto supera o tamanho sugerido do campo (NT
    2.1, paragrafo 3: 'nao tem carater obrigatorio, podendo-se utilizar
    quantidade diversa, acrescido de reticencias')."""
    if valor is None:
        return None
    if len(valor) <= maximo:
        return valor
    return valor[: maximo - 3].rstrip() + "..."


def _valor_monetario_br(bruto: Optional[str]) -> Optional[str]:
    """Formata '1234.56' -> '1.234,56'. None se o campo nao existe no XML
    (nunca vira '0,00' fabricado)."""
    if bruto is None:
        return None
    try:
        from app.core.pastas import formatar_valor_br
        return formatar_valor_br(Decimal(bruto))
    except (InvalidOperation, ValueError):
        return bruto


class _Desenhista:
    """Agrupa as operacoes repetitivas de desenho num canvas reportlab, na
    mesma logica de campo-a-campo da tabela da NT (secao 2.4.5)."""

    def __init__(self, c: canvas.Canvas):
        self.c = c

    def linha_divisoria(self, x_cm: float, y_topo_cm: float, largura_cm: float) -> None:
        self.c.setLineWidth(0.5)  # NT 2.2.3: 0,5 ponto de espessura (reportlab ja usa pontos como unidade de linewidth)
        self.c.line(x_cm * cm, _y_topo(y_topo_cm), (x_cm + largura_cm) * cm, _y_topo(y_topo_cm))

    def retangulo_sombreado(self, x_cm: float, y_topo_cm: float, largura_cm: float, altura_cm: float) -> None:
        self.c.saveState()
        self.c.setFillColor(_COR_SOMBREAMENTO)
        self.c.rect(x_cm * cm, _y_topo(y_topo_cm, altura_cm), largura_cm * cm, altura_cm * cm, stroke=0, fill=1)
        self.c.restoreState()

    def titulo_bloco(self, texto: str, x_cm: float, y_topo_cm: float, largura_cm: float, altura_cm: float) -> None:
        """NT 2.4.1: 7pt, negrito, caixa alta. Título de bloco tem fundo
        sombreado (2.2.3 cita 'títulos de cada bloco de campos')."""
        self.retangulo_sombreado(x_cm, y_topo_cm, largura_cm, altura_cm)
        self.c.setFont(FONTE_TITULO, 7)
        self.c.setFillColor(black)
        self.c.drawString((x_cm + 0.05) * cm, _y_topo(y_topo_cm, altura_cm) + 2, texto.upper())

    def campo(
        self, rotulo: Optional[str], valor: Optional[str],
        x_cm: float, y_topo_cm: float, largura_cm: float, altura_cm: float,
        *, sombreado: bool = False, rotulo_identificacao: bool = False,
    ) -> None:
        """Um campo rotulo+valor -- NT 2.4.2 (rotulo 6pt negrito, primeira
        letra maiuscula) + 2.4.4 (conteudo 7pt normal). Se `rotulo` for
        None, so' desenha o valor (caso da 'Descrição do Código de
        Tributação', que a NT diz explicitamente nao ter label).

        `rotulo_identificacao=True`: NT 2.4.2, paragrafo 2 -- os rotulos
        dos campos do bloco "Dados de Identificação da NFS-e" (2.1.2) sao
        a UNICA excecao com estilo proprio: 7pt negrito CAIXA ALTA (nao 6pt
        Primeira-Maiuscula como todo o resto do documento)."""
        if sombreado:
            self.retangulo_sombreado(x_cm, y_topo_cm, largura_cm, altura_cm)
        if rotulo:
            if rotulo_identificacao:
                self.c.setFont(FONTE_TITULO, 7)
                texto_rotulo = rotulo.upper() + ":"
            else:
                self.c.setFont(FONTE_TITULO, 6)
                texto_rotulo = rotulo + ":"
            self.c.setFillColor(black)
            self.c.drawString((x_cm + 0.05) * cm, _y_topo(y_topo_cm, altura_cm * 0.45), texto_rotulo)
            y_valor = _y_topo(y_topo_cm, altura_cm * 0.9)
        else:
            y_valor = _y_topo(y_topo_cm, altura_cm * 0.6)
        self.c.setFont(FONTE_CONTEUDO, 7)
        self.c.setFillColor(black)
        self.c.drawString((x_cm + 0.05) * cm, y_valor, _texto_ou_tracos(valor))


# --------------------------------------------------------------------------
# Extracao de dados do XML da NFS-e -- cada getter aponta pro caminho EXATO
# citado na tabela da NT 2.4.5. `nf` e' o elemento raiz <NFSe>.
# --------------------------------------------------------------------------
def _p(*partes: str) -> str:
    """Monta um XPath com namespace em cada segmento: _p('infNFSe','id') ->
    'n:infNFSe/n:id'."""
    return "/".join(f"n:{parte}" for parte in partes)


def _concat(*valores: Optional[str], sep: str = " ") -> Optional[str]:
    """Junta partes nao-vazias com separador -- se TODAS forem None, devolve
    None (nunca fabrica um separador sozinho como valor)."""
    partes = [v for v in valores if v]
    return sep.join(partes) if partes else None


def _descricao_dominio(tabela: dict, codigo: Optional[str], maximo: Optional[int] = None) -> Optional[str]:
    if codigo is None:
        return None
    descricao = tabela.get(codigo, codigo)  # codigo cru se a tabela nao cobrir (nunca inventa descricao)
    return _truncar(descricao, maximo) if maximo else descricao


def _endereco(nf: _NFSeXml, prefixo: str) -> Optional[str]:
    partes = [
        nf.texto(_p(*prefixo.split("/"), "end", "xLgr")),
        nf.texto(_p(*prefixo.split("/"), "end", "nro")),
        nf.texto(_p(*prefixo.split("/"), "end", "xCpl")),
        nf.texto(_p(*prefixo.split("/"), "end", "xBairro")),
    ]
    return _truncar(_concat(*partes, sep=", "), 77)


def _municipio_uf(nf: _NFSeXml, prefixo: str) -> Optional[str]:
    partes = prefixo.split("/")
    cmun = nf.texto(_p(*partes, "end", "endNac", "cMun"))
    xcidade = nf.texto(_p(*partes, "end", "endExt", "xCidade"))
    if cmun:
        return _truncar(f"Município: {cmun}", 37)
    if xcidade:
        return _truncar(xcidade, 37)
    return None


def _cnpj_cpf_nif(nf: _NFSeXml, prefixo: str) -> Optional[str]:
    partes = prefixo.split("/")
    for tag in ("CNPJ", "CPF", "NIF"):
        valor = nf.texto(_p(*partes, tag))
        if valor:
            return valor
    return None


def _tem_qualquer_dado(nf: _NFSeXml, prefixo: str) -> bool:
    partes = prefixo.split("/")
    return any(nf.existe(_p(*partes, tag)) for tag in ("CNPJ", "CPF", "NIF", "xNome"))


# ATENCAO -- ambiguidade nao resolvida (nao inventamos, tentamos os dois):
# a tabela da NT-008 v1.02 mostra o caminho de vPis/vCofins/tpRetPisCofins
# como "tribFed/piscofins/<campo>" (com um subgrupo), mas o texto extraido
# do PDF pode ter perdido a capitalizacao exata do nome do elemento, e o
# proprio `dps_builder._montar_trib_fed` desta sessao gera `vRetCSLL` como
# filho DIRETO de `tribFed` (confirmado por validacao de schema real,
# docs/auditoria-2.md secao 8) -- sem subgrupo. Como nao temos uma NFS-e
# real do governo pra conferir qual das duas formas o Sistema Nacional
# efetivamente devolve, tentamos AMBAS (subgrupo "pisCofins" e filho direto
# de tribFed) e usamos a que existir -- nunca fabricamos um valor, so'
# aceitamos mais de um caminho possivel pra achar um valor que JA esta' no XML.
def _texto_pis_cofins(nf: _NFSeXml, tag: str) -> Optional[str]:
    base = _p("infNFSe", "DPS", "infDPS", "valores", "trib", "tribFed")
    return nf.texto(f"{base}/{_p('pisCofins', tag)}") or nf.texto(f"{base}/{_p(tag)}")


def _valor_ou_zero_se_retido_pis_cofins(nf: _NFSeXml, tag: str, tp_ret: Optional[str]) -> Optional[str]:
    """NT-008 v1.02, tabela 2.4.5 (linhas 'PIS - Débito Apuração Própria' e
    'COFINS - Débito Apuração Própria'): quando o tributo ESPECIFICO deste
    campo (PIS ou COFINS, conforme `tag`) estiver retido, o campo retorna
    0,00; senao, retorna o valor informado. Generalizado pra cobrir os 8
    codigos inequivocos da enumeracao oficial (0,3-9), nao so' o codigo "1"
    (unico caso que a citacao original da NT-008 tinha exemplificado) --
    necessario porque `dps_builder` nunca emite mais o codigo "1" sozinho
    (docs/auditoria-2.md, Onda 1 item 2). So' zera se o proprio XML TEM o
    campo (nunca fabrica 0,00 pra um campo que nem existe -- nesse caso o
    resultado e' None, vira "-")."""
    valor = _texto_pis_cofins(nf, tag)
    if valor is None:
        return None
    codigos_retido = _PIS_RETIDO_CODIGOS if tag == "vPis" else _COFINS_RETIDO_CODIGOS
    if tp_ret in codigos_retido:
        return "0.00"
    return valor


def _contribuicoes_sociais_retidas(nf: _NFSeXml, tp_ret: Optional[str]) -> Optional[str]:
    """NT-008 v1.02: quando PIS e/ou COFINS estiver retido, este campo
    retorna o somatorio dos valores informados em vRetCSLL, vPis e vCofins;
    senao, retorna so' o valor de vRetCSLL. Mesma regra contraintuitiva ja
    documentada em dps_builder._montar_trib_fed, agora do lado da leitura
    (DANFSe) -- generalizada pra qualquer codigo com PIS ou COFINS retido
    (nao so' o codigo "1"), pelo mesmo motivo de `_valor_ou_zero_se_retido_pis_cofins`."""
    v_ret_csll = _texto_pis_cofins(nf, "vRetCSLL")
    algum_retido = tp_ret in _PIS_RETIDO_CODIGOS or tp_ret in _COFINS_RETIDO_CODIGOS
    if not algum_retido:
        return v_ret_csll
    partes = [_texto_pis_cofins(nf, t) for t in ("vPis", "vCofins")]
    valores_presentes = [Decimal(v) for v in ([v_ret_csll] + partes) if v is not None]
    if not valores_presentes:
        return None
    return str(sum(valores_presentes))


@dataclass
class DadosDanfse:
    """Todo campo que o DANFSe precisa, ja extraido e formatado -- montado
    UMA vez a partir do XML, a funcao de desenho so' consome isto (nunca
    volta a tocar o XML), pra deixar bem visivel que nada e' inventado depois
    da extracao."""

    # identificacao
    chave_acesso: Optional[str]
    numero_nfse: Optional[str]
    competencia: Optional[str]
    dh_processamento: Optional[str]
    numero_dps: Optional[str]
    serie_dps: Optional[str]
    dh_emissao_dps: Optional[str]
    tipo_emitente: Optional[str]
    situacao: Optional[str]
    finalidade: Optional[str]
    municipio_emissor: Optional[str]
    ambiente_gerador: Optional[str]
    tipo_ambiente: Optional[str]
    homologacao: bool
    # prestador
    prest_doc: Optional[str]
    prest_im: Optional[str]
    prest_fone: Optional[str]
    prest_nome: Optional[str]
    prest_municipio_uf: Optional[str]
    prest_email: Optional[str]
    prest_endereco: Optional[str]
    prest_simples_nacional: Optional[str]
    # tomador
    tem_tomador: bool
    toma_doc: Optional[str]
    toma_im: Optional[str]
    toma_fone: Optional[str]
    toma_nome: Optional[str]
    toma_municipio_uf: Optional[str]
    toma_email: Optional[str]
    toma_endereco: Optional[str]
    # destinatario
    tem_destinatario: bool
    destinatario_e_o_tomador: bool
    # servico
    codigo_tributacao: Optional[str]
    codigo_nbs: Optional[str]
    local_prestacao: Optional[str]
    descricao_codigo_tributacao: Optional[str]
    descricao_servico: Optional[str]
    # tributacao municipal
    tem_tributacao_municipal: bool
    tipo_tributacao_issqn: Optional[str]
    municipio_incidencia: Optional[str]
    regime_especial_issqn: Optional[str]
    bc_issqn: Optional[str]
    aliquota_aplicada: Optional[str]
    retencao_issqn: Optional[str]
    issqn_apurado: Optional[str]
    # tributacao federal
    v_ret_irrf: Optional[str]
    v_ret_cp: Optional[str]
    contribuicoes_sociais_retidas: Optional[str]
    v_pis_proprio: Optional[str]
    v_cofins_proprio: Optional[str]
    descricao_tp_ret_pis_cofins: Optional[str]
    # valor total
    v_serv: Optional[str]
    v_desc_incond: Optional[str]
    v_desc_cond: Optional[str]
    v_total_ret: Optional[str]
    v_liq: Optional[str]
    v_liq_total_ibscbs: Optional[str]
    # informacoes complementares
    info_complementares: Optional[str]
    totais_aproximados_tributos: str


def extrair_dados(nf: _NFSeXml) -> DadosDanfse:
    """Le o XML da NFS-e e devolve os dados ja formatados pro desenho --
    NENHUM valor aqui e' fabricado; ausencia no XML sempre vira None (que a
    camada de desenho converte pra "-" ou suprime a linha, conforme a regra
    especifica de cada campo, nunca um valor generico)."""
    tp_amb = nf.texto(_p("infNFSe", "DPS", "infDPS", "tpAmb"))
    tp_ret_pis_cofins = _texto_pis_cofins(nf, "tpRetPisCofins")

    return DadosDanfse(
        chave_acesso=nf.texto(_p("infNFSe", "id")),
        numero_nfse=nf.texto(_p("infNFSe", "nNFSe")),
        competencia=nf.texto(_p("infNFSe", "DPS", "infDPS", "dCompet")),
        dh_processamento=nf.texto(_p("infNFSe", "dhProc")),
        numero_dps=nf.texto(_p("infNFSe", "DPS", "infDPS", "nDPS")),
        serie_dps=nf.texto(_p("infNFSe", "DPS", "infDPS", "serie")),
        dh_emissao_dps=nf.texto(_p("infNFSe", "DPS", "infDPS", "dhEmi")),
        tipo_emitente=_descricao_dominio(_DESC_TP_EMIT, nf.texto(_p("infNFSe", "DPS", "infDPS", "tpEmit"))),
        situacao=nf.texto(_p("infNFSe", "cStat")),  # sem tabela de dominio confirmada -- mostra o codigo cru, nunca inventa descricao
        finalidade=nf.texto(_p("infNFSe", "DPS", "infDPS", "IBSCBS", "finNFSe")),
        municipio_emissor=nf.texto(_p("infNFSe", "emit", "enderNac", "xLocEmi")),
        ambiente_gerador=nf.texto(_p("infNFSe", "ambGer")),
        tipo_ambiente=tp_amb,
        homologacao=(tp_amb == "2"),
        prest_doc=_cnpj_cpf_nif(nf, "infNFSe/DPS/infDPS/prest"),
        prest_im=nf.texto(_p("infNFSe", "DPS", "infDPS", "prest", "IM")),
        prest_fone=nf.texto(_p("infNFSe", "DPS", "infDPS", "prest", "fone")),
        prest_nome=_truncar(nf.texto(_p("infNFSe", "DPS", "infDPS", "prest", "xNome")), 77),
        prest_municipio_uf=_municipio_uf(nf, "infNFSe/DPS/infDPS/prest"),
        prest_email=nf.texto(_p("infNFSe", "DPS", "infDPS", "prest", "email")),
        prest_endereco=_endereco(nf, "infNFSe/DPS/infDPS/prest"),
        prest_simples_nacional=_descricao_dominio(
            _DESC_OP_SIMP_NAC, nf.texto(_p("infNFSe", "DPS", "infDPS", "prest", "regTrib", "opSimpNac")), 37,
        ),
        tem_tomador=_tem_qualquer_dado(nf, "infNFSe/DPS/infDPS/toma"),
        toma_doc=_cnpj_cpf_nif(nf, "infNFSe/DPS/infDPS/toma"),
        toma_im=nf.texto(_p("infNFSe", "DPS", "infDPS", "toma", "IM")),
        toma_fone=nf.texto(_p("infNFSe", "DPS", "infDPS", "toma", "fone")),
        toma_nome=_truncar(nf.texto(_p("infNFSe", "DPS", "infDPS", "toma", "xNome")), 77),
        toma_municipio_uf=_municipio_uf(nf, "infNFSe/DPS/infDPS/toma"),
        toma_email=nf.texto(_p("infNFSe", "DPS", "infDPS", "toma", "email")),
        toma_endereco=_endereco(nf, "infNFSe/DPS/infDPS/toma"),
        tem_destinatario=_tem_qualquer_dado(nf, "infNFSe/DPS/infDPS/IBSCBS/dest"),
        destinatario_e_o_tomador=not _tem_qualquer_dado(nf, "infNFSe/DPS/infDPS/IBSCBS/dest"),
        codigo_tributacao=_concat(
            nf.texto(_p("infNFSe", "DPS", "infDPS", "serv", "cServ", "cTribNac")),
            nf.texto(_p("infNFSe", "cTribMun")), sep=" / ",
        ),
        codigo_nbs=nf.texto(_p("infNFSe", "DPS", "infDPS", "serv", "cServ", "cNBS")),
        local_prestacao=_truncar(nf.texto(_p("infNFSe", "xLocPrestacao")), 42),
        descricao_codigo_tributacao=_truncar(
            nf.texto(_p("infNFSe", "xTribMun")) or nf.texto(_p("infNFSe", "xTribNac")), 167,
        ),
        descricao_servico=_truncar(nf.texto(_p("infNFSe", "DPS", "infDPS", "serv", "cServ", "xDescServ")), 1297),
        tem_tributacao_municipal=nf.existe(_p("infNFSe", "DPS", "infDPS", "valores", "trib", "tribMun")),
        tipo_tributacao_issqn=_descricao_dominio(
            _DESC_TRIB_ISSQN, nf.texto(_p("infNFSe", "DPS", "infDPS", "valores", "trib", "tribMun", "tribISSQN")),
        ),
        municipio_incidencia=_truncar(nf.texto(_p("infNFSe", "xLocIncid")), 42),
        regime_especial_issqn=_descricao_dominio(
            _DESC_REG_ESP_TRIB, nf.texto(_p("infNFSe", "DPS", "infDPS", "prest", "regTrib", "regEspTrib")), 37,
        ),
        bc_issqn=_valor_monetario_br(nf.texto(_p("infNFSe", "valores", "vBC"))),
        aliquota_aplicada=nf.texto(_p("infNFSe", "valores", "pAliqAplic")),
        retencao_issqn=_descricao_dominio(
            _DESC_TP_RET_ISSQN, nf.texto(_p("infNFSe", "DPS", "infDPS", "valores", "trib", "tribMun", "tpRetISSQN")),
        ),
        issqn_apurado=_valor_monetario_br(nf.texto(_p("infNFSe", "valores", "vISSQN"))),
        v_ret_irrf=_valor_monetario_br(nf.texto(_p("infNFSe", "DPS", "infDPS", "valores", "trib", "tribFed", "vRetIRRF"))),
        v_ret_cp=_valor_monetario_br(nf.texto(_p("infNFSe", "DPS", "infDPS", "valores", "trib", "tribFed", "vRetCP"))),
        contribuicoes_sociais_retidas=_valor_monetario_br(_contribuicoes_sociais_retidas(nf, tp_ret_pis_cofins)),
        v_pis_proprio=_valor_monetario_br(_valor_ou_zero_se_retido_pis_cofins(nf, "vPis", tp_ret_pis_cofins)),
        v_cofins_proprio=_valor_monetario_br(_valor_ou_zero_se_retido_pis_cofins(nf, "vCofins", tp_ret_pis_cofins)),
        descricao_tp_ret_pis_cofins=_descricao_dominio(_DESC_TP_RET_PIS_COFINS, tp_ret_pis_cofins),
        v_serv=_valor_monetario_br(nf.texto(_p("infNFSe", "DPS", "infDPS", "valores", "vServPrest", "vServ"))),
        v_desc_incond=_valor_monetario_br(nf.texto(_p("infNFSe", "DPS", "infDPS", "valores", "vDescCondIncond", "vDescIncond"))),
        v_desc_cond=_valor_monetario_br(nf.texto(_p("infNFSe", "DPS", "infDPS", "valores", "vDescCondIncond", "vDescCond"))),
        v_total_ret=_valor_monetario_br(nf.texto(_p("infNFSe", "valores", "vTotalRet"))),
        v_liq=_valor_monetario_br(nf.texto(_p("infNFSe", "valores", "vLiq"))),
        v_liq_total_ibscbs=_valor_monetario_br(nf.texto(_p("infNFSe", "IBSCBS", "totCIBS", "vTotNF"))),
        info_complementares=_truncar(nf.texto(_p("infNFSe", "DPS", "infDPS", "serv", "infoCompl", "xInfComp")), 1997),
        # NT 2.4.5, nota 10: campo OBRIGATORIO mesmo sem dado equivalente no
        # XML -- e' um texto fixo de rodape, nao um "campo da NFS-e", entao
        # nao fere a regra de "nao inventar": a NT MANDA escrever isto.
        totais_aproximados_tributos=(
            "Totais Aproximados dos Tributos cfe. Lei nº 12.741/2012: "
            "Federais: - ; Estaduais: - ; Municipais: -"
        ),
    )


# --------------------------------------------------------------------------
# QR Code e marcas d'agua (NT 2.4.3 e 2.5.1/2.5.2)
# --------------------------------------------------------------------------
def _desenhar_qrcode(c: canvas.Canvas, chave_acesso: Optional[str]) -> None:
    if not chave_acesso:
        return
    url = f"https://www.nfse.gov.br/ConsultaPublica/?tpc=1&chave={chave_acesso}"
    widget = qr.QrCodeWidget(url)
    x1, y1, x2, y2 = widget.getBounds()
    tamanho_pt = 1.52 * cm
    desenho = Drawing(tamanho_pt, tamanho_pt, transform=[tamanho_pt / (x2 - x1), 0, 0, tamanho_pt / (y2 - y1), 0, 0])
    desenho.add(widget)
    renderPDF.draw(desenho, c, 17.48 * cm, _y_topo(1.67, 1.52))

    c.setFont(FONTE_CONTEUDO, 6)
    c.setFillColor(black)
    linhas = [
        "A autenticidade desta NFS-e",
        "pode ser verificada pela leitura deste código QR",
        "ou pela consulta da chave de acesso no portal nacional da NFS-e",
    ]
    y = _y_topo(3.36)
    for linha in linhas:
        c.drawString(15.80 * cm, y, linha)
        y -= 7


def _desenhar_marca_dagua(c: canvas.Canvas, texto: str) -> None:
    """NT 2.5.1/2.5.2: diagonal, min. 50pt, Arial normal, cinza K35."""
    c.saveState()
    c.setFont(FONTE_TITULO.replace("-Bold", ""), 50)
    c.setFillColor(_COR_MARCA_DAGUA)
    c.translate(LARGURA_PAGINA_CM / 2 * cm, ALTURA_PAGINA_CM / 2 * cm)
    c.rotate(45)
    c.drawCentredString(0, 0, texto)
    c.restoreState()


def _aviso_homologacao(c: canvas.Canvas) -> None:
    """NT 2.4.3, observação: 'NFS-e SEM VALIDADE JURÍDICA', negrito, 9pt,
    Arial, vermelho solido, abaixo do titulo -- so' quando tpAmb=2.
    Fica a meio caminho entre "DANFSe v2.0" (0.55) e "Documento Auxiliar
    da NFS-e" (1.25), com 0,35cm de vao pras 3 linhas nao se encostarem
    (9pt precisa de ~0,35cm entre linhas de base pra nao sobrepor)."""
    c.setFont(FONTE_TITULO, 9)
    c.setFillColor(red)
    c.drawCentredString((5.41 + 10.19 / 2) * cm, _y_topo(0.90), "NFS-e SEM VALIDADE JURÍDICA")


# --------------------------------------------------------------------------
# Montagem da pagina inteira
# --------------------------------------------------------------------------
_COL = [0.30, 5.41, 10.51, 15.62]  # NT 2.4.5: as 4 colunas de "Posição c/ relação à margem: Esq."
_LARG_COL = 5.09  # largura padrao de uma coluna de 1/4
_LARG_DUPLA = 10.19  # duas colunas juntas


def montar_danfse(dados: DadosDanfse) -> bytes:
    """Desenha o DANFSe inteiro (uma pagina A4) a partir de `DadosDanfse` ja
    extraidos -- esta funcao so' desenha, nunca decide o VALOR de um campo
    (isso e' trabalho de `extrair_dados`)."""
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    c.setTitle(f"DANFSe {dados.numero_nfse or ''}")
    d = _Desenhista(c)

    # Borda da pagina (NT 2.2.3: 1 ponto de espessura)
    c.setLineWidth(1)
    c.rect(MARGEM_CM * cm, MARGEM_CM * cm, (LARGURA_PAGINA_CM - 2 * MARGEM_CM) * cm, (ALTURA_PAGINA_CM - 2 * MARGEM_CM) * cm)

    # ---- CABEÇALHO ----
    d.retangulo_sombreado(0.30, 0.30, 20.40, 1.16)
    c.setFont(FONTE_TITULO, 9)
    c.setFillColor(black)
    c.drawCentredString((5.41 + 10.19 / 2) * cm, _y_topo(0.55), "DANFSe v2.0")
    c.setFont(FONTE_CONTEUDO, 9)
    c.drawCentredString((5.41 + 10.19 / 2) * cm, _y_topo(1.25), "Documento Auxiliar da NFS-e")
    if dados.homologacao:
        _aviso_homologacao(c)
    c.setFont(FONTE_CONTEUDO, 8)
    c.drawString(15.62 * cm, _y_topo(0.55), _texto_ou_tracos(dados.municipio_emissor))
    c.setFont(FONTE_CONTEUDO, 6)
    c.drawString(15.62 * cm, _y_topo(0.85), f"Ambiente: {_texto_ou_tracos(dados.ambiente_gerador)}")
    c.drawString(15.62 * cm, _y_topo(1.10), f"Tipo de ambiente: {_texto_ou_tracos(dados.tipo_ambiente)}")
    _desenhar_qrcode(c, dados.chave_acesso)

    # ---- DADOS DA NFS-e (2.1.2) ----
    # ATENCAO (achado real, docs/auditoria-2.md Onda 2 item 2): o Anexo I
    # (modelo visual oficial) NAO mostra nenhum titulo de bloco sombreado
    # pra esta secao -- "CHAVE DE ACESSO DA NFS-E" ja e' o primeiro rotulo,
    # sem faixa de titulo acima. A tabela 2.4.5 lista "DADOS DA NFS-e" com
    # Alt=2,84 (a altura do BLOCO INTEIRO, nao de uma faixa de titulo) --
    # confirmado comparando com o Anexo I (pagina 25 do PDF da NT).
    # Corrigido: sem titulo_bloco aqui, Chave de Acesso comeca direto em y0
    # com a altura exata da tabela (0,77), nao mais deslocada +0,30 (o que
    # tinha causado a sobreposicao "corrigida" erradamente numa sessao
    # anterior, reduzindo a altura em vez de remover o titulo fantasma).
    y0 = 1.48
    d.campo(
        "Chave de Acesso da NFS-e", dados.chave_acesso, 0.30, y0, 15.30, 0.77,
        rotulo_identificacao=True,
    )
    d.campo("Número da NFS-e", dados.numero_nfse, 0.30, y0 + 0.79, 5.09, 0.67, rotulo_identificacao=True)
    d.campo("Competência da NFS-e", dados.competencia, 5.41, y0 + 0.79, 5.09, 0.67, rotulo_identificacao=True)
    d.campo(
        "Data e Hora da Emissão da NFS-e", dados.dh_processamento, 10.51, y0 + 0.79, 5.09, 0.67,
        rotulo_identificacao=True,
    )
    d.campo("Número da DPS", dados.numero_dps, 0.30, y0 + 1.48, 5.09, 0.67, rotulo_identificacao=True)
    d.campo("Série da DPS", dados.serie_dps, 5.41, y0 + 1.48, 5.09, 0.67, rotulo_identificacao=True)
    d.campo(
        "Data e Hora da Emissão da DPS", dados.dh_emissao_dps, 10.51, y0 + 1.48, 5.09, 0.67,
        rotulo_identificacao=True,
    )
    d.campo(
        "Emitente da NFS-e", dados.tipo_emitente, 0.30, y0 + 2.17, 5.09, 0.67,
        sombreado=True, rotulo_identificacao=True,
    )
    d.campo("Situação da NFS-e", dados.situacao, 5.41, y0 + 2.17, 5.09, 0.67, rotulo_identificacao=True)
    d.campo("Finalidade", dados.finalidade, 10.51, y0 + 2.17, 5.09, 0.67, rotulo_identificacao=True)

    # ---- PRESTADOR / FORNECEDOR ----
    y = 4.34
    d.titulo_bloco("Prestador / Fornecedor", 0.30, y, 5.09, 0.63)
    d.campo("CNPJ / CPF / NIF", dados.prest_doc, 5.41, y, 5.09, 0.63)
    d.campo("Indicador Municipal (Inscrição)", dados.prest_im, 10.51, y, 5.09, 0.63)
    d.campo("Telefone", dados.prest_fone, 15.62, y, 5.09, 0.63)
    d.campo("Nome / Nome Empresarial", dados.prest_nome, 0.30, y + 0.64, 10.19, 0.63)
    d.campo("Município / Sigla UF", dados.prest_municipio_uf, 10.51, y + 0.64, 5.09, 0.63)
    # NT 2.4.5, nota 1: "Endereço" (Esq 0,30) e "Email" (Esq 10,51) sao a
    # MESMA linha -- achado real (docs/auditoria-2.md, Onda 2 item 2):
    # "Endereço" era extraido (`prest_endereco`) mas nunca desenhado, e
    # "Email" estava na coluna errada (0,30 em vez de 10,51).
    d.campo("Endereço", dados.prest_endereco, 0.30, y + 1.28, 10.19, 0.63)
    d.campo("Email", dados.prest_email, 10.51, y + 1.28, 10.19, 0.63)
    d.campo("Simples Nacional na Data de Competência", dados.prest_simples_nacional, 0.30, y + 1.92, 5.09, 0.63)

    # ---- TOMADOR / ADQUIRENTE ----
    y = 6.92
    if dados.tem_tomador:
        d.titulo_bloco("Tomador / Adquirente", 0.30, y, 5.09, 0.63)
        d.campo("CNPJ / CPF / NIF", dados.toma_doc, 5.41, y, 5.09, 0.63)
        d.campo("Indicador Municipal (Inscrição)", dados.toma_im, 10.51, y, 5.09, 0.63)
        d.campo("Telefone", dados.toma_fone, 15.62, y, 5.09, 0.63)
        d.campo("Nome / Nome Empresarial", dados.toma_nome, 0.30, y + 0.64, 10.19, 0.63)
        d.campo("Município / Sigla UF", dados.toma_municipio_uf, 10.51, y + 0.64, 5.09, 0.63)
        d.campo("Endereço", dados.toma_endereco, 0.30, y + 1.28, 10.19, 0.63)
        d.campo("Email", dados.toma_email, 10.51, y + 1.28, 10.19, 0.63)
    else:
        # NT 2.3.1: bloco todo suprimido, so' o aviso -- NUNCA fabricamos
        # dado de tomador que nao esteja na NFS-e.
        d.titulo_bloco("Tomador / Adquirente", 0.30, y, 20.40, 0.32)
        c.setFont(FONTE_CONTEUDO, 7)
        c.drawString(0.35 * cm, _y_topo(y + 0.32, 0.28), "TOMADOR/ADQUIRENTE DA OPERAÇÃO NÃO IDENTIFICADO NA NFS-e")

    # ---- DESTINATÁRIO DA OPERAÇÃO ----
    y = 8.86
    if dados.destinatario_e_o_tomador:
        d.titulo_bloco("Destinatário da Operação", 0.30, y, 20.40, 0.32)
        c.setFont(FONTE_CONTEUDO, 7)
        c.drawString(0.35 * cm, _y_topo(y + 0.32, 0.28), "O DESTINATÁRIO É O PRÓPRIO TOMADOR/ADQUIRENTE DA OPERAÇÃO")
    else:
        # dados reais do destinatario (grupo IBSCBS/dest) -- este app nao
        # gera IBSCBS hoje, entao na pratica sempre cai no ramo acima; o
        # ramo abaixo existe pra quando esse grupo passar a existir.
        d.titulo_bloco("Destinatário da Operação", 0.30, y, 5.09, 0.63)

    # ---- INTERMEDIÁRIO DA OPERAÇÃO ----
    # Achado real (docs/auditoria-2.md, Onda 2 item 5): este bloco e'
    # OBRIGATORIO pela NT (2.1.6), mas nunca tinha sido desenhado -- a
    # docstring do modulo AFIRMAVA que ele existia (divergencia
    # documentacao x codigo), e o "buraco" em branco no PDF entre
    # Destinatario e Servico Prestado era exatamente essa ausencia. Este
    # app nao gera dado de intermediario (nao ha grupo `interm` no
    # dps_builder), entao sempre usa a supressao da Nota 2 -- mesmo padrao
    # ja usado acima pro Tomador ausente.
    d.titulo_bloco("Intermediário da Operação", 0.30, y + 0.64, 20.40, 0.32)
    c.setFont(FONTE_CONTEUDO, 7)
    c.drawString(0.35 * cm, _y_topo(y + 0.96, 0.28), "INTERMEDIÁRIO DA OPERAÇÃO NÃO IDENTIFICADO NA NFS-e")

    # ---- SERVIÇO PRESTADO ----
    y = 12.74
    d.titulo_bloco("Serviço Prestado", 0.30, y, 5.09, 0.63)
    d.campo("Código de Tributação Nacional / Municipal", dados.codigo_tributacao, 5.41, y, 5.09, 0.63)
    d.campo("Código da NBS", dados.codigo_nbs, 10.51, y, 5.09, 0.63)
    d.campo("Local da Prestação / Sigla UF / País", dados.local_prestacao, 15.62, y, 5.09, 0.63)
    d.campo(None, dados.descricao_codigo_tributacao, 0.30, y + 0.65, 20.40, 0.38)
    d.campo("Descrição do Serviço", dados.descricao_servico, 0.30, y + 1.05, 20.40, 0.63)

    # ---- TRIBUTAÇÃO MUNICIPAL (ISSQN) ----
    y = 14.43
    if dados.tem_tributacao_municipal:
        d.titulo_bloco("Tributação Municipal (ISSQN)", 0.30, y, 5.09, 0.63)
        d.campo("Tipo de Tributação do ISSQN", dados.tipo_tributacao_issqn, 5.41, y, 5.09, 0.63)
        d.campo("Município / Sigla UF / País da Incidência do ISSQN", dados.municipio_incidencia, 10.51, y, 10.19, 0.63)
        d.campo("Regime Especial de Tributação do ISSQN", dados.regime_especial_issqn, 0.30, y + 0.65, 5.09, 0.63)
        d.campo("BC ISSQN", dados.bc_issqn, 0.30, y + 1.94, 5.09, 0.63)
        d.campo("Alíquota Aplicada", dados.aliquota_aplicada, 5.41, y + 1.94, 5.09, 0.63)
        d.campo("Retenção do ISSQN", dados.retencao_issqn, 10.51, y + 1.94, 5.09, 0.63)
        d.campo("ISSQN Apurado", dados.issqn_apurado, 15.62, y + 1.94, 5.09, 0.63)
    else:
        d.titulo_bloco("Tributação Municipal (ISSQN)", 0.30, y, 20.40, 0.32)
        c.setFont(FONTE_CONTEUDO, 7)
        c.drawString(0.35 * cm, _y_topo(y + 0.32, 0.28), "TRIBUTAÇÃO MUNICIPAL (ISSQN) - OPERAÇÃO NÃO SUJEITA AO ISSQN")

    # ---- TRIBUTAÇÃO FEDERAL (EXCETO CBS) ----
    y = 17.02
    d.titulo_bloco("Tributação Federal (exceto CBS)", 0.30, y, 5.09, 0.63)
    d.campo("IRRF", dados.v_ret_irrf, 5.41, y, 5.09, 0.63)
    d.campo("Contribuição Previdenciária - Retida", dados.v_ret_cp, 10.51, y, 5.09, 0.63)
    d.campo("Contribuições Sociais - Retidas", dados.contribuicoes_sociais_retidas, 15.62, y, 5.09, 0.63)
    d.campo("PIS - Débito Apuração Própria", dados.v_pis_proprio, 0.30, y + 0.65, 5.09, 0.63)
    d.campo("COFINS - Débito Apuração Própria", dados.v_cofins_proprio, 5.41, y + 0.65, 5.09, 0.63)
    d.campo("Descrição Contrib. Sociais - Retidas", dados.descricao_tp_ret_pis_cofins, 10.51, y + 0.65, 10.19, 0.63)

    # ---- TRIBUTAÇÃO IBS/CBS ----
    # Este app nao gera o grupo IBSCBS hoje (validacao suspensa
    # nacionalmente -- ver dps_builder.IBSCBS). O bloco fica no leiaute
    # (Anexo I exige a disposicao), mas 100% "-" (regra 12), nunca um
    # calculo nosso.
    y = 18.32
    d.titulo_bloco("Tributação IBS / CBS", 0.30, y, 20.40, 0.32)
    c.setFont(FONTE_CONTEUDO, 7)
    c.drawString(0.35 * cm, _y_topo(y + 0.32, 0.28), "- (grupo IBS/CBS com validação suspensa nacionalmente, não gerado nesta NFS-e)")

    # ---- VALOR TOTAL DA NFS-e ----
    y = 20.90
    d.titulo_bloco("Valor Total da NFS-e", 0.30, y, 5.09, 0.67)
    d.campo("Valor da Operação / Serviço", dados.v_serv, 5.41, y, 5.09, 0.67)
    d.campo("Desconto Incondicionado", dados.v_desc_incond, 10.51, y, 5.09, 0.67)
    d.campo("Desconto Condicionado", dados.v_desc_cond, 15.62, y, 5.09, 0.67)
    d.campo("Total das Retenções (ISSQN / Federais)", dados.v_total_ret, 0.30, y + 0.69, 5.09, 0.67)
    d.campo("Valor Líquido da NFS-e", dados.v_liq, 5.41, y + 0.69, 5.09, 0.67)
    d.campo("Total do IBS/CBS", "-", 10.51, y + 0.69, 5.09, 0.67)
    d.campo("Valor Líquido da NFS-e + IBS/CBS", dados.v_liq_total_ibscbs or dados.v_liq, 15.62, y + 0.69, 5.09, 0.67, sombreado=True)

    # ---- INFORMAÇÕES COMPLEMENTARES ----
    y = 22.27
    d.titulo_bloco("Informações Complementares", 0.30, y, 20.40, 0.39)
    texto_info = _concat(dados.info_complementares, dados.totais_aproximados_tributos, sep=" | ")
    d.campo(None, texto_info, 0.30, y + 0.41, 20.40, 4.5)

    # ---- CANHOTO ----
    y = 28.10
    d.linha_divisoria(0.30, y, 20.40)
    d.campo("Data Cientificação", None, 0.30, y, 5.09, 0.67)
    d.campo("Identificação e Assinatura", None, 5.41, y, 5.09, 0.67)
    d.campo("Nº NFS-e / Chave NFS-e", _concat(dados.numero_nfse, dados.chave_acesso, sep=" / "), 10.51, y, 10.19, 0.67)

    if dados.situacao and dados.situacao.strip().upper() not in ("100", "AUTORIZADA"):
        pass  # so' desenhamos marca d'agua explicitamente via montar_danfse_cancelada/substituida abaixo

    c.showPage()
    c.save()
    return buffer.getvalue()


def montar_danfse_pdf(xml_nfse_bytes: bytes, *, cancelada: bool = False, substituida: bool = False) -> bytes:
    """Ponto de entrada publico: XML da NFS-e (bytes) -> PDF do DANFSe
    (bytes). `cancelada`/`substituida` disparam a marca d'agua (NT 2.5.1/
    2.5.2) -- vem de fora (repo.py sabe o status da nota), nao do XML, ja
    que o XML da NFS-e em si nao muda quando ela e' cancelada depois."""
    nf = carregar_nfse(xml_nfse_bytes)
    dados = extrair_dados(nf)
    if not dados.chave_acesso:
        raise DadosIncompletosParaDanfse(
            "O XML da NFS-e não tem chave de acesso — não é possível montar o DANFSe."
        )
    pdf_bytes = montar_danfse(dados)

    if cancelada or substituida:
        # Reabre o PDF gerado e desenha a marca d'agua por cima (mais
        # simples que passar o texto pra dentro de `montar_danfse` e
        # espalhar a condicional por toda a funcao).
        from pypdf import PdfReader, PdfWriter

        leitor = PdfReader(BytesIO(pdf_bytes))
        pagina = leitor.pages[0]

        buffer_marca = BytesIO()
        c = canvas.Canvas(buffer_marca, pagesize=A4)
        _desenhar_marca_dagua(c, "CANCELADA" if cancelada else "SUBSTITUÍDA")
        c.save()
        buffer_marca.seek(0)
        pagina_marca = PdfReader(buffer_marca).pages[0]
        pagina.merge_page(pagina_marca)

        escritor = PdfWriter()
        escritor.add_page(pagina)
        saida = BytesIO()
        escritor.write(saida)
        pdf_bytes = saida.getvalue()

    return pdf_bytes
