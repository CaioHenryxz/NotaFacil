"""Tela 6 — Modelos de serviço e Mensalidades (espec-mvp-emissor-nfse.md,
secao 2 itens 3 e 5): "descrição, código de tributação nacional, valor
padrão, alíquota ISS" e "marca um tomador como 'mensalidade' (modelo + valor
+ dia do mês)".
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)

from app import repo
from app.core import tabelas_fiscais
from app.fiscal import dps_builder
from app.ui import widgets


class TelaModelos(QWidget):
    def __init__(self, repositorio: repo.Repositorio, parent=None):
        super().__init__(parent)
        self.repositorio = repositorio
        self.prestador_id: Optional[int] = None

        raiz = QVBoxLayout(self)
        raiz.addWidget(widgets.titulo("Modelos de serviço e mensalidades"))

        abas = QTabWidget()
        self.aba_modelos = _AbaModelos(repositorio)
        self.aba_mensalidades = _AbaMensalidades(repositorio)
        abas.addTab(self.aba_modelos, "Modelos de serviço")
        abas.addTab(self.aba_mensalidades, "Mensalidades")
        raiz.addWidget(abas)

    def definir_prestador(self, prestador_id: Optional[int]) -> None:
        self.prestador_id = prestador_id
        self.aba_modelos.definir_prestador(prestador_id)
        self.aba_mensalidades.definir_prestador(prestador_id)


class _AbaModelos(QWidget):
    def __init__(self, repositorio: repo.Repositorio, parent=None):
        super().__init__(parent)
        self.repositorio = repositorio
        self.prestador_id: Optional[int] = None
        self._editando_id: Optional[int] = None
        self._modelos: list = []
        self._optante_simples: bool = False

        raiz = QHBoxLayout(self)

        cartao_lista = widgets.Cartao()
        layout_lista = QVBoxLayout(cartao_lista)
        self.tabela = QTableWidget(0, 4)
        self.tabela.setHorizontalHeaderLabels(["Descrição", "Cód. tributação", "Valor padrão", "Alíquota ISS"])
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
        linha_acoes.addWidget(self.botao_editar)
        linha_acoes.addWidget(self.botao_excluir)
        linha_acoes.addStretch(1)
        layout_lista.addLayout(linha_acoes)

        raiz.addWidget(cartao_lista, stretch=2)

        cartao_novo = widgets.Cartao()
        layout_novo = QVBoxLayout(cartao_novo)
        layout_novo.addWidget(widgets.subtitulo("Novo modelo"))
        formulario = QFormLayout()
        self.campo_descricao = QLineEdit()
        self.campo_descricao.setMaxLength(dps_builder.TAMANHO_MAXIMO_DESCRICAO_SERVICO)
        formulario.addRow("Descrição:", self.campo_descricao)
        # Combo editavel: sugere os codigos de saude ja confirmados (evita
        # erro de digitacao, docs/auditoria.md Bloco 2.2), mas ainda aceita
        # texto livre pra qualquer outro codigo que o app nao tenha na lista.
        self.campo_trib_nacional = QComboBox()
        self.campo_trib_nacional.setEditable(True)
        self.campo_trib_nacional.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.campo_trib_nacional.lineEdit().setPlaceholderText("6 dígitos — escolha da lista ou digite")
        for codigo, descricao in tabelas_fiscais.CODIGOS_TRIBUTACAO_NACIONAL_SAUDE:
            self.campo_trib_nacional.addItem(f"{codigo} — {descricao}", codigo)
        self.campo_trib_nacional.setCurrentIndex(-1)
        self.campo_trib_nacional.currentIndexChanged.connect(self._ao_escolher_trib_nacional)
        formulario.addRow("Cód. tributação nacional:", self.campo_trib_nacional)
        self.campo_trib_municipal = QLineEdit()
        self.campo_trib_municipal.setPlaceholderText("3 dígitos — deixe em branco se a prefeitura não exigir")
        formulario.addRow("Cód. tributação municipal:", self.campo_trib_municipal)
        self.campo_nbs = QLineEdit()
        self.campo_nbs.setPlaceholderText("9 dígitos (NBS)")
        formulario.addRow("Código NBS:", self.campo_nbs)
        self.campo_valor_padrao = widgets.CampoValorMonetario()
        formulario.addRow("Valor padrão (R$):", self.campo_valor_padrao)
        self.campo_aliquota = QLineEdit()
        self.campo_aliquota.setPlaceholderText("Deixe em branco se o município já parametriza")
        self.rotulo_aliquota = QLabel("Alíquota ISS (%):")
        formulario.addRow(self.rotulo_aliquota, self.campo_aliquota)
        layout_novo.addLayout(formulario)

        self.botao_salvar = QPushButton("Salvar modelo")
        self.botao_salvar.clicked.connect(self._salvar)
        layout_novo.addWidget(self.botao_salvar)
        self.botao_cancelar_edicao = widgets.botao_secundario("Cancelar edição")
        self.botao_cancelar_edicao.clicked.connect(self._cancelar_edicao)
        self.botao_cancelar_edicao.setVisible(False)
        layout_novo.addWidget(self.botao_cancelar_edicao)
        layout_novo.addStretch(1)
        raiz.addWidget(cartao_novo, stretch=1)

    def definir_prestador(self, prestador_id: Optional[int]) -> None:
        self._cancelar_edicao()
        self.prestador_id = prestador_id
        self._atualizar_trava_aliquota()
        self._recarregar()

    def _atualizar_trava_aliquota(self) -> None:
        """opSimpNac 2 (MEI) ou 3 (ME/EPP): o ISS desse prestador vai no DAS,
        nao "por fora" na nota -- travar o campo evita a secretaria digitar um
        valor que o backend vai descartar de qualquer forma (ver
        app.fiscal.dps_builder._pAliq_deve_ser_omitido, docs/auditoria.md
        Bloco 2.3)."""
        prestador = self.repositorio.obter_prestador(self.prestador_id) if self.prestador_id else None
        self._optante_simples = bool(prestador and prestador.get("regime") in ("2", "3"))
        self.campo_aliquota.setEnabled(not self._optante_simples)
        if self._optante_simples:
            self.campo_aliquota.clear()
            self.campo_aliquota.setPlaceholderText("Não se aplica — ISS deste prestador vai no DAS (Simples Nacional)")
        else:
            self.campo_aliquota.setPlaceholderText("Deixe em branco se o município já parametriza")

    def _recarregar(self) -> None:
        self.tabela.setRowCount(0)
        self._modelos = []
        if self.prestador_id is None:
            self._atualizar_botoes()
            return
        modelos = self.repositorio.listar_modelos_servico(self.prestador_id)
        self._modelos = modelos
        self.tabela.setRowCount(len(modelos))
        for linha, m in enumerate(modelos):
            texto_descricao = m["descricao"]
            if m.get("precisa_revisao_cod_trib_municipal"):
                texto_descricao = f"⚠ REVISAR — {texto_descricao}"
            item_descricao = QTableWidgetItem(texto_descricao)
            item_descricao.setData(Qt.ItemDataRole.UserRole, m["id"])
            if m.get("precisa_revisao_cod_trib_municipal"):
                item_descricao.setToolTip(
                    "O código de tributação municipal deste serviço está num formato antigo "
                    "e inválido (não tem 3 dígitos) — edite e corrija (ou apague) antes de emitir "
                    "uma nota com este serviço."
                )
            self.tabela.setItem(linha, 0, item_descricao)
            self.tabela.setItem(linha, 1, QTableWidgetItem(m["cod_tributacao_nacional"]))
            self.tabela.setItem(linha, 2, QTableWidgetItem(f"R$ {m['valor_padrao']}"))
            self.tabela.setItem(linha, 3, QTableWidgetItem(m.get("aliquota") or "(automática)"))
        self._atualizar_botoes()

    def _id_selecionado(self) -> Optional[int]:
        linha = self.tabela.currentRow()
        if linha < 0:
            return None
        item = self.tabela.item(linha, 0)
        if item is None:
            return None
        return item.data(Qt.ItemDataRole.UserRole)

    def _modelo_selecionado(self) -> Optional[dict]:
        modelo_id = self._id_selecionado()
        if modelo_id is None:
            return None
        for m in self._modelos:
            if m["id"] == modelo_id:
                return m
        return None

    def _atualizar_botoes(self) -> None:
        tem_selecao = self._id_selecionado() is not None
        self.botao_editar.setEnabled(tem_selecao)
        self.botao_excluir.setEnabled(tem_selecao)

    def _ao_escolher_trib_nacional(self, indice: int) -> None:
        codigo = self.campo_trib_nacional.itemData(indice)
        if codigo:
            self.campo_trib_nacional.blockSignals(True)
            self.campo_trib_nacional.setEditText(codigo)
            self.campo_trib_nacional.blockSignals(False)

    def _validar_campos(self) -> Optional[str]:
        descricao = self.campo_descricao.text().strip()
        trib_nacional = self.campo_trib_nacional.currentText().strip()
        trib_municipal = self.campo_trib_municipal.text().strip()
        nbs = self.campo_nbs.text().strip()

        if not descricao:
            return "Digite uma descrição para o serviço."
        if len(descricao) > dps_builder.TAMANHO_MAXIMO_DESCRICAO_SERVICO:
            return f"A descrição passou de {dps_builder.TAMANHO_MAXIMO_DESCRICAO_SERVICO} caracteres — a Receita vai rejeitar. Encurte o texto."
        if len(trib_nacional) != 6 or not trib_nacional.isdigit():
            return "O código de tributação nacional tem 6 dígitos."
        # cTribMun e' OPCIONAL (a prefeitura pode nao ter um desdobro proprio
        # do ISSQN) -- so' valida o formato se o usuario digitou algo (docs/
        # auditoria-2.md, secao 8.1: era exigido com 10 digitos, o que e'
        # estruturalmente invalido pro XSD oficial; o certo e' 3 digitos, ou
        # em branco).
        if trib_municipal and (len(trib_municipal) != 3 or not trib_municipal.isdigit()):
            return (
                "O código de tributação municipal tem 3 dígitos (confira com a prefeitura) "
                "— ou deixe em branco se a prefeitura não tiver um código próprio."
            )
        if len(nbs) != 9 or not nbs.isdigit():
            return "O código NBS tem 9 dígitos."
        if self.campo_valor_padrao.valor_decimal() <= 0:
            return "Digite um valor padrão válido, maior que zero."
        return None

    def _salvar(self) -> None:
        if self.prestador_id is None:
            return
        erro = self._validar_campos()
        if erro:
            widgets.mostrar_erro(self, erro)
            return

        descricao = self.campo_descricao.text().strip()
        trib_nacional = self.campo_trib_nacional.currentText().strip()
        trib_municipal = self.campo_trib_municipal.text().strip()
        nbs = self.campo_nbs.text().strip()
        valor_padrao = self.campo_valor_padrao.valor_normalizado()
        # optante do Simples nunca manda aliquota (defesa em profundidade --
        # o backend tambem trava isso, ver _atualizar_trava_aliquota acima)
        aliquota = None if self._optante_simples else (self.campo_aliquota.text().strip().replace(",", ".") or None)

        if self._editando_id is not None:
            try:
                self.repositorio.atualizar_modelo_servico(
                    self.prestador_id, self._editando_id, descricao=descricao,
                    cod_tributacao_nacional=trib_nacional, cod_tributacao_municipal=trib_municipal,
                    cod_nbs=nbs, valor_padrao=valor_padrao, aliquota=aliquota,
                )
            except Exception as exc:  # noqa: BLE001
                widgets.mostrar_erro(self, exc, "Não deu pra salvar")
                return
            self._cancelar_edicao()
            self._recarregar()
            return

        try:
            self.repositorio.criar_modelo_servico(
                self.prestador_id, descricao=descricao, cod_tributacao_nacional=trib_nacional,
                cod_tributacao_municipal=trib_municipal, cod_nbs=nbs,
                valor_padrao=valor_padrao, aliquota=aliquota,
            )
        except Exception as exc:  # noqa: BLE001
            widgets.mostrar_erro(self, exc, "Não deu pra salvar")
            return

        self._limpar_formulario()
        self._recarregar()

    def _limpar_formulario(self) -> None:
        for campo in (self.campo_descricao, self.campo_trib_municipal, self.campo_nbs, self.campo_aliquota):
            campo.clear()
        self.campo_valor_padrao.limpar()
        # QComboBox.clear() apagaria a lista de sugestoes inteira -- so
        # limpar o texto digitado/selecionado, sem tocar nos itens.
        self.campo_trib_nacional.setCurrentIndex(-1)
        self.campo_trib_nacional.clearEditText()

    # ------------------------------------------------------------------
    def _editar_selecionado(self) -> None:
        modelo = self._modelo_selecionado()
        if modelo is None:
            return
        self._editando_id = modelo["id"]
        self.campo_descricao.setText(modelo["descricao"])
        self.campo_trib_nacional.blockSignals(True)
        self.campo_trib_nacional.setEditText(modelo["cod_tributacao_nacional"])
        self.campo_trib_nacional.blockSignals(False)
        self.campo_trib_municipal.setText(modelo["cod_tributacao_municipal"])
        self.campo_nbs.setText(modelo["cod_nbs"])
        self.campo_valor_padrao.definir_valor(modelo["valor_padrao"])
        if not self._optante_simples:
            self.campo_aliquota.setText(modelo.get("aliquota") or "")
        self.botao_salvar.setText("Salvar alterações")
        self.botao_cancelar_edicao.setVisible(True)
        if modelo.get("precisa_revisao_cod_trib_municipal"):
            widgets.mostrar_info(
                self,
                "O código de tributação municipal deste serviço foi cadastrado antigamente com "
                "10 dígitos — mas o Sistema Nacional NFS-e exige exatamente 3 dígitos (ou nenhum, "
                "se a prefeitura não tiver um código próprio de ISSQN além do nacional). "
                "Enquanto não corrigir esse campo (apagando-o ou digitando o código certo de 3 "
                "dígitos, confira com a prefeitura ou seu contador), o programa vai recusar emitir "
                "qualquer nota nova com este serviço.",
                "Este serviço precisa de revisão",
            )

    def _cancelar_edicao(self) -> None:
        self._editando_id = None
        self._limpar_formulario()
        self.botao_salvar.setText("Salvar modelo")
        self.botao_cancelar_edicao.setVisible(False)

    def _excluir_selecionado(self) -> None:
        modelo = self._modelo_selecionado()
        if modelo is None or self.prestador_id is None:
            return
        if not widgets.confirmar(
            self, f'Excluir o serviço "{modelo["descricao"]}"? Essa ação não pode ser desfeita.'
        ):
            return
        try:
            self.repositorio.excluir_modelo_servico(self.prestador_id, modelo["id"])
        except Exception as exc:  # noqa: BLE001
            widgets.mostrar_erro(self, exc, "Não deu pra excluir")
            return
        if self._editando_id == modelo["id"]:
            self._cancelar_edicao()
        self._recarregar()


class _AbaMensalidades(QWidget):
    def __init__(self, repositorio: repo.Repositorio, parent=None):
        super().__init__(parent)
        self.repositorio = repositorio
        self.prestador_id: Optional[int] = None
        self._editando_id: Optional[int] = None
        self._modelos: list = []
        self._recorrencias: list = []

        raiz = QHBoxLayout(self)

        cartao_lista = widgets.Cartao()
        layout_lista = QVBoxLayout(cartao_lista)
        self.tabela = QTableWidget(0, 4)
        self.tabela.setHorizontalHeaderLabels(["Tomador", "Serviço", "Valor", "Dia do mês"])
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
        linha_acoes.addWidget(self.botao_editar)
        linha_acoes.addWidget(self.botao_excluir)
        linha_acoes.addStretch(1)
        layout_lista.addLayout(linha_acoes)

        raiz.addWidget(cartao_lista, stretch=2)

        cartao_novo = widgets.Cartao()
        layout_novo = QVBoxLayout(cartao_novo)
        layout_novo.addWidget(widgets.subtitulo("Nova mensalidade"))
        formulario = QFormLayout()
        self.combo_tomador = QComboBox()
        formulario.addRow("Tomador:", self.combo_tomador)
        self.combo_modelo = QComboBox()
        self.combo_modelo.currentIndexChanged.connect(self._preencher_valor_padrao)
        formulario.addRow("Serviço:", self.combo_modelo)
        self.campo_valor = widgets.CampoValorMonetario()
        formulario.addRow("Valor (R$):", self.campo_valor)
        self.campo_dia = QSpinBox()
        self.campo_dia.setRange(1, 28)
        self.campo_dia.setValue(1)
        formulario.addRow("Dia do mês:", self.campo_dia)
        self.marca_ativo = QCheckBox("Ativa")
        self.marca_ativo.setChecked(True)
        formulario.addRow("", self.marca_ativo)
        layout_novo.addLayout(formulario)

        self.botao_salvar = QPushButton("Salvar mensalidade")
        self.botao_salvar.clicked.connect(self._salvar)
        layout_novo.addWidget(self.botao_salvar)
        self.botao_cancelar_edicao = widgets.botao_secundario("Cancelar edição")
        self.botao_cancelar_edicao.clicked.connect(self._cancelar_edicao)
        self.botao_cancelar_edicao.setVisible(False)
        layout_novo.addWidget(self.botao_cancelar_edicao)
        layout_novo.addStretch(1)
        raiz.addWidget(cartao_novo, stretch=1)

    def definir_prestador(self, prestador_id: Optional[int]) -> None:
        self._cancelar_edicao()
        self.prestador_id = prestador_id
        self._recarregar()

    def _recarregar(self) -> None:
        self.tabela.setRowCount(0)
        self.combo_tomador.clear()
        self.combo_modelo.clear()
        self._modelos = []
        self._recorrencias = []
        if self.prestador_id is None:
            self._atualizar_botoes()
            return

        tomadores_por_id = {t["id"]: t for t in self.repositorio.listar_tomadores(self.prestador_id)}
        modelos_por_id = {}
        for m in self.repositorio.listar_modelos_servico(self.prestador_id):
            modelos_por_id[m["id"]] = m
            self.combo_modelo.addItem(f"{m['descricao']} (R$ {m['valor_padrao']})", m["id"])
            self._modelos.append(m)
        for t in tomadores_por_id.values():
            self.combo_tomador.addItem(t["nome"], t["id"])
        self._preencher_valor_padrao()

        recorrencias = self.repositorio.listar_recorrencias(self.prestador_id, apenas_ativas=False)
        self._recorrencias = recorrencias
        self.tabela.setRowCount(len(recorrencias))
        for linha, r in enumerate(recorrencias):
            tomador = tomadores_por_id.get(r["tomador_id"], {})
            modelo = modelos_por_id.get(r["modelo_id"], {})
            item_tomador = QTableWidgetItem(tomador.get("nome", "?"))
            item_tomador.setData(Qt.ItemDataRole.UserRole, r["id"])
            self.tabela.setItem(linha, 0, item_tomador)
            self.tabela.setItem(linha, 1, QTableWidgetItem(modelo.get("descricao", "?")))
            self.tabela.setItem(linha, 2, QTableWidgetItem(f"R$ {r['valor']}" + ("" if r["ativo"] else " (inativa)")))
            self.tabela.setItem(linha, 3, QTableWidgetItem(str(r["dia_do_mes"])))
        self._atualizar_botoes()

    def _preencher_valor_padrao(self) -> None:
        indice = self.combo_modelo.currentIndex()
        if 0 <= indice < len(self._modelos):
            self.campo_valor.definir_valor(self._modelos[indice]["valor_padrao"])

    def _id_selecionado(self) -> Optional[int]:
        linha = self.tabela.currentRow()
        if linha < 0:
            return None
        item = self.tabela.item(linha, 0)
        if item is None:
            return None
        return item.data(Qt.ItemDataRole.UserRole)

    def _recorrencia_selecionada(self) -> Optional[dict]:
        recorrencia_id = self._id_selecionado()
        if recorrencia_id is None:
            return None
        for r in self._recorrencias:
            if r["id"] == recorrencia_id:
                return r
        return None

    def _atualizar_botoes(self) -> None:
        tem_selecao = self._id_selecionado() is not None
        self.botao_editar.setEnabled(tem_selecao)
        self.botao_excluir.setEnabled(tem_selecao)

    def _salvar(self) -> None:
        if self.prestador_id is None:
            return
        tomador_id = self.combo_tomador.currentData()
        modelo_id = self.combo_modelo.currentData()
        if tomador_id is None or modelo_id is None:
            widgets.mostrar_erro(self, "Cadastre um tomador e um modelo de serviço antes de criar a mensalidade.")
            return
        if self.campo_valor.valor_decimal() <= 0:
            widgets.mostrar_erro(self, "Digite um valor válido, maior que zero.")
            return
        valor = self.campo_valor.valor_normalizado()

        if self._editando_id is not None:
            try:
                self.repositorio.atualizar_recorrencia(
                    self.prestador_id, self._editando_id, tomador_id=tomador_id, modelo_id=modelo_id,
                    valor=valor, dia_do_mes=self.campo_dia.value(),
                )
            except Exception as exc:  # noqa: BLE001
                widgets.mostrar_erro(self, exc, "Não deu pra salvar")
                return
            self._cancelar_edicao()
            self._recarregar()
            return

        try:
            self.repositorio.criar_recorrencia(
                self.prestador_id, tomador_id=tomador_id, modelo_id=modelo_id,
                valor=valor, dia_do_mes=self.campo_dia.value(), ativo=self.marca_ativo.isChecked(),
            )
        except Exception as exc:  # noqa: BLE001
            widgets.mostrar_erro(self, exc, "Não deu pra salvar")
            return

        self._recarregar()

    # ------------------------------------------------------------------
    def _editar_selecionado(self) -> None:
        recorrencia = self._recorrencia_selecionada()
        if recorrencia is None:
            return
        self._editando_id = recorrencia["id"]
        self.combo_tomador.blockSignals(True)
        indice_tomador = self.combo_tomador.findData(recorrencia["tomador_id"])
        if indice_tomador >= 0:
            self.combo_tomador.setCurrentIndex(indice_tomador)
        self.combo_tomador.blockSignals(False)

        self.combo_modelo.blockSignals(True)
        indice_modelo = self.combo_modelo.findData(recorrencia["modelo_id"])
        if indice_modelo >= 0:
            self.combo_modelo.setCurrentIndex(indice_modelo)
        self.combo_modelo.blockSignals(False)

        self.campo_valor.definir_valor(recorrencia["valor"])
        self.campo_dia.setValue(recorrencia["dia_do_mes"])
        self.marca_ativo.setEnabled(False)
        self.botao_salvar.setText("Salvar alterações")
        self.botao_cancelar_edicao.setVisible(True)

    def _cancelar_edicao(self) -> None:
        self._editando_id = None
        self.campo_valor.limpar()
        self.campo_dia.setValue(1)
        self.marca_ativo.setEnabled(True)
        self.botao_salvar.setText("Salvar mensalidade")
        self.botao_cancelar_edicao.setVisible(False)

    def _excluir_selecionado(self) -> None:
        recorrencia = self._recorrencia_selecionada()
        if recorrencia is None or self.prestador_id is None:
            return
        tomador = self.repositorio.obter_tomador(self.prestador_id, recorrencia["tomador_id"])
        nome_tomador = tomador["nome"] if tomador else "?"
        if not widgets.confirmar(
            self,
            f'Excluir a mensalidade de "{nome_tomador}"? Essa ação não pode ser desfeita. '
            "Se já existe nota emitida a partir dela, pause em vez de excluir.",
        ):
            return
        try:
            self.repositorio.excluir_recorrencia(self.prestador_id, recorrencia["id"])
        except Exception as exc:  # noqa: BLE001
            widgets.mostrar_erro(self, exc, "Não deu pra excluir")
            return
        if self._editando_id == recorrencia["id"]:
            self._cancelar_edicao()
        self._recarregar()
