"""Tela 3 — Painel "Meu Dia" (espec-mvp-emissor-nfse.md, secao 2 item 1b):
"Hoje: 23 mensalidades de 6 prestadores prontas -> [Emitir todas]" + pendencias,
rejeicoes e certificados perto de vencer. E a UNICA tela que mistura
prestadores — todo o resto do app respeita o prestador selecionado no topo.
"""
from __future__ import annotations

import datetime
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QHBoxLayout, QHeaderView, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from app import repo
from app.core import fila
from app.ui import tema, widgets


class TelaMeuDia(QWidget):
    def __init__(
        self, repositorio: repo.Repositorio, obter_pasta_base: Callable[[], object],
        *, obter_hoje: Callable[[], datetime.date] = datetime.date.today, parent=None,
    ):
        super().__init__(parent)
        self.repositorio = repositorio
        self.obter_pasta_base = obter_pasta_base
        self.obter_hoje = obter_hoje
        self._montar_layout()
        self.atualizar()

    # ------------------------------------------------------------------
    def _montar_layout(self) -> None:
        raiz = QVBoxLayout(self)

        cabecalho = QHBoxLayout()
        cabecalho.addWidget(widgets.titulo("Meu Dia"))
        cabecalho.addStretch(1)
        self.botao_atualizar = widgets.botao_secundario("Atualizar")
        self.botao_atualizar.clicked.connect(self.atualizar)
        cabecalho.addWidget(self.botao_atualizar)
        raiz.addLayout(cabecalho)

        self.rotulo_resumo = widgets.subtitulo("")
        raiz.addWidget(self.rotulo_resumo)

        # --- sugestoes de mensalidade (item 4 da automacao pedida) -----
        self.cartao_sugestoes = widgets.Cartao()
        layout_sugestoes = QVBoxLayout(self.cartao_sugestoes)
        layout_sugestoes.addWidget(widgets.titulo("Isso poderia ser automático"))
        layout_sugestoes.addWidget(widgets.subtitulo(
            "Emitidas na mão, sempre pro mesmo tomador e serviço, em meses seguidos — "
            "dá pra virar mensalidade zero-clique."
        ))
        self.tabela_sugestoes = _nova_tabela(
            ["", "Prestador", "Tomador", "Serviço", "Valor", "Meses seguidos", "Dia do mês", ""]
        )
        layout_sugestoes.addWidget(self.tabela_sugestoes)
        raiz.addWidget(self.cartao_sugestoes)

        # --- mensalidades de hoje --------------------------------------
        cartao_mensalidades = widgets.Cartao()
        layout_mensalidades = QVBoxLayout(cartao_mensalidades)
        linha_titulo_m = QHBoxLayout()
        linha_titulo_m.addWidget(widgets.subtitulo("Mensalidades de hoje"))
        linha_titulo_m.addStretch(1)
        self.botao_emitir_todas = QPushButton("Emitir todas")
        self.botao_emitir_todas.clicked.connect(self._emitir_todas)
        linha_titulo_m.addWidget(self.botao_emitir_todas)
        layout_mensalidades.addLayout(linha_titulo_m)

        self.tabela_mensalidades = _nova_tabela(["", "Prestador", "Tomador", "Serviço", "Valor", "Situação"])
        layout_mensalidades.addWidget(self.tabela_mensalidades)
        raiz.addWidget(cartao_mensalidades)

        linha_pendentes_rejeitadas = QHBoxLayout()

        cartao_pendentes = widgets.Cartao()
        layout_pendentes = QVBoxLayout(cartao_pendentes)
        layout_pendentes.addWidget(widgets.subtitulo("Notas pendentes na fila"))
        self.tabela_pendentes = _nova_tabela(["", "Prestador", "Tomador", "Valor", "Tentativas", "Próxima tentativa"])
        layout_pendentes.addWidget(self.tabela_pendentes)
        linha_pendentes_rejeitadas.addWidget(cartao_pendentes)

        cartao_rejeitadas = widgets.Cartao()
        layout_rejeitadas = QVBoxLayout(cartao_rejeitadas)
        layout_rejeitadas.addWidget(widgets.subtitulo("Notas rejeitadas"))
        self.tabela_rejeitadas = _nova_tabela(["", "Prestador", "Tomador", "Valor", "Motivo"])
        layout_rejeitadas.addWidget(self.tabela_rejeitadas)
        linha_pendentes_rejeitadas.addWidget(cartao_rejeitadas)

        raiz.addLayout(linha_pendentes_rejeitadas)

        cartao_certificados = widgets.Cartao()
        layout_certificados = QVBoxLayout(cartao_certificados)
        layout_certificados.addWidget(widgets.subtitulo("Certificados perto de vencer"))
        self.tabela_certificados = _nova_tabela(["", "Prestador", "Vence em", "Dias restantes"])
        layout_certificados.addWidget(self.tabela_certificados)
        raiz.addWidget(cartao_certificados)

    # ------------------------------------------------------------------
    def atualizar(self) -> None:
        dados = self.repositorio.dados_meu_dia(self.obter_hoje())

        sugestoes = dados["sugestoes_mensalidade"]
        self.cartao_sugestoes.setVisible(bool(sugestoes))
        self.tabela_sugestoes.setRowCount(len(sugestoes))
        for linha, s in enumerate(sugestoes):
            _preencher_linha_com_cor(self.tabela_sugestoes, linha, s["prestador_cor"], [
                s["prestador_nome"], s["tomador_nome"], s["modelo_descricao"],
                f"R$ {s['valor_sugerido']}", str(s["meses_seguidos"]),
            ])
            spin_dia = QSpinBox()
            spin_dia.setRange(1, 28)
            spin_dia.setValue(min(28, self.obter_hoje().day))
            self.tabela_sugestoes.setCellWidget(linha, 6, spin_dia)
            botao_virar = QPushButton("Virar mensalidade")
            botao_virar.clicked.connect(
                lambda _checked=False, s=s, spin=spin_dia: self._virar_mensalidade(s, spin.value())
            )
            self.tabela_sugestoes.setCellWidget(linha, 7, botao_virar)

        mensalidades = dados["mensalidades_hoje"]
        self.tabela_mensalidades.setRowCount(len(mensalidades))
        for linha, m in enumerate(mensalidades):
            _preencher_linha_com_cor(self.tabela_mensalidades, linha, m["prestador_cor"], [
                m["prestador_nome"], m["tomador_nome"], m["modelo_descricao"],
                f"R$ {m['valor']}",
                "Já emitida este mês" if m["ja_emitida_no_mes"] else "Aguardando",
            ])
        self.botao_emitir_todas.setEnabled(any(not m["ja_emitida_no_mes"] for m in mensalidades))

        notas_pendentes = dados["notas_pendentes"]
        self.tabela_pendentes.setRowCount(len(notas_pendentes))
        for linha, n in enumerate(notas_pendentes):
            proxima = n["proxima_tentativa_em"] or "assim que possível"
            _preencher_linha_com_cor(self.tabela_pendentes, linha, n["prestador_cor"], [
                n["prestador_nome"], n["tomador_nome"], f"R$ {n['valor']}",
                str(n["tentativas"]), proxima,
            ])

        notas_rejeitadas = dados["notas_rejeitadas"]
        self.tabela_rejeitadas.setRowCount(len(notas_rejeitadas))
        for linha, n in enumerate(notas_rejeitadas):
            _preencher_linha_com_cor(self.tabela_rejeitadas, linha, n["prestador_cor"], [
                n["prestador_nome"], n["tomador_nome"], f"R$ {n['valor']}", n["motivo_rejeicao"] or "",
            ])

        certificados = dados["certificados_a_vencer"]
        self.tabela_certificados.setRowCount(len(certificados))
        for linha, c in enumerate(certificados):
            _preencher_linha_com_cor(self.tabela_certificados, linha, c["prestador_cor"], [
                c["prestador_nome"], c["cert_venc_em"], f"{c['dias_restantes']} dias",
            ])
            item_dias = self.tabela_certificados.item(linha, 3)
            item_dias.setForeground(QColor(_cor_urgencia_certificado(c["dias_restantes"])))
            fonte = item_dias.font()
            fonte.setBold(True)
            item_dias.setFont(fonte)

        self.rotulo_resumo.setText(
            f"Hoje: {len(mensalidades)} mensalidade(s) · {len(notas_pendentes)} nota(s) pendente(s) · "
            f"{len(notas_rejeitadas)} rejeitada(s) · {len(certificados)} certificado(s) vencendo"
        )

    # ------------------------------------------------------------------
    def _virar_mensalidade(self, sugestao: dict, dia_do_mes: int) -> None:
        """Item 4 da automação pedida: converte um padrão detectado (mesmo
        tomador+serviço emitido na mão em meses seguidos) numa recorrência
        de verdade, sem a secretária precisar ir até "Modelos e mensalidades"
        preencher tudo de novo — os dados já vêm do histórico."""
        self.repositorio.criar_recorrencia(
            sugestao["prestador_id"], tomador_id=sugestao["tomador_id"], modelo_id=sugestao["modelo_id"],
            valor=sugestao["valor_sugerido"], dia_do_mes=dia_do_mes, ativo=True,
        )
        widgets.mostrar_info(
            self, f"Mensalidade automática criada pra {sugestao['tomador_nome']}.", "Mensalidade criada",
        )
        self.atualizar()

    def _emitir_todas(self) -> None:
        # Criar as notas 'pendente' e' rapido e local (so' banco) -- so' o
        # envio de verdade (`processar_fila`, rede) roda em thread separada
        # (docs/auditoria.md, Bloco 7 item 2). A protecao contra clique duplo
        # continua em duas camadas: `ja_emitida_no_mes` vira verdade assim
        # que a nota e' criada abaixo (antes de qualquer rede), e o botao fica
        # desabilitado enquanto o envio roda.
        hoje = self.obter_hoje()
        criadas = fila.criar_notas_das_recorrencias_do_dia(self.repositorio, hoje)
        if not criadas:
            widgets.mostrar_info(self, "Não há mensalidades pendentes de hoje pra emitir.")
            return

        self.botao_emitir_todas.setEnabled(False)
        self.botao_emitir_todas.setText("Emitindo…")
        pasta_base = self.obter_pasta_base()

        def _trabalho(repositorio):
            return fila.processar_fila(repositorio, pasta_base)

        self._thread_emitir_todas = widgets.executar_com_nova_conexao(
            self, self.repositorio.caminho_db, _trabalho,
            self._ao_emitir_todas_sucesso, self._ao_emitir_todas_erro,
        )

    def _ao_emitir_todas_sucesso(self, resultados) -> None:
        emitidas = sum(1 for r in resultados if r["status"] == "emitida")
        rejeitadas = sum(1 for r in resultados if r["status"] == "rejeitada")
        pendentes = sum(1 for r in resultados if r["status"] == "pendente")
        widgets.mostrar_info(
            self,
            f"{emitidas} nota(s) emitida(s), {rejeitadas} rejeitada(s), {pendentes} ainda pendente(s) "
            f"(o programa tenta de novo sozinho).",
            "Emissão em lote concluída",
        )
        self.botao_emitir_todas.setText("Emitir todas")
        self.atualizar()  # reavalia setEnabled com base nas mensalidades restantes

    def _ao_emitir_todas_erro(self, exc: BaseException) -> None:
        self.botao_emitir_todas.setText("Emitir todas")
        widgets.mostrar_erro(self, exc, "Não deu pra emitir")
        self.atualizar()


def _nova_tabela(colunas: list) -> QTableWidget:
    tabela = QTableWidget(0, len(colunas))
    tabela.setHorizontalHeaderLabels(colunas)
    tabela.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
    tabela.setColumnWidth(0, 18)
    tabela.horizontalHeader().setSectionResizeMode(len(colunas) - 1, QHeaderView.ResizeMode.Stretch)
    tabela.verticalHeader().setVisible(False)
    tabela.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    tabela.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    return tabela


def _preencher_linha_com_cor(tabela: QTableWidget, linha: int, cor_hex: str, valores: list) -> None:
    item_cor = QTableWidgetItem()
    item_cor.setBackground(_cor_qt(cor_hex))
    tabela.setItem(linha, 0, item_cor)
    for coluna, valor in enumerate(valores, start=1):
        tabela.setItem(linha, coluna, QTableWidgetItem(str(valor)))


def _cor_qt(cor_hex: str):
    return QColor(cor_hex or tema.COR_TEXTO_SECUNDARIO)


def _cor_urgencia_certificado(dias_restantes: int) -> str:
    """Tiers de alerta da espec §2 item 9c: 30/15/7 dias antes do vencimento."""
    if dias_restantes <= 7:
        return tema.COR_ERRO
    if dias_restantes <= 15:
        return tema.COR_ALERTA
    return "#B08900"  # >15 e <=30: aviso mais discreto, ainda visivel
