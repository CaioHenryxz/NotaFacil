# XSD oficial do Sistema Nacional NFS-e (v1.01)

Vendorizado (não baixado a cada teste) pra `tests/test_schema_xsd.py` poder
validar o XML da DPS de verdade, sem depender de rede — o mesmo pacote
`NFSe-ESQUEMAS_XSD-v1.01-20260209.zip` usado na auditoria de
`docs/auditoria-2.md`, seção 8 (o "achado mais importante" daquela
auditoria: nenhuma verificação anterior tinha rodado validação de schema
de verdade, só leitura visual — foi assim que o bug do `cTribMun` com 10
dígitos, em vez de 3, passou despercebido).

- **Fonte:** `https://www.gov.br/nfse/pt-br/biblioteca/documentacao-tecnica/documentacao-atual/nfse-esquemas_xsd-v1-01-20260209.zip`
- **Baixado em:** 23/jul/2026 (confirmado no portal, na ocasião, como o
  pacote vigente em produção — sem versão mais nova publicada).
- **Não editar estes arquivos.** Se sair um XSD novo, baixar o pacote de
  novo inteiro e substituir a pasta — não remendar arquivo por arquivo.

Achado conhecido registrado em `docs/auditoria-2.md`, seção 8.2: o tipo
`TSSerieDPS` (campo `serie`) usa o padrão `^0{0,4}\d{1,5}$`, mas XML Schema
(Anexo F da spec W3C) não trata `^`/`$` como âncoras — são literais nesse
dialeto de regex. Isso faz QUALQUER valor normal de série falhar contra
esse padrão especificamente. É um bug de autoria do XSD **oficial do
governo**, não deste app — `tests/test_schema_xsd.py` ignora
especificamente esse erro (e só esse) ao decidir se o documento passou.
