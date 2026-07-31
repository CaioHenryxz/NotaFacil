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
from decimal import ROUND_HALF_EVEN, ROUND_HALF_UP, Decimal
from typing import List, Optional

from cryptography.hazmat.primitives.serialization import Encoding
from lxml import etree
from signxml import XMLSigner, methods

NS = "http://www.sped.fazenda.gov.br/nfse"
NSMAP = {None: NS}

# Limites de tamanho confirmados por leitura direta do XSD oficial baixado
# (NFSe-ESQUEMAS_XSD-v1.01-20260209, arquivo tiposSimples_v1.01.xsd) -- nao
# adivinhados nem de fonte secundaria. docs/auditoria.md, Bloco 3, item 4:
# "textos longos... nao confirmei o limite exato do XSD, ficou pendente".
TAMANHO_MAXIMO_DESCRICAO_SERVICO = 2000  # xDescServ, tipo TSDesc2000 (min 1, max 2000)
TAMANHO_MAXIMO_NOME = 300  # xNome do tomador/prestador, tipo TSNomeRazaoSocial (min 1, max 300)

# Caracteres de controle proibidos em qualquer documento XML 1.0 (mesmo
# escapados) -- ver https://www.w3.org/TR/xml/#charsets, "Char" ::= ...
# exclui 0x0-0x8, 0xB-0xC, 0xE-0x1F. Acento, cedilha, apostrofo, "&", emoji
# etc. NAO entram aqui -- sao caracteres XML validos (lxml escapa "&"/"<"
# sozinho na serializacao); isto e' so' uma rede de seguranca contra um
# controle invisivel colado sem querer (docs/auditoria.md, Bloco 3, item 3).
_CARACTERES_INVALIDOS_XML = "".join(chr(c) for c in list(range(0x00, 0x09)) + list(range(0x0B, 0x0D)) + list(range(0x0E, 0x20)))
_TABELA_REMOCAO_XML = str.maketrans("", "", _CARACTERES_INVALIDOS_XML)


class CampoMuitoLongo(ValueError):
    """Mensagem ja pronta pra mostrar na tela -- nao precisa de traducao."""


def _texto_seguro_xml(valor: str) -> str:
    """Remove caracteres de controle que quebrariam a serializacao do XML
    (lxml levanta ValueError se .text tiver um deles). Nao mexe em Unicode
    "de verdade" (acento, cedilha, apostrofo, emoji) -- so' o punhado de
    bytes de controle que nenhum editor de texto normal insere de proposito."""
    return valor.translate(_TABELA_REMOCAO_XML)


def _exigir_tamanho_maximo(valor: str, maximo: int, nome_campo: str) -> None:
    if len(valor) > maximo:
        raise CampoMuitoLongo(
            f'{nome_campo} tem {len(valor)} caracteres — o máximo aceito é {maximo}. '
            "Encurte o texto antes de emitir (a Receita rejeitaria a nota)."
        )


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
    # NOTA (docs/auditoria.md, conformidade de leiaute — grupo "toma"): o XSD
    # oficial marca "toma" como minOccurs="0" (opcional pro schema — existe o
    # caso legitimo de "consumidor final nao identificado" em alguns
    # municipios/servicos). Este app NAO usa essa flexibilidade de proposito:
    # todo cliente de um medico PJ (paciente pessoa fisica ou convenio pessoa
    # juridica) e' sempre um tomador identificavel por CPF/CNPJ, entao
    # `montar_dps_xml` sempre gera "toma" incondicionalmente — nao existe
    # fluxo de "nota avulsa sem tomador" no app. Da mesma forma, o campo
    # `cNaoNIF` (motivo de nao informar NIF de tomador ESTRANGEIRO sem
    # CPF/CNPJ/NIF brasileiro) nunca se aplica aqui: o publico do app e'
    # 100% de tomadores brasileiros com CPF ou CNPJ.


@dataclass
class IBSCBS:
    """Estrutura reservada pro grupo `<IBSCBS>` (Reforma Tributaria do
    Consumo — NT-004 v2.0, 10/12/2025 + evolucoes na NT-009). NAO
    instanciado/usado em lugar nenhum ainda: a propria NT-004 v2.0 diz que "as
    validacoes dos dados relativos aos grupos 'IBSCBS' [...] ainda nao estarao
    sendo aplicadas [...] ficando temporariamente suspensas", e nao existe
    cronograma publicado (confirmado por leitura das NT-004, NT-007 e NT-009 —
    as tres repetem a mesma promessa de "cronograma sera publicado em breve";
    checado de novo em jul/2026, ainda sem data). Ver docs/auditoria.md, Bloco
    1 item 2 — item de monitoramento manual, nao mecanismo automatico.

    Campos confirmados por pesquisa (nomes/semantica, nao a estrutura XSD
    completa — soh reservar o espaco, nao implementar):
      - finNFSe: finalidade da NFS-e (indicador de operacao dentro do grupo
        IBSCBS, tabela propria do leiaute da reforma).
      - cIndOp: indicador da operacao, segundo a tabela do Anexo VII
        (AnexoVII-IndOp_IBSCBS) publicada junto com a NT.
      - indDest: destinatario dos servicos — "0" quando tomador da NFS-e e'
        quem efetivamente recebe o servico, "1" quando o destinatario real e'
        outra pessoa fisica/juridica ou estabelecimento diferente do tomador.
      - valores: os proprios valores de IBS/CBS (grupo aninhado, campos ainda
        nao mapeados aqui — fora de escopo enquanto a validacao seguir
        suspensa).

    QUANDO isso deixar de ser opcional (cronograma publicado): criar os
    campos reais aqui, adicionar um `Optional[IBSCBS]` em `Servico` ou
    `DadosDPS`, e montar o grupo dentro de `valores` (irmao de `trib`) em
    `montar_dps_xml` — soh entao. Ate la, esta classe existe soh como
    lembrete estrutural de onde isso vai entrar; nao remover mesmo estando
    sem uso (linter pode reclamar — e' proposital).
    """
    fin_nfse: Optional[str] = None
    c_ind_op: Optional[str] = None
    ind_dest: Optional[str] = None


@dataclass
class Servico:
    # cTribNac (LC 116/2003): 6 digitos = Item(2) + Subitem(2) + Desdobro Nacional(2)
    codigo_tributacao_nacional: str
    # cTribMun: OPCIONAL (minOccurs="0" em TCCServ, tiposComplexos_v1.01.xsd) --
    # desdobramento MUNICIPAL do ISSQN, 3 digitos numericos quando informado
    # (TCCodTribMun, tiposSimples_v1.01.xsd: pattern "[0-9]{3}"). Confirmado
    # em auditoria (docs/auditoria-2.md, secao 8.1) que o app gerava isso com
    # 10 digitos -- estruturalmente invalido pro XSD oficial. NAO e' um
    # "cTribNac com zeros a mais": e' um codigo proprio de cada prefeitura,
    # sem lista nacional -- se a prefeitura nao publicar/exigir um desdobro
    # proprio, o campo fica de fora do XML (ver `_montar_servico` abaixo).
    # Nunca adivinhar um valor -- um cTribMun invalido gera rejeicao E0314
    # ("codigo nao existe ou nao e' administrado pelo municipio"). Passe None
    # (ou "") quando a prefeitura nao tiver desdobro proprio -- quem monta
    # este dataclass (app/core/fila.py) decide isso a partir do cadastro.
    codigo_tributacao_municipal: Optional[str]
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

    # --- Retencoes federais (grupo tribFed, opcional) -- docs/auditoria.md,
    # Bloco 1.6/2.4: convenio/plano de saude pagando prestador PJ costuma
    # reter IRRF (Lei 7.450/85 art. 53-II + RIR/2018 art. 714). Cada valor
    # abaixo e' o R$ JA CALCULADO (percentual * valor do servico) -- quem
    # monta o Servico (app/core/fila.py) faz essa conta a partir do cadastro
    # do tomador ou de uma sobrescrita so' desta nota. Ver
    # `_montar_trib_fed` pra como isso vira XML (inclusive a regra
    # contraintuitiva de somar PIS+COFINS+CSLL num unico campo).
    valor_retido_irrf: Optional[str] = None     # vRetIRRF
    valor_retido_pis: Optional[str] = None      # soma dentro de vRetCSLL, NAO tem campo proprio no XML
    valor_retido_cofins: Optional[str] = None   # idem
    valor_retido_csll: Optional[str] = None     # idem
    valor_retido_inss: Optional[str] = None     # vRetCP (contribuicao previdenciaria)


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
    # docs/auditoria.md, Bloco 7 item 6: era literalmente o nome do script
    # descartavel do Sprint 0 -- toda nota real ficaria se identificando pra
    # sempre como um teste antigo. Mesmo valor ja usado em
    # app.fiscal.evento_builder (cancelamento), pra nao divergir entre os
    # dois documentos gerados pelo mesmo produto.
    versao_aplicativo: str = "emissor-nfse-0.1"


# --------------------------------------------------------------------------
# Helpers de formatacao (o XSD e estrito quanto a padrao de string)
# --------------------------------------------------------------------------


def _valor_monetario(x) -> str:
    """Formata para o padrao TSDec15V2/TSDec1V2: '0', '0.00' ou '[1-9]\\d*(\\.\\d{2})?'."""
    d = Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return str(d)


def _valor_monetario_half_even(x) -> str:
    """RESERVADO pro futuro grupo IBSCBS (`vPIS`/`vCOFINS` — valor DEVIDO, ver
    `IBSCBS` acima e `_montar_trib_fed` pro contraste com retencao). NAO
    chamado em lugar nenhum hoje porque esses campos nao sao gerados enquanto
    IBSCBS estiver com validacao suspensa.

    A NT-007 (SE/CGNFS-e, vigente desde 09/02/2026) documenta, especificamente
    pra `vPIS`/`vCOFINS`, arredondamento bancario (half-even — "banker's
    rounding", tambem chamado ROUND_HALF_EVEN) com tolerancia de R$ 0,01 na
    comparacao/validacao desses valores — diferente do arredondamento
    comercial (ROUND_HALF_UP) que `_valor_monetario` usa pra `vServ`/`pAliq`
    (e que continua correto pra esses dois campos: a regra do half-even e'
    especifica de vPIS/vCOFINS, nao geral). NAO usar esta funcao pra nenhum
    outro campo por analogia — cada campo do leiaute pode ter sua propria
    regra de arredondamento, confirmar antes de reaproveitar."""
    d = Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)
    return str(d)


def _dentro_da_tolerancia_vpis_vcofins(valor_calculado: Decimal, valor_informado: Decimal) -> bool:
    """RESERVADO junto com `_valor_monetario_half_even` (mesmo motivo — sem
    uso ate o grupo IBSCBS sair da validacao suspensa). A NT-007 tolera ate
    R$ 0,01 de diferenca entre o valor calculado pelo emissor e o valor
    aceito pela validacao da Receita pra vPIS/vCOFINS, por causa de
    divergencia de arredondamento entre sistemas diferentes."""
    return abs(valor_calculado - valor_informado) <= Decimal("0.01")


def _tipo_inscricao(documento: str) -> str:
    """1=CPF, 2=CNPJ (regra do DPS/NFS-e Nacional; invertida em relacao a NF-e)."""
    return "1" if len(documento) == 11 else "2"


def _pAliq_deve_ser_omitido(prestador: "Prestador", servico: "Servico") -> bool:
    """Decide se o campo pAliq (aliquota do ISS) deve ser OMITIDO da nota —
    docs/auditoria.md, Bloco 2.3 ("médico do Simples Nacional recebendo nota
    com aliquota que não deveria aparecer nela").

    Base normativa (Anexo I - SEFIN_ADN-DPS_NFSe-SNNFSe v1.00, 10/12/2025,
    aba "RN DPS_NFS-e" — planilha oficial de regras de negocio da DPS,
    gov.br/nfse/biblioteca/documentacao-tecnica/documentacao-atual):

      - Regra E1302 (prestador MEI, opSimpNac=2): "Exceto para o campo vLiq,
        não é permitido informar os demais campos do grupo valores para
        prestador de serviço optante do simples nacional do tipo MEI." —
        proíbe pAliq de forma praticamente absoluta pro MEI, sempre.
      - Regras E0625 (município com convênio ATIVO) e E0631 (município SEM
        convênio ativo) — prestador ME/EPP (opSimpNac=3), apuração do ISSQN
        pelo Simples Nacional, SEM retenção (tpRetISSQN=1): "Não é permitido
        informar alíquota quando não há indicação de retenção do ISSQN...
        para o prestador de serviço ME/EPP... com apuração do ISSQN pelo
        simples nacional." — as duas regras juntas cobrem TODOS os
        municípios (ativos ou não), sempre proibindo pAliq nesse caso.
      - EXCEÇÃO que este helper também respeita: quando HÁ retenção
        (tpRetISSQN=2 Retido pelo tomador, ou 3 Retido pelo intermediário),
        as regras E0619/E0621 INVERTEM a exigência — pAliq passa a ser
        OBRIGATÓRIO (alíquota mínima de 1,8%) mesmo pro optante. Não
        confirmamos uma Nota Técnica numerada tratando esse ponto
        especificamente — a fonte primária é a própria planilha de regras de
        negócio acima. Ver também docs/auditoria.md, Bloco 1.6: o campo
        tpRetISSQN ainda não tem UI pra virar "2"/"3" na prática — até isso
        existir, esse ramo (retenção) nunca é de fato exercitado.

    Base legal "de cima" (fora do leiaute técnico): LC 123/2006 (Estatuto
    Nacional da ME/EPP — Simples Nacional), art. 13, VIII (o ISS é um dos
    tributos recolhidos dentro do DAS, documento único) e art. 18, caput (o
    valor devido é apurado por alíquota EFETIVA calculada sobre a receita
    bruta acumulada do optante, não "por nota" com uma alíquota que o
    prestador escolhe) — a LC não veda expressamente "destacar" o ISS numa
    nota; a vedação formal/técnica vem das regras de negócio do leiaute
    citadas acima, não de um artigo de lei com essa redação literal."""
    optante_simples = prestador.opcao_simples_nacional in ("2", "3")
    ha_retencao = servico.tipo_retencao_issqn in ("2", "3")
    return optante_simples and not ha_retencao


_CODIGOS_TP_RET_PIS_COFINS = {
    # (pis_retido, cofins_retido, csll_retido) -> codigo TSTipoRetPISCofins
    # (tiposSimples_v1.01.xsd) -- as 8 combinacoes cobrem os 8 codigos
    # inequivocos da enumeracao oficial (ver docstring de _montar_trib_fed).
    (False, False, False): "0",
    (True, True, True): "3",
    (True, True, False): "4",
    (True, False, False): "5",
    (False, True, False): "6",
    (False, True, True): "7",
    (False, False, True): "8",
    (True, False, True): "9",
}


def _codigo_tp_ret_pis_cofins(pis_retido: bool, cofins_retido: bool, csll_retido: bool) -> str:
    """Logica de mapeamento ja correta e testada (tests/test_dps_builder.py)
    -- mas SEM uso ativo em `_montar_trib_fed` no momento, porque emitir
    tpRetPisCofins exige tambem um <CST> que este app ainda nao decidiu (ver
    comentario em `_montar_trib_fed`). Nao remover -- e' o que vai ser
    chamado assim que essa decisao for tomada."""
    return _CODIGOS_TP_RET_PIS_COFINS[(pis_retido, cofins_retido, csll_retido)]


def _montar_trib_fed(trib: etree._Element, s: "Servico") -> None:
    """Monta o grupo opcional <tribFed> (retenções federais) dentro de
    <trib>, quando houver QUALQUER retenção federal na nota — docs/auditoria.md,
    Bloco 1.6/2.4: convênio/plano de saúde pagando prestador PJ geralmente
    retém IRRF na fonte (Lei 7.450/85, art. 53-II + RIR/2018 — Decreto
    9.580/2018, art. 714), cenário confirmado pela Solução de Consulta Receita
    Federal SRRF06/DISIT nº 6021/2018 (trata especificamente de clínicas
    credenciadas recebendo de convênio).

    Campos (grupo TCTribFederal, confirmado por inspeção direta do XSD
    oficial v1.01):
      - vRetIRRF: valor retido de IRRF.
      - vRetCSLL: **regra contraintuitiva da NT-007** — este campo NÃO é "só
        CSLL". A Nota Técnica determina explicitamente que valores retidos de
        PIS, COFINS e CSLL devem ser SOMADOS e informados juntos aqui, apesar
        do nome do campo sugerir só CSLL. NÃO "corrija" isso achando que é bug
        — é exatamente assim que o leiaute nacional pede. Se um dia isso
        mudar (ex.: quando IBSCBS virar obrigatório e os tributos passarem a
        ter campos próprios), vai ser uma mudança de leiaute, não uma
        correção deste código.
      - vRetCP: valor retido de contribuição previdenciária (INSS).
      - tpRetPisCofins: indicador de retenção de PIS/COFINS/CSLL. CONFIRMADO
        (docs/auditoria-2.md, Onda 1 item 2) contra a documentação OFICIAL do
        próprio XSD (`tiposSimples_v1.01.xsd`, tipo `TSTipoRetPISCofins`,
        anotação `<xs:documentation>`) — não é mais suposição por analogia:
            0 PIS/COFINS/CSLL Não Retidos   3 PIS/COFINS/CSLL Retidos
            4 PIS/COFINS Retidos, CSLL Não  5 só PIS Retido
            6 só COFINS Retido              7 COFINS/CSLL Retidos, PIS Não
            8 só CSLL Retido                9 PIS/CSLL Retidos, COFINS Não
        (Os códigos 1 e 2 também existem na enumeração oficial — "PIS/COFINS
        Retidos"/"Não Retidos" — mas NÃO mencionam CSLL, então são ambíguos
        pro nosso caso; usamos sempre um dos 8 códigos acima, que descrevem
        as 8 combinações de PIS/COFINS/CSLL sem ambiguidade nenhuma.)
        ATENÇÃO: a suposição ANTERIOR deste código (`"1"`=não retido,
        `"2"`=retido, por analogia errada com `tpRetISSQN`) estava com a
        polaridade **invertida** — "1" na verdade significa retido, não o
        contrário. Corrigido nesta revisão.

    IMPORTANTE — não confundir com `vPIS`/`vCOFINS` (campos DIFERENTES, do
    grupo IBSCBS, que representam o valor DEVIDO pelo prestador, nunca o
    retido — a própria NT-007 alerta que esse é um erro comum de outros
    sistemas). Este builder não gera `vPIS`/`vCOFINS` porque o grupo IBSCBS
    está com validação suspensa hoje (ver docs/auditoria.md, Bloco 1.2)."""
    pis_retido = s.valor_retido_pis is not None
    cofins_retido = s.valor_retido_cofins is not None
    csll_retido = s.valor_retido_csll is not None
    pis_cofins_csll_retido = sum(
        Decimal(str(v)) for v in (s.valor_retido_pis, s.valor_retido_cofins, s.valor_retido_csll) if v is not None
    ) if any((pis_retido, cofins_retido, csll_retido)) else None

    tem_alguma_retencao_federal = any(
        v is not None for v in (s.valor_retido_irrf, pis_cofins_csll_retido, s.valor_retido_inss)
    )
    if not tem_alguma_retencao_federal:
        return

    trib_fed = _el(trib, "tribFed")
    # tpRetPisCofins NAO pode ser filho direto de tribFed -- confirmado por
    # validacao de schema real (docs/auditoria-2.md, Onda 1 item 2): o XSD
    # oficial (TCTribFederal, tiposComplexos_v1.01.xsd) so' aceita
    # tpRetPisCofins DENTRO do subgrupo opcional <piscofins>
    # (TCTribOutrosPisCofins), que por sua vez EXIGE um campo <CST> (Código
    # de Situação Tributária do PIS/COFINS -- minOccurs implicito "1", sem
    # default) -- uma classificacao fiscal SEPARADA (regime proprio de
    # PIS/COFINS do prestador pra este servico, ex. "01 Operação Tributável
    # com Alíquota Básica"), que este app nunca coletou nem tem base pra
    # decidir sozinho. Ate essa decisao ser tomada (ver conversa com o
    # usuario), NAO emitimos tpRetPisCofins pra nao gerar XML invalido --
    # vRetCSLL/vRetIRRF/vRetCP continuam validos como filhos diretos (unico
    # campo afetado por esta descoberta e' o proprio tpRetPisCofins).
    # ORDEM IMPORTA (xs:sequence, TCTribFederal): piscofins, vRetCP,
    # vRetIRRF, vRetCSLL -- confirmado por validacao de schema real
    # (docs/auditoria-2.md, Onda 1 item 2: gerar fora desta ordem faz o XSD
    # rejeitar o elemento seguinte inteiro, ex. "vRetIRRF nao esperado").
    if s.valor_retido_inss is not None:
        _el(trib_fed, "vRetCP", _valor_monetario(s.valor_retido_inss))
    if s.valor_retido_irrf is not None:
        _el(trib_fed, "vRetIRRF", _valor_monetario(s.valor_retido_irrf))
    if pis_cofins_csll_retido is not None:
        _el(trib_fed, "vRetCSLL", _valor_monetario(pis_cofins_csll_retido))


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
#
# Conferencia campo-a-campo contra o XSD oficial v1.01-20260209 (confirmado
# em jul/2026 como ainda o pacote vigente em Producao — nenhum XSD mais novo
# publicado; docs/auditoria.md tem o detalhe da pesquisa) de tudo que
# `infDPS` exige:
#   tpAmb, dhEmi, verAplic, serie, nDPS, dCompet, tpEmit, cLocEmi  -> gerados
#   prest (CNPJ/CPF + regTrib.opSimpNac + regTrib.regEspTrib)      -> gerado
#   toma (CNPJ/CPF + xNome)             -> gerado incondicionalmente, ver
#                                           docstring de `Tomador` acima
#   serv.locPrest.cLocPrestacao         -> gerado
#   serv.cServ (cTribNac + xDescServ)   -> gerado (cNBS tambem, exigido pelas
#                                           regras de negocio mesmo nao sendo
#                                           o par minimo do xsd:sequence;
#                                           cTribMun e' minOccurs="0" de
#                                           verdade -- so' sai se informado)
#   valores.vServPrest.vServ           -> gerado
#   valores.trib.tribMun + totTrib      -> gerado
# Unico campo com obrigatoriedade condicional que este app nao gera nunca:
# `cNaoNIF` — s0 se aplica a tomador ESTRANGEIRO sem CPF/CNPJ/NIF brasileiro,
# cenario que nao existe no publico deste app (ver `Tomador` acima).


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
    nome_tomador = _texto_seguro_xml(t.nome)
    _exigir_tamanho_maximo(nome_tomador, TAMANHO_MAXIMO_NOME, "O nome do tomador")
    _el(toma, "xNome", nome_tomador)
    if t.email:
        _el(toma, "email", t.email)

    # --- serv (TCServ) ---
    serv = _el(inf, "serv")
    s = dados.servico
    loc_prest = _el(serv, "locPrest")
    _el(loc_prest, "cLocPrestacao", s.codigo_municipio_prestacao)
    c_serv = _el(serv, "cServ")
    _el(c_serv, "cTribNac", s.codigo_tributacao_nacional)
    # cTribMun e' OPCIONAL (minOccurs="0") -- so' sai no XML se a prefeitura
    # tiver desdobro proprio confirmado (ver comentario em `Servico` acima).
    if s.codigo_tributacao_municipal:
        _el(c_serv, "cTribMun", s.codigo_tributacao_municipal)
    descricao_servico = _texto_seguro_xml(s.descricao)
    _exigir_tamanho_maximo(descricao_servico, TAMANHO_MAXIMO_DESCRICAO_SERVICO, "A descrição do serviço")
    _el(c_serv, "xDescServ", descricao_servico)
    _el(c_serv, "cNBS", s.codigo_nbs)

    # --- valores (TCInfoValores) ---
    valores = _el(inf, "valores")
    v_serv_prest = _el(valores, "vServPrest")
    _el(v_serv_prest, "vServ", _valor_monetario(s.valor))
    trib = _el(valores, "trib")
    trib_mun = _el(trib, "tribMun")
    _el(trib_mun, "tribISSQN", "1")  # 1 = Operacao tributavel
    _el(trib_mun, "tpRetISSQN", s.tipo_retencao_issqn)
    # ISS de quem e' optante do Simples Nacional (MEI ou ME/EPP) e' recolhido
    # dentro do DAS, por aliquota efetiva calculada sobre a receita bruta
    # acumulada -- NUNCA "por nota". Ver _pAliq_deve_ser_omitido pra base
    # normativa completa (regras E1302/E0625/E0631 do leiaute + LC 123/2006).
    if _pAliq_deve_ser_omitido(dados.prestador, s):
        pass
    elif s.aliquota_iss is not None:
        _el(trib_mun, "pAliq", _valor_monetario(s.aliquota_iss))
    _montar_trib_fed(trib, s)
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
