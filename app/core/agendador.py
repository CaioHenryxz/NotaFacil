"""Motor de recorrências (Etapa 3 item 1) — espec-mvp-emissor-nfse.md,
secao 2 item 5 e secao 4:

    "O app, rodando na bandeja do Windows, emite sozinho no dia configurado
    e avisa por notificação. Zero cliques por nota."

    "Limitação aceita: PC desligado no dia -> emite na próxima abertura
    (comportamento documentado, não bug)."

Este módulo é só o CÁLCULO de quais dias processar e a orquestração de um
ciclo; quem chama de fato (QTimer a cada 15 min, ou o próprio app ao abrir)
é a UI (app/ui/main_window.py). Nenhuma linha aqui sabe o que é uma bandeja
ou uma notificação — devolve dados, quem mostra é a UI.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import List, Optional

from app import repo
from app.core import fila

CHAVE_CONFIG_ULTIMA_VERIFICACAO = "ultima_verificacao_recorrencias"


@dataclass
class ResultadoCiclo:
    notas_criadas_catchup: List[int] = field(default_factory=list)
    dias_atrasados: List[dt.date] = field(default_factory=list)
    resultados_fila: List[dict] = field(default_factory=list)

    @property
    def houve_atraso(self) -> bool:
        return bool(self.dias_atrasados)

    @property
    def emitidas_atrasadas(self) -> int:
        ids_atrasadas = set(self.notas_criadas_catchup)
        return sum(
            1 for r in self.resultados_fila
            if r["status"] == "emitida" and r["nota_id"] in ids_atrasadas
        )

    @property
    def total_emitidas(self) -> int:
        return sum(1 for r in self.resultados_fila if r["status"] == "emitida")

    @property
    def total_rejeitadas(self) -> int:
        return sum(1 for r in self.resultados_fila if r["status"] == "rejeitada")


def _dias_a_processar(repositorio: "repo.Repositorio", hoje: dt.date) -> List[dt.date]:
    """Quais dias (do último já verificado +1 até hoje) precisam ser
    conferidos pra recorrências devidas. Primeira execução de todas: só hoje
    (não sai catchando retroativo desde o início dos tempos)."""
    ultima_str = repositorio.get_config(CHAVE_CONFIG_ULTIMA_VERIFICACAO)
    if ultima_str is None:
        return [hoje]
    ultima = dt.date.fromisoformat(ultima_str)
    if ultima >= hoje:
        return [hoje]  # mesmo dia, tick repetido — reprocessa (dedupe e' por mes, idempotente)
    dias = []
    d = ultima + dt.timedelta(days=1)
    while d <= hoje:
        dias.append(d)
        d += dt.timedelta(days=1)
    return dias


def rodar_ciclo(
    repositorio: "repo.Repositorio",
    pasta_base,
    *,
    emissor: Optional[fila.EmissorCallable] = None,
    hoje: Optional[dt.date] = None,
) -> ResultadoCiclo:
    """Um ciclo completo do agendador:
    1. Para cada dia devido desde a última verificação (inclusive dias
       atrasados, se o app ficou fechado), cria as notas das mensalidades
       daquele dia que ainda não saíram este mês.
    2. Processa a fila inteira (essas notas recém-criadas + qualquer retry
       pendente de antes) — 1 única chamada cobre os itens 1 e 2 da Etapa 3.

    Chamado pelo QTimer da UI a cada 15 min, e uma vez ao abrir o app."""
    hoje = hoje or dt.date.today()
    dias = _dias_a_processar(repositorio, hoje)

    notas_criadas: List[int] = []
    dias_atrasados: List[dt.date] = []
    for dia in dias:
        criadas = fila.criar_notas_das_recorrencias_do_dia(repositorio, dia)
        notas_criadas.extend(criadas)
        if dia < hoje and criadas:
            dias_atrasados.append(dia)

    repositorio.set_config(CHAVE_CONFIG_ULTIMA_VERIFICACAO, hoje.isoformat())

    kwargs = {} if emissor is None else {"emissor": emissor}
    resultados = fila.processar_fila(repositorio, pasta_base, agora=dt.datetime.combine(hoje, dt.datetime.now().time()), **kwargs)

    return ResultadoCiclo(
        notas_criadas_catchup=notas_criadas, dias_atrasados=dias_atrasados, resultados_fila=resultados,
    )
