# Plano de correção — em linguagem simples

Baseado em `docs/auditoria.md` (auditoria completa de 22/jul/2026). Nenhum código foi alterado até aqui.

**Contexto de prazo (atualizado por você):** São José dos Campos já migrou pro padrão nacional em 15/12/2025 (Decreto Municipal 20.100/2025) — isso já aconteceu, não é mais uma pendência. O prazo que importa de verdade é **01/09/2026**, quando a Resolução CGSN 189/2026 passa a **obrigar empresas do Simples Nacional a emitir só pelo Emissor Nacional** (site do governo ou API). Como o nosso app já emite pela API oficial, **ele já é um caminho válido pra essa obrigação** — não é algo que compete com a mudança, é uma forma de cumpri-la. O risco não é "o app vai parar de funcionar" — é "o app pode gerar uma nota tecnicamente aceita, mas com informação fiscal errada", que é justamente o que os itens abaixo destravam.

---

## 1. Os 17 achados, em uma linha cada, sem jargão

### 🔴 Bloqueadores (7)

| # | O que está errado, em uma frase | O que acontece de ruim se não corrigir |
|---|---|---|
| 1 | Quando o médico é do Simples Nacional, a nota pode sair mostrando um imposto (ISS) que não deveria aparecer nela — porque esse imposto já vai dentro do pacote mensal do Simples (o DAS). | A nota pode ser recusada pelo governo, ou pior: ser aceita com uma informação fiscal errada, que pode confundir o contador ou gerar cobrança indevida depois. |
| 2 | O app sempre escreve "nenhum valor foi retido" na nota, mesmo quando o convênio de fato retém uma parte do pagamento. | A nota fica desalinhada com o que realmente aconteceu no pagamento — dor de cabeça na hora de fechar a contabilidade do mês. |
| 3 | Quando um convênio paga o médico (PJ pagando PJ), a lei manda reter um pedaço como imposto de renda na fonte — o app não tem nenhum lugar pra registrar isso. | Mesmo problema do item 2, mas envolvendo a Receita Federal em vez do município — a nota declara um valor que não bate com o que o médico recebeu de verdade. |
| 4 | Quando você clica em "Cancelar" uma nota, o app só some com ela na sua tela/pasta — ele nunca avisa o Governo que ela foi cancelada. | A nota continua 100% válida perante a Receita mesmo depois de "cancelada" no app — risco real de cobrança sobre algo que você achava cancelado, ou confusão se o cliente reclamar de ter recebido nota errada. |
| 5 | Se você corrigir o nome de um médico já cadastrado (tipo, ajustar um acento), as notas antigas ficam numa pasta com o nome velho e as novas vão pra uma pasta com nome novo, sem avisar ninguém. | Na hora de mandar tudo pro contador no fim do mês, é fácil esquecer metade das notas — elas ficaram "escondidas" numa pasta diferente. |
| 6 | Se alguém digitar o valor da nota com "R$" na frente (comum ao copiar de outro lugar), o programa trava com uma mensagem de erro em código, não em português. | Numa demonstração ou no uso real, passa a impressão de que o programa quebrou, quando é só um jeito de digitar que ele não sabe entender ainda. |
| 7 | No aplicativo desktop, toda vez que ele precisa falar com a internet (buscar CNPJ, testar certificado, ou emitir de verdade), a janela inteira congela sem nenhum aviso de "carregando". | Numa demo com internet ruim, o programa pode parecer que travou/crashou bem na hora de clicar no botão mais importante: "Emitir". |

### 🟡 Importantes (10)

| # | O que está errado, em uma frase | O que acontece de ruim se não corrigir |
|---|---|---|
| 8 | O app não confere se um CNPJ/CPF digitado é válido de verdade — só conta se tem a quantidade certa de números. | Um número digitado errado só é descoberto quando o Governo recusar a nota, não antes, na hora de cadastrar. |
| 9 | O campo de descrição do serviço não avisa se o texto ficou grande demais pro que o Governo aceita. | Uma descrição muito longa pode ser recusada só na hora de emitir, sem aviso prévio. |
| 10 | Existe uma mudança de imposto chegando aos poucos nas notas fiscais nacionais (Reforma Tributária) — hoje ainda não é obrigatória, mas pode virar obrigatória sem aviso claro de quando. | Se isso virar obrigatório e ninguém perceber, TODAS as notas passam a ser recusadas de uma hora pra outra, sem ninguém entender o motivo. |
| 11 | O app não sugere o código certo pra "consulta médica" — quem cadastra precisa saber esse código de cabeça. | Um código digitado errado só aparece como problema na hora de emitir, gerando confusão sobre "qual é o código certo". |
| 12 | O app aceita qualquer coisa não-vazia como Inscrição Municipal, sem checar se tem o formato certo de São José dos Campos. | Um número errado só vira problema na hora de tentar emitir, não no cadastro. |
| 13 | Pra médicos organizados em sociedade (mais de um médico dividindo o mesmo CNPJ), existe uma forma de pagar um valor fixo de imposto em vez de porcentagem — o app deixa marcar essa opção, mas não calcula o valor sozinho. | Baixo risco — só funciona se alguém souber calcular esse valor por fora (ex.: o contador). Não gera erro sozinho. |
| 14 | Se duas cópias do programa tentarem gravar no mesmo arquivo de dados ao mesmo tempo, pode aparecer uma mensagem de erro em código de programador em vez de uma mensagem normal. | Situação rara, mas se acontecer, parece um erro grave quando na real é só duas janelas abertas sem querer. |
| 15 | O programa deixa abrir mais de uma cópia dele ao mesmo tempo sem avisar — e como ele "some" pra bandeja do Windows ao fechar (em vez de fechar de verdade), é fácil abrir de novo por engano achando que não estava rodando. | Aumenta a chance do problema do item 14 acontecer. |
| 16 | Se o "motor" do programa (a parte que roda por trás) cair no meio de uma ação, pode aparecer uma mensagem de erro em inglês na tela. | Situação rara e só visual — passa impressão de programa malfeito numa hora ruim, mas não afeta nenhum dado. |
| 17 | Toda nota fiscal emitida carrega, escondida dentro do arquivo, uma identificação que diz que foi gerada por um "script de teste" de quando o projeto começou — não pelo nome real do produto. | Não muda o valor nem invalida a nota, mas é embaraçoso se alguém (contador, auditor) abrir o arquivo e ver isso. |

---

## 2. O que afeta o seu caso real (médico PJ, Simples Nacional, SJC, emitindo pra convênio PJ e paciente particular PF)

| # | Afeta convênio (PJ) | Afeta particular (PF) | Por quê |
|---|---|---|---|
| 1 (alíquota Simples) | ✅ Sim | ✅ Sim | O problema é do médico (prestador), não depende de quem paga — toda nota desse médico sai com o mesmo risco. |
| 2 (retenção ISS não registrada) | ✅ Sim | ⬜ Não se aplica | Só faz sentido reter ISS quando quem paga é uma empresa (convênio); pessoa física não retém imposto de terceiro. |
| 3 (retenção federal IRRF) | ✅ Sim | ⬜ Não se aplica | Mesma lógica — a lei que obriga a retenção (Lei 7.450/85) só vale de empresa pra empresa; paciente pessoa física não é obrigado a reter nada. |
| 4 (cancelamento não avisa o governo) | ✅ Sim | ✅ Sim | Vale pra qualquer nota, de qualquer tomador. |
| 5 (editar prestador quebra pasta) | ✅ Sim | ✅ Sim | É sobre a pasta do médico, não depende de quem é o paciente/convênio. |
| 6 (valor com R$ quebra) | ✅ Sim | ✅ Sim | Digitação de valor, igual pros dois casos. |
| 7 (desktop trava) | ✅ Sim | ✅ Sim | Acontece em qualquer emissão, não depende de quem paga. |
| 8 (CNPJ/CPF sem validação) | ✅ Sim (CNPJ do convênio) | ✅ Sim (CPF do paciente) | É exatamente o tipo de dado que os dois casos usam — CNPJ pro convênio, CPF pro particular. |
| 9 (descrição sem limite) | ✅ Sim | ✅ Sim | Genérico, não depende do tomador. |
| 11 (código de tributação sem sugestão) | ✅ Sim | ✅ Sim | O código do serviço médico é o mesmo não importa quem paga. |
| 12 (Inscrição Municipal sem validação) | ✅ Sim | ✅ Sim | É um dado do médico (prestador), usado em toda nota dele. |

## 3. O que NÃO afeta esse caso e pode esperar

| # | Por quê pode esperar |
|---|---|
| 10 (IBS/CBS ainda não obrigatório) | Confirmado na pesquisa: essa parte do imposto está **suspensa** hoje pelo próprio Governo — não é uma pendência do seu médico específico, é uma mudança nacional futura sem data ainda. Só precisa de alguém acompanhando as notícias de vez em quando. |
| 13 (Sociedade Uniprofissional) | Só importa se o médico dividir o CNPJ com outros médicos numa sociedade — pelo que você descreveu (médico PJ, sozinho), não é o caso agora. Guardar pra quando/se isso mudar. |
| 14 (erro de banco travado) | É sobre usar o programa errado (duas cópias abertas ao mesmo tempo), não sobre o seu médico especificamente. |
| 15 (duas cópias do programa) | Mesma razão do item 14 — comportamento do programa, não do seu caso fiscal. |
| 16 (erro em inglês raro) | É cosmético e raro — só aparece se o "motor" cair bem na hora errada. Não muda nenhum dado fiscal. |
| 17 (identificação de "script de teste" na nota) | Não muda o valor nem a validade de nenhuma nota — é só estética/profissionalismo. Corrige-se em minutos quando sobrar tempo. |

---

## 4. Ordem de correção sugerida, com esforço estimado

| Ordem | O que fazer | Achado(s) | Tempo estimado | Por que nessa posição |
|---|---|---|---|---|
| 1 | Impedir que a alíquota de ISS seja enviada quando o médico é do Simples Nacional | 1 | 2-3 horas | Afeta 100% das notas desse médico — é o mais urgente e o mais barato de corrigir. |
| 2 | Criar onde marcar "esse pagamento teve retenção de ISS" numa nota/tomador | 2 | 3-4 horas | Direto ligado ao caso do convênio, que é metade do faturamento do médico. |
| 3 | Corrigir a edição de prestador pra não perder a pasta de notas antigas | 5 | 1-2 horas | Rápido de corrigir e evita perder a organização dos arquivos já no próximo mês. |
| 4 | Fazer o programa entender valores digitados com "R$" e mostrar erro em português quando o valor não fizer sentido | 6 | 2-3 horas | Alta chance de acontecer sem querer, inclusive numa demonstração. |
| 5 | Corrigir a identificação da nota pra não dizer mais "script de teste" | 17 | 15 minutos | Trivialmente rápido, vale fazer junto com qualquer um dos itens acima. |
| — | **Itens 1 a 5 acima somam menos de um dia e meio de trabalho.** | | | |
| 6 | Implementar o cancelamento de verdade, avisando o Governo (não só escondendo a nota localmente) | 4 | 1-2 dias | É o item de maior risco jurídico/fiscal — precisa existir antes de qualquer cliente pagante usar a função de cancelar de verdade. |
| 7 | Criar onde registrar a retenção de imposto federal (IR) quando um convênio paga o médico | 3 | 1-2 dias | Necessário antes do primeiro cliente que realmente recebe de convênio com retenção — não bloqueia uma demonstração com dado de teste. |
| 8 | Fazer as telas de rede do aplicativo desktop (buscar CNPJ, testar certificado, emitir) pararem de travar a janela inteira | 7 | 1 dia | Resolve o maior risco de "parecer que travou" numa demonstração ao vivo. |
| 9 | Conferir matematicamente se o CNPJ/CPF digitado é válido, antes de tentar emitir | 8 | 1-2 horas | Evita gastar uma tentativa de emissão real por causa de erro de digitação. |
| 10 | Sugerir/pré-preencher o código de tributação pra serviços médicos comuns | 11 | 2-3 horas | Reduz erro de digitação num campo que hoje depende de decorar um número. |
| 11 | Validar o formato da Inscrição Municipal de SJC no cadastro | 12 | 1-2 horas | Baixo risco, mas rápido de fazer junto com o item 9. |
| 12 | Avisar quando a nota ficar grande demais na descrição do serviço | 9 | 1-2 horas | Baixo risco, mas evita uma rejeição de emissão por texto longo demais. |
| 13 | Criar uma consulta pra checar se uma nota já foi emitida antes de tentar de novo, caso a internet caia no meio do envio | (bônus, não estava nos 17 mas está na auditoria completa) | 4-6 horas | Baixa chance de acontecer, mas se acontecer é grave (risco de nota duplicada). |
| 14 | Traduzir o erro de "banco travado" + impedir abrir duas cópias do programa ao mesmo tempo | 14 e 15 | 2-3 horas | Baixa prioridade — só importa se alguém usar o programa de um jeito não previsto. |

**Resumo prático:** os itens 1 a 5 (menos de 2 dias somados) já resolvem tudo que é urgente e específico do seu médico. Os itens 6 e 7 (cancelamento e retenção federal) são os únicos que realmente precisam estar prontos antes de um cliente pagante de verdade usar o app no dia a dia — mas não impedem uma demonstração controlada, desde que você evite mostrar "cancelar" e evite mostrar convênio com retenção ao vivo.
