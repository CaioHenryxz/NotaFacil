"""Interpretacao do valor monetario digitado pelo usuario -- docs/auditoria.md,
Bloco 3: o campo aceitava "R$ 1.500,00" ou "1.500.00" e so quebrava depois,
dentro do `Decimal()`, com um erro tecnico cru (`InvalidOperation`).

Feito pra aceitar o jeito brasileiro de digitar (ponto de milhar, virgula
decimal) SEM depender so' da mascara da UI -- a API "crua" (app/api.py) fica
exposta pro prototipo web, entao a validacao tem que ser forte aqui tambem
(defesa em profundidade, mesmo padrao ja usado pra aliquota do Simples
Nacional e pra retencoes).

Limite de tamanho: `TSDec15V2` (tipo do campo `vServ` no XSD oficial v1.01,
`tiposSimples_v1.01.xsd`) e' "1 a 15 digitos mais 2 casas decimais" --
confirmado por leitura direta do XSD baixado (nao por fonte secundaria),
pattern `0|0\\.[0-9]{2}|[1-9]{1}[0-9]{0,14}(\\.[0-9]{2})?`. Esse e' o teto
real: nao e' so' o app que rejeita valor gigante, e' o proprio leiaute.
"""
from __future__ import annotations

import re
from decimal import Decimal
from typing import Iterable, Optional, TypedDict

MAXIMO_DIGITOS_INTEIROS = 15  # TSDec15V2 -- ver docstring do modulo

# Item 3 da automacao pedida pelo usuario: alerta (nunca bloqueia) quando o
# valor digitado foge muito do que aquele tomador+servico costuma pagar --
# pega cedo o erro de digitacao real que a auditoria descreveu (docs/
# auditoria.md, Bloco 3: "R$300 virar R$3.000 por um zero a mais"), sem
# travar quem realmente mudou o valor de proposito (reajuste, servico extra).
MINIMO_NOTAS_PARA_PADRAO = 2  # sem pelo menos 2 notas anteriores, nao ha "padrao" pra comparar
LIMITE_DESVIO_PADRAO = Decimal("0.5")  # 50% de diferenca da media dispara o alerta


class AlertaValorForaDoPadrao(TypedDict):
    media_historica: str
    quantidade_notas: int
    percentual_diferenca: float


class ValorInvalido(ValueError):
    """Mensagem ja pronta pra mostrar na tela -- nao precisa de traducao."""


def normalizar_valor_monetario(bruto) -> str:
    """Recebe o que o usuario digitou (ou o que veio da API crua) e devolve
    uma string no formato exato que `_valor_monetario`/TSDec15V2 esperam:
    "1234.56", sempre com ponto decimal e 2 casas. Levanta `ValorInvalido`
    (mensagem em portugues claro, pronta pra tela) pra qualquer coisa que nao
    de' pra interpretar com certeza -- nunca deixa passar lixo pro Decimal()
    la na frente estourar um erro tecnico."""
    texto = str(bruto).strip()
    if not texto:
        raise ValorInvalido("Digite um valor. O campo não pode ficar vazio.")

    # Remove "R$", espaco comum e NBSP -- o resto tem que ser so digito e
    # separador (',' '.'), com opcional '-' na frente (bloqueado embaixo).
    texto = texto.replace("R$", "").replace("\xa0", " ").strip()
    texto = texto.replace(" ", "")

    negativo = texto.startswith("-")
    if negativo:
        texto = texto[1:]

    if not re.fullmatch(r"[0-9.,]+", texto or ""):
        raise ValorInvalido(f'Não entendi o valor "{bruto}". Digite só números, ponto e vírgula.')

    tem_virgula = "," in texto
    tem_ponto = "." in texto

    if tem_virgula and tem_ponto:
        # O ultimo separador que aparece e' o decimal; o outro e' milhar e
        # some. Ex.: "1.500,00" -> decimal e' a virgula -> "1500.00".
        if texto.rfind(",") > texto.rfind("."):
            inteiro_e_decimal = texto.replace(".", "").split(",")
        else:
            inteiro_e_decimal = texto.replace(",", "").split(".")
        if len(inteiro_e_decimal) != 2:
            raise ValorInvalido(f'Valor "{bruto}" com formato ambíguo. Digite algo como 1500,00 ou 1500.00.')
        parte_inteira, parte_decimal = inteiro_e_decimal
    elif tem_virgula:
        partes = texto.split(",")
        if len(partes) != 2:
            raise ValorInvalido(f'Valor "{bruto}" com formato ambíguo. Digite algo como 1500,00.')
        parte_inteira, parte_decimal = partes
    elif tem_ponto:
        grupos = texto.split(".")
        if len(grupos) == 2 and len(grupos[1]) in (1, 2):
            # Um ponto so', 1-2 digitos depois: decimal (ex.: "1500.00", "1500.5").
            parte_inteira, parte_decimal = grupos[0], grupos[1]
        elif all(len(g) == 3 for g in grupos[1:]) and len(grupos[0]) >= 1:
            # Todo mundo depois do primeiro grupo tem exatamente 3 digitos:
            # ponto de milhar sem centavos (ex.: "1.500" -> 1500, "1.234.567").
            parte_inteira, parte_decimal = "".join(grupos), "00"
        else:
            # Ambiguo de verdade (ex.: "1.500.00" — dois pontos, o ultimo
            # grupo nao tem 3 digitos: nem milhar nem decimal bate). Nao
            # adivinha — pede pra digitar de novo (docs/auditoria.md, Bloco 3).
            raise ValorInvalido(
                f'Não entendi o valor "{bruto}" — tem mais de um separador e não ficou claro qual é '
                "o decimal. Digite algo como 1500,00 ou 1.500,00."
            )
    else:
        parte_inteira, parte_decimal = texto, "00"

    if not parte_inteira.isdigit() or not parte_decimal.isdigit():
        raise ValorInvalido(f'Não entendi o valor "{bruto}". Digite só números, ponto e vírgula.')

    if len(parte_decimal) > 2:
        # Mais de 2 casas decimais e' quase sempre erro de digitacao (ex.:
        # "1500,999") -- antes isso arredondava sozinho pra 1501,00, sem
        # avisar ninguem. Bloqueia e pede confirmacao em vez de adivinhar.
        raise ValorInvalido(
            f'O valor "{bruto}" tem mais de duas casas decimais. Confira e digite de novo (ex.: 1500,99).'
        )
    parte_decimal = parte_decimal.ljust(2, "0")

    parte_inteira = parte_inteira.lstrip("0") or "0"
    if len(parte_inteira) > MAXIMO_DIGITOS_INTEIROS:
        raise ValorInvalido(f'O valor "{bruto}" é grande demais (máximo {MAXIMO_DIGITOS_INTEIROS} dígitos antes da vírgula).')

    valor = Decimal(f"{parte_inteira}.{parte_decimal}")
    if negativo:
        valor = -valor

    if valor <= 0:
        raise ValorInvalido("O valor precisa ser maior que zero.")

    return f"{valor:.2f}"


def valor_foge_do_padrao(
    valor_novo: str, historico: Iterable[str], *, limite: Decimal = LIMITE_DESVIO_PADRAO,
) -> Optional[AlertaValorForaDoPadrao]:
    """Compara `valor_novo` (já normalizado, ex.: "3000.00") com a média dos
    últimos valores emitidos pro mesmo tomador+serviço (`historico`, mais
    recente primeiro — ver `repo.historico_valores_tomador`). Devolve `None`
    quando está dentro do padrão OU quando não há histórico suficiente pra
    ter um padrão de verdade (nota nova pra aquele tomador não é "fora do
    padrão", é só a primeira). Nunca bloqueia — só informa pra tela decidir
    se mostra um aviso; quem chama sempre pode emitir mesmo assim."""
    valores_historicos = [Decimal(v) for v in historico]
    if len(valores_historicos) < MINIMO_NOTAS_PARA_PADRAO:
        return None

    media = sum(valores_historicos) / len(valores_historicos)
    if media == 0:
        return None
    novo = Decimal(str(valor_novo))
    desvio = abs(novo - media) / media
    if desvio <= limite:
        return None

    return {
        "media_historica": f"{media:.2f}",
        "quantidade_notas": len(valores_historicos),
        "percentual_diferenca": float((desvio * 100).quantize(Decimal("1"))),
    }
