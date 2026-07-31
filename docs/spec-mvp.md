# Espec MVP — Emissor Automático de NFS-e (Desktop)

**Versão:** 0.1 — 19/jul/2026
**Autores:** Rafael (arquitetura), Diego (fiscal/integração), Marina (desktop), Túlio (escopo)
**Princípio norteador:** custo de infra R$ 0, mínimo de trabalho manual do usuário, mínimo de código nosso.

---

## 1. Objetivo

App desktop Windows que emite NFS-e pelo **Emissor Nacional (API oficial)** com o mínimo de cliques possível. Público principal: **a secretária que emite para vários prestadores** — clínica médica (cada médico tem CNPJ e certificado próprios), oficina mecânica com sócios prestadores, escritórios de contabilidade/advocacia. Público secundário: o prestador solo que emite a própria nota. Gatilho de mercado: obrigatoriedade de emissão exclusiva pelo Emissor Nacional a partir de 01/09/2026.

**Conceito central: Prestadores como espaços isolados.** Cada prestador (ex.: "Dr. João Cardoso") é um workspace completo e estanque dentro do app: certificado A1 próprio, tomadores próprios, recorrências próprias, numeração própria, pasta própria no disco. Nada de um prestador vaza para outro — nem no banco, nem na tela, nem nas pastas. A secretária troca de prestador por um seletor no topo (com cor por prestador para evitar erro visual) ou opera todos de uma vez pelo painel consolidado.

**Métrica de sucesso do MVP:** um cliente beta emite as notas do mês inteiro em menos de 2 minutos de trabalho manual.

## 2. O que o MVP FAZ (escopo fechado)

1. **Configuração única (onboarding):** cadastrar cada prestador — importar certificado A1 (.pfx + senha), dados (CNPJ, IM, regime), escolher nome de exibição e cor, testar conexão em homologação. Adicionar novo prestador a qualquer momento (limite conforme plano).
1b. **Painel "Meu Dia" (consolidado):** visão de todos os prestadores de uma vez — *"Hoje: 23 mensalidades de 6 prestadores prontas → [Emitir todas]"* + pendências, rejeições e certificados perto de vencer. É a tela inicial da secretária.
2. **Cadastro de tomadores:** CNPJ/CPF → busca automática dos dados na BrasilAPI/ReceitaWS (gratuitas). Usuário só confirma.
3. **Modelos de serviço:** descrição, código de tributação nacional, valor padrão, alíquota ISS. Um tomador pode ter um modelo vinculado.
4. **Emissão avulsa:** tela única — tomador + modelo + valor → botão "Emitir". 3 cliques.
5. **Emissão recorrente (o coração da automação):** marca um tomador como "mensalidade" (modelo + valor + dia do mês). O app, rodando na bandeja do Windows, emite sozinho no dia configurado e avisa por notificação. Zero cliques por nota.
6. **Emissão em lote:** importa CSV/XLSX (tomador, serviço, valor) → revisa → emite tudo.
7. **Fila com retry:** toda emissão entra numa fila local. API do governo fora do ar → nota fica "pendente" e o app tenta de novo sozinho (backoff: 5 min, 30 min, 2 h) até emitir. Usuário não faz nada.
8. **Pós-emissão automática:** baixa o DANFSe (PDF) e XML, salva na estrutura de pastas organizada por prestador (ver §5b), e envia por e-mail ao tomador usando o SMTP do próprio usuário (Gmail/Outlook com senha de app). Botão opcional "enviar por WhatsApp" abre link `wa.me` com mensagem pronta.
9. **Cancelamento** de nota emitida (dentro do prazo legal). A nota cancelada é **movida** para a subpasta `Canceladas/` do mês — o app nunca apaga arquivo fiscal, só move.
9b. **Fechamento mensal por prestador:** botão "Fechar mês" gera, dentro da pasta do mês de cada prestador, um `Resumo-<mês>.csv` (nota, data, tomador, valor, status) e um ZIP com todos os XMLs, pronto pra mandar ao contador por e-mail em 1 clique.
9c. **Alerta de vencimento do certificado A1:** aviso no painel e por e-mail 30/15/7 dias antes, por prestador.
10. **Licenciamento:** login simples (e-mail/senha via Supabase Auth). App valida licença ativa a cada abertura; cache de 7 dias para funcionar offline.
11. **Auto-update:** app checa versão no GitHub Releases ao abrir; se houver nova, baixa e instala.

## 3. O que o MVP NÃO FAZ (cortado de propósito)

| Cortado | Volta quando |
|---|---|
| NF-e/NFC-e de produto (comércio) | Nunca no MVP. Outro produto. |
| Versão web/Mac/Linux | Demanda comprovada (>20 pedidos) |
| Múltiplos logins de funcionários com permissões (a conta é do escritório; a separação do MVP é **por prestador**, não por funcionário) | Primeiro escritório grande pedir |
| Certificado A3/token físico | Cliente pagante pedir |
| Gateway de pagamento (Stripe/Asaas) | >15 clientes. Antes: Pix manual + Caio ativa a licença no Supabase na mão |
| Relatórios/dashboard fiscal | v2 |
| Cálculo IBS/CBS (Reforma) | Quando a NT do layout for obrigatória — monitorar |
| Sincronizar cadastro de tomadores na nuvem | v2. MVP: dados locais + botão "exportar backup" |

## 4. Arquitetura

**Padrão: desktop burro, servidor quase inexistente.**

```
┌────────────────────────── Máquina do cliente ──────────────────────────┐
│  App PySide6 (Python 3.12)                                             │
│  ├─ UI (3 telas: Emitir | Tomadores | Configurações)                   │
│  ├─ SQLite local (stdlib) → tomadores, modelos, fila, notas emitidas   │
│  ├─ Motor de emissão:                                                  │
│  │    monta DPS (XML) → assina com A1 (lib signxml/xmlsec)             │
│  │    → POST API Emissor Nacional → guarda chave de acesso + PDF/XML   │
│  ├─ Agendador: QTimer a cada 15 min (recorrências + retry da fila)     │
│  └─ Ícone na bandeja (inicia com o Windows)                            │
└───────────────┬────────────────────────────────────────────────────────┘
                │ HTTPS (só metadados, nunca certificado)
        ┌───────▼────────┐          ┌──────────────────────┐
        │ Supabase FREE  │          │ APIs externas (grátis)│
        │ auth: contas   │          │ • Emissor Nacional    │
        │ tabela licenses│          │   (produção + homolog.)│
        │ tabela events  │          │ • BrasilAPI (CNPJ)    │
        └────────────────┘          │ • GitHub Releases     │
                                    └──────────────────────┘
```

**Decisões e porquês (ponytail):**

- **SQLite, não Postgres remoto, para dados fiscais.** Stdlib, zero custo, funciona offline, e o dado fica na máquina do cliente (menos LGPD pra nós). Supabase guarda só conta, licença e eventos de telemetria anônimos.
- **Certificado A1 nunca sai da máquina.** Fica criptografado localmente (DPAPI do Windows via `keyring`). Assinatura é 100 % local. Nosso servidor nunca vê certificado nem senha. `ponytail:` isso também elimina o maior risco jurídico do negócio.
- **Agendador dentro do app na bandeja**, não serviço do Windows nem cron no servidor. Emissão exige o certificado local, então automação server-side é impossível por definição — a bandeja é a solução mais simples que cumpre "zero cliques". Limitação aceita: PC desligado no dia → emite na próxima abertura (comportamento documentado, não bug).
- **E-mail pelo SMTP do usuário**, não SendGrid/Resend. R$ 0, sem limite nosso, e o e-mail chega "de" quem o tomador conhece. `ponytail:` se virar dor de suporte (senha de app), avaliar Resend free.
- **Cobrança: Pix manual + boolean no Supabase.** Um gateway inteiro pra <15 clientes é over-engineering. Planilha + Pix resolve.
- **Auto-update via GitHub Releases + PyInstaller.** Sem servidor de update próprio. `ponytail:` se instalador der atrito, avaliar Inno Setup (grátis).

## 5. Fluxo de emissão (caminho crítico)

```
Gatilho (clique | recorrência | lote)
  → valida dados (CNPJ, valor > 0, código de serviço)
  → grava na fila local com status=pendente
  → monta XML da DPS conforme layout nacional vigente
  → assina (A1 local)
  → POST /nfse (homologação até o beta aprovar; produção depois)
  → sucesso: status=emitida, salva chave, baixa PDF+XML, dispara e-mail
  → erro de rede/5xx: mantém pendente, agenda retry (5min→30min→2h→a cada 6h)
  → erro de validação (4xx): status=rejeitada + motivo legível na tela
```

Toda transição de status fica logada no SQLite (auditoria local do cliente).

## 5b. Organização em disco (parte do produto, não detalhe)

Pasta base configurável — padrão `Documentos\Notas Fiscais\`. **Dica vendável de custo zero:** se a secretária apontar a pasta base para uma pasta do OneDrive/Google Drive, ganha backup em nuvem automático sem a gente pagar 1 centavo de storage.

```
📁 Notas Fiscais\
├── 📁 Dr. João Cardoso\                ← nome de exibição do prestador
│   ├── 📁 2026\
│   │   ├── 📁 09 - Setembro\
│   │   │   ├── 📁 Emitidas\
│   │   │   │   ├── NFSe 0123 - Unimed SJC - R$ 1.500,00.pdf
│   │   │   │   └── NFSe 0123 - Unimed SJC - R$ 1.500,00.xml
│   │   │   ├── 📁 Canceladas\          ← nota cancelada é MOVIDA pra cá
│   │   │   ├── 📄 Resumo - Setembro.csv     (gerado no "Fechar mês")
│   │   │   └── 📦 XMLs - Setembro.zip       (gerado no "Fechar mês")
│   │   └── 📁 10 - Outubro\ ...
│   └── 📄 _Dados do Prestador.txt      (CNPJ, IM — referência rápida)
├── 📁 Dra. Ana Lima\ ...
└── 📁 Oficina do Zé - Retífica\ ...
```

**Regras (pensadas para nunca dar problema):**
- PDF e XML sempre juntos, mesmo nome-base. Padrão: `NFSe <número> - <tomador> - R$ <valor>` — legível por humano, encontrável no Windows Search.
- Nomes sanitizados automaticamente (remove `\/:*?"<>|`, limita tamanho, resolve acento). Dois tomadores com nome igual → sufixo com CNPJ curto.
- O app **cria** e **move** arquivos, **nunca apaga**. Cancelou → move pra `Canceladas\`. Reemitiu → novo arquivo, o antigo permanece.
- O caminho de cada arquivo fica gravado no SQLite; se a secretária mover/renomear na mão, o app detecta no acesso e oferece regravar o PDF/XML a partir do banco (o XML autoritativo sempre existe no banco também — pasta corrompida ≠ dado perdido).
- Renomeou o prestador no app → o app renomeia a pasta junto (com confirmação).
- Botão "Abrir pasta" em toda nota e todo prestador — a secretária nunca precisa caçar arquivo.

## 6. Modelo de dados

**SQLite (local) — tudo escopado por prestador:**
- `prestadores` (id, nome_exibicao, cnpj, im, regime, cor, pasta_nome, cert_venc_em) — a senha do certificado fica no keyring do Windows, nunca no banco
- `tomadores` (id, **prestador_id**, doc, nome, email, telefone, endereço…)
- `modelos_servico` (id, **prestador_id**, descrição, cod_tributacao_nacional, valor_padrao, aliquota)
- `recorrencias` (id, **prestador_id**, tomador_id, modelo_id, valor, dia_do_mes, ativo)
- `notas` (id, **prestador_id**, tomador_id, valor, status[pendente|emitida|rejeitada|cancelada], chave_acesso, **xml_conteudo**, xml_path, pdf_path, tentativas, criada_em, emitida_em)
- `config` (chave/valor: smtp, pasta_base, prefs)

Toda query da UI filtra por `prestador_id` numa camada única de acesso (`repo.py`) — a tela nunca monta SQL. `ponytail:` é o jeito mais barato de garantir que a separação nunca vaza: um único lugar pra errar, um único lugar pra testar. O painel "Meu Dia" é a exceção deliberada: agrega todos, mas é read-only + ações em lote.

**Supabase (free):**
- `auth.users` (nativo)
- `licenses` (user_id, plano, **max_prestadores**, ativa bool, expira_em) + RLS: usuário lê só a própria linha
- `events` (user_id, tipo, versão_app, criado_em) — telemetria mínima: instalou, emitiu (contagem, sem dados da nota), erro fatal

Limites do free tier (500 MB DB, 50k MAU) aguentam milhares de clientes nesse desenho, porque o pesado fica todo no SQLite.

## 7. Stack e dependências (lista fechada)

| Camada | Escolha | Motivo |
|---|---|---|
| Linguagem | Python 3.12 | Stack do Caio |
| UI | PySide6 | Nativo Windows, maduro, LGPL grátis |
| Banco local | sqlite3 (stdlib) | R$ 0, offline |
| Assinatura XML | signxml + cryptography | Assinatura digital do DPS |
| HTTP | httpx | Retry/timeout decentes |
| Certificado | cryptography (ler .pfx) + keyring (guardar senha) | DPAPI nativo |
| Empacote | PyInstaller | Caio já conhece as pegadinhas |
| Backend | supabase-py | Auth + licenças |
| E-mail | smtplib (stdlib) | R$ 0 |

Nada além disso entra sem o Rafael aprovar.

## 8. Riscos técnicos e mitigação

1. **Detalhes exatos da API do Emissor Nacional** (endpoints, contribuinte credenciamento, layout da DPS versão vigente) → **Sprint 0 é um spike**: ler a documentação oficial (Portal NFS-e / Sefin Nacional), emitir 1 nota em **homologação (Produção Restrita)** via script puro, sem UI. Nada de UI antes disso funcionar — é o risco nº 1 do projeto.
2. **Mudança de layout (IBS/CBS)** → assinar o feed de Notas Técnicas do Comitê Gestor; isolar a montagem do XML num módulo único (`dps_builder.py`) pra mudança custar 1 arquivo.
3. **Instabilidade da API do governo** → já coberto pela fila com retry.
4. **PyInstaller + antivírus falso-positivo** → assinar o executável fica pra depois (certificado code-signing custa dinheiro); mitigar com instruções de exceção no onboarding. `ponytail:` comprar code-signing quando o suporte doer.

## 9. Sprints (2 semanas cada, ajustável à agenda Embraer+UNIFESP)

| Sprint | Entrega | Critério de aceite |
|---|---|---|
| **0 — Spike fiscal** | Script Python que emite 1 NFS-e em homologação com certificado A1 de teste | Nota aparece consultável no ambiente de homologação |
| **1 — Núcleo** | SQLite + fila com retry + emissão avulsa via UI mínima | Emitir 5 notas seguidas com API "caindo" simulada |
| **2 — Automação** | Recorrências + bandeja + lote CSV + e-mail automático | 1 mês simulado de mensalidades sem clique |
| **3 — Produto** | Onboarding, licença Supabase, PyInstaller, auto-update | Instalar do zero num PC limpo em <10 min |
| **4 — Beta** | 3–5 clientes reais em SJC, homologação → produção | 1 cliente emite o mês em <2 min de trabalho manual |

## 10. Custo total do MVP

| Item | Custo |
|---|---|
| Supabase free | R$ 0 |
| GitHub (repo + Releases) | R$ 0 |
| BrasilAPI, SMTP próprio, wa.me | R$ 0 |
| Certificado A1 de teste p/ desenvolvimento | ~R$ 130–200/ano (único custo real — ou usar o de um cliente beta com autorização) |
| Domínio + landing page (opcional agora) | ~R$ 40/ano quando quiser |

**Total pra chegar ao beta: ≤ R$ 200.**

## 11. Posicionamento vs. concorrência (resumo da pesquisa 19/jul/2026)

| Concorrente | Modelo | Fraqueza que exploramos |
|---|---|---|
| Emissor Nacional (governo) | Web grátis, manual | Nota por nota, sem recorrência, sem organização |
| Omie / Conta Azul | ERP web R$ 150+/mês | Caro e complexo pra quem só quer emitir |
| Spedy / eNotas | Web, cobra por nota (~R$ 2,49/venda), foco e-commerce/infoproduto | Caro em volume; certificado sobe pro servidor deles; não atende clínica/oficina |
| Brasil NFe / Focus / PlugNotas | API pra contadores, multi-CNPJ | Exige desenvolvedor — secretária não integra API |
| IOB Emissor | Web ilimitado | Genérico, sem automação de recorrência nem multi-prestador amigável |

**Nossa frase de venda:** *"O único programa que a secretária instala hoje e que emite sozinho as notas de todos os médicos da clínica, com tudo organizado em pastas — preço fixo, e o certificado nunca sai do seu computador."*

---

*Nota da Dra. Helena: antes do primeiro cliente pagante, validar com um contador real: enquadramento do produto, responsabilidade sobre notas emitidas com dado errado (colocar no Termo de Uso), e conferir se o município do cliente já está operacional no padrão nacional.*
