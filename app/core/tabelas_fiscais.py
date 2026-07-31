"""Tabelas de referencia pra sugerir valores ao usuario -- nunca usadas como
fallback silencioso nem chumbadas na montagem do XML (`app.fiscal.dps_builder`
sempre recebe o codigo que o usuario efetivamente escolheu/digitou).

docs/auditoria.md, Bloco 2 item 2 / Bloco "Plano de correcao" item 11:
"codigo de tributacao nacional sem sugestao/lista pra evitar erro de
digitacao" -- o campo era texto livre sem nenhuma ajuda, e cTribNac errado
(2 digitos trocados) so seria percebido na rejeicao da Receita.
"""
from __future__ import annotations

# cTribNac (LC 116/2003, item 4 "Servicos de saude, assistencia medica e
# congeneres") -- lista "Codigos de Tributacao Nacional NFS-e", vigente a
# contar de 24/11/2025 (fonte secundaria, reproduzindo a tabela oficial do
# Comitê Gestor da NFS-e; nao e' o download direto do gov.br, mas confere com
# o unico codigo ja confirmado por 2 fontes de mercado na auditoria original,
# 040101 = Medicina). Cada item: (codigo de 6 digitos, descricao curta).
# Curada pro publico deste app (medicos PJ e clinicas correlatas) -- nao
# inclui outros itens da lista completa (ex.: item 5 veterinaria).
CODIGOS_TRIBUTACAO_NACIONAL_SAUDE: list[tuple[str, str]] = [
    ("040101", "Medicina"),
    ("040102", "Biomedicina"),
    ("040201", "Análises clínicas e congêneres"),
    ("040202", "Patologia e congêneres"),
    ("040203", "Eletricidade médica (eletroestimulação, cardioversão etc.)"),
    ("040204", "Radioterapia, quimioterapia e congêneres"),
    ("040205", "Ultrassonografia, ressonância, radiologia, tomografia"),
    ("040301", "Hospitais e congêneres"),
    ("040302", "Laboratórios e congêneres"),
    ("040303", "Clínicas, prontos-socorros, ambulatórios e congêneres"),
    ("040401", "Instrumentação cirúrgica"),
    ("040501", "Acupuntura"),
    ("040601", "Enfermagem, inclusive serviços auxiliares"),
    ("040701", "Serviços farmacêuticos"),
    ("040801", "Terapia ocupacional"),
    ("040802", "Fisioterapia"),
    ("040803", "Fonoaudiologia"),
    ("040901", "Terapias de qualquer espécie (físico, orgânico, mental)"),
    ("041001", "Nutrição"),
    ("041101", "Obstetrícia"),
    ("041201", "Odontologia"),
    ("041301", "Ortóptica"),
    ("041401", "Próteses sob encomenda"),
    ("041501", "Psicanálise"),
    ("041601", "Psicologia"),
    ("041801", "Inseminação artificial, fertilização in vitro"),
    ("041901", "Bancos de sangue, leite, pele, olhos, óvulos, sêmen"),
    ("042001", "Coleta de sangue, leite, tecidos, sêmen, órgãos"),
    ("042101", "Unidade de atendimento/assistência/tratamento móvel"),
    ("042201", "Planos de medicina de grupo/convênios de assistência"),
    ("042301", "Outros planos de saúde (terceiros credenciados/cooperados)"),
]

# cTribMun (desdobro MUNICIPAL do ISSQN, 3 dígitos quando informado, TCCodTribMun
# em tiposSimples_v1.01.xsd -- ver docs/auditoria-2.md, secao 8.1) NAO tem uma
# tabela de sugestao aqui, ao contrario do cTribNac acima. Pesquisado
# especificamente pra Sao Jose dos Campos/SP (municipio de referencia deste
# app) em jul/2026: nao existe lista publica confirmada de codigos de 3
# digitos pra medicina nem pra nenhum outro servico -- a documentacao de
# integradores de mercado (nfe.io, CIGAM, TecnoSpeed) so descreve o FORMATO
# do campo e recomenda "consulte a lista da sua prefeitura", sem publicar a
# lista de SJC em si. cTribMun e' OPCIONAL (minOccurs="0") e cada prefeitura
# publica (ou nao) seu proprio desdobro -- um codigo certo numa cidade pode
# nao existir em outra (rejeicao E0314: "codigo nao existe ou nao e'
# administrado pelo municipio"). Por isso: NUNCA inventar um valor aqui.
# Se/quando a Prefeitura de SJC confirmar (ou a API de Parametros Municipais
# do Sistema Nacional devolver) um codigo real pra medicina, adicionar uma
# tabela `CODIGOS_TRIBUTACAO_MUNICIPAL_SJC_SAUDE` no mesmo formato acima --
# ate la, o campo fica em branco por padrao (ver app.fiscal.dps_builder.Servico
# .codigo_tributacao_municipal).
