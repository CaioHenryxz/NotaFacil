# Exemplos fiscais — leia isto antes de mandar qualquer coisa pro contador

## ⚠️ Isto aqui é uma DEMONSTRAÇÃO TÉCNICA, não um documento fiscal de verdade

Todo XML e PDF desta pasta foi gerado com dados **fictícios** (CNPJ de
teste, "Dr. Teste", "Unimed SJC" etc.) só pra provar, campo a campo, que o
código do app (`app/fiscal/dps_builder.py` e `app/fiscal/danfse_builder.py`)
monta o documento certo pra cada situação. **Nenhum arquivo daqui deve ser
enviado pro contador como se fosse uma nota real** — nenhum tem assinatura
válida, nenhum foi aceito pelo governo, e os códigos fiscais (tributação
nacional/municipal, NBS) são só exemplos, não necessariamente os certos
pro SEU serviço.

## O que perguntar pro contador ANTES de emitir a primeira nota de verdade

Antes de usar o app pra emitir uma nota real, peça pro seu contador
confirmar estes pontos — são exatamente os pontos que mudam o XML gerado
(ver exemplos abaixo) e que só quem conhece o seu cadastro/atividade sabe
responder com certeza:

1. **Regime tributário:** você é MEI, ME/EPP optante do Simples Nacional,
   ou regime normal? (Isso muda se a alíquota do ISS aparece na nota ou não
   — ver Exemplo 1 abaixo.)
2. **Código de tributação nacional (cTribNac)** do seu serviço — 6 dígitos,
   tabela LC 116/2003. O app sugere alguns códigos comuns de saúde em
   `app/core/tabelas_fiscais.py`, mas confirme o seu com o contador.
3. **Código de tributação municipal (cTribMun)**, se a sua prefeitura
   exigir um desdobro próprio (3 dígitos) — muitas prefeituras não têm
   esse código; se a sua não tiver, deixe o campo em branco no app.
4. **Alíquota do ISS** do seu município pro seu tipo de serviço (só
   relevante se você NÃO for optante do Simples).
5. **Retenções na fonte:** se algum tomador (convênio, plano de saúde,
   órgão público) retém IRRF/PIS/COFINS/CSLL/INSS na fonte, e com qual
   percentual — ver Exemplo 2 abaixo.

## Exemplo 1 — Simples Nacional vs. regime normal (a diferença é a alíquota do ISS)

- **`exemplo-1a-dps-medico-simples-nacional-sem-aliquota.xml`**
  (`opSimpNac = 3`, ME/EPP optante): o bloco `<tribMun>` tem só
  `tribISSQN` e `tpRetISSQN` — **sem `<pAliq>`**, mesmo a alíquota "2.00"
  tendo sido digitada no cadastro do serviço. O ISS desse prestador vai
  embutido no DAS mensal, não é calculado nota a nota.

- **`exemplo-1b-dps-medico-regime-normal-com-aliquota.xml`**
  (`opSimpNac = 1`, não optante): mesmíssimo `<tribMun>`, mas **com
  `<pAliq>2.00</pAliq>`** — porque esse prestador não está no Simples,
  então a alíquota do ISS precisa mesmo aparecer na nota.

Todo o resto do XML é idêntico entre os dois arquivos — a única mudança é
a consequência direta do regime tributário (base normativa completa em
`app.fiscal.dps_builder._pAliq_deve_ser_omitido`).

## Exemplo 2 — Retenção na fonte (convênio) vs. sem retenção (particular)

Caso comum: convênio (Unimed, Bradesco Saúde) pagando médico PJ retém
IRRF na fonte (1,5%, Lei 7.450/85); paciente particular (pessoa física)
nunca retém imposto de terceiro. Mesmo prestador, mesmo serviço — só muda
quem paga.

- **`exemplo-2a-dps-convenio-com-retencao-irrf.xml`** — tomador é uma PJ
  (Unimed, `<CNPJ>`), nota de R$ 1.000,00, com **1,5% de IRRF retido**. O
  XML sai com um grupo **`<tribFed>`** novo, contendo
  `<vRetIRRF>15.00</vRetIRRF>` (1.000 × 1,5%).

- **`exemplo-2b-dps-particular-sem-retencao.xml`** — tomador é uma PF
  (`<CPF>`), nota de R$ 300,00, **sem nenhuma retenção**. O XML **não tem
  `<tribFed>` nenhum** — o grupo inteiro só aparece quando existe retenção
  de verdade (base normativa completa em
  `app.fiscal.dps_builder._montar_trib_fed`).

## Exemplo 3 — DANFSe (o PDF que o cliente recebe)

Contexto: a API oficial de geração do DANFSe (`buscar_danfse`) será
suspensa em 03/08/2026 (NT SE/CGNFS-e nº 008/2026, v1.02), então o app
passou a montar esse PDF localmente, seguindo o leiaute da NT campo a
campo (`app/fiscal/danfse_builder.py`).

- **`exemplo-3-nfse-completa-fonte-do-danfse.xml`** — XML **sintético** de
  uma NFS-e completa (não é uma resposta real do governo). Representa o
  cenário mais completo que o app produz hoje: médico do Simples Nacional
  atendendo por convênio PJ com retenção de IRRF.
- **`exemplo-3-danfse-gerado-localmente.pdf`** — o DANFSe montado a partir
  do XML acima, pra comparação visual campo a campo com um DANFSe emitido
  pela API oficial.
- **`exemplo-3-danfse-cancelada.pdf`** — mesmo XML, com a marca d'água
  diagonal "CANCELADA" exigida pela NT quando a NFS-e já foi cancelada.

Cobertura automatizada completa está em `tests/test_dps_builder.py`,
`tests/test_danfse_builder.py` e `tests/test_schema_xsd.py` (este último
valida o XML de verdade contra o XSD oficial do governo).

## Como os exemplos de DPS (1a/1b/2a/2b) foram gerados

```python
from lxml import etree
from app.fiscal import dps_builder as db

dados = db.DadosDPS(
    ambiente="homologacao",
    prestador=db.Prestador(
        documento="11222333000181", inscricao_municipal="437791",
        codigo_municipio="3549904", opcao_simples_nacional="3",  # ou "1"
    ),
    tomador=db.Tomador(documento="12345678000199", nome="Unimed São José dos Campos"),
    servico=db.Servico(
        codigo_tributacao_nacional="040101", codigo_tributacao_municipal="040",
        codigo_nbs="105011900", descricao="Consulta médica - clínica geral",
        codigo_municipio_prestacao="3549904", valor="300.00", aliquota_iss="2.00",
    ),
)
xml = etree.tostring(db.montar_dps_xml(dados), pretty_print=True, xml_declaration=True, encoding="UTF-8")
```

Sem certificado, sem assinatura, sem rede — só a montagem do XML.

## `tpRetPisCofins` — corrigido, mas com uma pendência nova (achado da Onda 1)

A polaridade invertida (`"1"` sendo tratado como "não retido") foi
**corrigida** — confirmado contra a fonte mais primária possível, a própria
documentação inline do XSD oficial (`TSTipoRetPISCofins`,
`tiposSimples_v1.01.xsd`), que descreve 10 códigos (0-9), não um binário.

Só que essa mesma verificação revelou algo mais sério: **o XSD só aceita
`tpRetPisCofins` DENTRO de um subgrupo `<piscofins>`, que por sua vez EXIGE
um campo `<CST>`** (Código de Situação Tributária do PIS/COFINS — uma
classificação fiscal separada, sobre o regime próprio de PIS/COFINS do
prestador, não sobre a retenção). Como o app nunca coletou nem decidiu que
CST usar, `tpRetPisCofins` fica **temporariamente suspenso** (não é emitido)
até essa decisão ser tomada — `vRetIRRF`/`vRetCSLL`/`vRetCP` continuam
sendo gerados normalmente (não são afetados). Ver comentário completo em
`app.fiscal.dps_builder._montar_trib_fed`.
