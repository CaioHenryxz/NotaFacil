"""Fechamento mensal por prestador (Etapa 3 item 6, espec §2 item 9b):
"gera, dentro da pasta do mês de cada prestador, um Resumo-<mês>.csv (nota,
data, tomador, valor, status) e um ZIP com todos os XMLs, pronto pra mandar
ao contador por e-mail em 1 clique."
"""
from __future__ import annotations

import csv
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from app import repo
from app.core import pastas


@dataclass
class ResultadoFechamento:
    resumo_path: Path
    zip_path: Path
    quantidade_notas: int
    mes_nome: str


def fechar_mes(
    repositorio: repo.Repositorio, prestador_id: int, pasta_base, ano: int, mes: int
) -> ResultadoFechamento:
    prestador = repositorio.obter_prestador(prestador_id)
    if prestador is None:
        raise ValueError(f"Prestador {prestador_id} não encontrado.")

    notas = repositorio.listar_notas_do_mes(prestador_id, ano, mes)

    pasta_do_mes = pastas.pasta_mes(
        pasta_base, prestador["nome_exibicao"], ano, mes, prestador.get("pasta_nome")
    )
    pasta_do_mes.mkdir(parents=True, exist_ok=True)
    nome_mes = pastas.nome_pasta_mes(mes).split(" - ", 1)[1]

    caminho_resumo = pasta_do_mes / f"Resumo - {nome_mes}.csv"
    with open(caminho_resumo, "w", newline="", encoding="utf-8-sig") as f:
        escritor = csv.writer(f, delimiter=";")
        escritor.writerow(["Numero", "Data", "Tomador", "Valor", "Status", "Chave de acesso"])
        for n in notas:
            escritor.writerow([
                n["numero_dps"],
                (n.get("emitida_em") or n.get("criada_em") or "")[:10],
                n["tomador_nome"],
                n["valor"],
                n["status"],
                n.get("chave_acesso") or "",
            ])

    caminho_zip = pasta_do_mes / f"XMLs - {nome_mes}.zip"
    with zipfile.ZipFile(caminho_zip, "w", zipfile.ZIP_DEFLATED) as z:
        for n in notas:
            xml_path = n.get("xml_path")
            if xml_path and Path(xml_path).exists():
                z.write(xml_path, arcname=Path(xml_path).name)

    return ResultadoFechamento(
        resumo_path=caminho_resumo, zip_path=caminho_zip,
        quantidade_notas=len(notas), mes_nome=nome_mes,
    )
