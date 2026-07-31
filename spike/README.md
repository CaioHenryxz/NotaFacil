# Spike Sprint 0 — emitir 1 NFS-e em homologação (Produção Restrita)

Objetivo (espec-mvp-emissor-nfse.md, §8, risco 1): validar contra a API real do
Emissor Nacional os pontos que nenhuma leitura de documentação resolve sozinha —
layout exato da DPS aceito, forma de assinatura, e o roteiro de erros de
validação — **antes** de começar a UI. Este é código puro, sem PySide6, sem
SQLite, sem fila: um script, uma nota.

Dependências usadas (subconjunto da lista fechada da espec, §7): `httpx`,
`signxml`, `cryptography` (mais `lxml`, que é dependência transitiva do
`signxml` e faz a montagem do XML). Nada de UI/banco/e-mail/licenciamento aqui
— isso é Sprint 1+.

## O que você precisa antes de rodar

1. **Python 3.12** instalado.
2. **Um certificado A1 de teste** (.pfx + senha) de um prestador cadastrado e
   conveniado no Sistema Nacional NFS-e, com inscrição municipal ativa. Sem
   isso não dá pra testar — é o único item pago do MVP inteiro (espec, §10).
   Se o Caio já tiver certificado de um cliente beta autorizado, usar esse.
3. Saber o **CNPJ/CPF do prestador**, a **inscrição municipal** e o
   **código IBGE do município** onde ele está cadastrado.
4. Um **código de tributação nacional (`cTribNac`)** e **código de tributação
   municipal (`cTribMun`)** válidos para o serviço a ser testado — ver seção
   "Como descobrir os códigos" abaixo.

## Instalação

```bash
cd spike
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install httpx signxml cryptography
```

## Configuração

```bash
copy config.exemplo.json config.json
```

Edite `config.json` com os dados reais do prestador/tomador/serviço de teste.
**Não** commite `config.json` nem o `.pfx` — os dois têm segredo/dado
sensível. Só `config.exemplo.json` (com zeros) deve ir pro controle de versão.

A senha do certificado **não** vai no JSON. Ou:

- exporte a variável de ambiente `NFSE_CERT_SENHA` antes de rodar, ou
- deixe em branco e o script pergunta a senha na hora (`getpass`, não fica no
  histórico do shell).

```bash
set NFSE_CERT_SENHA=sua-senha-aqui   # cmd
$env:NFSE_CERT_SENHA = "sua-senha-aqui"  # PowerShell
```

## Rodar

```bash
python emitir_nota.py config.json
```

O script:
1. lê o `.pfx`, extrai chave privada + certificado (`cryptography`);
2. monta a DPS em XML (`dps_builder.montar_dps_xml`);
3. assina o `infDPS` com o certificado (`dps_builder.assinar_dps`, XMLDSig via
   `signxml`), anexando `<Signature>` como irmão de `<infDPS>` dentro de
   `<DPS>` — exatamente como o XSD oficial define (`TCDPS`);
4. compacta o XML assinado (gzip) e codifica em base64;
5. faz `POST` para a Sefin Nacional em **produção restrita**
   (`https://sefin.producaorestrita.nfse.gov.br/SefinNacional/nfse`),
   autenticando via **mTLS** com o mesmo certificado A1 (o certificado é usado
   tanto para assinar o XML quanto para autenticar a conexão HTTPS — são dois
   usos distintos do mesmo arquivo);
6. imprime a DPS enviada e a resposta da API. Em sucesso (`201`), grava o XML
   da NFS-e gerada em `nfse_<chave-de-acesso>.xml` — essa é a prova de que a
   nota existe e está consultável em homologação (critério de aceite do
   Sprint 0).

## Como descobrir os códigos (`cTribNac`, `cTribMun`, `cNBS`, alíquota)

Antes de emitir, a API de **Parâmetros Municipais** do próprio Emissor
Nacional informa o que o município de destino exige:

- `GET /parametros_municipais/{codigoMunicipio}/{codigoServico}` — alíquotas,
  regime especial e deduções/reduções para aquele código de serviço.

Esses valores variam por município e por atividade — não dá pra cravar um
default universal. O `config.exemplo.json` traz valores de exemplo (com
formato correto, mas sem validade fiscal real) só para não deixar o JSON
vazio.

## O que está confirmado vs. o que precisa validar no teste real

Toda a estrutura abaixo foi conferida diretamente contra o **XSD oficial v1.01**
do Sistema Nacional NFS-e (mesmo namespace usado pela API:
`http://www.sped.fazenda.gov.br/nfse`) e contra o *Manual dos Contribuintes -
Sistema Nacional NFS-e v1.2* (gov.br/nfse). A DPS gerada por `dps_builder.py`
foi validada de ponta a ponta (montagem + assinatura) contra esse XSD antes de
este spike ser entregue — inclusive o atributo `versao="1.01"` do elemento
`<DPS>` (o XSD rejeita `"1.00"`, valor citado por algumas fontes secundárias).
Isso cobre a forma dos elementos. O que o XSD **não** garante — e só a
resposta real da API confirma — é:

| Ponto | Status | Onde olhar se rejeitar |
|---|---|---|
| Endpoint `POST /nfse` em `sefin.producaorestrita.nfse.gov.br/SefinNacional` | Confirmado por 3 fontes independentes (manual oficial, relato técnico de integração, thread de outro integrador) | — |
| Corpo `{"dpsXmlGZipB64": "<xml assinado, gzip, base64>"}` | Confirmado por relato de integração real | Se a API responder erro de parsing do corpo, conferir Swagger em `adn.producaorestrita.nfse.gov.br/contribuintes/docs/index.html` (não consegui raspar o Swagger — bloqueou a busca automatizada) |
| Ordem/nomes dos elementos de `infDPS`, `prest`, `toma`, `serv`, `valores` | Confirmado direto no XSD | — |
| `tpInsc` no `Id` do DPS = 1 CPF / 2 CNPJ (invertido vs. NF-e) | **Não confirmado no XSD** (a regra de formação do `Id` é regra de negócio do Anexo I, não do XSD). Vem de relato de integração real | Erro `RNG6110` ou `E0004` de "Id/identificador da DPS" → primeira coisa a checar |
| Algoritmo de assinatura (RSA-SHA256, digest SHA-256, C14N não-exclusivo) | **Não confirmado por fonte primária** — é a convenção usual dos DF-es brasileiros (NF-e/NFS-e municipal), aplicada aqui por analogia | Erro de assinatura (tipo `E0714`, "arquivo enviado com erro na assinatura") → tentar `rsa-sha1`/outro `c14n_algorithm` em `dps_builder.assinar_dps` |
| `cTribMun` com 10 dígitos | Confirmado no XSD (`TSCodTribMun`, `pattern [0-9]{10}`) — **diferente** do que blogs de terceiros descrevem (alguns citam 3 dígitos) | — |
| `cNBS` obrigatório, 9 dígitos | Confirmado no XSD (`minOccurs="1"`) — fácil de esquecer, vários integradores tratam como opcional | Erro de campo obrigatório ausente em `cNBS` |
| `opSimpNac`: 1 Não optante / 2 MEI / 3 ME-EPP | Confirmado no XSD — **atenção**: é o oposto do que alguma documentação de terceiros sugere (tratando 1 como "optante") | — |

Se a primeira tentativa for rejeitada, a mensagem de erro da API (campos
`Codigo`/`Descricao`/`Complemento` no JSON de resposta, impresso pelo script)
é a fonte mais confiável — mais do que qualquer blog de terceiro consultado
aqui. Ajustar `dps_builder.py` e rodar de novo é o próprio processo do Sprint 0.

## Estrutura

- `dps_builder.py` — só a montagem e assinatura do XML (`montar_dps_xml`,
  `assinar_dps`, `serializar`). Zero I/O de rede, zero leitura de arquivo —
  isolado de propósito (espec, §8, risco 2: mudança de layout custa 1 arquivo).
- `emitir_nota.py` — orquestração: lê config e certificado, chama o
  `dps_builder`, faz a chamada HTTPS com mTLS, trata a resposta.
- `config.exemplo.json` — modelo de configuração (sem segredo).

## Fontes consultadas

- Manual dos Contribuintes - Sistema Nacional NFS-e, Guia para utilização das
  API's do Emissor Público Nacional, v1.2 (out/2025) — gov.br/nfse.
- `schema_v101.xsd` — XSD oficial do layout DPS/NFS-e v1.01 (mesmo namespace
  usado pela API nacional).
- Portal gov.br/nfse — [Documentação Técnica](https://www.gov.br/nfse/pt-br/biblioteca/documentacao-tecnica) e [APIs Prod. Restrita e Produção](https://www.gov.br/nfse/pt-br/biblioteca/documentacao-tecnica/apis-prod-restrita-e-producao).
- Relatos técnicos de integradores independentes (formato do corpo da
  requisição, regra de formação do `Id` da DPS, gotchas de validação).

## Próximo passo depois que a nota emitir

Consultar a nota pela chave de acesso (`GET /nfse/{chaveAcesso}`) no mesmo
ambiente, pra fechar o critério de aceite do Sprint 0 ("nota aparece
consultável no ambiente de homologação"). Não incluí esse passo no script
porque o objetivo aqui era só a emissão — mas é a mesma lógica de mTLS + URL
base, só troca o método/caminho.
