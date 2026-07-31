"""Tela 7 — Histórico de notas (espec-mvp-emissor-nfse.md, secao 2 itens 7-9):
filtro por status; "Abrir pasta" (nunca precisa caçar arquivo), "Cancelar
nota" (move pra Canceladas/, nunca apaga) e "WhatsApp" (abre wa.me com
mensagem pronta).

Etapa 3: coluna de status do e-mail automático + botão "Reenviar" (item 4);
"Fechar mês" gera Resumo/ZIP e oferece enviar ao contador (item 6).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QHeaderView, QInputDialog, QPushButton, QSpinBox,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from app import repo
from app.core import email as email_service
from app.core import fechamento, fila, mensagens
from app.ui import widgets

_OPCOES_STATUS = [
    ("Todas", None),
    ("Pendentes", repo.STATUS_PENDENTE),
    ("Emitidas", repo.STATUS_EMITIDA),
    ("Rejeitadas", repo.STATUS_REJEITADA),
    ("Canceladas", repo.STATUS_CANCELADA),
]

_ROTULO_EMAIL = {
    repo.EMAIL_NAO_ENVIADO: "—",
    repo.EMAIL_ENVIADO: "Enviado",
    repo.EMAIL_FALHOU: "Não enviado",
}


class TelaHistorico(QWidget):
    def __init__(self, repositorio: repo.Repositorio, obter_pasta_base: Callable[[], object], parent=None):
        super().__init__(parent)
        self.repositorio = repositorio
        self.obter_pasta_base = obter_pasta_base
        self.prestador_id: Optional[int] = None
        self._notas: list = []
        self._montar_layout()

    def _montar_layout(self) -> None:
        raiz = QVBoxLayout(self)
        cabecalho = QHBoxLayout()
        cabecalho.addWidget(widgets.titulo("Histórico de notas"))
        cabecalho.addStretch(1)
        cabecalho.addWidget(widgets.subtitulo("Filtrar:"))
        self.combo_status = QComboBox()
        for rotulo, _valor in _OPCOES_STATUS:
            self.combo_status.addItem(rotulo)
        self.combo_status.currentIndexChanged.connect(self._recarregar)
        cabecalho.addWidget(self.combo_status)
        raiz.addLayout(cabecalho)

        cartao = widgets.Cartao()
        layout_cartao = QVBoxLayout(cartao)
        self.tabela = QTableWidget(0, 7)
        self.tabela.setHorizontalHeaderLabels(["Número", "Tomador", "Valor", "Status", "E-mail", "Detalhe", "Data"])
        self.tabela.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        self.tabela.verticalHeader().setVisible(False)
        self.tabela.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.tabela.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.tabela.itemSelectionChanged.connect(self._atualizar_botoes)
        layout_cartao.addWidget(self.tabela)
        raiz.addWidget(cartao)

        linha_botoes = QHBoxLayout()
        self.botao_abrir_pasta = widgets.botao_secundario("Abrir pasta")
        self.botao_abrir_pasta.clicked.connect(self._abrir_pasta)
        self.botao_whatsapp = widgets.botao_secundario("WhatsApp")
        self.botao_whatsapp.clicked.connect(self._abrir_whatsapp)
        self.botao_reenviar_email = widgets.botao_secundario("Reenviar e-mail")
        self.botao_reenviar_email.clicked.connect(self._reenviar_email)
        self.botao_cancelar = widgets.botao_perigo("Cancelar nota")
        self.botao_cancelar.setEnabled(False)
        self.botao_cancelar.setToolTip(
            "Cancela de verdade junto à Receita (evento e101101) — só fica \"cancelada\" "
            "depois da confirmação do governo."
        )
        self.botao_cancelar.clicked.connect(self._cancelar_nota)
        linha_botoes.addWidget(self.botao_abrir_pasta)
        linha_botoes.addWidget(self.botao_whatsapp)
        linha_botoes.addWidget(self.botao_reenviar_email)
        linha_botoes.addStretch(1)
        linha_botoes.addWidget(self.botao_cancelar)
        raiz.addLayout(linha_botoes)
        self._atualizar_botoes()

        raiz.addWidget(widgets.linha_horizontal())
        cartao_fechamento = widgets.Cartao()
        layout_fechamento = QHBoxLayout(cartao_fechamento)
        layout_fechamento.addWidget(widgets.subtitulo("Fechar mês:"))
        import datetime
        hoje = datetime.date.today()
        self.spin_mes = QSpinBox()
        self.spin_mes.setRange(1, 12)
        self.spin_mes.setValue(hoje.month)
        self.spin_ano = QSpinBox()
        self.spin_ano.setRange(2020, 2100)
        self.spin_ano.setValue(hoje.year)
        layout_fechamento.addWidget(self.spin_mes)
        layout_fechamento.addWidget(self.spin_ano)
        self.botao_fechar_mes = QPushButton("Fechar mês")
        self.botao_fechar_mes.clicked.connect(self._fechar_mes)
        layout_fechamento.addWidget(self.botao_fechar_mes)
        layout_fechamento.addStretch(1)
        raiz.addWidget(cartao_fechamento)

    # ------------------------------------------------------------------
    def definir_prestador(self, prestador_id: Optional[int]) -> None:
        self.prestador_id = prestador_id
        self._recarregar()

    def _recarregar(self) -> None:
        self._notas = []
        self.tabela.setRowCount(0)
        if self.prestador_id is None:
            self._atualizar_botoes()
            return

        _rotulo, status = _OPCOES_STATUS[self.combo_status.currentIndex()]
        self._notas = self.repositorio.listar_notas_detalhado(self.prestador_id, status)
        self.tabela.setRowCount(len(self._notas))
        for linha, nota in enumerate(self._notas):
            detalhe = ""
            if nota["status"] == repo.STATUS_REJEITADA and nota.get("motivo_rejeicao"):
                detalhe = mensagens.traduzir_motivo_rejeicao(nota["motivo_rejeicao"])
            elif nota["status"] == repo.STATUS_EMITIDA and nota.get("chave_acesso"):
                detalhe = f"Chave: {nota['chave_acesso']}"

            self.tabela.setItem(linha, 0, QTableWidgetItem(nota["numero_dps"]))
            self.tabela.setItem(linha, 1, QTableWidgetItem(nota["tomador_nome"]))
            self.tabela.setItem(linha, 2, QTableWidgetItem(f"R$ {nota['valor']}"))
            self.tabela.setCellWidget(linha, 3, widgets.Selo(nota["status"]))
            item_email = QTableWidgetItem(_ROTULO_EMAIL.get(nota.get("email_status"), "—"))
            if nota.get("email_status") == repo.EMAIL_FALHOU:
                from PySide6.QtGui import QColor
                item_email.setForeground(QColor("#C43D3D"))
            self.tabela.setItem(linha, 4, item_email)
            self.tabela.setItem(linha, 5, QTableWidgetItem(detalhe))
            self.tabela.setItem(linha, 6, QTableWidgetItem((nota.get("emitida_em") or nota["criada_em"] or "")[:16]))
        self._atualizar_botoes()

    def _nota_selecionada(self) -> Optional[dict]:
        linhas = self.tabela.selectionModel().selectedRows() if self.tabela.selectionModel() else []
        if not linhas:
            return None
        return self._notas[linhas[0].row()]

    def _atualizar_botoes(self) -> None:
        nota = self._nota_selecionada()
        tem_arquivo = bool(nota and nota.get("xml_path"))
        pode_cancelar = bool(nota and nota["status"] == repo.STATUS_EMITIDA)
        pode_reenviar = bool(nota and nota["status"] == repo.STATUS_EMITIDA and nota.get("tomador_email"))
        self.botao_abrir_pasta.setEnabled(tem_arquivo)
        self.botao_whatsapp.setEnabled(bool(nota))
        # Cancelamento real (evento e101101 pro governo) reativado depois dos
        # 4 testes obrigatorios passarem (docs/auditoria.md, Bloco 4.4;
        # tests/test_fila.py::TestCancelamento) — so' habilita pra nota EMITIDA,
        # nunca pra uma ja cancelada ou com cancelamento em andamento.
        self.botao_cancelar.setEnabled(pode_cancelar)
        self.botao_reenviar_email.setEnabled(pode_reenviar)

    # ------------------------------------------------------------------
    def _abrir_pasta(self) -> None:
        nota = self._nota_selecionada()
        if not nota or not nota.get("xml_path"):
            return
        pasta = Path(nota["xml_path"]).parent
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(pasta)))

    def _abrir_whatsapp(self) -> None:
        nota = self._nota_selecionada()
        if not nota:
            return
        telefone = re.sub(r"\D", "", nota.get("tomador_telefone") or "")
        if not telefone:
            widgets.mostrar_erro(self, "Este tomador não tem telefone cadastrado.")
            return
        if not telefone.startswith("55"):
            telefone = "55" + telefone
        mensagem = (
            f"Olá {nota['tomador_nome']}, segue sua nota fiscal (NFS-e {nota['numero_dps']}), "
            f"no valor de R$ {nota['valor']}."
        )
        from urllib.parse import quote
        QDesktopServices.openUrl(QUrl(f"https://wa.me/{telefone}?text={quote(mensagem)}"))

    def _reenviar_email(self) -> None:
        nota = self._nota_selecionada()
        if not nota or self.prestador_id is None:
            return
        prestador_id = self.prestador_id
        nota_id = nota["id"]

        # Roda numa thread separada -- docs/auditoria.md, Bloco 7 item 2:
        # envio de e-mail e' rede (SMTP), nao pode travar a janela.
        self.botao_reenviar_email.setEnabled(False)
        self.botao_reenviar_email.setText("Enviando…")

        def _trabalho(repositorio):
            prestador = repositorio.obter_prestador(prestador_id)
            tomador = repositorio.obter_tomador(prestador_id, nota["tomador_id"])
            nota_atual = repositorio.obter_nota(prestador_id, nota_id)
            email_service.reenviar_nota_email(repositorio, prestador, tomador, nota_atual)
            return repositorio.obter_nota(prestador_id, nota_id)

        self._thread_email = widgets.executar_com_nova_conexao(
            self, self.repositorio.caminho_db, _trabalho, self._ao_reenviar_email_sucesso, self._ao_reenviar_email_erro,
        )

    def _ao_reenviar_email_sucesso(self, nota_atualizada) -> None:
        self.botao_reenviar_email.setText("Reenviar e-mail")
        self._recarregar()
        if nota_atualizada["email_status"] == repo.EMAIL_ENVIADO:
            widgets.mostrar_info(self, "E-mail enviado com sucesso.")
        else:
            widgets.mostrar_erro(
                self, f"Não deu pra enviar: {nota_atualizada.get('email_erro') or 'erro desconhecido'}",
                "E-mail não enviado",
            )

    def _ao_reenviar_email_erro(self, exc: BaseException) -> None:
        self.botao_reenviar_email.setText("Reenviar e-mail")
        self._recarregar()
        widgets.mostrar_erro(self, exc, "Não deu pra enviar")

    _OPCOES_MOTIVO_CANCELAMENTO = [
        ("Erro na emissão (dado errado, nota duplicada etc.)", "1"),
        ("Serviço não foi prestado", "2"),
        ("Outro motivo", "9"),
    ]

    def _cancelar_nota(self) -> None:
        nota = self._nota_selecionada()
        if not nota or self.prestador_id is None:
            return
        if not widgets.confirmar(
            self,
            f"Cancelar a nota {nota['numero_dps']} de {nota['tomador_nome']}? "
            "Isso avisa a Receita — só fica \"cancelada\" de verdade depois da confirmação do governo. "
            "O arquivo será movido para a pasta \"Canceladas\" só nesse momento, nunca apagado.",
        ):
            return

        rotulos = [r for r, _c in self._OPCOES_MOTIVO_CANCELAMENTO]
        rotulo_escolhido, ok = QInputDialog.getItem(
            self, "Motivo do cancelamento", "Por que essa nota está sendo cancelada?", rotulos, editable=False,
        )
        if not ok:
            return
        cod_motivo = dict(
            (r, c) for r, c in self._OPCOES_MOTIVO_CANCELAMENTO
        )[rotulo_escolhido]

        motivo_texto = None
        if cod_motivo == "9":
            motivo_texto, ok = QInputDialog.getText(self, "Descreva o motivo", "Motivo do cancelamento:")
            if not ok or not motivo_texto.strip():
                widgets.mostrar_erro(self, "Descreva o motivo pra continuar com \"Outro motivo\".")
                return
            motivo_texto = motivo_texto.strip()

        prestador_id = self.prestador_id
        nota_id = nota["id"]

        # Roda numa thread separada -- docs/auditoria.md, Bloco 7 item 2:
        # cancelamento avisa a Receita de verdade (rede), nao pode travar a janela.
        self.botao_cancelar.setEnabled(False)
        self.botao_cancelar.setText("Cancelando…")

        def _trabalho(repositorio):
            return fila.solicitar_cancelamento(
                repositorio, prestador_id, nota_id, cod_motivo=cod_motivo, motivo_texto=motivo_texto,
            )

        self._thread_cancelar = widgets.executar_com_nova_conexao(
            self, self.repositorio.caminho_db, _trabalho, self._ao_cancelar_sucesso, self._ao_cancelar_erro,
        )

    def _ao_cancelar_sucesso(self, resultado) -> None:
        self.botao_cancelar.setText("Cancelar nota")
        self._recarregar()
        status = resultado.get("status")
        if status == repo.STATUS_CANCELADA:
            widgets.mostrar_info(self, "Nota cancelada — a Receita confirmou o cancelamento.")
        elif status == repo.STATUS_CANCELAMENTO_PENDENTE:
            widgets.mostrar_info(
                self,
                "Não deu pra falar com a Receita agora (sem internet ou o sistema está fora do ar). "
                "O pedido de cancelamento ficou na fila e o programa vai tentar de novo sozinho.",
            )
        elif "erro_cancelamento" in resultado:
            widgets.mostrar_erro(
                self, mensagens.traduzir_erro_cancelamento(resultado["erro_cancelamento"]), "Não deu pra cancelar",
            )

    def _ao_cancelar_erro(self, exc: BaseException) -> None:
        self.botao_cancelar.setText("Cancelar nota")
        self._recarregar()
        widgets.mostrar_erro(self, exc, "Não deu pra cancelar")

    # ------------------------------------------------------------------
    def _fechar_mes(self) -> None:
        if self.prestador_id is None:
            widgets.mostrar_erro(self, "Selecione um prestador primeiro.")
            return
        try:
            resultado = fechamento.fechar_mes(
                self.repositorio, self.prestador_id, self.obter_pasta_base(),
                self.spin_ano.value(), self.spin_mes.value(),
            )
        except Exception as exc:  # noqa: BLE001
            widgets.mostrar_erro(self, exc, "Não deu pra fechar o mês")
            return

        if resultado.quantidade_notas == 0:
            widgets.mostrar_info(self, f"Nenhuma nota emitida em {resultado.mes_nome} pra fechar.")
            return

        if not widgets.confirmar(
            self,
            f"Fechamento de {resultado.mes_nome} pronto ({resultado.quantidade_notas} nota(s)):\n"
            f"{resultado.resumo_path.name}\n{resultado.zip_path.name}\n\n"
            "Quer enviar por e-mail ao contador agora?",
        ):
            return

        destinatario, ok = QInputDialog.getText(self, "Enviar ao contador", "E-mail do contador:")
        if not ok or not destinatario.strip():
            return

        prestador = self.repositorio.obter_prestador(self.prestador_id)
        destinatario = destinatario.strip()

        # Roda numa thread separada -- docs/auditoria.md, Bloco 7 item 2:
        # envio de e-mail e' rede (SMTP), nao pode travar a janela.
        self.botao_fechar_mes.setEnabled(False)
        self.botao_fechar_mes.setText("Enviando…")

        def _trabalho(repositorio):
            email_service.enviar_fechamento_email(
                repositorio, destinatario, prestador["nome_exibicao"], resultado.mes_nome,
                anexos=[resultado.resumo_path, resultado.zip_path],
            )
            return destinatario

        self._thread_fechamento = widgets.executar_com_nova_conexao(
            self, self.repositorio.caminho_db, _trabalho,
            self._ao_fechar_mes_sucesso, self._ao_fechar_mes_erro,
        )

    def _ao_fechar_mes_sucesso(self, destinatario: str) -> None:
        self.botao_fechar_mes.setEnabled(True)
        self.botao_fechar_mes.setText("Fechar mês")
        widgets.mostrar_info(self, f"Fechamento enviado para {destinatario}.")

    def _ao_fechar_mes_erro(self, exc: BaseException) -> None:
        self.botao_fechar_mes.setEnabled(True)
        self.botao_fechar_mes.setText("Fechar mês")
        widgets.mostrar_erro(self, exc, "Não deu pra enviar")
