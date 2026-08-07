"""Tela 4 — Emissão avulsa (espec-mvp-emissor-nfse.md, secao 2 item 4):
"tela unica — tomador + modelo + valor -> botao Emitir. 3 cliques."
"""
from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QComboBox, QFormLayout, QHBoxLayout, QPushButton, QVBoxLayout, QWidget

from app import repo
from app.core import fila
from app.core import valores as valores_service
from app.ui import tema, widgets


class TelaEmitir(QWidget):
    def __init__(self, repositorio: repo.Repositorio, obter_pasta_base: Callable[[], object], parent=None):
        super().__init__(parent)
        self.repositorio = repositorio
        self.obter_pasta_base = obter_pasta_base
        self.prestador_id: Optional[int] = None
        self._modelos_por_indice: list = []
        # Item 3 da automacao pedida: alerta (nunca bloqueia) se o valor
        # digitado fugir muito do padrao historico do tomador+servico --
        # debounce curto pra nao recalcular a cada tecla digitada.
        self._timer_alerta_valor = QTimer(self)
        self._timer_alerta_valor.setSingleShot(True)
        self._timer_alerta_valor.setInterval(400)
        self._timer_alerta_valor.timeout.connect(self._verificar_alerta_valor)
        self._montar_layout()

    def _montar_layout(self) -> None:
        raiz = QVBoxLayout(self)
        raiz.addWidget(widgets.titulo("Emitir nota avulsa"))
        raiz.addWidget(widgets.subtitulo("Escolha o tomador e o serviço — o valor já vem preenchido, mas pode mudar."))

        cartao = widgets.Cartao()
        formulario = QFormLayout(cartao)

        self.combo_tomador = QComboBox()
        self.combo_tomador.currentIndexChanged.connect(self._ao_trocar_tomador)
        formulario.addRow("Tomador:", self.combo_tomador)

        self.combo_modelo = QComboBox()
        self.combo_modelo.currentIndexChanged.connect(self._preencher_valor_padrao)
        formulario.addRow("Serviço (modelo):", self.combo_modelo)

        self.campo_valor = widgets.CampoValorMonetario()
        self.campo_valor.textEdited.connect(lambda _texto: self._timer_alerta_valor.start())
        formulario.addRow("Valor (R$):", self.campo_valor)

        raiz.addWidget(cartao)

        self.rotulo_alerta_valor = widgets.subtitulo("")
        self.rotulo_alerta_valor.setWordWrap(True)
        self.rotulo_alerta_valor.setStyleSheet(f"color: {tema.COR_ALERTA}; font-weight: 600;")
        self.rotulo_alerta_valor.setVisible(False)
        raiz.addWidget(self.rotulo_alerta_valor)

        cartao_retencoes = widgets.Cartao()
        layout_retencoes = QVBoxLayout(cartao_retencoes)
        layout_retencoes.addWidget(widgets.subtitulo(
            "Retenção na fonte desta nota — já vem com o padrão do tomador, pode ajustar só aqui."
        ))
        self.painel_retencoes = widgets.PainelRetencoes()
        layout_retencoes.addWidget(self.painel_retencoes)
        raiz.addWidget(cartao_retencoes)

        linha_botao = QHBoxLayout()
        linha_botao.addStretch(1)
        self.botao_emitir = QPushButton("Emitir")
        self.botao_emitir.clicked.connect(self._emitir)
        linha_botao.addWidget(self.botao_emitir)
        raiz.addLayout(linha_botao)
        raiz.addStretch(1)

        self.rotulo_aviso = widgets.subtitulo(
            "Cadastre um prestador e pelo menos um tomador e um modelo de serviço primeiro."
        )
        self.rotulo_aviso.setWordWrap(True)
        raiz.addWidget(self.rotulo_aviso)

    # ------------------------------------------------------------------
    def definir_prestador(self, prestador_id: Optional[int]) -> None:
        self.prestador_id = prestador_id
        self._recarregar()

    def _recarregar(self) -> None:
        self.combo_tomador.clear()
        self.combo_modelo.clear()
        self._modelos_por_indice = []

        if self.prestador_id is None:
            self.rotulo_alerta_valor.setVisible(False)
            self._atualizar_estado()
            return

        for tomador in self.repositorio.listar_tomadores(self.prestador_id):
            self.combo_tomador.addItem(tomador["nome"], tomador["id"])

        for modelo in self.repositorio.listar_modelos_servico(self.prestador_id):
            self.combo_modelo.addItem(f"{modelo['descricao']} (R$ {modelo['valor_padrao']})", modelo["id"])
            self._modelos_por_indice.append(modelo)

        self._preencher_valor_padrao()
        self._atualizar_estado()

    def _atualizar_estado(self) -> None:
        pronto = (
            self.prestador_id is not None
            and self.combo_tomador.count() > 0
            and self.combo_modelo.count() > 0
        )
        self.botao_emitir.setEnabled(pronto)
        self.combo_tomador.setEnabled(pronto)
        self.combo_modelo.setEnabled(pronto)
        self.campo_valor.setEnabled(pronto)
        self.rotulo_aviso.setVisible(not pronto)

    def _preencher_valor_padrao(self) -> None:
        indice = self.combo_modelo.currentIndex()
        if 0 <= indice < len(self._modelos_por_indice):
            self.campo_valor.definir_valor(self._modelos_por_indice[indice]["valor_padrao"])
        self._timer_alerta_valor.start()

    def _ao_trocar_tomador(self) -> None:
        """Carrega o padrão de retenção do tomador escolhido (docs/auditoria.md,
        Bloco 1.6/2.4: "a regra costuma ser fixa por convênio") — o usuário
        ainda pode ajustar so' pra esta nota antes de emitir."""
        tomador_id = self.combo_tomador.currentData()
        if tomador_id is None or self.prestador_id is None:
            self.painel_retencoes.definir_valores({})
        else:
            tomador = self.repositorio.obter_tomador(self.prestador_id, tomador_id)
            self.painel_retencoes.definir_valores(tomador or {})
        self._timer_alerta_valor.start()

    def _verificar_alerta_valor(self) -> None:
        """Item 3 da automação pedida: avisa (nunca bloqueia) se o valor
        fugir muito do que esse tomador+serviço costuma pagar — pega cedo
        o erro de digitação (docs/auditoria.md, Bloco 3) em vez de só
        descobrir na rejeição ou no extrato do mês."""
        tomador_id = self.combo_tomador.currentData()
        modelo_id = self.combo_modelo.currentData()
        if (
            tomador_id is None or modelo_id is None or self.prestador_id is None
            or self.campo_valor.valor_decimal() <= 0
        ):
            self.rotulo_alerta_valor.setVisible(False)
            return
        historico = self.repositorio.historico_valores_tomador(self.prestador_id, tomador_id, modelo_id)
        alerta = valores_service.valor_foge_do_padrao(self.campo_valor.valor_normalizado(), historico)
        if alerta is None:
            self.rotulo_alerta_valor.setVisible(False)
            return
        self.rotulo_alerta_valor.setText(
            f"⚠ As últimas {alerta['quantidade_notas']} nota(s) desse tomador pra esse serviço ficaram em torno "
            f"de R$ {alerta['media_historica']} — esse valor está bem diferente "
            f"({alerta['percentual_diferenca']:.0f}%). Confira antes de emitir (pode estar certo mesmo assim)."
        )
        self.rotulo_alerta_valor.setVisible(True)

    # ------------------------------------------------------------------
    def _emitir(self) -> None:
        tomador_id = self.combo_tomador.currentData()
        modelo_id = self.combo_modelo.currentData()
        if tomador_id is None or modelo_id is None:
            widgets.mostrar_erro(self, "Escolha um tomador e um serviço.")
            return
        if self.campo_valor.valor_decimal() <= 0:
            widgets.mostrar_erro(self, "Digite um valor válido, maior que zero.")
            return
        valor = self.campo_valor.valor_normalizado()
        retencoes = self.painel_retencoes.valores()
        prestador_id = self.prestador_id
        pasta_base = self.obter_pasta_base()

        # Roda numa thread separada -- docs/auditoria.md, Bloco 7 item 2: e'
        # literalmente o botao principal do app, nao pode travar a janela
        # durante o envio pra Receita (ate 60s de timeout, ver api_nacional.py).
        self.botao_emitir.setEnabled(False)
        self.botao_emitir.setText("Emitindo…")

        def _trabalho(repositorio):
            nota_id = repositorio.criar_nota(
                prestador_id, tomador_id=tomador_id, modelo_id=modelo_id, valor=valor, retencoes=retencoes,
            )
            fila.processar_fila(repositorio, pasta_base)
            return repositorio.obter_nota(prestador_id, nota_id)

        self._thread_emitir = widgets.executar_com_nova_conexao(
            self, self.repositorio.caminho_db, _trabalho, self._ao_emitir_sucesso, self._ao_emitir_erro,
        )

    def _ao_emitir_sucesso(self, nota) -> None:
        self.botao_emitir.setEnabled(True)
        self.botao_emitir.setText("Emitir")
        if nota["status"] == repo.STATUS_EMITIDA:
            widgets.mostrar_info(
                self,
                f"Nota emitida! Chave de acesso: {nota['chave_acesso']}\nArquivo salvo em:\n{nota['xml_path']}",
                "Nota emitida",
            )
        elif nota["status"] == repo.STATUS_REJEITADA:
            from app.core import mensagens
            widgets.mostrar_erro(self, mensagens.traduzir_motivo_rejeicao(nota["motivo_rejeicao"]), "Nota rejeitada")
        else:
            widgets.mostrar_info(
                self,
                "O sistema da Receita não respondeu agora. A nota ficou pendente e o "
                "programa vai tentar de novo sozinho.",
                "Nota pendente",
            )

    def _ao_emitir_erro(self, exc: BaseException) -> None:
        self.botao_emitir.setEnabled(True)
        self.botao_emitir.setText("Emitir")
        widgets.mostrar_erro(self, exc, "Não deu pra emitir")
