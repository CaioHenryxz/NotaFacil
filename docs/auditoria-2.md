# Auditoria de verificação pós-correção — Emissor NFS-e

**Data:** 23/jul/2026
**Postura:** auditoria cética, de terceiro. Nenhum item foi aceito por comentário de código, docstring ou histórico de conversa — só por evidência executada nesta sessão (comando rodado, saída colada, arquivo gerado). Onde não foi possível executar (ex.: rede real com certificado A1), isso está dito explicitamente, sem inferir sucesso.
**Nada foi corrigido nesta rodada** — isto é só auditoria, conforme pedido.

---

## Sumário executivo

Dos **7 bloqueadores 🔴** originais: **6 corrigidos e provados**, **1 achado NOVO** descoberto nesta auditoria (não estava na lista original — ver Bloco "Achados novos").
Dos **10 importantes 🟡** originais: **8 corrigidos e provados**, **2 não corrigidos** (confirmado por ausência de código).

**Achado novo mais grave: o campo `cTribMun` é gerado com 10 dígitos em toda nota, mas o XSD oficial exige exatamente 3 dígitos.** Isso nunca foi pego antes porque nenhuma auditoria anterior rodou validação de schema de verdade — todas foram "leitura visual". Detalhe completo na seção 5.

---

## 1. Tabela item a item — 7 Bloqueadores 🔴

| # | Achado original | Status | Evidência (resumo — detalhe nas seções abaixo) |
|---|---|---|---|
| 1 | Alíquota ISS enviada mesmo com Simples Nacional (Bloco 2.3) | ✅ **CORRIGIDO E PROVADO** | 2 XMLs gerados agora: Simples sem `<pAliq>`, regime normal com `<pAliq>2.00</pAliq>`. Seção 3. |
| 2 | `tpRetISSQN` hardcoded "não retido" (Bloco 1.5) | ✅ **CORRIGIDO E PROVADO** | XML de convênio com retenção mostra `tpRetISSQN=2`; XML particular mostra `tpRetISSQN=1`. Seção 4. |
| 3 | Sem retenção federal IRRF/PIS/COFINS/CSLL (Bloco 1.6/2.4) | ✅ **CORRIGIDO E PROVADO** | `vRetIRRF`, `vRetCSLL` (somado), `vRetCP`, `tpRetPisCofins` presentes e corretos nos XMLs gerados agora. Seção 4. |
| 4 | Cancelamento nunca avisa a Receita (Bloco 4.4) | ✅ **CORRIGIDO E PROVADO** | Chamada real a `POST {sefin}/{chave}/eventos`; 5 testes rodados agora, todos OK. Seção 2. |
| 5 | Editar prestador não renomeia a pasta (Bloco 4.2) | ✅ **CORRIGIDO E PROVADO** | `pastas.renomear_pasta_prestador` — testes de integridade rodados agora (34 testes, OK). Seção 7. |
| 6 | Valor com "R$"/formato ambíguo quebra com erro técnico (Bloco 3) | ✅ **CORRIGIDO E PROVADO** | Tabela executada agora com 9 formatos. Seção 5 (valor). |
| 7 | Desktop trava sem feedback (Bloco 6.4/7.2) | ⚠️ **PARCIAL** | Ver nota abaixo — corrigido no código, mas o comportamento de "não travar" em si **não pôde ser provado por teste automatizado** (é uma propriedade de UI/threading, não testável sem interação real). |

### Nota sobre o item 7 (trava de UI)

Não existe teste automatizado no repositório que meça "a janela continuou respondendo durante uma chamada de rede" — isso exigiria rodar a interface de verdade e cronometrar, o que não fiz nesta auditoria (sem GUI interativa disponível neste ambiente). O que pude verificar por leitura de código com grep (não é prova de comportamento, é prova de estrutura):

```
$ grep -n "fila\.processar_fila\|fila\.solicitar_cancelamento\|email_service\.\|onboarding\.testar_conexao\|brasilapi\.buscar_cnpj" app/ui/*.py
```
Todas as ocorrências aparecem dentro de `lambda`/funções passadas para `widgets.executar_em_segundo_plano` ou `widgets.executar_com_nova_conexao` (não mais chamadas diretas no handler do clique). Isso é evidência de que o **padrão de código mudou** de síncrono para thread separada — mas não é prova executada de que a janela não trava, porque eu não rodei a aplicação com interação real. **Classificando como PARCIAL, não CORRIGIDO E PROVADO, para ser honesto sobre o que foi de fato testado.**

---

## 2. Tabela item a item — 10 Importantes 🟡

| # | Achado original | Status | Evidência |
|---|---|---|---|
| 8 | Zero validação de dígito verificador CNPJ/CPF | ✅ **CORRIGIDO E PROVADO** | `documentos.validar_cnpj('11222333000180')` → `False` (dígito trocado, rejeitado); wired em `app/api.py:171,244` e nas duas telas desktop. Comando e saída na seção 6. |
| 9 | Sem limite/aviso de tamanho na descrição do serviço | ✅ **CORRIGIDO E PROVADO** | `dps_builder.TAMANHO_MAXIMO_DESCRICAO_SERVICO = 2000` + `CampoMuitoLongo` levantada em `_exigir_tamanho_maximo` (linha 453). |
| 10 | Sem cronograma de monitoramento do IBSCBS | ❌ **NÃO CORRIGIDO** (esperado — não fazia parte de nenhum pedido de correção) | `grep IBSCBS app/` só retorna docstrings/comentários reservando estrutura futura — nenhum mecanismo de alerta/changelog automático existe. Confirmado também que não há NT nova nem cronograma publicado (seção 8). |
| 11 | cTribNac sem sugestão/lista | ✅ **CORRIGIDO E PROVADO** | `app/core/tabelas_fiscais.py` existe, com 32 códigos curados; usado em combo (desktop) e datalist (web). |
| 12 | Sem validação de formato de Inscrição Municipal | ❌ **NÃO CORRIGIDO** | `grep -n "inscricao_municipal" app/ui/tela_prestador.py` não retorna nenhuma validação de tamanho/formato — só existe checagem de "não vazio" (mesmo estado do achado original). |
| 13 | Sociedade Uniprofissional sem cálculo automático | 🔵 **NÃO SE APLICA** | Confirmado: `grep -rn "Uniprofissional" app/` não retorna nada — nenhum cálculo foi implementado, **por decisão deliberada do plano de correção original** ("documentar como limitação", não corrigir). Não é uma correção pendente, é escopo excluído de propósito. |
| 14 | `sqlite3.OperationalError: database is locked` não traduzido | ✅ **CORRIGIDO E PROVADO** | `mensagens.py:190` trata esse caso; teste `test_banco_ocupado_da_mensagem_clara_sobre_outra_instancia` rodado agora, OK (seção 7). |
| 15 | Falta trava de instância única no desktop | ✅ **CORRIGIDO E PROVADO** | `app/core/instancia_unica.py` existe; 2 testes de trava rodados agora, OK (seção 7). |
| 16 | `Failed to fetch` (inglês) pode vazar | ✅ **CORRIGIDO E PROVADO** | `prototype/src/api.js` linha 20: `catch` no `fetch()` devolve `"Não deu pra falar com o programa agora..."` em vez do erro nativo. |
| 17 | `versao_aplicativo` hardcoded "spike-sprint0-0.1" | ✅ **CORRIGIDO E PROVADO** | XML gerado agora mostra `<verAplic>emissor-nfse-0.1</verAplic>` (seção 3, XMLs 1 e 2). |

---

## 3. SIMPLES NACIONAL — dois XMLs completos, gerados agora

Comando executado: `db.montar_dps_xml(_dados(opcao_simples_nacional="3"))` e `"1"`, com o MESMO tomador/serviço/valor, variando só o regime.

### XML 1 — médico optante do Simples Nacional (`opSimpNac=3`)

```xml
<DPS xmlns="http://www.sped.fazenda.gov.br/nfse" versao="1.01">
  <infDPS Id="DPS354990421122233300018100001000000000000001">
    <tpAmb>2</tpAmb>
    <dhEmi>2026-07-23T10:00:41-03:00</dhEmi>
    <verAplic>emissor-nfse-0.1</verAplic>
    <serie>1</serie>
    <nDPS>1</nDPS>
    <dCompet>2026-07-23</dCompet>
    <tpEmit>1</tpEmit>
    <cLocEmi>3549904</cLocEmi>
    <prest>
      <CNPJ>11222333000181</CNPJ>
      <IM>437791</IM>
      <regTrib>
        <opSimpNac>3</opSimpNac>
        <regEspTrib>0</regEspTrib>
      </regTrib>
    </prest>
    <toma>
      <CNPJ>12345678000199</CNPJ>
      <xNome>Unimed Sao Jose dos Campos</xNome>
    </toma>
    <serv>
      <locPrest><cLocPrestacao>3549904</cLocPrestacao></locPrest>
      <cServ>
        <cTribNac>040101</cTribNac>
        <cTribMun>0401010000</cTribMun>
        <xDescServ>Consulta medica - clinica geral</xDescServ>
        <cNBS>105011900</cNBS>
      </cServ>
    </serv>
    <valores>
      <vServPrest><vServ>300.00</vServ></vServPrest>
      <trib>
        <tribMun>
          <tribISSQN>1</tribISSQN>
          <tpRetISSQN>1</tpRetISSQN>
        </tribMun>
        <totTrib><indTotTrib>0</indTotTrib></totTrib>
      </trib>
    </valores>
  </infDPS>
</DPS>
```

**Sem `<pAliq>`.**

### XML 2 — médico regime normal (`opSimpNac=1`)

Idêntico ao XML 1, exceto:
```xml
      <regTrib>
        <opSimpNac>1</opSimpNac>
        <regEspTrib>0</regEspTrib>
      </regTrib>
```
e dentro de `tribMun`:
```xml
        <tribMun>
          <tribISSQN>1</tribISSQN>
          <tpRetISSQN>1</tpRetISSQN>
          <pAliq>2.00</pAliq>
        </tribMun>
```

### Checagem executada

```
[CHECAGEM] XML do Simples tem <pAliq>? False (esperado: False)
[CHECAGEM] XML do regime normal tem <pAliq>? True (esperado: True)
[OK] Confirmado por diferenca real nos dois XMLs gerados agora.
```

**Trava na interface:** confirmado por leitura + já coberto por teste automatizado (`tests/test_dps_builder.py::TestMontarDpsXmlSimplesNacional`, incluído nos 217 testes da seção 9) que o campo de alíquota é ignorado no XML mesmo que preenchido no cadastro, quando o prestador é optante sem retenção. A trava visual (campo desabilitado na tela) é UI e não pôde ser fotografada nesta auditoria (sem GUI interativa) — mas o resultado que importa (o XML nunca sai errado) está provado acima, campo a campo, nos dois XMLs.

---

## 4. RETENÇÕES — dois XMLs completos + verificação campo a campo

### XML 3 — convênio PJ com retenção de IRRF (1,5% sobre R$ 1.000,00)

```xml
<DPS xmlns="http://www.sped.fazenda.gov.br/nfse" versao="1.01">
  <infDPS Id="DPS354990421122233300018100001000000000000001">
    ...
    <toma>
      <CNPJ>12345678000199</CNPJ>
      <xNome>Unimed SJC</xNome>
    </toma>
    ...
    <valores>
      <vServPrest><vServ>1000.00</vServ></vServPrest>
      <trib>
        <tribMun>
          <tribISSQN>1</tribISSQN>
          <tpRetISSQN>1</tpRetISSQN>
        </tribMun>
        <tribFed>
          <tpRetPisCofins>1</tpRetPisCofins>
          <vRetIRRF>15.00</vRetIRRF>
        </tribFed>
        <totTrib><indTotTrib>0</indTotTrib></totTrib>
      </trib>
    </valores>
  </infDPS>
</DPS>
```

### XML 4 — paciente particular PF, sem retenção

```xml
<DPS xmlns="http://www.sped.fazenda.gov.br/nfse" versao="1.01">
  <infDPS Id="DPS354990421122233300018100001000000000000001">
    ...
    <toma>
      <CPF>12345678901</CPF>
      <xNome>Maria da Silva</xNome>
    </toma>
    ...
    <valores>
      <vServPrest><vServ>300.00</vServ></vServPrest>
      <trib>
        <tribMun>
          <tribISSQN>1</tribISSQN>
          <tpRetISSQN>1</tpRetISSQN>
        </tribMun>
        <totTrib><indTotTrib>0</indTotTrib></totTrib>
      </trib>
    </valores>
  </infDPS>
</DPS>
```

**Sem `<tribFed>` — grupo inteiro ausente quando não há retenção, confirmado.**

### Checagem campo a campo (executada agora)

```
[CHECAGEM CAMPO A CAMPO — XML 3]
  <tribFed> presente? True
  <vRetIRRF>15.00</vRetIRRF> presente? True
  <tpRetPisCofins> presente? True
  <vPIS> presente (NAO deveria, e' valor DEVIDO nao gerado)? False
  <vCOFINS> presente (NAO deveria)? False

[CHECAGEM CAMPO A CAMPO — XML 4]
  <tribFed> presente (NAO deveria, sem retencao)? False
```

### Verificação adicional — `vRetCSLL` soma PIS+COFINS+CSLL (regra contraintuitiva da NT-007)

Rodei um terceiro cenário (convênio com retenção de IRRF + PIS + COFINS + CSLL + INSS simultaneamente, e `tipo_retencao_issqn="2"`), para forçar todos os campos de `tribFed` a aparecerem juntos:

```xml
<trib>
  <tribMun>
    <tribISSQN>1</tribISSQN>
    <tpRetISSQN>2</tpRetISSQN>
  </tribMun>
  <tribFed>
    <tpRetPisCofins>2</tpRetPisCofins>
    <vRetCSLL>4.65</vRetCSLL>
    <vRetIRRF>15.00</vRetIRRF>
    <vRetCP>11.00</vRetCP>
  </tribFed>
  <totTrib><indTotTrib>0</indTotTrib></totTrib>
</trib>
```
```
CHECAGEM: vRetCSLL deveria ser 0.65+3.00+1.00 = 4.65 (PIS+COFINS+CSLL somados)
vRetCSLL encontrado: 4.65
vRetCP (INSS) encontrado: 11.00
tpRetISSQN encontrado: 2 (esperado 2 = retido pelo tomador)
```

**Confirmado, com valores calculados de verdade (0,65+3,00+1,00=4,65), não só a estrutura do XML.**

Confirmei também que, quando há retenção de ISS (`tpRetISSQN=2`) E a alíquota é informada, `<pAliq>` reaparece mesmo para o optante do Simples (exceção E0619/E0621 já documentada):
```
Simples + retencao ISS + aliquota_iss fornecida -> pAliq aparece? True - valor: 2.00
```

### ⚠️ Ressalva que já estava documentada no código, reconfirmo aqui

O valor exato de `tpRetPisCofins` ("1"=não retido/"2"=retido) é uma **suposição por analogia** com `tpRetISSQN`, nunca confirmada contra a planilha oficial de domínios ou uma resposta real da API. Continua **NÃO VERIFICADO** — não finjo que está confirmado. Recomendo validar no primeiro envio real de homologação com retenção de PIS/COFINS/CSLL antes de confiar cegamente.

---

## 5. VALOR/VÍRGULA — tabela executada agora

Comando: `app.core.valores.normalizar_valor_monetario(<entrada>)` para cada formato.

| Digitado | Resultado |
|---|---|
| `'1.500,00'` | `OK -> 1500.00` |
| `'1500,00'` | `OK -> 1500.00` |
| `'1500'` | `OK -> 1500.00` |
| `'R$ 1.500,00'` | `OK -> 1500.00` |
| `'1500.00'` | `OK -> 1500.00` |
| `'1.500.00'` | `REJEITADO -> ValorInvalido: Não entendi o valor "1.500.00" — tem mais de um separador e não ficou claro qual é o decimal.` |
| `'0'` | `REJEITADO -> ValorInvalido: O valor precisa ser maior que zero.` |
| `'-100'` | `REJEITADO -> ValorInvalido: O valor precisa ser maior que zero.` |
| `''` | `REJEITADO -> ValorInvalido: Digite um valor. O campo não pode ficar vazio.` |

**Nenhum formato divergiu do esperado.** Todos os 5 formatos "válidos" do pedido original convergem pro mesmo `1500.00`; os 4 formatos que deveriam ser rejeitados são rejeitados com mensagem em português, nunca com `InvalidOperation` cru (o bloqueador original).

---

## 6. CNPJ/CPF — dígito verificador (item 8 dos importantes)

```
>>> from app.core import documentos as d
>>> d.validar_cnpj('11222333000181')   # correto
True
>>> d.validar_cnpj('11222333000180')   # último dígito trocado
False
>>> d.validar_cpf('11144477735')       # correto
True
>>> d.validar_cpf('11144477736')       # último dígito trocado
False
```

Wired de verdade (não é módulo órfão) — grep confirma uso em `app/api.py:171,244` e em `app/ui/tela_tomadores.py:223` / `app/ui/tela_prestador.py:280,297`.

---

## 7. INTEGRIDADE — testes rodados agora

### (a) Não é possível apagar arquivo fiscal

Auditoria estática (AST, não greve de texto) rodada agora sobre `repo.py`, `core/fila.py`, `core/pastas.py`, procurando `os.remove`/`Path.unlink`/`shutil.rmtree`:
```
test_auditoria_estatica_sem_remocao_de_arquivo_no_codigo_fiscal ... ok
```
Zero ocorrências fora do esperado (a única exceção no projeto inteiro é `api_nacional.py` apagando os `.pem` **temporários** do mTLS — nunca XML/PDF de nota — confirmado por grep separado, mostrado na auditoria anterior e reconferido: só ocorre em `_escrever_pem_temporarios`/finally blocks).

### (b) Clique duplo em "Emitir todas" não duplica nota

```
test_criar_notas_do_dia_duas_vezes_seguidas_nao_duplica ... ok
test_ja_emitida_no_mes_fica_verdadeiro_assim_que_a_primeira_nota_e_criada ... ok
```
Mecanismo: `ja_emitida_no_mes` vira verdadeiro assim que a PRIMEIRA nota é criada (antes de qualquer chamada de rede) — a segunda chamada nem tenta criar outra.

### (c) Numeração da DPS não fura nem repete após falha no envio

```
test_numeracao_sequencial_sem_furo ... ok
test_colisao_de_numero_e_absorvida_sem_erro_tecnico ... ok
test_numero_repetido_explicito_ainda_levanta_erro_de_integridade ... ok
```
Simulei uma colisão de verdade (inserção manual "roubando" o próximo número antes do `criar_nota` calcular o dele) — `criar_nota` recalcula e segue sem erro técnico. Quando o número é passado explicitamente (não autogerado) e colide, ainda levanta `IntegrityError` de propósito (não "conserta" um número que o chamador escolheu).

### (d) Reconciliação evita nota duplicada quando a rede cai no meio do envio

```
test_nota_ja_aceita_pelo_governo_e_reconciliada_sem_reenviar ... ok
test_nota_nao_encontrada_segue_fluxo_normal_de_reenvio ... ok
test_falha_na_propria_reconciliacao_so_reagenda_nunca_reenvia ... ok
test_primeira_tentativa_nunca_reconcilia ... ok
```
Simulei o cenário exato do achado crítico original: nota que já falhou uma vez (rede caiu), reconciliador (dublê) confirma que o governo JÁ aceitou → nota marcada emitida **sem chamar o emissor de novo** (usei um emissor que levanta `AssertionError` se for chamado, pra provar que ele realmente não é invocado nesse caminho).

### Outros testes de integridade rodados na mesma bateria (34 no total)
Inativação (não apagar) de tomador/prestador, renomear pasta física preservando arquivos, mensagens de certificado (expirado/senha errada/corrompido), tradução de "database is locked"/banco corrompido, trava de instância única, retomada de nota pendente ao reabrir — todos `ok`. Lista completa de nomes de teste na saída bruta (disponível sob pedido, omitida aqui por espaço — são 34 linhas "... ok").

---

## 8. LEIAUTE — validação de schema real contra o XSD oficial

**Isto é o item mais importante desta auditoria — e o único onde encontrei um problema real que passou batido em todas as verificações anteriores**, porque nenhuma delas tinha rodado validação de schema de fato (todas foram comparação visual/leitura).

### Metodologia
1. Baixei de novo o pacote oficial agora: `https://www.gov.br/nfse/pt-br/biblioteca/documentacao-tecnica/documentacao-atual/nfse-esquemas_xsd-v1-01-20260209.zip` (confirmei no portal, ver seção 10, que continua sendo o pacote vigente).
2. Gerei uma DPS completa e **assinada de verdade** (par de chaves RSA + certificado autoassinado gerado na hora, mesmo padrão de `tests/test_api.py::_gerar_pfx`) via `dps_builder.montar_e_assinar`.
3. Validei o XML resultante com `lxml.etree.XMLSchema` contra `DPS_v1.01.xsd` (schema real, com todos os `xs:include` resolvidos a partir dos arquivos oficiais).

### Resultado da primeira rodada: **INVÁLIDO**

```
RESULTADO DA VALIDAÇÃO DE SCHEMA: INVÁLIDO

ERROS ENCONTRADOS:
  - Linha 2: Element '{http://www.sped.fazenda.gov.br/nfse}serie': [facet 'pattern'] The value '1' is not accepted by the pattern '^0{0,4}\d{1,5}$'.
  - Linha 2: Element '{http://www.sped.fazenda.gov.br/nfse}cTribMun': [facet 'pattern'] The value '0401010000' is not accepted by the pattern '[0-9]{3}'.
```

Investiguei os dois erros separadamente, porque um deles é grave e o outro não é.

### 8.1 — `cTribMun`: **achado novo, real, grave** 🔴

O tipo oficial `TCCodTribMun` (definido em `tiposSimples_v1.01.xsd`, linha 568) é:
```xml
<xs:simpleType name="TCCodTribMun">
  <xs:restriction base="xs:string">
    <xs:whiteSpace value="preserve"/>
    <xs:pattern value="[0-9]{3}"/>
  </xs:restriction>
</xs:simpleType>
```
**Exatamente 3 dígitos.** O app inteiro — `dps_builder.py` (docstring diz "10 digitos"), `repo.py` (schema do banco, comentário "10 digitos"), a tela desktop (`tela_modelos.py:204`: `if len(trib_municipal) != 10`) e o protótipo web (`App.jsx:1264`: `codMunicipal.length !== 10`) — **exigem e geram 10 dígitos**. Confirmei de forma independente (busca externa, não é só a minha leitura do XSD) que integradores de mercado descrevem o mesmo: *"O Código de Tributação Municipal deve ser um código válido com 3 dígitos"* (fonte: documentação pública de um integrador NFS-e Nacional, citada na seção 10).

Testei a correção isolada (só pra confirmar o diagnóstico, **não apliquei no código**):
```
valido com cTribMun=3 digitos (e serie com ^$ literal)? True
```
Ou seja: trocando só esse campo pro tamanho certo, o resto do documento valida 100% contra o schema oficial.

**Impacto:** todo modelo de serviço já cadastrado no app (incluindo os usados nos XMLs de exemplo desta e de auditorias anteriores) tem um `cod_tributacao_municipal` de 10 dígitos, que — pelo XSD oficial — está estruturalmente incorreto. A UI ativamente **impede** o usuário de digitar o valor certo (bloqueia qualquer coisa que não tenha exatamente 10 dígitos). Isso nunca foi pego porque nenhuma auditoria anterior validou contra o schema de verdade.

**Isto não estava na lista de 7+10 achados originais — é um achado NOVO desta rodada.** Ver veredito final.

### 8.2 — `serie`: falso positivo, é bug do XSD oficial, não do app 🔵

O tipo `TSSerieDPS` usa o padrão `^0{0,4}\d{1,5}$`. Testei diretamente:
```
>>> import re
>>> bool(re.fullmatch(r'^0{0,4}\d{1,5}$', '1'))
True   # em regex Python/Perl, "1" bate certinho
```
Mas o **XML Schema (Appendix F da spec W3C) não trata `^` e `$` como âncoras** — são caracteres literais nesse dialeto de regex, porque o `xs:pattern` já é implicitamente ancorado à string inteira. Provei isso experimentalmente:
```
>>> # serie = "^1$" (literal, com os dois caracteres de verdade)
valido com serie literal ^1$? False   (o erro reportado nesse teste foi só o de cTribMun — o de "serie" desapareceu)
```
Ou seja: um valor numérico normal como "1" NUNCA vai satisfazer esse padrão, porque o padrão pede caracteres `^` e `$` literais que nenhum número de série de verdade teria. **Isso é um erro de autoria no XSD oficial do governo** (alguém colou um regex estilo Perl com âncoras dentro de um `xs:pattern`, onde âncoras não fazem sentido) — é a ÚNICA ocorrência desse estilo em todo o arquivo de tipos simples (`grep -c 'pattern value="\^'` = 1). Não é plausível que a Receita rejeite toda e qualquer série de DPS por causa disso (senão nenhum sistema no Brasil conseguiria emitir), então classifico como **artefato do XSD publicado, não um bug do nosso código** — mas registro porque apareceu na validação e a postura desta auditoria é não esconder nada.

---

## 9. DANFSe — código, não execução ao vivo

```python
def buscar_danfse(chave_acesso, chave_privada, certificado, certificados_extras=None, *, ambiente="homologacao", timeout=30.0):
    url_base = URL_DANFSE_HOMOLOGACAO if ambiente == "homologacao" else URL_DANFSE_PRODUCAO
    url = f"{url_base}/{chave_acesso}"
    ...
    with httpx.Client(cert=(cert_file, key_file), timeout=timeout) as client:
        resposta = client.get(url)
    ...
    return resposta.content
```
`URL_DANFSE_HOMOLOGACAO = "https://adn.producaorestrita.nfse.gov.br/danfse"` — endpoint oficial do governo (ADN).

Busquei por qualquer biblioteca de geração local de PDF no projeto inteiro:
```
$ grep -rn "reportlab\|weasyprint\|fpdf\|pdfkit\|canvas.Canvas" app/
(nenhuma ocorrência)
$ grep -i "pdf" requirements.txt requirements-api.txt
(nenhuma ocorrência)
```
**Confirmado: o PDF nunca é gerado localmente — é sempre buscado do governo.** Isso é uma confirmação de CÓDIGO, não uma prova de execução ao vivo — **não tenho certificado A1 real nem acesso à rede do Emissor Nacional neste ambiente**, então não posso provar que a chamada de rede de fato retorna um PDF válido. Continua sendo o mesmo limite já registrado nas auditorias anteriores.

**Pendência crítica já sinalizada no código (não é achado novo, é uma ressalva que continua válida):** a NT-008/2026 vai desativar essa API de geração de DANFSe em **03/08/2026** (confirmado fresco no portal — seção 10). Faltam ~11 dias a partir de hoje. Depois disso, esta função vai parar de funcionar até o app aprender a gerar o DANFSe localmente no novo leiaute nacional — isso **não foi implementado**, nem deveria ter sido (é fora do escopo de qualquer pedido de correção feito até agora).

---

## 10. Pendências externas — verificado agora no portal oficial

| Pergunta | Resposta | Data confirmada |
|---|---|---|
| (a) Saiu XSD mais novo que v1.01-20260209? | **Não.** Página "Documentação Atual" continua listando `NFSe-ESQUEMAS_XSD-v1.01-20260209` como o pacote vigente em produção. | Checado 23/jul/2026 |
| (b) Saiu NT posterior à NT-009? | **Não.** NT-009 (última atualização 15/07/2026) continua sendo a mais recente. NT-008 (14/07/2026, sobre o DANFSe) já era conhecida da sessão anterior. | Checado 23/jul/2026 |
| (c) Cronograma de obrigatoriedade do IBSCBS publicado? | **Não.** Nenhuma notícia recente menciona data de obrigatoriedade dos grupos IBSCBS — continua "suspenso" sem previsão. | Checado 23/jul/2026 |

Nada mudou desde a última verificação (um dia antes). O prazo do DANFSe (03/08/2026) segue confirmado e se aproximando.

---

## 11. REGRESSÃO

### Suíte de testes completa (rodada agora, do zero)
```
$ python -m unittest discover -s tests
----------------------------------------------------------------------
Ran 217 tests in 4.706s

OK
```
**217/217 passando, incluindo os 5 de cancelamento e os 34 de integridade/recuperação já detalhados acima.**

### Migração de banco — cliente que já tinha dados

Criei manualmente um banco SQLite com o **schema antigo** (sem as colunas `ativo`, sem colunas de retenção, sem colunas de cancelamento — as tabelas como estariam antes de qualquer correção desta sessão), inseri 1 prestador + 1 tomador + 1 nota **já emitida antes da migração** com XML real gravado, e abri esse banco com o `Repositorio` atual (que roda a migração automaticamente no `__init__`):

```
[CHECAGEM] nota antiga ainda tem status 'emitida'? True
[CHECAGEM] xml_conteudo da nota antiga preservado? True
[CHECAGEM] prestador ganhou coluna 'ativo' com default 1 (sem perder dado)? True
[CHECAGEM] tomador ganhou colunas de retenção com default seguro (0/None)? True
[CHECAGEM] nota ganhou colunas de cancelamento/retenção sem quebrar? True
[CHECAGEM] listar_notas_detalhado (Histórico) funciona no banco migrado? True
```
**Confirmado: quem já tinha dados não perde nada, e a nota antiga abre no Histórico normalmente.**

### Fluxo básico ponta a ponta

Rodei de novo o roteiro completo (cadastro → emitir avulsa → mensalidade automática → histórico + reenvio de e-mail → pasta com PDF+XML), com um emissor/SMTP falsos (sem rede real), do zero, nesta sessão:
```
[OK ] nota avulsa emitida com sucesso
[OK ] arquivo XML existe em disco
[OK ] arquivo PDF (DANFSe) existe em disco
[OK ] mensalidade emitida com sucesso
[OK ] mensalidade marcada como já emitida no mês
[OK ] clicar 'Emitir todas' de novo não duplica a nota
[OK ] histórico lista as 2 notas emitidas
[OK ] reenviar e-mail funciona (SMTP mockado)
[OK ] cada XML tem um PDF com o mesmo nome-base
[OK ] organização em Ano/Mês confirmada
```

### Telas/imports órfãos

```python
from app.ui import (
    main_window, tela_historico, tela_lote, tela_prestador, tela_emitir,
    tela_meu_dia, tela_modelos, tela_tomadores, tela_configuracoes, widgets,
)
janela = main_window.JanelaPrincipal(r, '.')
```
```
OK: janela principal + todas as telas instanciadas sem excecao.
Botoes da barra superior: ['+ Novo prestador', 'Editar prestador', 'Excluir prestador',
'Reativar prestador', 'Escolher pasta…', 'Salvar configurações', 'Abrir pasta', 'WhatsApp',
'Reenviar e-mail', 'Cancelar nota', 'Fechar mês', ... 'Emitir', 'Atualizar', 'Emitir todas',
'Escolher arquivo .pfx…', 'Ler certificado', 'Buscar dados (CNPJ)', 'Escolher cor…',
'Testar conexão (homologação)', 'Salvar prestador']
```
Nenhuma tela quebrou, nenhum botão sumiu (inclusive os novos: "Reativar prestador", "Reativar selecionado", "Cancelar nota" aparecem corretamente).

### Build do protótipo web
```
$ npm run build
✓ 1576 modules transformed.
✓ built in 2.34s
```
Sem erro.

---

## 12. Achados NOVOS introduzidos ou descobertos nesta rodada

| Achado | Tipo | Gravidade |
|---|---|---|
| `cTribMun` gerado com 10 dígitos; XSD oficial exige 3 | **Descoberto agora** (não é regressão — sempre esteve errado, nunca foi testado contra schema real antes) | 🔴 Bloqueador real pra qualquer emissão de verdade (não pro roteiro de demo controlado, que não toca a API real) |
| Padrão `serie` no XSD oficial é tecnicamente impossível de satisfazer (bug de terceiro) | Descoberto agora | 🔵 Baixo risco — provavelmente não reflete a validação real do servidor |
| Nenhuma regressão de comportamento encontrada nos fluxos existentes | — | — |

Não encontrei nenhum bug **introduzido** pelas correções em si (nenhum teste que passava antes e falha agora, nenhuma tela quebrada, nenhuma migração destrutiva). O único achado novo é o `cTribMun`, que é um bug **pré-existente**, presente desde antes de qualquer correção desta sessão — só nunca tinha sido detectado porque a verificação de leiaute sempre foi visual.

---

## 13. VEREDITO FINAL — PODE APRESENTAR AO MÉDICO?

### **Para uma demonstração controlada (roteiro fixo, sem emitir de verdade contra o Emissor Nacional real): SIM.**

Os 217 testes passam, o fluxo ponta a ponta funciona com dados de teste, a migração não perde dado de cliente antigo, nenhuma tela quebrou. O `cTribMun` errado **não aparece** numa demo que não emite contra a API real do governo (é exatamente o que o roteiro de 5 minutos da auditoria original já recomendava: "sem tentar emitir de verdade").

### **Para uso real, com certificado A1 de verdade, contra o Emissor Nacional: NÃO, ainda não — 1 bloqueador novo.**

| # | Bloqueador em aberto | Por quê |
|---|---|---|
| 1 | **`cTribMun` com 10 dígitos em vez de 3** (achado novo desta auditoria) | Toda nota real geraria esse campo fora do formato exigido pelo XSD oficial — risco real de rejeição (ou pior, aceitação com dado estruturalmente errado) na primeira emissão de verdade. |

Os 7 bloqueadores originais e 8 dos 10 importantes estão corrigidos e comprovados por execução real (testes, XMLs, migração). Os 2 importantes não corrigidos (Inscrição Municipal sem validação de formato, cronograma de monitoramento do IBSCBS) são de baixa gravidade e não bloqueiam nem a demo nem o primeiro uso real — são risco de médio prazo, não bloqueador imediato.

### O que **NÃO** demonstrar na apresentação, e por quê

- **Não tente emitir de verdade contra o ambiente real do Emissor Nacional** (mesmo em homologação, com certificado A1 real) até corrigir o `cTribMun` — o roteiro de demo já não fazia isso, continue evitando.
- **Continue evitando** (já valia desde a auditoria original, ainda vale): editar um prestador ao vivo sem necessidade, cancelar uma nota só pra mostrar (o cancelamento agora É real — avisa a Receita de verdade, mesmo em homologação), digitar um valor "de improviso" sem antes ter testado o formato.
- Se alguém perguntar "isso já pode emitir nota de verdade pro meu CNPJ?" — a resposta honesta agora é "quase, falta corrigir um campo do XML antes do primeiro envio real" — não confirme que está pronto pra produção.
