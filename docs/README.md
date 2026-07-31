# Índice da pasta docs/

## Se você vai mandar algo pro contador, comece aqui:

📁 **[`exemplos-fiscais/`](exemplos-fiscais/README.md)** — exemplos de XML/PDF
gerados pelo app pra cada situação (Simples Nacional vs. regime normal,
com/sem retenção na fonte), **e um checklist do que pedir pro contador
confirmar antes da primeira emissão real**. Leia o aviso no topo daquele
README antes de mandar qualquer arquivo pra qualquer lugar — nenhum
arquivo daquela pasta é uma nota fiscal de verdade.

## Histórico do projeto (auditorias e planejamento)

Estes documentos registram decisões, achados e correções ao longo do
desenvolvimento — são referenciados por comentários no código-fonte
(`docs/auditoria.md, Bloco X`, `docs/auditoria-2.md, seção Y`), por isso
continuam nesta pasta com o nome e o caminho originais, sem mudar.

- **[`spec-mvp.md`](spec-mvp.md)** — especificação original do app (o que
  ele deveria fazer, escopo do MVP).
- **[`auditoria.md`](auditoria.md)** — primeira auditoria fiscal completa
  (22/jul/2026): bloqueadores e pontos de atenção encontrados antes de
  qualquer correção.
- **[`plano-correcao.md`](plano-correcao.md)** — plano de correção dos
  achados da auditoria, em linguagem simples.
- **[`auditoria-2.md`](auditoria-2.md)** — auditoria de verificação
  pós-correção: o que foi corrigido e provado, o que ficou parcial, e um
  achado novo (código de tributação municipal com formato errado — já
  corrigido depois desta auditoria).
