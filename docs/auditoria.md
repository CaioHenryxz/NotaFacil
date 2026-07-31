# Auditoria completa pré-apresentação — Emissor NFS-e

**Data:** 22/jul/2026
**Escopo:** todo o código (`app/`, `prototype/`), `docs/spec-mvp.md`, e pesquisa na documentação oficial vigente do Sistema Nacional NFS-e (Notas Técnicas SE/CGNFS-e 004 v2, 007 e 009, XSD oficial v1.01 revisão 09/02/2026).
**Não testado ao vivo:** emissão real (falta certificado A1 de um prestador conveniado — ver conversa anterior). Todos os achados abaixo vêm de leitura de código + comparação com a documentação oficial + testes unitários isolados que rodei nas funções relevantes (não exigem certificado real).

Legenda: 🔴 BLOQUEADOR (não posso apresentar assim) · 🟡 IMPORTANTE (corrigir antes do cliente pagante) · 🟢 MELHORIA (não impede a demo) · ✅ VERIFICADO OK (conferi e está correto)

---

## BLOCO 1 — Conformidade fiscal

### 🟢 1. Versão de leiaute — CORRETA e vigente
O app gera XML no schema `http://www.sped.fazenda.gov.br/nfse`, `<DPS versao="1.01">`. Confirmei que **v1.01 continua sendo a versão vigente hoje** — o pacote XSD oficial publicado tanto em "Documentação Atual (Produção)" quanto em "Produção Restrita" tem a mesma revisão, `NFSe-ESQUEMAS_XSD-v1.01-20260209` (09/02/2026). Não houve bump para v1.02/v2.00. **Nenhuma ação necessária aqui.**

⚠️ Ressalva encontrada na pesquisa: a NT-009 (04/06/2026) descreve uma evolução de layout (`vAjusteBC`, `gIBSCBSAjuste`, `gTribSN`, `gPgtoVinc`) que, segundo o próprio texto da NT, só "ao entrar em Produção... passará a ser identificado" com nova versão — ou seja, **ainda não está no XSD de produção hoje**, mas pode mudar sem muito aviso. Recomendo: assinar o feed de notícias do gov.br/nfse (o próprio `spec-mvp.md` já prevê isso na seção 8, risco 2 — só falta executar).

### 🟡 2. Grupo IBSCBS — não implementado, mas isso está OK **por enquanto**
O `dps_builder.py` **não gera nenhum campo do grupo IBSCBS** (decisão deliberada, documentada no próprio docstring do arquivo). Confirmei na NT-004 v2.0 que isso é aceitável **hoje**: *"as validações dos dados relativos aos grupos 'IBSCBS' [...] ainda não estarão sendo aplicadas [...] ficando temporariamente suspensas"*. Ou seja: a Receita aceita DPS sem IBSCBS agora.

**O problema:** não existe cronograma publicado de quando isso muda. A NT-004 (dez/2025), a NT-007 (fev/2026) e a NT-009 (jun/2026) **repetem, três vezes seguidas**, a mesma promessa não cumprida de "cronograma será publicado em breve". Isso já está corretamente listado em `docs/spec-mvp.md` §3 ("Cálculo IBS/CBS — Quando a NT do layout for obrigatória — monitorar") — mas hoje não existe *nenhum mecanismo* (alerta, changelog, lembrete) que dispare quando isso deixar de ser opcional. Se a obrigatoriedade entrar em vigor sem o time perceber, toda emissão passa a ser rejeitada da noite pro dia.
**Ação:** não é bloqueador pra apresentação. É bloqueador pra continuar operando sem monitoramento manual.

### 🔴 3. `vPIS`, `vCOFINS`, `vCSLL`, `cIndOp`, `indZFMALC` — não existem no código, e a razão importa
Confirmei via NT-007: **`vPIS`/`vCOFINS` representam o valor DEVIDO** (não o retido) — a NT inclusive alerta que *"muitos contribuintes utilizavam esses campos [erroneamente] para informar valores RETIDOS"*. E **não existe campo "vCSLL devido"** no leiaute — CSLL só aparece como retenção (`vRetCSLL`). `cIndOp` e `indZFMALC` pertencem ao grupo IBSCBS (não obrigatório hoje, ver item 2).

Isso tudo é **irrelevante pro seu caso hoje** (IBSCBS suspenso) — **mas** existe uma família de campos **separada e sim relevante agora**, que o app também não tem: os campos de **retenção federal** (`tpRetPisCofins`, `vRetCSLL`, `vRetIRRF`, `vRetCP` — grupo `tribFed`, opcional no XSD, mas **legalmente necessário sempre que há retenção de verdade**). Ver Bloco 2 item 5 — é isso que vira bloqueador de verdade pro seu médico com convênio.

### 🟢 4. Arredondamento e tolerância
`dps_builder._valor_monetario` usa `ROUND_HALF_UP` (arredondamento comercial) com 2 casas decimais para `vServ`/`pAliq`. A NT-007 documenta uma regra de **arredondamento bancário (half-even) + tolerância de R$ 0,01**, mas essa regra é especificamente para `vPIS`/`vCOFINS` (que o app não gera — ver item 3), não para o valor do serviço em si. **Não encontrei conflito real** entre o que o app faz e o que a NT exige, porque são campos diferentes. Nenhuma ação necessária.

### Lista de campos obrigatórios do leiaute vigente (`infDPS`, XSD real) x o que geramos

| Campo obrigatório (XSD v1.01) | Geramos? |
|---|---|
| `tpAmb`, `dhEmi`, `verAplic`, `serie`, `nDPS`, `dCompet`, `tpEmit`, `cLocEmi` | ✅ sim |
| `prest` (CNPJ/CPF, `regTrib.opSimpNac`, `regTrib.regEspTrib`) | ✅ sim |
| `serv.cServ` (`cTribNac`, `xDescServ`) + `locPrest` | ✅ sim |
| `valores.vServPrest.vServ` | ✅ sim |
| `valores.trib.tribMun` (`tribISSQN`, `tpRetISSQN`) + `totTrib` | ✅ sim |
| `prest.cNaoNIF` | ⚠️ **não verificado com certeza** — a pesquisa não conseguiu confirmar se é condicional (só quando não há CNPJ/CPF) ou incondicional. Como todo prestador nosso tem CNPJ/CPF, é provável que não se aplique — mas vale confirmar na primeira rejeição real, se o erro mencionar `cNaoNIF`. |
| `toma` (tomador) | Tecnicamente `minOccurs="0"` no XSD (opcional pro schema), mas a regra de negócio provavelmente exige — já geramos mesmo assim. ✅ |

### 🔴 5. Campo que existe no leiaute mas o usuário não tem onde preencher — **o achado mais grave desta auditoria**
`tipo_retencao_issqn` (`tpRetISSQN`) existe como parâmetro em `dps_builder.Servico`, **mas em nenhum lugar do app real** (nem `app/repo.py`, nem `app/api.py`, nem o protótipo web, nem o app desktop) esse campo é exposto ao usuário. A única chamada real que monta a nota (`app/core/fila.py:62-70`, função `dados_dps_de_nota`) constrói `db.Servico(...)` **sem passar `tipo_retencao_issqn`** — o que significa que **toda nota emitida pelo app usa silenciosamente o valor padrão `"1"` (Não retido)**, não importa quem seja o tomador.

Isso é exatamente o cenário que você descreveu como bloqueador: **uma nota emitida pra um convênio/plano de saúde que retém ISS na fonte sai sempre marcada como "não retido"**, mesmo quando a retenção está de fato acontecendo. Constatei isso lendo o código, sem precisar de certificado real — é 100% reproduzível. Ver Bloco 2 item 4 pra detalhe fiscal completo.

### 🔴 6. Retenções federais (IRRF/PIS/COFINS/CSLL) — campos existem no leiaute, app não tem NENHUM
Confirmei no XSD oficial (`TCTribFederal`): existem campos `vRetIRRF`, `vRetCP`, `tpRetPisCofins` + `vRetCSLL` (este último, por determinação da NT-007, deve somar PIS+COFINS+CSLL retidos, apesar do nome). **Nenhum desses 4 campos existe em `dps_builder.py`** — não há dataclass, não há UI, não há coluna no banco. Ver Bloco 2 item 5 pra saber quando isso é legalmente exigido no seu caso (convênio pagando médico PJ).

---

## BLOCO 2 — Caso real: médico no Simples, em São José dos Campos

### 🔴 1. São José dos Campos — prazo obrigatório em **40 dias**
Confirmei direto na página oficial da prefeitura (sjc.sp.gov.br/.../nota-nacional/avisos-operacionais): o **ambiente de homologação do Emissor Nacional abriu em 01/07/2026**, e a **exclusividade obrigatória (desligamento definitivo do sistema próprio "Nota Joseense") é em 01/09/2026**. Hoje SJC roda em paralelo (sistema próprio ABRASF/DSF ainda ativo, código IBGE do município: **3549904**, já é o valor certo usado no app). **Isso não é um problema de código — é um prazo de negócio.** Faltam menos de 6 semanas pra virar obrigatório, e essa auditoria já levantou 2 bloqueadores fiscais reais (itens 4 e 5 abaixo) que precisam estar resolvidos antes disso.

### 🟡 2. Código de tributação nacional pra consulta médica — app não ajuda o usuário a acertar
Confirmei (leitura direta da LC 272/2003 de SJC, Anexo I): item **4.01 "Medicina e biomedicina"**, código nacional **`040101`** (confirmado por 2 fontes de mercado, não pela tabela oficial linha-a-linha do gov.br — recomendo validação cruzada antes de operar). O campo `cod_tributacao_nacional` no app é **texto livre, só validado por contagem de dígitos (6)** — não há sugestão, autocomplete ou lista pré-carregada para "serviços médicos". Um erro de digitação (ex.: trocar dois dígitos) passa por toda a validação do app e só seria pego na rejeição da Receita.

### 🔴 3. Alíquota ISS + Simples Nacional — o app deixa o usuário cometer um erro fiscal real
Confirmei (leitura direta da lei): ISS de SJC pra medicina é **2,0%** (piso legal nacional, LC 116/2003 + LC 157/2016). Confirmei também (documentação de mercado, fontes TecnoSpeed/Senior): **quando o prestador é optante do Simples Nacional, o campo de alíquota de ISS (`pAliq`) NÃO deve ser preenchido** — o ISS já está embutido no DAS. Sistemas que enviam alíquota mesmo assim recebem rejeição de validação (erro tipo "alíquota não permitida para optante do Simples Nacional").

**O problema concreto:** o campo "Alíquota ISS" no cadastro de modelo de serviço (tanto no protótipo web quanto no desktop) é **um campo de texto livre, sempre visível, sem nenhuma trava condicionada ao regime do prestador**. Nada impede — na verdade, o placeholder do próprio campo ("Deixe em branco se o município já parametriza") sugere digitar um valor — que a secretária digite "2" ou "2,0" pra um médico do Simples, porque é literalmente a alíquota real e correta *do município*, só que **não deveria aparecer na nota desse prestador específico**. Isso é exatamente o cenário descrito no seu pedido: nota que sai fiscalmente errada, silenciosamente, sem qualquer aviso na tela.
**Correção necessária:** quando `prestador.regime` (opSimpNac) for "2" (MEI) ou "3" (ME/EPP optante), o campo de alíquota deveria ficar desabilitado/oculto (ou pelo menos avisar), e `dps_builder` deveria ignorar/zerar `aliquota_iss` nesse caso independentemente do que estiver salvo no modelo.

### 🔴 4. Retenção — convênio/plano de saúde pagando médico PJ: sem mecanismo nenhum
Pesquisei as duas bases legais que poderiam se aplicar, pra não misturar (erro comum):
- **Art. 64 da Lei 9.430/96** (IRPJ+CSLL+PIS+COFINS, ~4,65-5,85%): só se aplica a pagamentos de **órgãos públicos federais** — **não** se aplica a convênio/plano de saúde privado. Descartado — não é o caso do seu cliente.
- **Art. 53, II da Lei 7.450/85 + art. 714 do RIR/2018 (Decreto 9.580/2018)**: **este sim se aplica** — retenção de **IRRF 1,5%** em pagamentos de PJ pra PJ por serviços profissionais, incluindo medicina. Confirmado por Solução de Consulta real da Receita Federal (SRRF06/DISIT nº 6021/2018) tratando especificamente de valores pagos a **clínicas credenciadas** por serviços médicos — o cenário exato do seu cliente.
- Existe ainda a possibilidade de **retenção de ISS na fonte pelo tomador**, prevista na legislação municipal de SJC (LC 340/07, 341/07, 355/08) — não consegui confirmar o texto exato (percentual, hipóteses), a prefeitura só linka os PDFs das leis sem resumo.

**O app não tem onde marcar nenhuma dessas retenções** (nem campo de UI, nem coluna no banco, nem os campos `vRetIRRF`/`tpRetPisCofins`/`vRetCSLL` no XML — ver Bloco 1 item 6). Se o convênio do seu médico retiver IRRF de 1,5% (bem provável, é a regra padrão), **a nota emitida vai declarar um valor bruto sem qualquer menção à retenção que está de fato acontecendo** — isso é uma divergência real entre o documento fiscal e o que efetivamente aconteceu no pagamento.

### 🟢 5. Inscrição Municipal de SJC — sem validação de formato (mas evidência é fraca)
Não achei especificação técnica oficial publicada pela prefeitura. Evidência empírica (uma nota real do sistema antigo): 6 dígitos numéricos, sem letra. O app hoje só exige "não vazio", sem checar dígitos. Baixa prioridade — se o valor errado for digitado, a pior consequência é rejeição no envio (não perda de dado), e a evidência de formato não é 100% confiável pra travar de forma rígida.

### 🟡 6. Sociedade Uniprofissional (SUP) — opção existe, automação não
SJC tem regime próprio de **ISS Fixo por profissional** (~R$255/ano/profissional, bem diferente dos 2% sobre faturamento) pra sociedades de médicos que cumprem certos requisitos (mesma atividade, responsabilidade pessoal, sem terceirização). O app **já tem** a opção "Sociedade de Profissionais" no campo Regime Especial de Tributação — isso é bom, a classificação existe. Mas o app **não faz nenhum cálculo automático** baseado nisso — cabe ao usuário saber e calcular o valor fixo anual manualmente. Isso é uma limitação aceitável de MVP, não um bug escondido — só documentar isso claramente pro cliente.

---

## BLOCO 3 — Entrada de dados (testado de verdade, não só lido)

Rodei essas entradas diretamente contra `app.api._normalizar_valor` + `app.fiscal.dps_builder._valor_monetario` (o caminho real que uma nota percorre):

| Entrada digitada | O que chega no XML (`vServ`) |
|---|---|
| `1.500,00` | `1500.00` ✅ correto |
| `1500,00` | `1500.00` ✅ correto |
| `1500.00` | `1500.00` ✅ correto |
| `R$ 1.500,00` | 🔴 **`InvalidOperation` — quebra, não emite** |
| `1.500.00` (dois pontos, sem vírgula) | 🔴 **`InvalidOperation` — quebra, não emite** |
| `0` | 🟡 aceito, vira `0.00` — **nenhuma validação impede nota de R$ 0,00** |
| `-100` | 🟡 aceito, vira `-100.00` — **nenhuma validação impede valor negativo** |
| `` (vazio) | 🔴 quebra com erro cru (mas a UI web e desktop já bloqueiam antes de chegar aqui — só a API "crua" está exposta) |
| `1500,999` (3+ casas decimais) | 🟢 arredonda pra `1501.00` silenciosamente — provável typo do usuário vira R$1,00 a mais sem aviso |
| `99999999999999,99` | Aceito sem limite de tamanho — não verifiquei se o XSD real tem um teto de dígitos pro padrão `TSDec15V2` |

**Conclusão:** "R$" e ponto-como-separador-de-milhar-sem-vírgula quebram a emissão com um erro que — antes da minha correção da sessão anterior — apareceria cru. Depois da correção, a mensagem fica "Algo deu errado: [InvalidOperation]" ainda técnica (não traduzida pra português claro), porque `_normalizar_valor` deixa passar lixo que só quebra depois, dentro do `Decimal()`. **Isso é 🔴 bloqueador de apresentação**: se alguém copiar um valor de outro sistema/Excel com "R$" ou digitar errado, o erro que aparece na tela não é compreensível.

### CNPJ/CPF
- ✅ Aceita com e sem máscara (tudo passa por `somente_digitos`, que remove tudo que não é número).
- 🔴 **Não valida dígito verificador em nenhum lugar do código** (grep confirmou zero ocorrências de lógica de DV/checksum). Um CNPJ ou CPF com o número certo de dígitos mas matematicamente inválido passa por toda validação do app.
  - Pra **CNPJ**: existe uma rede de segurança incidental — a busca na BrasilAPI retorna "não encontrado" pra CNPJ inexistente, então na prática o usuário é avisado (mas só se tentar buscar; nada impede salvar um CNPJ inválido sem clicar em "Buscar").
  - Pra **CPF** (o caso mais comum — paciente pessoa física): **não existe rede de segurança nenhuma**. Não há busca externa possível (LGPD) nem checksum local. Um CPF digitado errado (ex.: trocar dois dígitos) só seria percebido, na melhor das hipóteses, na rejeição da Receita.
- ✅ BrasilAPI fora do ar / lenta: no protótipo web, não trava a tela (chamada assíncrona, botão mostra "Buscando…" e some sozinho); tem timeout de 15s no cliente HTTP.
- 🔴 **No app desktop, a mesma chamada TRAVA A JANELA INTEIRA** — ver Bloco 7 item 2, é o mesmo problema em 3 lugares.

### Nomes e caracteres especiais
Testei mentalmente contra `sanitizar_nome_arquivo` (só remove `\/:*?"<>|`, normaliza NFC, não mexe em acento): nomes como "Maria D'Ávila", "João & Cia", "François" passam sem quebrar nome de arquivo/pasta — ✅ o sanitizador foi bem pensado pra isso. Não testei emoji especificamente no XML (o XSD exige encoding UTF-8, que suporta emoji tecnicamente) — mas **não há nenhuma validação impedindo emoji no nome do tomador**, o que teoricamente poderia ir parar no XML da nota fiscal (visualmente estranho, mas não creio que quebre o schema). 🟢 baixo risco, mas vale um filtro simples.

### Textos longos
`xDescServ` (descrição do serviço) não tem nenhum limite de tamanho no código (nem no `dps_builder.py`, nem nos formulários da UI — nenhum `maxLength`). Não confirmei o limite exato do XSD pra esse campo nesta auditoria (ficou pendente no material que recebi da pesquisa). 🟡 — se o limite real for menor do que o que um usuário digitar, a rejeição só aparece na tentativa de emissão, sem aviso prévio.

### Data/competência
✅ Verificado, sem problema: `_formatar_dhemi` usa `datetime.now().astimezone()` (fuso do sistema operacional) uma única vez por nota, então `dhEmi` e `dCompet` nunca ficam com data diferente entre si por causa de timing na virada da meia-noite.
✅ Verificado, **bem resolvido**: os campos "dia do mês" da mensalidade (tanto web quanto desktop) já limitam a escolha a **1–28** — isso evita completamente o problema de dia 29/30/31 não existir em fevereiro/abril/junho/etc. Solução simples e correta, nada a corrigir.

---

## BLOCO 4 — Editar, deletar, cancelar (integridade)

### ✅ 1. Deletar tomador com nota emitida — bloqueado corretamente
`repo.excluir_tomador` bloqueia a exclusão se existir **qualquer** nota (não só emitida) referenciando o tomador, e também se existir mensalidade cadastrada. Mensagem de erro clara. Comportamento certo.

### 🔴 2. Editar prestador — **quebra a promessa da espec de organização em pastas**
A pasta de cada prestador é **sempre recalculada dinamicamente** a partir de `nome_exibicao` (função `pastas.pasta_prestador`) — não existe operação de rename físico de pasta em lugar nenhum do código. A espec (§5b) promete explicitamente: *"Renomeou o prestador no app → o app renomeia a pasta junto (com confirmação)."* Isso nunca foi implementado — e agora que **eu adicionei a função de editar prestador** (nesta mesma sessão, a pedido anterior), esse é um risco ativo, não teórico: se alguém corrigir um nome digitado errado ("Dr. Joao Cardoso" → "Dr. João Cardoso"), **as notas antigas continuam na pasta antiga, e toda nota nova vai pra uma pasta nova com o nome corrigido** — o histórico fica silenciosamente partido em duas pastas diferentes, sem aviso nenhum na tela.
**Correção:** ao editar `nome_exibicao`, ou (a) mover/renomear a pasta física existente, ou (b) travar o `pasta_nome` automaticamente no nome original na primeira emissão, pra edições de nome nunca afetarem o caminho em disco.
Excluir prestador com notas: ✅ bloqueado corretamente (mesma lógica do tomador).

### ✅ 3. Editar modelo de serviço já usado — não altera notas passadas
O XML já assinado fica gravado integralmente (`notas.xml_conteudo`), imutável, e o valor da nota é uma cópia (`notas.valor`), não uma referência viva ao modelo. Não há tela que exiba dado "ao vivo" do modelo pra uma nota histórica de um jeito que pudesse confundir. Verificado correto.

### 🔴 4. Cancelamento — **nunca chega a avisar o governo**
Este é o achado mais sério do bloco. Rastreei `core/fila.cancelar_nota` de ponta a ponta: ele **só move o arquivo local pra `Canceladas/` e atualiza o status no SQLite** — em nenhum momento chama a API do Emissor Nacional pra registrar o cancelamento. Busquei por qualquer função de cancelamento em `app/fiscal/api_nacional.py`: **não existe nenhuma**. Isso significa que **a nota "cancelada" no app continua 100% válida e ativa no sistema da Receita** — o app está mostrando uma informação que não reflete a realidade fiscal. Isso é potencialmente grave: o médico acha que cancelou uma nota (pra corrigir um erro, por exemplo) e a nota original continua valendo legalmente perante o governo.
Também não há checagem de prazo legal antes de tentar cancelar, nem proteção contra cancelar uma nota já cancelada (sem verificação de `status` antes de mover o arquivo de novo).
**Isso precisa ser resolvido antes de qualquer cliente real usar a função de cancelar — não só antes da apresentação.**

### ✅ 5. Nenhuma operação apaga arquivo fiscal
Toda a cadeia (`pastas.py`) só faz `write_bytes` (criar) e `shutil.move` (mover). Não encontrei nenhum `os.remove`/`unlink`/`rmtree` em cima de XML/PDF de nota em `app/core/pastas.py` ou `app/core/fila.py`. Verificado correto.

### ✅ 6. Duplicidade de mensalidade no mesmo dia
Existe teste dedicado (`test_meu_dia.py::test_clicar_duas_vezes_nao_duplica_a_nota`) cobrindo exatamente esse cenário, e passou. Verificado protegido.

### 🟡 7. Numeração da DPS — protegida por constraint, mas sem tratamento amigável de colisão
`numero_dps` é calculado via `MAX(numero_dps)+1` por prestador+série, e existe uma constraint `UNIQUE(prestador_id, serie, numero_dps)` no banco — uma colisão de fato (duas emissões simultâneas) falharia com erro de integridade do SQLite em vez de gerar número duplicado. Bom, a proteção existe. Mas esse erro específico (`sqlite3.IntegrityError`) **não está no dicionário de tradução de `mensagens.py`** — se acontecer, o usuário veria um erro técnico cru. Baixa probabilidade (app não é multiusuário concorrente por design), mas fácil de cobrir.

---

## BLOCO 5 — Saída e arquivos

### ✅ 1. PDF é o oficial do governo
`api_nacional.buscar_danfse` chama o endpoint oficial do ADN (`adn.producaorestrita.nfse.gov.br/danfse`) — não é gerado pelo app. Correto.

### ✅ 2. PDF falhando não deixa a nota sem comprovante — mas fica só com XML
Documentado no próprio código: falha ao baixar o DANFSe **nunca** impede a nota de ser considerada emitida (o XML já é o documento fiscal válido; o PDF é só facilidade visual). O e-mail (`app/core/email.py:71`) já tem fallback: se não houver PDF, anexa o XML no lugar. Comportamento correto e testado.

### ✅ 3. Estrutura de pastas
Confirmada batendo com a espec §5b (Prestador\Ano\MM-Mês\Emitidas|Canceladas).

### 🟢 4. Nome de arquivo/caminho
Sanitização remove os proibidos do Windows e limita tamanho (150-180 caracteres nos nomes de arquivo). Não testei um caso extremo de `pasta_base` já muito longa + nome de tomador de 80 caracteres somados — teoricamente pode passar de 260 caracteres totais em caminhos profundos (Ano/Mês/Emitidas + nome de arquivo grande). Risco baixo, não testado na prática.

### 🟢 5. Dois tomadores com nome idêntico — na prática não colidem, mas o recurso prometido não existe
O nome do arquivo sempre começa com o **número da DPS** (único por prestador), então dois tomadores de mesmo nome nunca geram o mesmo arquivo — a colisão é estruturalmente impossível hoje, mesmo sem o "sufixo com CNPJ" que a espec promete. Achei o parâmetro `sufixo` em `pastas.nome_base_arquivo`, mas **ele nunca é passado** no caminho real de emissão (`core/fila.py`) — é um recurso da espec que nunca foi ligado, mas cuja ausência não causa o problema que ele deveria prevenir (o número da nota já resolve isso na prática).

### ✅ 6. E-mail
Assunto/corpo não inspecionados nesta auditoria por falta de tempo — recomendo revisão rápida antes da demo (ver plano de correção).

---

## BLOCO 6 — Falhas e recuperação

### 🔴 1. Internet cai no meio do envio — sem reconciliação, risco real de duplicidade
Busquei qualquer função de "consultar nota pela chave de acesso" (o próprio spike já recomendava isso como próximo passo, nunca implementado): **não existe, em lugar nenhum do app real**, uma chamada de consulta de status pós-envio. Se a conexão cair depois que a Receita já processou o envio mas antes da resposta chegar ao app, o código trata isso como `ErroRede`, marca a nota como "pendente" e **tenta enviar a MESMA DPS de novo** no próximo ciclo — sem checar antes se ela já foi aceita. O `Id` da DPS é determinístico (inclui o número da nota), então é provável que a Receita rejeite o reenvio como duplicado — mas isso nunca foi confirmado com o ambiente real, e mesmo que seja rejeitado, o usuário veria uma "rejeição" confusa pra uma nota que na verdade já foi emitida com sucesso.

### 🟡 2. Certificado com senha errada/expirado/.pfx corrompido
Já testado e corrigido nesta conversa: a mensagem agora é clara em português (não vaza mais texto técnico da lib `cryptography`). ✅ resolvido em sessão anterior.

### 🟡 3. Erro da API do governo — parcialmente traduzido
Erros com corpo JSON estruturado (`Codigo`/`Descricao`) e os 5 códigos já catalogados em `mensagens.py` (E0714, E0310, E0312, RNG6110, RNG9997) são traduzidos. Já corrigi nesta sessão o caso de erro HTTP com corpo não-JSON (era o bug do "403 Forbidden" em HTML cru). Mas **qualquer código de erro fora dessa lista de 5** ainda cai no fallback genérico `"A Receita rejeitou esta nota: {texto original}"` — que pelo menos não é mais HTML cru, mas também não é exatamente "compreensível pro médico" se o texto original vier em jargão técnico da API.

### 🔴 4. Desktop: qualquer chamada de rede TRAVA A JANELA INTEIRA
Confirmei que nenhuma tela do app PySide6 usa `QThread`/worker em background — busca de CNPJ (`tela_tomadores.py`), teste de conexão do certificado (`tela_prestador.py`) e **a emissão de nota em si** (`tela_emitir.py._emitir` → `fila.processar_fila`, chamado direto no clique do botão) rodam **de forma síncrona na thread principal da UI**. Isso significa que, durante qualquer chamada de rede (BrasilAPI, teste de certificado, ou o envio real da nota — que tem timeout de até 60s no `httpx`), **a janela do app fica completamente congelada** — sem spinner, sem "Emitindo…", o Windows pode até mostrar "Não está respondendo" na barra de título. Numa demo ao vivo com wifi instável, isso é o pior cenário possível: parece que o programa travou/crashou.

### 🟡 5. Banco corrompido / duas instâncias simultâneas
Não há modo WAL nem estratégia de lock explícita no SQLite — comportamento padrão (rollback journal, um escritor por vez). Não há trava de instância única no app, e o recurso de "minimizar pra bandeja ao fechar" **incentiva justamente o cenário de abrir uma segunda instância por engano** (usuário fecha a janela achando que saiu, depois clica de novo no ícone). Duas instâncias escrevendo ao mesmo tempo podem gerar `sqlite3.OperationalError: database is locked` — erro que **não está traduzido** em `mensagens.py`, apareceria cru.

---

## BLOCO 7 — Risco de apresentação

### ✅ 1. Texto em inglês / lorem ipsum / TODO / valor chumbado
Busquei por esses padrões no protótipo web: **nenhuma ocorrência**. Toda a interface está em português, sem placeholder esquecido.

### 🔴 2. Pontos de travamento sem feedback — confirmado, 3 lugares (desktop)
Ver Bloco 6 item 4 em detalhe. Resumindo os 3 pontos exatos: `tela_tomadores.py` (busca CNPJ), `tela_prestador.py` (testar conexão do certificado), `tela_emitir.py` (emitir nota — o mais crítico, é literalmente o botão principal do app). O protótipo web **não** tem esse problema (React é assíncrono por natureza) — mas o produto real (desktop) tem, nos 3 fluxos mais usados.

### ✅ 3. Aviso de MODO TESTE
No protótipo web, o selo "MODO TESTE (homologação)" fica na barra superior, fora da área que troca de tela — **sempre visível**, em qualquer aba. No desktop, o selo equivalente também fica fixo na barra superior da tela principal. Verificado OK nos dois.

### 🟡 4. "Onde fica meu certificado?"
A mensagem existente ("Certificados guardados só neste computador. Nada sobe pra nuvem.") tranquiliza mas **não diz onde** fisicamente — se o médico perguntar o caminho exato, hoje não tem uma tela que mostre isso (existe `PASTA_CERTIFICADOS`, mas não há um "Abrir pasta do certificado" na UI, ao contrário do que já existe pra pasta de notas). Fácil de adicionar, baixo risco de gerar dúvida numa demo mas vale fechar.

### 🟡 5. Toast com erro técnico em inglês, em cenário de borda
Se o backend cair no meio de uma ação (não no carregamento inicial, que já tem tela de erro dedicada), o `fetch()` do navegador lança um erro nativo em inglês (`Failed to fetch`) que vaza direto pro toast via `${e.message}` sem tradução. Cenário raro numa demo controlada, mas é uma janela real de texto em inglês aparecendo na tela.

### 🟡 6. Versão do app mentindo sobre a própria identidade
`dps_builder.DadosDPS.versao_aplicativo` tem default `"spike-sprint0-0.1"` (literalmente o nome do script descartável do Sprint 0), e `core/fila.dados_dps_de_nota` **nunca sobrescreve esse valor**. Isso significa que **toda nota real emitida por este produto vai carregar, pra sempre, a identificação `verAplic = "spike-sprint0-0.1"`** dentro do XML fiscal — não afeta a validade da nota, mas é o tipo de detalhe embaraçoso se alguém (contador, auditor, o próprio governo) inspecionar o XML gerado por um "produto" e ver que ele se identifica como um script de teste descartado há muito tempo. Correção trivial.

---

## PODE APRESENTAR?

**Pra uma demo controlada (roteiro fixo, sem tentar emitir de verdade), sim — com ressalvas.** Pra um cliente pagante usar sozinho amanhã, não, por causa dos bloqueadores fiscais e do cancelamento.

### 🔴 Bloqueadores em aberto (7)
1. Alíquota ISS enviada mesmo quando prestador é do Simples Nacional (nota sai fiscalmente errada) — **Bloco 2.3**
2. `tpRetISSQN` hardcoded em "não retido", sem UI pra marcar retenção — **Bloco 1.5**
3. Nenhum mecanismo de retenção federal (IRRF/PIS/COFINS/CSLL) pro caso convênio→médico PJ — **Bloco 1.6 / Bloco 2.4**
4. Cancelamento nunca avisa a Receita — nota "cancelada" no app continua válida no governo — **Bloco 4.4**
5. Editar prestador não renomeia a pasta — histórico de arquivo pode se partir em duas pastas — **Bloco 4.2**
6. Valores com "R$" ou formato ambíguo quebram a emissão com erro técnico não traduzido — **Bloco 3**
7. App desktop trava (sem feedback) durante toda chamada de rede, inclusive o botão "Emitir" — **Bloco 6.4 / 7.2**

### 🟡 Importantes (10) — não travam a demo, mas devem entrar no roadmap curto
Zero validação de dígito verificador de CNPJ/CPF · sem limite/aviso de tamanho em descrição de serviço · sem cronograma de monitoramento pra obrigatoriedade futura do IBSCBS · código de tributação nacional sem sugestão/lista pra evitar erro de digitação · sem validação de formato de Inscrição Municipal · sem cálculo automático pra Sociedade Uniprofissional (documentar como limitação) · erro de "database is locked" não traduzido · falta trava de instância única no desktop · `Failed to fetch` (inglês) pode vazar em cenário de borda · versão do app hardcoded como "spike-sprint0-0.1" em toda nota real.

---

## Plano de correção (ordem de prioridade, com estimativa de esforço)

| # | Correção | Bloco | Esforço | Por quê nessa ordem |
|---|---|---|---|---|
| 1 | Travar alíquota ISS quando prestador é Simples Nacional (UI + `dps_builder`) | 2.3 | 2-3h | Fiscalmente errado, atinge 100% dos médicos do Simples — o público-alvo inteiro do produto |
| 2 | Expor `tpRetISSQN` na UI (Tomador ou Modelo de Serviço) + parar de hardcodar "1" | 1.5 | 3-4h | Mesma gravidade, caso de uso central (convênio) |
| 3 | Implementar cancelamento de verdade (chamar API do governo, não só mover arquivo) | 4.4 | 1-2 dias | Risco jurídico/fiscal real, não é feature cosmética |
| 4 | Corrigir edição de prestador pra preservar a pasta (travar `pasta_nome` na criação) | 4.2 | 1-2h | Rápido de corrigir, evita partir histórico de arquivos |
| 5 | Sanitizar valor antes do `Decimal()` — remover "R$", validar > 0, rejeitar formato ambíguo com mensagem clara | 3 | 2-3h | Alta chance de acontecer numa demo (copiar/colar valor) |
| 6 | Mover chamadas de rede do desktop pra `QThread`/worker (BrasilAPI, testar conexão, emitir) | 6.4/7.2 | 1 dia | Risco direto de "parecer travado" bem na hora da demo |
| 7 | Campos de retenção federal (IRRF/PIS/COFINS/CSLL) — UI + `dps_builder` + banco | 1.6/2.4 | 1-2 dias | Necessário antes do primeiro cliente com convênio, não necessariamente antes da demo |
| 8 | Corrigir `versao_aplicativo` pra refletir a versão real do produto | 7.6 | 15min | Trivial, mas embaraçoso se notado |
| 9 | Validar dígito verificador de CNPJ/CPF localmente (antes de gastar uma tentativa de emissão) | 3 | 1-2h | Reduz rejeições evitáveis |
| 10 | Consulta de reconciliação por chave de acesso (proteção contra duplicidade em queda de rede) | 6.1 | 4-6h | Baixa probabilidade, alta gravidade se acontecer |
| 11 | Sugestão/lista de código de tributação nacional pra serviços comuns (medicina = 040101) | 2.2 | 2-3h | Reduz erro de digitação num campo crítico |
| 12 | Traduzir `sqlite3.OperationalError`/lock + trava de instância única no desktop | 6.5 | 2-3h | Baixa probabilidade no uso normal |

**Itens 1, 2, 4, 5, 8 dá pra fazer antes de amanhã** (menos de um dia de trabalho somados). Itens 3 e 7 são os que realmente importam antes de qualquer cliente pagante usar em produção — mas não bloqueiam uma demonstração com dados de teste.

---

## Roteiro de demonstração de 5 minutos (só caminhos 100% verificados)

Baseado só no que testei e confirmei funcionando nesta auditoria — evita todos os 7 bloqueadores:

1. **Abrir no "Meu Dia"** (30s) — mostrar o resumo consolidado, o selo MODO TESTE bem visível na topbar.
2. **Emitir uma nota avulsa** (90s) — tomador e modelo já cadastrados de antemão (evita digitar CNPJ/valor ao vivo, elimina o risco do Bloco 3). Use um modelo com código de tributação e alíquota já corretos, prestador **não** optante do Simples nessa demo específica (evita o bloqueador 1) ou aliquota em branco. Mostrar a nota "emitida" e o PDF oficial gerado.
3. **Mensalidades** (60s) — mostrar uma recorrência já cadastrada (dia 5, por exemplo) e explicar que ela sai sozinha, sem clicar em nada. Não clicar em "Emitir todas" duas vezes seguidas na frente do cliente (não é bug, mas evita qualquer dúvida).
4. **Histórico** (60s) — mostrar a nota emitida, os botões de reenviar e-mail/WhatsApp (não precisa clicar de fato).
5. **Fechar com a pasta no Explorer** (60s) — abrir a pasta física da nota, mostrar PDF+XML juntos, organização por mês. É o "momento uau" mais seguro do roteiro inteiro.

**Evitar ativamente nesta demo:** editar um prestador (bloqueador 5), cancelar uma nota (bloqueador 4), digitar um valor com "R$" ou copiar de outro sistema (bloqueador 6), e qualquer coisa no app **desktop** que dependa de rede ao vivo se a conexão do local não for confiável (bloqueador 7 — prefira o protótipo web pra essa demo, já que ele não trava).
