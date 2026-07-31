"""Tela — Emissão em lote (Etapa 3 item 5, espec §2 item 6): "importa
CSV/XLSX (tomador, serviço, valor) -> revisa -> emite tudo".
"""
from __future__ import annotations

from typing import Callable, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QHeaderView, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from app import repo
from app.core import fila, lote
from app.ui import widgets


class TelaLote(QWidget):
    def __init__(self, repositorio: repo.Repositorio, obter_pasta_base: Callable[[], object], parent=None):
        super().__init__(parent)
        self.repositorio = repositorio
        self.obter_pasta_base = obter_pasta_base
        self.prestador_id: Optional[int] = None
        self._linhas: List[lote.LinhaLote] = []
        self._montar_layout()

    def _montar_layout(self) -> None:
        raiz = QVBoxLayout(self)
        raiz.addWidget(widgets.titulo("Emitir em lote"))
        raiz.addWidget(widgets.subtitulo(
            "Importe uma planilha (.csv ou .xlsx) com as colunas: tomador, serviço, valor."
        ))

        linha_arquivo = QHBoxLayout()
        self.botao_importar = QPushButton("Importar arquivo…")
        self.botao_importar.clicked.connect(self._importar)
        linha_arquivo.addWidget(self.botao_importar)
        self.rotulo_arquivo = widgets.subtitulo("Nenhum arquivo importado ainda.")
        linha_arquivo.addWidget(self.rotulo_arquivo)
        linha_arquivo.addStretch(1)
        raiz.addLayout(linha_arquivo)

        cartao = widgets.Cartao()
        layout_cartao = QVBoxLayout(cartao)
        self.tabela = QTableWidget(0, 5)
        self.tabela.setHorizontalHeaderLabels(["Linha", "Tomador", "Serviço", "Valor", "Situação"])
        self.tabela.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.tabela.verticalHeader().setVisible(False)
        self.tabela.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout_cartao.addWidget(self.tabela)
        raiz.addWidget(cartao)

        linha_botao = QHBoxLayout()
        self.rotulo_resumo = widgets.subtitulo("")
        linha_botao.addWidget(self.rotulo_resumo)
        linha_botao.addStretch(1)
        self.botao_emitir = QPushButton("Emitir linhas válidas")
        self.botao_emitir.setEnabled(False)
        self.botao_emitir.clicked.connect(self._emitir)
        linha_botao.addWidget(self.botao_emitir)
        raiz.addLayout(linha_botao)

    # ------------------------------------------------------------------
    def definir_prestador(self, prestador_id: Optional[int]) -> None:
        self.prestador_id = prestador_id
        self._linhas = []
        self.tabela.setRowCount(0)
        self.rotulo_arquivo.setText("Nenhum arquivo importado ainda.")
        self.rotulo_resumo.setText("")
        self.botao_emitir.setEnabled(False)

    # ------------------------------------------------------------------
    def _importar(self) -> None:
        if self.prestador_id is None:
            widgets.mostrar_erro(self, "Cadastre e selecione um prestador primeiro.")
            return
        caminho, _filtro = QFileDialog.getOpenFileName(
            self, "Escolher planilha", "", "Planilhas (*.csv *.xlsx)"
        )
        if not caminho:
            return
        try:
            linhas_brutas = lote.ler_arquivo(caminho)
            self._linhas = lote.revisar(self.repositorio, self.prestador_id, linhas_brutas)
        except Exception as exc:  # noqa: BLE001
            widgets.mostrar_erro(self, exc, "Não deu pra ler o arquivo")
            return

        self.rotulo_arquivo.setText(caminho.split("/")[-1].split("\\")[-1])
        self._preencher_tabela()

    def _preencher_tabela(self) -> None:
        self.tabela.setRowCount(len(self._linhas))
        for i, linha in enumerate(self._linhas):
            self.tabela.setItem(i, 0, QTableWidgetItem(str(linha.numero_linha)))
            self.tabela.setItem(i, 1, QTableWidgetItem(linha.tomador_texto))
            self.tabela.setItem(i, 2, QTableWidgetItem(linha.servico_texto))
            self.tabela.setItem(i, 3, QTableWidgetItem(linha.valor_texto))
            situacao = QTableWidgetItem("OK" if linha.valida else linha.erro)
            if not linha.valida:
                from PySide6.QtGui import QColor
                situacao.setForeground(QColor("#C43D3D"))
            self.tabela.setItem(i, 4, situacao)

        validas = sum(1 for l in self._linhas if l.valida)
        invalidas = len(self._linhas) - validas
        self.rotulo_resumo.setText(f"{validas} linha(s) prontas pra emitir · {invalidas} com erro (não serão emitidas)")
        self.botao_emitir.setEnabled(validas > 0)

    # ------------------------------------------------------------------
    def _emitir(self) -> None:
        if self.prestador_id is None or not self._linhas:
            return
        validas = [l for l in self._linhas if l.valida]
        if not widgets.confirmar(self, f"Emitir {len(validas)} nota(s) agora?"):
            return

        self.botao_emitir.setEnabled(False)
        self.botao_emitir.setText("Emitindo…")
        prestador_id = self.prestador_id
        linhas = self._linhas
        pasta_base = self.obter_pasta_base()

        # Roda numa thread separada -- docs/auditoria.md, Bloco 7 item 2: um
        # lote pode ter dezenas de notas, cada uma com uma chamada de rede;
        # sincrono, isso travaria a janela por muito mais que 3 segundos.
        def _trabalho(repositorio):
            lote.emitir_linhas_validas(repositorio, prestador_id, linhas)
            return fila.processar_fila(repositorio, pasta_base)

        self._thread_emitir = widgets.executar_com_nova_conexao(
            self, self.repositorio.caminho_db, _trabalho, self._ao_emitir_sucesso, self._ao_emitir_erro,
        )

    def _ao_emitir_sucesso(self, resultados) -> None:
        self.botao_emitir.setText("Emitir linhas válidas")
        self.botao_emitir.setEnabled(True)
        emitidas = sum(1 for r in resultados if r["status"] == "emitida")
        rejeitadas = sum(1 for r in resultados if r["status"] == "rejeitada")
        pendentes = sum(1 for r in resultados if r["status"] == "pendente")
        widgets.mostrar_info(
            self,
            f"{emitidas} nota(s) emitida(s), {rejeitadas} rejeitada(s), {pendentes} pendente(s) "
            "(o programa tenta de novo sozinho).",
            "Lote processado",
        )
        self.definir_prestador(self.prestador_id)

    def _ao_emitir_erro(self, exc: BaseException) -> None:
        self.botao_emitir.setText("Emitir linhas válidas")
        self.botao_emitir.setEnabled(True)
        widgets.mostrar_erro(self, exc, "Não deu pra emitir o lote")
