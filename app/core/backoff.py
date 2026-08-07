"""Cronograma de nova tentativa (retry) compartilhado entre a fila de
emissao (core/fila.py) e o reenvio automatico de e-mail falhado
(core/email.py). Extraido de fila.py pra este modulo neutro porque
core/email.py nao pode importar core/fila.py (fila.py ja importa email.py
pra disparar o envio pos-emissao — importar de volta criaria ciclo).

5 min -> 30 min -> 2 h -> dai em diante, a cada 6 h (espec, secao 2 item 7).
"""
from __future__ import annotations

import datetime as dt

BACKOFF = [dt.timedelta(minutes=5), dt.timedelta(minutes=30), dt.timedelta(hours=2)]
RETRY_RECORRENTE = dt.timedelta(hours=6)


def proximo_atraso(tentativas: int) -> dt.timedelta:
    """tentativas=1 -> 5min, 2 -> 30min, 3 -> 2h, 4+ -> 6h em diante."""
    if tentativas <= 0:
        tentativas = 1
    if tentativas <= len(BACKOFF):
        return BACKOFF[tentativas - 1]
    return RETRY_RECORRENTE
