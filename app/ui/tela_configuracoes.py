"""Tela 8 — Configurações (espec-mvp-emissor-nfse.md, secao 2 item 8): pasta
base das notas e dados de e-mail SMTP — o envio automatico pos-emissao (Etapa
3) ja usa esses dados. Tambem tem a opcao "Iniciar com o Windows" (Etapa 3
item 3), espelhada no menu da bandeja.
"""
from __future__ import annotations

from typing import Callable

from PySide6.QtWidgets import (
    QCheckBox, QFileDialog, QFormLayout, QHBoxLayout, QLineEdit, QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from app import repo
from app.core import email_config, inicializacao_windows
from app.ui import widgets


class TelaConfiguracoes(QWidget):
    def __init__(self, repositorio: repo.Repositorio, pasta_base_padrao: str, ao_salvar_pasta_base: Callable[[str], None], parent=None):
        super().__init__(parent)
        self.repositorio = repositorio
        self.pasta_base_padrao = pasta_base_padrao
        self.ao_salvar_pasta_base = ao_salvar_pasta_base
        self._montar_layout()
        self._carregar()

    def _montar_layout(self) -> None:
        raiz = QVBoxLayout(self)
        raiz.addWidget(widgets.titulo("Configurações"))

        cartao_pasta = widgets.Cartao()
        layout_pasta = QVBoxLayout(cartao_pasta)
        layout_pasta.addWidget(widgets.subtitulo("Onde guardar as notas"))
        linha_pasta = QHBoxLayout()
        self.campo_pasta = QLineEdit()
        botao_escolher = QPushButton("Escolher pasta…")
        botao_escolher.clicked.connect(self._escolher_pasta)
        linha_pasta.addWidget(self.campo_pasta, stretch=1)
        linha_pasta.addWidget(botao_escolher)
        layout_pasta.addLayout(linha_pasta)
        raiz.addWidget(cartao_pasta)

        cartao_smtp = widgets.Cartao()
        layout_smtp = QVBoxLayout(cartao_smtp)
        layout_smtp.addWidget(widgets.subtitulo("E-mail para enviar as notas (SMTP)"))
        layout_smtp.addWidget(widgets.subtitulo(
            "Só guardando por enquanto — o envio automático chega na próxima etapa."
        ))
        formulario = QFormLayout()
        self.campo_host = QLineEdit()
        self.campo_host.setPlaceholderText("smtp.gmail.com")
        formulario.addRow("Servidor SMTP:", self.campo_host)
        self.campo_porta = QSpinBox()
        self.campo_porta.setRange(1, 65535)
        self.campo_porta.setValue(587)
        formulario.addRow("Porta:", self.campo_porta)
        self.campo_usuario = QLineEdit()
        self.campo_usuario.setPlaceholderText("seu-email@gmail.com")
        formulario.addRow("Usuário (e-mail):", self.campo_usuario)
        self.campo_senha = QLineEdit()
        self.campo_senha.setEchoMode(QLineEdit.EchoMode.Password)
        self.campo_senha.setPlaceholderText("Senha de app (não a senha normal da conta)")
        formulario.addRow("Senha:", self.campo_senha)
        layout_smtp.addLayout(formulario)
        raiz.addWidget(cartao_smtp)

        cartao_inicializacao = widgets.Cartao()
        layout_inicializacao = QVBoxLayout(cartao_inicializacao)
        layout_inicializacao.addWidget(widgets.subtitulo("Inicialização"))
        self.marca_iniciar_com_windows = QCheckBox("Iniciar automaticamente com o Windows")
        try:
            self.marca_iniciar_com_windows.setChecked(inicializacao_windows.esta_habilitado())
        except Exception:  # noqa: BLE001
            self.marca_iniciar_com_windows.setEnabled(False)
        self.marca_iniciar_com_windows.toggled.connect(self._alternar_inicio_automatico)
        layout_inicializacao.addWidget(self.marca_iniciar_com_windows)
        raiz.addWidget(cartao_inicializacao)

        linha_botao = QHBoxLayout()
        linha_botao.addStretch(1)
        self.botao_salvar = QPushButton("Salvar configurações")
        self.botao_salvar.clicked.connect(self._salvar)
        linha_botao.addWidget(self.botao_salvar)
        raiz.addLayout(linha_botao)
        raiz.addStretch(1)

    def _carregar(self) -> None:
        self.campo_pasta.setText(email_config.obter_pasta_base(self.repositorio, padrao=self.pasta_base_padrao))
        smtp = email_config.obter_smtp(self.repositorio)
        self.campo_host.setText(smtp.host)
        self.campo_porta.setValue(smtp.porta)
        self.campo_usuario.setText(smtp.usuario)
        self.campo_senha.setText(smtp.senha)

    def _alternar_inicio_automatico(self, ligado: bool) -> None:
        try:
            inicializacao_windows.habilitar() if ligado else inicializacao_windows.desabilitar()
        except inicializacao_windows.IndisponivelNestaPlataforma:
            pass

    def _escolher_pasta(self) -> None:
        pasta = QFileDialog.getExistingDirectory(self, "Escolher pasta base das notas", self.campo_pasta.text())
        if pasta:
            self.campo_pasta.setText(pasta)

    def _salvar(self) -> None:
        pasta = self.campo_pasta.text().strip()
        if not pasta:
            widgets.mostrar_erro(self, "Escolha uma pasta base para as notas.")
            return
        email_config.salvar_pasta_base(self.repositorio, pasta)
        self.ao_salvar_pasta_base(pasta)
        email_config.salvar_smtp(
            self.repositorio, host=self.campo_host.text().strip(), porta=self.campo_porta.value(),
            usuario=self.campo_usuario.text().strip(), senha=self.campo_senha.text(),
        )
        widgets.mostrar_info(self, "Configurações salvas.")
