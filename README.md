# NotaFácil — emissor de NFS-e para Windows

Este guia explica, passo a passo, como instalar e usar o Emissor NFS-e. Não
é preciso saber programar. Sempre que aparecer o nome de um botão ou de uma
aba, é exatamente o texto que você vai ver na tela — procure por ele.

---

## 1. O que é este programa

O Emissor NFS-e é um programa que roda no seu computador (Windows) e emite
Notas Fiscais de Serviço Eletrônicas (NFS-e) pelo **Emissor Nacional**, o
sistema oficial do governo. Cada médico/prestador de serviço tem seu próprio
certificado digital e sua própria pasta de notas — nada se mistura entre
eles. O programa também sabe emitir mensalidades sozinho (sem você precisar
clicar todo mês) e mandar a nota por e-mail pro cliente automaticamente.

---

## 2. O que você precisa ter antes de começar

- **Python instalado no computador** (versão 3.12 ou mais recente).
  - Baixe em: https://www.python.org/downloads/ (baixe e execute o
    instalador; na primeira tela do instalador, **marque a caixinha "Add
    python.exe to PATH"** antes de clicar em Instalar — esse passo é fácil
    de esquecer e sem ele o programa não funciona).
  - Para conferir se já está instalado e qual a versão, abra o **Prompt de
    Comando** (aperte a tecla Windows, digite `cmd`, aperte Enter) e digite:
    ```
    python --version
    ```
    Se aparecer algo como `Python 3.12.4` ou mais novo, está tudo certo.

- **O arquivo do certificado digital A1 de cada médico/prestador** — um
  arquivo com final `.pfx` (às vezes `.p12`) — **e a senha desse
  certificado**. Sem isso, você não emite nota nenhuma; é o próprio
  certificado que "assina" a nota no lugar da assinatura de próprio punho.
  Guarde o arquivo em algum lugar do computador onde você vai lembrar
  (ex.: `Documentos\Certificados`).

---

## 3. Como instalar o programa

Abra o **Prompt de Comando** (tecla Windows → digite `cmd` → Enter) e
digite os comandos abaixo, um de cada vez, apertando Enter depois de cada
um. Troque `caminho\onde\voce\salvou\o\projeto` pelo lugar onde você colocou
a pasta do programa.

```
cd caminho\onde\voce\salvou\o\projeto\emissor-nfse
```
```
python -m venv .venv
```
```
.venv\Scripts\activate
```
```
pip install -r requirements.txt
```

O terceiro comando cria um "ambiente" só pro programa (não mexe em mais
nada do seu computador). O quarto baixa e instala as peças que o programa
precisa — pode demorar alguns minutos na primeira vez. Se aparecer bastante
texto passando na tela, é normal.

Você só precisa repetir esse passo a passo **uma vez**. Nas próximas vezes,
basta abrir o Prompt de Comando, entrar na pasta do projeto (`cd
caminho\...`), rodar `.venv\Scripts\activate` e ir direto pro próximo passo.

---

## 4. Como abrir o programa

Com o Prompt de Comando ainda aberto na pasta do projeto (e o `.venv`
ativado, passo anterior), digite:

```
python -m app.main
```

A janela do programa deve abrir em alguns segundos.

---

## 5. IMPORTANTE — o programa começa em modo de TESTE (Homologação)

Assim que você abrir o programa, vai ver uma **faixa laranja no topo da
tela**, do lado do nome do prestador, escrito:

> 🧪 **HOMOLOGAÇÃO (teste) — as notas emitidas aqui NÃO valem como
> documento fiscal real**

Isso quer dizer que, do jeito que o programa vem hoje, **toda nota que você
emitir vai para o ambiente de testes do governo (chamado de "Produção
Restrita")** — perfeito pra você e o médico praticarem, errarem, testarem
à vontade, sem nenhum risco. Nenhuma nota emitida nesse modo tem validade
fiscal. Enquanto essa faixa estiver na tela, pode clicar em tudo sem medo.

A seção 10 deste guia explica, com todo cuidado, como mudar pra emissão de
verdade quando chegar a hora.

### "Onde fica o certificado digital do médico?"

Só neste computador — o programa **nunca** copia o arquivo `.pfx` pra
lugar nenhum: ele fica exatamente na pasta onde você escolheu ele no
cadastro (ex.: `Documentos\Certificados\`). Nem o arquivo nem a senha vão
pra internet, pra nuvem ou pra qualquer servidor nosso — a assinatura da
nota é feita 100% aqui na máquina. Se precisar confirmar o caminho exato de
um prestador já cadastrado, clique em **"Editar prestador"** e depois em
**"Abrir pasta do certificado"**.

---

## 6. Primeiro uso — passo a passo

### a) Cadastrar o primeiro prestador (médico)

Na primeira vez que o programa abre (banco de dados vazio), ele já cai
direto na tela de cadastro. Depois da primeira vez, use o botão
**"+ Novo prestador"** no canto superior direito pra cadastrar os
seguintes.

1. Clique em **"Escolher arquivo .pfx…"** e selecione o certificado do
   médico.
2. Digite a senha do certificado no campo e clique em **"Ler certificado"**.
   O CNPJ (ou CPF) do médico é lido automaticamente de dentro do arquivo.
3. Se o documento for CNPJ, clique em **"Buscar dados (CNPJ)"** — o nome e
   o endereço vêm sozinhos da Receita Federal. Se for CPF (médico autônomo),
   não existe essa busca automática (é dado protegido por lei), então
   preencha o **"Nome de exibição"** você mesma.
4. Preencha a **Inscrição municipal**, confira o **Regime (Simples
   Nacional)** e escolha uma **cor** pra esse prestador — essa cor aparece
   do lado do nome dele em toda tela, pra você nunca confundir um médico com
   outro.
5. Clique em **"Testar conexão (homologação)"**. Deve aparecer uma
   mensagem dizendo que o certificado foi aceito. Se der erro, veja a seção
   9 antes de continuar.
6. Clique em **"Salvar prestador"**.

### b) Cadastrar um tomador (o cliente que vai receber a nota)

1. Vá na aba **"Tomadores"**.
2. No quadro da direita, digite só o **CNPJ** no campo e clique em
   **"Buscar"** — nome e endereço vêm sozinhos.
   (Pra CPF não tem busca automática, pelo mesmo motivo do item anterior —
   digite o nome à mão.)
3. Clique em **"Salvar tomador"**.

### c) Criar um modelo de serviço

1. Vá na aba **"Modelos e mensalidades"**, na sub-aba **"Modelos de
   serviço"**.
2. Preencha a descrição do serviço (ex.: "Consulta"), o **código de
   tributação nacional** (6 números) e, se a prefeitura exigir (nem toda
   cidade tem), o **código de tributação municipal** (3 números — pergunte
   pro contador do médico ou pra prefeitura; se a cidade não tiver um
   código próprio, deixe esse campo em branco), o **código NBS**
   (9 números) e o **valor padrão**.
3. Clique em **"Salvar modelo"**.

### d) Emitir uma nota avulsa

1. Vá na aba **"Emitir nota"**.
2. Escolha o **tomador** e o **serviço** (o valor já vem preenchido
   sozinho, mas pode mudar se precisar).
3. Clique em **"Emitir"**.

Se der certo, aparece uma mensagem com a chave de acesso da nota e o
caminho de onde o arquivo foi salvo.

### e) Onde encontrar o PDF/XML salvo

Toda nota emitida é salva automaticamente em:

```
Documentos\Notas Fiscais\<Nome do Prestador>\<Ano>\<Mês, ex.: "09 - Setembro">\Emitidas\
```

Pra não precisar procurar manualmente, vá na aba **"Histórico"**, clique
na nota na lista e depois no botão **"Abrir pasta"** — isso abre a pasta
certa direto no Windows Explorer, com o PDF e o XML já ali.

### f) Cliente retém imposto na fonte (convênio, plano de saúde)?

No cadastro do tomador (ou na hora de emitir a nota avulsa, se for só
daquela vez), tem uma pergunta em português simples: **"Este tomador retém
imposto na fonte?"**. Marque a caixinha do imposto que se aplica (IRRF,
ISS etc.) e o percentual — não precisa saber nome de campo de XML nem lei
nenhuma, o programa cuida da parte técnica sozinho. Convênios como Unimed
costumam ter uma regra fixa (ex.: sempre retêm 1,5% de IRRF) — cadastre uma
vez no tomador e todas as notas seguintes já vêm certas.

### g) Emitir várias notas de uma vez (planilha)

Na aba **"Emitir em lote"**, clique em **"Importar arquivo…"** e escolha
uma planilha `.csv` ou `.xlsx` com as colunas: tomador, serviço, valor. O
programa mostra uma prévia com o que vai e o que tem erro (linha por
linha, antes de emitir qualquer coisa) — corrija a planilha se precisar e
importe de novo. Só depois clique em **"Emitir linhas válidas"**.

### h) Cancelar uma nota

Cancelar de verdade avisa a Receita — a nota só fica "cancelada" depois da
confirmação do governo (nunca antes). No **Histórico**, clique na nota e
em **"Cancelar nota"**, escolha o motivo (erro na emissão, serviço não
prestado, ou outro) e confirme. Atenção: **existe um prazo legal** definido
pela prefeitura para cancelar — se passou do prazo, o programa avisa
claramente e a nota continua válida (peça orientação ao contador sobre como
corrigir, geralmente com uma nota de ajuste). O arquivo só é movido para a
pasta "Canceladas" depois da confirmação — nunca é apagado.

### i) Tomador ou prestador que não usa mais o sistema

Excluir só é permitido se aquele tomador/prestador nunca teve nota emitida
nem mensalidade cadastrada (pra não perder histórico por engano). Se já tem
histórico, o programa oferece **"Inativar"** em vez de excluir: some da
lista do dia a dia, mas nada é apagado — dá pra reativar a qualquer momento
marcando a caixinha **"Mostrar inativos"** na tela de Tomadores (ou
Prestadores, no topo da janela) e clicando em **"Reativar"**.

---

## 7. Como testar a automação (mensalidades sozinhas)

1. Vá em **"Modelos e mensalidades"** → sub-aba **"Mensalidades"**.
2. Escolha o tomador e o serviço, confira o valor, e no campo **"Dia do
   mês"** coloque **o dia de hoje** (assim você não precisa esperar o mês
   inteiro pra ver funcionando).
3. Deixe a caixinha **"Ativa"** marcada e clique em **"Salvar
   mensalidade"**.
4. Feche o programa (a janela vai pra bandeja do Windows, perto do
   relógio) e abra de novo com `python -m app.main` — ou simplesmente
   espere até 15 minutos com o programa aberto.
5. Você vai ver um aviso aparecer perto do relógio do Windows (a
   "notificação da bandeja") avisando que uma nota foi emitida sozinha. Na
   aba **"Meu Dia"**, a mensalidade aparece marcada como já emitida, e ela
   também aparece no **Histórico**, com o PDF já salvo na pasta.

Não precisa fazer mais nada — isso é literalmente o que vai acontecer
sozinho, todo mês, no dia configurado, mesmo que o computador tenha ficado
desligado no dia exato (o programa emite assim que perceber, na próxima vez
que for aberto, e avisa que a nota estava atrasada).

---

## 8. Como configurar o e-mail automático (a parte mais chata, mas só se faz uma vez)

O programa manda a nota por e-mail pro cliente sozinho, assim que ela é
emitida — mas primeiro você precisa contar pra ele qual e-mail usar pra
enviar. A maioria dos serviços de e-mail (Gmail, Outlook) não deixa mais
usar a senha normal da sua conta em programas de fora — é preciso criar uma
**"senha de aplicativo"**, uma senha extra, só pra isso, que não desce o
mesmo login da sua caixa de entrada.

### Se você usa Gmail

1. Sua conta Google precisa ter a **verificação em duas etapas** ligada
   (se ainda não tiver, acesse `myaccount.google.com` → **Segurança** →
   **Verificação em duas etapas**, e ative).
2. Ainda em `myaccount.google.com` → **Segurança**, procure por **"Senhas
   de app"** (ou acesse diretamente `myaccount.google.com/apppasswords`).
3. Dê um nome pra ela, tipo "Emissor NFS-e", e clique em gerar. O Google vai
   mostrar uma senha de 16 letras — **copie ela** (sem os espaços).
4. No Emissor NFS-e, vá na aba **"Configurações"** e preencha:
   - **Servidor SMTP:** `smtp.gmail.com`
   - **Porta:** `587`
   - **Usuário (e-mail):** o seu e-mail completo (ex.:
     `clinica@gmail.com`)
   - **Senha:** a senha de 16 letras que você copiou (não é a senha normal
     do Gmail!)
5. Clique em **"Salvar configurações"**.

### Se você usa Outlook/Hotmail

1. Servidor SMTP: `smtp.office365.com` — Porta: `587`.
2. Se a conta tiver verificação em duas etapas, gere uma senha de
   aplicativo em `account.microsoft.com` → **Segurança** → **Opções de
   segurança avançadas** → **Senhas de aplicativo**, e use ela no lugar da
   senha normal.

Depois de configurado, não precisa fazer mais nada — toda nota emitida
(avulsa, em lote ou mensalidade automática) já sai com o e-mail pro
tomador, com o PDF/XML anexado.

---

## 9. Deu problema? Os erros mais comuns

**"Certificado não pôde ser lido" / "Não deu pra abrir o certificado"**
A senha digitada está errada, ou o arquivo `.pfx` está corrompido/é outro
arquivo. Confira maiúsculas/minúsculas e o Caps Lock, e confirme que
escolheu o arquivo certo. Se o problema persistir, peça pro médico
exportar o certificado de novo.

**"Não foi possível falar com o sistema da Receita agora"**
Não tem internet no momento, ou o sistema do governo está fora do ar. Não
precisa fazer nada — a nota fica "pendente" e o programa tenta de novo
sozinho (em 5 min, depois 30 min, depois de 2 em 2 horas). Só confira sua
internet se demorar demais.

**E-mail aparece como "Não enviado" no Histórico**
O SMTP não está configurado (veja a seção 8), ou a senha usada é a senha
normal da conta em vez da senha de aplicativo. A nota **já foi emitida
normalmente** — só o envio do e-mail falhou. Corrija a configuração e
clique em **"Reenviar e-mail"** na nota, no Histórico.

**Nota aparece como "Rejeitada"**
O motivo aparece traduzido em português, sem código técnico, na coluna
"Detalhe" do Histórico. Na maioria das vezes é um dado errado no **modelo
de serviço** (código de tributação nacional/municipal) — confira com o
contador do médico e corrija o modelo antes de tentar de novo.

**Não encontro CNPJ ao clicar em "Buscar"**
O CNPJ não existe na Receita Federal, ou você digitou algum número errado.
Confira os 14 números. Se o CNPJ realmente for novo/recente, pode levar
alguns dias pra aparecer nas bases públicas — nesse caso, preencha os
dados manualmente.

**Não consigo nem abrir o programa (`python -m app.main` dá erro)**
Confirme que está na pasta certa (`cd caminho\...\emissor-nfse`) e que
rodou `.venv\Scripts\activate` antes — o Prompt de Comando deve mostrar
`(.venv)` escrito no começo da linha. Se ainda der erro, rode de novo
`pip install -r requirements.txt` pra garantir que nada ficou faltando.

**"Este CNPJ/CPF não é válido" ao salvar um cadastro**
O número tem a quantidade certa de dígitos, mas o dígito verificador não
bate — quase sempre é erro de digitação (dois números trocados). Confira
o número com calma antes de digitar de novo.

**"Não deu pra falar com o programa agora" (só no protótipo web)**
A Janela 1 (o backend, `python -m app.api`) não está aberta ou travou.
Confira se essa janela ainda está rodando; se não estiver, abra de novo
(veja a seção 11).

---

## 9.1 Checklist de teste antes de apresentar pro médico

Rode esse roteiro sozinha, sem o médico do lado, pra confirmar que está
tudo certo antes da apresentação de verdade. Leva uns 5 minutos:

1. **Abra o programa** (`python -m app.main`) e confira que a faixa
   🧪 **HOMOLOGAÇÃO (teste)** aparece bem visível no topo — se não
   aparecer, **pare e avise**, isso não pode acontecer na apresentação.
2. Na aba **"Meu Dia"**, confira que o resumo do dia aparece (mesmo que
   vazio, não pode dar erro na tela).
3. **Emita uma nota avulsa** (seção 6d) com um prestador que **não** seja
   optante do Simples Nacional, ou com a alíquota em branco — confirme que
   aparece a mensagem "Nota emitida!" com a chave de acesso.
4. Vá no **Histórico**, confirme que a nota aparece na lista, clique em
   **"Abrir pasta"** e confira que o PDF e o XML estão lá, com o mesmo
   nome de arquivo.
5. Volte pra **"Meu Dia"** e confira que a nota que você acabou de emitir
   não aparece mais como pendente.

Se todos os 5 passos passarem sem nenhuma mensagem de erro em inglês, sem
texto técnico cru (tipo "Traceback" ou "Exception") e sem a janela travar
por mais de alguns segundos, **está pronto pra apresentar**. Evite, na
frente do médico: editar um prestador com pressa, cancelar uma nota só pra
mostrar (o cancelamento avisa a Receita de verdade, mesmo em homologação),
e copiar/colar um valor de outro sistema sem conferir o formato antes.

---

## 10. ⚠️ MUITO IMPORTANTE — como trocar de Homologação (teste) pra Produção (nota de verdade)

**Só faça isso com autorização explícita do médico/prestador.** A partir do
momento em que você troca pra produção, **toda nota emitida é um documento
fiscal real**, com validade legal, que o médico é obrigado a declarar e
pagar imposto em cima. Não existe "desfazer" — uma nota de produção emitida
por engano é um problema fiscal de verdade, não um erro que se apaga.

Por segurança, essa troca **não é um botão na tela** — é preciso mudar
diretamente no código do programa, um passo deliberado, exatamente pra
evitar que alguém mude sem querer:

1. Feche o programa.
2. Abra o arquivo `app/core/fila.py` num editor de texto (o Bloco de Notas
   do Windows serve).
3. Use "Localizar" (Ctrl+F) e procure pelo texto `homologacao` (sem
   acento — é assim que está escrito no arquivo). Você vai encontrar esse
   texto **3 vezes**, dentro da função `emitir_nota_real` e logo acima
   dela. Troque as três ocorrências para `producao`.
4. Salve o arquivo.
5. Abra o programa de novo (`python -m app.main`). A partir daí, a faixa
   no topo da tela não vai mais dizer "HOMOLOGAÇÃO" — e toda nota emitida
   passa a ser real.

Se algum dia quiser voltar pro modo de teste, é só desfazer a mesma troca
(trocar `producao` de volta pra `homologacao` nos mesmos 3 lugares).

---

## 11. Protótipo web (prototype/) — a vitrine conectada ao backend real

Além do programa desktop, existe um protótipo web (`prototype/`) com uma
interface mais bonita pra mostrar pro cliente — mas que fala com o **mesmo
backend, mesmo banco de dados, mesmas regras** do programa desktop. Cadastrar
um prestador ou emitir uma nota por ali é tão real quanto fazer isso no app
desktop (inclusive aparece no mesmo Histórico, na mesma pasta).

Pra isso funcionar, precisa de **dois programas rodando ao mesmo tempo**, em
duas janelas de terminal separadas:

**Janela 1 — o backend (a "ponte" com o banco de dados):**
```
.venv\Scripts\activate
pip install -r requirements-api.txt
python -m app.api
```
Deixe essa janela aberta. Ela mostra `Running on http://127.0.0.1:8000`.

**Janela 2 — o frontend (a tela bonita):**
```
cd prototype
npm install
npm run dev
```
Abre em `http://localhost:5173/` — acesse esse endereço no navegador.

Se a Janela 1 não estiver rodando, o protótipo mostra um aviso claro na tela
("Não consegui falar com o backend...") em vez de travar.

`npm install` só precisa rodar uma vez (ou de novo se este guia disser que
uma dependência nova foi adicionada). Nas próximas vezes, só `npm run dev`.

---

## Documentação técnica

Para quem for mexer no código: a especificação completa do projeto está em
`docs/spec-mvp.md`, e o spike original (Sprint 0, primeiro teste da API do
governo) está em `spike/`, intocado, como referência histórica. A ponte
HTTP entre o protótipo web e o backend (`app/api.py`) não faz parte do
produto descrito na espec — é só uma ferramenta de demonstração/venda.
