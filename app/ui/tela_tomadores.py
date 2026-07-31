"""Tela 5 — Tomadores (espec-mvp-emissor-nfse.md, secao 2 item 2):
"CNPJ/CPF -> busca automatica dos dados na BrasilAPI... Usuario so confirma."
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QFormLayout, QHBoxLayout, QHeaderView, QLineEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from app import repo
from app.core import brasilapi, documentos
from app.fiscal import dps_builder
from app.ui import widgets


class TelaTomadores(QWidget):
    def __init__(self, repositorio: repo.Repositorio, parent=None):
        super().__init__(parent)
        self.repositorio = repositorio
        self.prestador_id: Optional[int] = None
        self._editando_id: Optional[int] = None
        self._montar_layout()

    def _montar_layout(self) -> None:
        raiz = QVBoxLayout(self)
        raiz.addWidget(widgets.titulo("Tomadores"))

        linha_principal = QHBoxLayout()

        cartao_lista = widgets.Cartao()
        layout_lista = QVBoxLayout(cartao_lista)
        layout_lista.addWidget(widgets.subtitulo("Cadastrados"))
        self.marca_mostrar_inativos = QCheckBox("Mostrar inativos")
        self.marca_mostrar_inativos.toggled.connect(self._recarregar_lista)
        layout_lista.addWidget(self.marca_mostrar_inativos)
        self.tabela = QTableWidget(0, 5)
        self.tabela.setHorizontalHeaderLabels(["Nome", "CNPJ/CPF", "E-mail", "Telefone", "Status"])
        self.tabela.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tabela.verticalHeader().setVisible(False)
        self.tabela.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.tabela.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.tabela.itemSelectionChanged.connect(self._atualizar_botoes)
        layout_lista.addWidget(self.tabela)

        linha_acoes = QHBoxLayout()
        self.botao_editar = widgets.botao_secundario("Editar selecionado")
        self.botao_editar.setEnabled(False)
        self.botao_editar.clicked.connect(self._editar_selecionado)
        self.botao_excluir = widgets.botao_perigo("Excluir selecionado")
        self.botao_excluir.setEnabled(False)
        self.botao_excluir.clicked.connect(self._excluir_selecionado)
        self.botao_reativar = widgets.botao_secundario("Reativar selecionado")
        self.botao_reativar.setEnabled(False)
        self.botao_reativar.setVisible(False)
        self.botao_reativar.clicked.connect(self._reativar_selecionado)
        linha_acoes.addWidget(self.botao_editar)
        linha_acoes.addWidget(self.botao_excluir)
        linha_acoes.addWidget(self.botao_reativar)
        linha_acoes.addStretch(1)
        layout_lista.addLayout(linha_acoes)

        linha_principal.addWidget(cartao_lista, stretch=2)

        cartao_novo = widgets.Cartao()
        layout_novo = QVBoxLayout(cartao_novo)
        layout_novo.addWidget(widgets.subtitulo("Novo tomador"))
        formulario = QFormLayout()

        linha_doc = QHBoxLayout()
        self.campo_documento = QLineEdit()
        self.campo_documento.setPlaceholderText("Só números")
        self.botao_buscar = QPushButton("Buscar")
        self.botao_buscar.clicked.connect(self._buscar_dados)
        linha_doc.addWidget(self.campo_documento, stretch=1)
        linha_doc.addWidget(self.botao_buscar)
        formulario.addRow("CNPJ/CPF:", linha_doc)

        self.campo_nome = QLineEdit()
        self.campo_nome.setMaxLength(dps_builder.TAMANHO_MAXIMO_NOME)
        formulario.addRow("Nome:", self.campo_nome)
        self.campo_email = QLineEdit()
        formulario.addRow("E-mail:", self.campo_email)
        self.campo_telefone = QLineEdit()
        formulario.addRow("Telefone:", self.campo_telefone)
        self.campo_endereco = QLineEdit()
        formulario.addRow("Endereço:", self.campo_endereco)

        layout_novo.addLayout(formulario)
        layout_novo.addWidget(widgets.subtitulo("Este tomador retém imposto na fonte? (regra fixa por convênio)"))
        self.painel_retencoes = widgets.PainelRetencoes()
        layout_novo.addWidget(self.painel_retencoes)
        self.botao_salvar = QPushButton("Salvar tomador")
        self.botao_salvar.clicked.connect(self._salvar)
        layout_novo.addWidget(self.botao_salvar)
        self.botao_cancelar_edicao = widgets.botao_secundario("Cancelar edição")
        self.botao_cancelar_edicao.clicked.connect(self._cancelar_edicao)
        self.botao_cancelar_edicao.setVisible(False)
        layout_novo.addWidget(self.botao_cancelar_edicao)
        layout_novo.addStretch(1)

        linha_principal.addWidget(cartao_novo, stretch=1)
        raiz.addLayout(linha_principal)

        self.rotulo_aviso = widgets.subtitulo("Cadastre um prestador primeiro.")
        raiz.addWidget(self.rotulo_aviso)

    # ------------------------------------------------------------------
    def definir_prestador(self, prestador_id: Optional[int]) -> None:
        self._cancelar_edicao()
        self.prestador_id = prestador_id
        self.setEnabled(prestador_id is not None)
        self.rotulo_aviso.setVisible(prestador_id is None)
        self._recarregar_lista()

    def _recarregar_lista(self) -> None:
        self.tabela.setRowCount(0)
        self._tomadores: list = []
        if self.prestador_id is None:
            self._atualizar_botoes()
            return
        apenas_ativos = not self.marca_mostrar_inativos.isChecked()
        tomadores = self.repositorio.listar_tomadores(self.prestador_id, apenas_ativos=apenas_ativos)
        self._tomadores = tomadores
        self.tabela.setRowCount(len(tomadores))
        for linha, t in enumerate(tomadores):
            item_nome = QTableWidgetItem(t["nome"])
            item_nome.setData(Qt.ItemDataRole.UserRole, t["id"])
            self.tabela.setItem(linha, 0, item_nome)
            self.tabela.setItem(linha, 1, QTableWidgetItem(t["doc"]))
            self.tabela.setItem(linha, 2, QTableWidgetItem(t.get("email") or ""))
            self.tabela.setItem(linha, 3, QTableWidgetItem(t.get("telefone") or ""))
            self.tabela.setItem(linha, 4, QTableWidgetItem("Ativo" if t.get("ativo", 1) else "Inativo"))
        self._atualizar_botoes()

    def _id_selecionado(self) -> Optional[int]:
        linha = self.tabela.currentRow()
        if linha < 0:
            return None
        item = self.tabela.item(linha, 0)
        if item is None:
            return None
        return item.data(Qt.ItemDataRole.UserRole)

    def _tomador_selecionado(self) -> Optional[dict]:
        tomador_id = self._id_selecionado()
        if tomador_id is None:
            return None
        return next((t for t in self._tomadores if t["id"] == tomador_id), None)

    def _atualizar_botoes(self) -> None:
        tomador = self._tomador_selecionado()
        tem_selecao = tomador is not None
        ativo = bool(tomador.get("ativo", 1)) if tomador else True
        self.botao_editar.setEnabled(tem_selecao and ativo)
        self.botao_excluir.setEnabled(tem_selecao and ativo)
        self.botao_reativar.setVisible(tem_selecao and not ativo)
        self.botao_reativar.setEnabled(tem_selecao and not ativo)

    def _buscar_dados(self) -> None:
        doc = brasilapi.somente_digitos(self.campo_documento.text())
        if len(doc) == 11:
            widgets.mostrar_info(
                self,
                "CPF não tem busca automática (dado pessoal protegido por lei). "
                "Digite o nome do tomador manualmente.",
            )
            return
        if len(doc) != 14:
            widgets.mostrar_erro(self, "Digite um CNPJ (14 números) ou CPF (11 números).")
            return
        # Busca roda numa thread separada -- docs/auditoria.md, Bloco 3/7.2:
        # antes disso a chamada de rede travava a janela inteira se a
        # BrasilAPI estivesse fora do ar/lenta.
        self.botao_buscar.setEnabled(False)
        self.botao_buscar.setText("Buscando…")
        self._thread_busca_cnpj = widgets.executar_em_segundo_plano(
            self, lambda: brasilapi.buscar_cnpj(doc),
            self._ao_buscar_dados_sucesso, self._ao_buscar_dados_erro,
        )

    def _ao_buscar_dados_sucesso(self, dados) -> None:
        self.botao_buscar.setEnabled(True)
        self.botao_buscar.setText("Buscar")
        self.campo_nome.setText(dados.nome_fantasia or dados.razao_social)
        self.campo_email.setText(dados.email or "")
        self.campo_telefone.setText(dados.telefone or "")
        self.campo_endereco.setText(dados.endereco_formatado)

    def _ao_buscar_dados_erro(self, exc: BaseException) -> None:
        self.botao_buscar.setEnabled(True)
        self.botao_buscar.setText("Buscar")
        widgets.mostrar_erro(self, exc, "Não encontrei esse CNPJ")

    def _salvar(self) -> None:
        if self.prestador_id is None:
            return
        nome = self.campo_nome.text().strip()
        if not nome:
            widgets.mostrar_erro(self, "Digite o nome do tomador.")
            return

        if self._editando_id is not None:
            try:
                self.repositorio.atualizar_tomador(
                    self.prestador_id, self._editando_id, nome=nome,
                    email=self.campo_email.text().strip() or None,
                    telefone=self.campo_telefone.text().strip() or None,
                    endereco=self.campo_endereco.text().strip() or None,
                    retencoes=self.painel_retencoes.valores(),
                )
            except Exception as exc:  # noqa: BLE001
                widgets.mostrar_erro(self, exc, "Não deu pra salvar")
                return
            self._cancelar_edicao()
            self._recarregar_lista()
            return

        try:
            doc = documentos.exigir_documento_valido(self.campo_documento.text())
        except documentos.DocumentoInvalido as exc:
            widgets.mostrar_erro(self, exc)
            return

        duplicados = self.repositorio.tomadores_com_nome_duplicado(self.prestador_id, nome)
        if duplicados and not widgets.confirmar(
            self,
            f'Já existe um tomador chamado "{nome}" cadastrado. Cadastrar mais um com o mesmo nome?',
        ):
            return

        try:
            self.repositorio.criar_tomador(
                self.prestador_id, doc=doc, nome=nome,
                email=self.campo_email.text().strip() or None,
                telefone=self.campo_telefone.text().strip() or None,
                endereco=self.campo_endereco.text().strip() or None,
                retencoes=self.painel_retencoes.valores(),
            )
        except Exception as exc:  # noqa: BLE001
            widgets.mostrar_erro(self, exc, "Não deu pra salvar")
            return

        self._limpar_formulario()
        self._recarregar_lista()

    def _limpar_formulario(self) -> None:
        self.campo_documento.clear()
        self.campo_nome.clear()
        self.campo_email.clear()
        self.campo_telefone.clear()
        self.campo_endereco.clear()
        self.painel_retencoes.definir_valores({})

    # ------------------------------------------------------------------
    def _editar_selecionado(self) -> None:
        tomador_id = self._id_selecionado()
        if tomador_id is None or self.prestador_id is None:
            return
        tomador = self.repositorio.obter_tomador(self.prestador_id, tomador_id)
        if tomador is None:
            return
        self._editando_id = tomador_id
        self.campo_documento.setText(tomador["doc"])
        self.campo_documento.setEnabled(False)
        self.botao_buscar.setEnabled(False)
        self.campo_nome.setText(tomador["nome"])
        self.campo_email.setText(tomador.get("email") or "")
        self.campo_telefone.setText(tomador.get("telefone") or "")
        self.campo_endereco.setText(tomador.get("endereco") or "")
        self.painel_retencoes.definir_valores(tomador)
        self.botao_salvar.setText("Salvar alterações")
        self.botao_cancelar_edicao.setVisible(True)

    def _cancelar_edicao(self) -> None:
        self._editando_id = None
        self.campo_documento.setEnabled(True)
        self.botao_buscar.setEnabled(True)
        self._limpar_formulario()
        self.botao_salvar.setText("Salvar tomador")
        self.botao_cancelar_edicao.setVisible(False)

    def _excluir_selecionado(self) -> None:
        tomador_id = self._id_selecionado()
        if tomador_id is None or self.prestador_id is None:
            return
        tomador = self.repositorio.obter_tomador(self.prestador_id, tomador_id)
        nome = tomador["nome"] if tomador else ""
        if not widgets.confirmar(
            self, f'Excluir o tomador "{nome}"? Essa ação não pode ser desfeita.'
        ):
            return
        try:
            self.repositorio.excluir_tomador(self.prestador_id, tomador_id)
        except ValueError as exc:
            # Tem nota/mensalidade vinculada -- exclusao definitiva bloqueada
            # de proposito (docs/auditoria.md, Bloco 4.1). Oferece inativar
            # em vez de so' mostrar o erro e travar o usuario.
            if widgets.confirmar(
                self,
                f"{exc}\n\nDeseja inativar este tomador em vez de excluir? "
                "Ele some da lista ativa, mas o histórico de notas continua intacto e dá pra reativar depois.",
                "Inativar em vez de excluir?",
            ):
                self.repositorio.inativar_tomador(self.prestador_id, tomador_id)
            else:
                return
        except Exception as exc:  # noqa: BLE001
            widgets.mostrar_erro(self, exc, "Não deu pra excluir")
            return
        if self._editando_id == tomador_id:
            self._cancelar_edicao()
        self._recarregar_lista()

    def _reativar_selecionado(self) -> None:
        tomador_id = self._id_selecionado()
        if tomador_id is None or self.prestador_id is None:
            return
        self.repositorio.reativar_tomador(self.prestador_id, tomador_id)
        self._recarregar_lista()
