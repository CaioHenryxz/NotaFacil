"""Janela principal: seletor de prestador fixo no topo (tela 2) + abas pras
demais telas. Abre direto na tela de cadastro se nao houver nenhum prestador
ainda; depois disso abre sempre no "Meu Dia" (espec-mvp-emissor-nfse.md,
secao 2 item 1b: "e' a tela inicial da secretaria").

Etapa 3 (automacao): fechar a janela minimiza pra bandeja (nao encerra); um
QTimer de 15 min roda o agendador (recorrencias do dia + retries da fila) e
notifica pela bandeja quando algo acontece sozinho — inclusive o catch-up de
mensalidades atrasadas se o PC estava desligado no dia (espec §4).
"""
from __future__ import annotations

import datetime
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QCloseEvent, QColor, QDesktopServices, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QColorDialog, QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QMainWindow, QMenu, QPushButton, QStackedWidget, QSystemTrayIcon, QTabWidget,
    QVBoxLayout, QWidget,
)

from app import repo
from app.core import agendador, email_config, inicializacao_windows, mensagens, pastas
from app.ui import tema, widgets
from app.ui.tela_configuracoes import TelaConfiguracoes
from app.ui.tela_emitir import TelaEmitir
from app.ui.tela_historico import TelaHistorico
from app.ui.tela_lote import TelaLote
from app.ui.tela_meu_dia import TelaMeuDia
from app.ui.tela_modelos import TelaModelos
from app.ui.tela_prestador import _OPCOES_REGIME, _OPCOES_REGIME_ESPECIAL, TelaCadastroPrestador
from app.ui.tela_tomadores import TelaTomadores

INTERVALO_AGENDADOR_MS = 15 * 60 * 1000  # 15 minutos (Etapa 3 item 2)


def _icone_circulo(cor_hex: Optional[str], tamanho: int = 14) -> QIcon:
    pixmap = QPixmap(tamanho, tamanho)
    pixmap.fill(Qt.GlobalColor.transparent)
    pintor = QPainter(pixmap)
    pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
    pintor.setBrush(QColor(cor_hex or tema.COR_TEXTO_SECUNDARIO))
    pintor.setPen(Qt.PenStyle.NoPen)
    pintor.drawEllipse(0, 0, tamanho, tamanho)
    pintor.end()
    return QIcon(pixmap)


def _icone_app() -> QIcon:
    """Ícone simples gerado em código — sem depender de um arquivo .ico
    (isso entra quando o PyInstaller empacotar o app, Etapa 4)."""
    tamanho = 64
    pixmap = QPixmap(tamanho, tamanho)
    pixmap.fill(Qt.GlobalColor.transparent)
    pintor = QPainter(pixmap)
    pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
    pintor.setBrush(QColor(tema.COR_PRIMARIA))
    pintor.setPen(Qt.PenStyle.NoPen)
    pintor.drawRoundedRect(4, 4, tamanho - 8, tamanho - 8, 14, 14)
    pintor.setPen(QColor("white"))
    fonte = pintor.font()
    fonte.setBold(True)
    fonte.setPointSize(28)
    pintor.setFont(fonte)
    pintor.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "N")
    pintor.end()
    return QIcon(pixmap)


class JanelaPrincipal(QMainWindow):
    def __init__(
        self,
        repositorio: repo.Repositorio,
        pasta_base_padrao: str,
        *,
        obter_hoje: Callable[[], datetime.date] = datetime.date.today,
    ):
        super().__init__()
        self.repositorio = repositorio
        self.pasta_base = Path(email_config.obter_pasta_base(repositorio, padrao=pasta_base_padrao))
        self.prestador_ativo_id: Optional[int] = None
        self.obter_hoje = obter_hoje
        self._saindo_de_verdade = False

        self.setWindowTitle("Emissor NFS-e")
        self.setWindowIcon(_icone_app())
        self.resize(1280, 820)

        self.pilha = QStackedWidget()
        self.setCentralWidget(self.pilha)

        self._pagina_onboarding = self._montar_pagina_onboarding()
        self._pagina_principal = self._montar_pagina_principal()
        self.pilha.addWidget(self._pagina_onboarding)
        self.pilha.addWidget(self._pagina_principal)

        self._carregar_prestadores(selecionar_primeiro=True)

        self._montar_bandeja()

        self.timer_agendador = QTimer(self)
        self.timer_agendador.setInterval(INTERVALO_AGENDADOR_MS)
        self.timer_agendador.timeout.connect(self.rodar_ciclo_automatico)
        self.timer_agendador.start()
        # roda um ciclo logo ao abrir — e' o que cobre "PC desligado no dia
        # da mensalidade -> emite na proxima abertura" (espec §4)
        QTimer.singleShot(1500, self.rodar_ciclo_automatico)

    # ------------------------------------------------------------------
    def obter_pasta_base(self) -> Path:
        return self.pasta_base

    def _ao_salvar_pasta_base(self, pasta: str) -> None:
        self.pasta_base = Path(pasta)

    # ------------------------------------------------------------------
    def _montar_pagina_onboarding(self) -> QWidget:
        pagina = QWidget()
        layout = QVBoxLayout(pagina)
        layout.addWidget(widgets.subtitulo("Bem-vindo! Cadastre o primeiro prestador para começar."))
        tela = TelaCadastroPrestador(self.repositorio)
        tela.prestador_criado.connect(self._ao_criar_primeiro_prestador)
        layout.addWidget(tela)
        return pagina

    def _montar_pagina_principal(self) -> QWidget:
        pagina = QWidget()
        raiz = QVBoxLayout(pagina)

        barra = QHBoxLayout()
        rotulo = QLabel("Prestador:")
        rotulo.setStyleSheet("font-weight: 600;")
        barra.addWidget(rotulo)
        self.combo_prestador = QComboBox()
        self.combo_prestador.setIconSize(QSize(14, 14))
        self.combo_prestador.setMinimumWidth(280)
        self.combo_prestador.currentIndexChanged.connect(self._ao_trocar_prestador)
        barra.addWidget(self.combo_prestador)
        barra.addStretch(1)

        # Aviso fixo de ambiente: hoje o app so' emite em homologacao (teste)
        # — ver docs/spec-mvp.md §8 risco 1 e o README ("como trocar pra
        # producao"). E' so' um rotulo (nao muda nada sozinho); o texto
        # reflete o que ja esta' fixo no codigo (app/core/fila.py).
        selo_ambiente = QLabel("🧪 HOMOLOGAÇÃO (teste) — as notas emitidas aqui NÃO valem como documento fiscal real")
        selo_ambiente.setStyleSheet(
            f"background-color: {tema.COR_ALERTA}; color: white; border-radius: 6px; "
            f"padding: 6px 12px; font-weight: 600;"
        )
        barra.addWidget(selo_ambiente)
        barra.addStretch(1)

        botao_novo = widgets.botao_secundario("+ Novo prestador")
        botao_novo.clicked.connect(self._abrir_dialogo_novo_prestador)
        barra.addWidget(botao_novo)

        self.botao_editar_prestador = widgets.botao_secundario("Editar prestador")
        self.botao_editar_prestador.setEnabled(False)
        self.botao_editar_prestador.clicked.connect(self._abrir_dialogo_editar_prestador)
        barra.addWidget(self.botao_editar_prestador)

        self.botao_excluir_prestador = widgets.botao_perigo("Excluir prestador")
        self.botao_excluir_prestador.setEnabled(False)
        self.botao_excluir_prestador.clicked.connect(self._excluir_prestador_ativo)
        barra.addWidget(self.botao_excluir_prestador)

        self.botao_reativar_prestador = widgets.botao_secundario("Reativar prestador")
        self.botao_reativar_prestador.setEnabled(False)
        self.botao_reativar_prestador.setVisible(False)
        self.botao_reativar_prestador.clicked.connect(self._reativar_prestador_ativo)
        barra.addWidget(self.botao_reativar_prestador)

        self.marca_mostrar_prestadores_inativos = QCheckBox("Mostrar inativos")
        self.marca_mostrar_prestadores_inativos.toggled.connect(lambda _: self._carregar_prestadores())
        barra.addWidget(self.marca_mostrar_prestadores_inativos)

        raiz.addLayout(barra)

        self.abas = QTabWidget()
        self.tela_meu_dia = TelaMeuDia(self.repositorio, self.obter_pasta_base, obter_hoje=lambda: self.obter_hoje())
        self.tela_emitir = TelaEmitir(self.repositorio, self.obter_pasta_base)
        self.tela_lote = TelaLote(self.repositorio, self.obter_pasta_base)
        self.tela_tomadores = TelaTomadores(self.repositorio)
        self.tela_modelos = TelaModelos(self.repositorio)
        self.tela_historico = TelaHistorico(self.repositorio, self.obter_pasta_base)
        self.tela_configuracoes = TelaConfiguracoes(
            self.repositorio, str(self.pasta_base), self._ao_salvar_pasta_base
        )

        self.abas.addTab(self.tela_meu_dia, "Meu Dia")
        self.abas.addTab(self.tela_emitir, "Emitir nota")
        self.abas.addTab(self.tela_lote, "Emitir em lote")
        self.abas.addTab(self.tela_tomadores, "Tomadores")
        self.abas.addTab(self.tela_modelos, "Modelos e mensalidades")
        self.abas.addTab(self.tela_historico, "Histórico")
        self.abas.addTab(self.tela_configuracoes, "Configurações")
        self.abas.currentChanged.connect(self._ao_trocar_aba)
        raiz.addWidget(self.abas)

        self._telas_escopadas_por_prestador = [
            self.tela_emitir, self.tela_lote, self.tela_tomadores, self.tela_modelos, self.tela_historico,
        ]
        return pagina

    # ------------------------------------------------------------------
    # bandeja do Windows (Etapa 3 item 3)
    # ------------------------------------------------------------------

    def _montar_bandeja(self) -> None:
        self.tray: Optional[QSystemTrayIcon] = None
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return  # ex.: rodando em ambiente sem bandeja (testes offscreen)

        self.tray = QSystemTrayIcon(_icone_app(), self)
        self.tray.setToolTip("Emissor NFS-e")

        menu = QMenu()
        acao_abrir = QAction("Abrir", self)
        acao_abrir.triggered.connect(self._restaurar_janela)
        menu.addAction(acao_abrir)

        self.acao_iniciar_com_windows = QAction("Iniciar com o Windows", self)
        self.acao_iniciar_com_windows.setCheckable(True)
        self.acao_iniciar_com_windows.setChecked(inicializacao_windows.esta_habilitado())
        self.acao_iniciar_com_windows.toggled.connect(self._alternar_inicio_automatico)
        menu.addAction(self.acao_iniciar_com_windows)

        menu.addSeparator()
        acao_sair = QAction("Sair", self)
        acao_sair.triggered.connect(self._sair_de_verdade)
        menu.addAction(acao_sair)

        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._ao_ativar_bandeja)
        self.tray.show()

    def _alternar_inicio_automatico(self, ligado: bool) -> None:
        try:
            if ligado:
                inicializacao_windows.habilitar()
            else:
                inicializacao_windows.desabilitar()
        except inicializacao_windows.IndisponivelNestaPlataforma:
            pass

    def _ao_ativar_bandeja(self, motivo) -> None:
        if motivo in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self._restaurar_janela()

    def _restaurar_janela(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _sair_de_verdade(self) -> None:
        self._saindo_de_verdade = True
        self.close()

    def notificar(self, titulo: str, mensagem: str) -> None:
        if self.tray is not None:
            self.tray.showMessage(titulo, mensagem, QSystemTrayIcon.MessageIcon.Information, 8000)

    def closeEvent(self, evento: QCloseEvent) -> None:  # noqa: N802 (Qt override)
        if self._saindo_de_verdade or self.tray is None:
            evento.accept()
            return
        evento.ignore()
        self.hide()
        self.notificar("Emissor NFS-e", "O app continua rodando na bandeja — clique aqui pra abrir de novo.")

    # ------------------------------------------------------------------
    # agendador automático (Etapa 3 itens 1 e 2)
    # ------------------------------------------------------------------

    def rodar_ciclo_automatico(self) -> None:
        """Roda numa thread separada -- docs/auditoria.md, Bloco 7 item 2:
        este ciclo dispara SOZINHO (QTimer de 15 min + uma vez ao abrir),
        sem o usuário clicar em nada — sincrono, ele travaria a janela do
        nada, no meio de qualquer outra coisa que a secretária estivesse
        fazendo, o que seria ainda mais confuso que um travamento esperado
        depois de um clique."""
        hoje = self.obter_hoje()

        def _trabalho(repositorio):
            return agendador.rodar_ciclo(repositorio, self.pasta_base, hoje=hoje)

        self._thread_ciclo_automatico = widgets.executar_com_nova_conexao(
            self, self.repositorio.caminho_db, _trabalho,
            self._ao_ciclo_automatico_sucesso, self._ao_ciclo_automatico_erro,
        )

    def _ao_ciclo_automatico_sucesso(self, resultado: agendador.ResultadoCiclo) -> None:
        if resultado.houve_atraso:
            self.notificar("Mensalidades atrasadas", mensagens.mensagem_catchup(resultado.emitidas_atrasadas))
        else:
            texto = mensagens.mensagem_ciclo_automatico(resultado.total_emitidas, resultado.total_rejeitadas)
            if texto:
                self.notificar("Emissor NFS-e", texto)

        if self.pilha.currentWidget() is self._pagina_principal and self.abas.currentWidget() is self.tela_meu_dia:
            self.tela_meu_dia.atualizar()

    def _ao_ciclo_automatico_erro(self, exc: BaseException) -> None:
        # Ciclo automatico: nunca interrompe o usuario com uma caixa de erro
        # pra algo que ele nem sabia que estava rodando -- so' log silencioso
        # (mesmo espirito de "falha de e-mail nunca derruba a emissao").
        pass

    # ------------------------------------------------------------------
    def _carregar_prestadores(self, *, selecionar_primeiro: bool = False) -> None:
        mostrar_inativos = self.marca_mostrar_prestadores_inativos.isChecked()
        prestadores = self.repositorio.listar_prestadores(apenas_ativos=not mostrar_inativos)
        self._prestadores = prestadores
        if not prestadores:
            self.pilha.setCurrentWidget(self._pagina_onboarding)
            return

        self.pilha.setCurrentWidget(self._pagina_principal)
        self.combo_prestador.blockSignals(True)
        self.combo_prestador.clear()
        for p in prestadores:
            rotulo = p["nome_exibicao"] if p.get("ativo", 1) else f'{p["nome_exibicao"]} (inativo)'
            self.combo_prestador.addItem(_icone_circulo(p.get("cor")), rotulo, p["id"])
        self.combo_prestador.blockSignals(False)

        if selecionar_primeiro and self.combo_prestador.count() > 0:
            self.combo_prestador.setCurrentIndex(0)
        self._ao_trocar_prestador(self.combo_prestador.currentIndex())
        self.tela_meu_dia.atualizar()

    def _ao_trocar_prestador(self, indice: int) -> None:
        self.prestador_ativo_id = self.combo_prestador.itemData(indice) if indice >= 0 else None
        prestador = next((p for p in getattr(self, "_prestadores", []) if p["id"] == self.prestador_ativo_id), None)
        ativo = bool(prestador.get("ativo", 1)) if prestador else True
        self.botao_editar_prestador.setEnabled(self.prestador_ativo_id is not None and ativo)
        self.botao_excluir_prestador.setEnabled(self.prestador_ativo_id is not None and ativo)
        self.botao_reativar_prestador.setVisible(self.prestador_ativo_id is not None and not ativo)
        self.botao_reativar_prestador.setEnabled(self.prestador_ativo_id is not None and not ativo)
        for tela in self._telas_escopadas_por_prestador:
            tela.definir_prestador(self.prestador_ativo_id)

    def _ao_trocar_aba(self, indice: int) -> None:
        if self.abas.widget(indice) is self.tela_meu_dia:
            self.tela_meu_dia.atualizar()

    def _abrir_dialogo_novo_prestador(self) -> None:
        dialogo = QDialog(self)
        dialogo.setWindowTitle("Novo prestador")
        dialogo.resize(760, 760)
        layout = QVBoxLayout(dialogo)
        tela = TelaCadastroPrestador(self.repositorio)
        tela.prestador_criado.connect(lambda _id: self._ao_prestador_adicionado(dialogo))
        layout.addWidget(tela)
        dialogo.exec()

    def _ao_prestador_adicionado(self, dialogo: QDialog) -> None:
        self._carregar_prestadores()
        dialogo.accept()

    def _ao_criar_primeiro_prestador(self, _prestador_id: int) -> None:
        self._carregar_prestadores(selecionar_primeiro=True)

    # ------------------------------------------------------------------
    # editar / excluir prestador ativo
    # ------------------------------------------------------------------

    def _abrir_dialogo_editar_prestador(self) -> None:
        if self.prestador_ativo_id is None:
            return
        prestador = self.repositorio.obter_prestador(self.prestador_ativo_id)
        if prestador is None:
            return

        dialogo = QDialog(self)
        dialogo.setWindowTitle("Editar prestador")
        dialogo.resize(480, 420)
        layout = QVBoxLayout(dialogo)
        formulario = QFormLayout()

        campo_nome = QLineEdit(prestador["nome_exibicao"])
        formulario.addRow("Nome de exibição:", campo_nome)

        campo_im = QLineEdit(prestador["im"])
        campo_im.setMaxLength(15)  # TSInscMun, tiposSimples_v1.01.xsd
        formulario.addRow("Inscrição municipal:", campo_im)

        campo_municipio = QLineEdit(prestador["codigo_municipio"])
        formulario.addRow("Município (código IBGE):", campo_municipio)

        combo_regime = QComboBox()
        for rotulo, _codigo in _OPCOES_REGIME:
            combo_regime.addItem(rotulo)
        indice_regime = next(
            (i for i, (_r, codigo) in enumerate(_OPCOES_REGIME) if codigo == prestador.get("regime")), 0
        )
        combo_regime.setCurrentIndex(indice_regime)
        formulario.addRow("Regime (Simples Nacional):", combo_regime)
        aviso_regime = widgets.subtitulo(
            "Se for optante (MEI ou ME/EPP), o ISS já vai embutido no DAS mensal — o campo de "
            "alíquota nos serviços deste prestador fica travado automaticamente."
        )
        aviso_regime.setWordWrap(True)
        formulario.addRow("", aviso_regime)

        combo_regime_especial = QComboBox()
        for rotulo, _codigo in _OPCOES_REGIME_ESPECIAL:
            combo_regime_especial.addItem(rotulo)
        indice_regime_especial = next(
            (i for i, (_r, codigo) in enumerate(_OPCOES_REGIME_ESPECIAL)
             if codigo == prestador.get("regime_especial_tributacao")), 0
        )
        combo_regime_especial.setCurrentIndex(indice_regime_especial)
        formulario.addRow("Regime especial de tributação:", combo_regime_especial)

        cor_escolhida = {"valor": prestador.get("cor") or tema.CORES_PRESTADOR_SUGERIDAS[0]}
        linha_cor = QHBoxLayout()
        ponto_cor = widgets.PontoCor(cor_escolhida["valor"], diametro=22)
        botao_cor = QPushButton("Escolher cor…")

        def _escolher_cor() -> None:
            cor = QColorDialog.getColor(parent=dialogo)
            if cor.isValid():
                cor_escolhida["valor"] = cor.name()
                ponto_cor.definir_cor(cor_escolhida["valor"])

        botao_cor.clicked.connect(_escolher_cor)
        linha_cor.addWidget(ponto_cor)
        linha_cor.addWidget(botao_cor)
        linha_cor.addStretch(1)
        formulario.addRow("Cor deste prestador:", linha_cor)

        # Resposta direta pra "onde fica meu certificado?" (docs/auditoria.md,
        # Bloco 7 item 4) -- o arquivo nunca e' copiado, fica exatamente onde
        # foi escolhido no cadastro; este botao abre essa pasta de verdade.
        def _abrir_pasta_certificado() -> None:
            caminho_pfx = prestador.get("caminho_pfx")
            if not caminho_pfx:
                widgets.mostrar_erro(dialogo, "Este prestador não tem certificado cadastrado.")
                return
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(caminho_pfx).parent)))

        botao_abrir_pasta_cert = widgets.botao_secundario("Abrir pasta do certificado")
        botao_abrir_pasta_cert.clicked.connect(_abrir_pasta_certificado)
        formulario.addRow("Certificado A1:", botao_abrir_pasta_cert)

        layout.addLayout(formulario)

        linha_botoes = QHBoxLayout()
        botao_cancelar = widgets.botao_secundario("Cancelar")
        botao_cancelar.clicked.connect(dialogo.reject)
        botao_salvar = QPushButton("Salvar alterações")
        linha_botoes.addStretch(1)
        linha_botoes.addWidget(botao_cancelar)
        linha_botoes.addWidget(botao_salvar)
        layout.addLayout(linha_botoes)

        def _salvar() -> None:
            nome = campo_nome.text().strip()
            im = campo_im.text().strip()
            municipio = campo_municipio.text().strip()
            if not nome:
                widgets.mostrar_erro(dialogo, "Digite um nome de exibição para este prestador.")
                return
            if not im:
                widgets.mostrar_erro(dialogo, "Digite a inscrição municipal.")
                return
            if len(im) > 15:
                widgets.mostrar_erro(dialogo, "A inscrição municipal tem no máximo 15 caracteres (padrão do leiaute nacional).")
                return
            if not municipio.isdigit() or len(municipio) != 7:
                widgets.mostrar_erro(dialogo, "O código do município (IBGE) precisa ter 7 números.")
                return
            try:
                pasta_nome = None
                if nome != prestador["nome_exibicao"]:
                    # Renomeia a pasta fisica de verdade -- docs/auditoria.md,
                    # Bloco 4.2: antes, so' o nome_exibicao mudava e a pasta
                    # ficava orfa/duplicada.
                    pasta_nome = pastas.renomear_pasta_prestador(self.pasta_base, prestador, nome)
                self.repositorio.atualizar_prestador(
                    self.prestador_ativo_id,
                    nome_exibicao=nome, im=im, codigo_municipio=municipio,
                    regime=_OPCOES_REGIME[combo_regime.currentIndex()][1],
                    regime_especial_tributacao=_OPCOES_REGIME_ESPECIAL[combo_regime_especial.currentIndex()][1],
                    cor=cor_escolhida["valor"],
                    pasta_nome=pasta_nome,
                )
            except Exception as exc:  # noqa: BLE001
                widgets.mostrar_erro(dialogo, exc, "Não deu pra salvar")
                return
            self._carregar_prestadores()
            dialogo.accept()

        botao_salvar.clicked.connect(_salvar)
        dialogo.exec()

    def _excluir_prestador_ativo(self) -> None:
        if self.prestador_ativo_id is None:
            return
        prestador = self.repositorio.obter_prestador(self.prestador_ativo_id)
        nome = prestador["nome_exibicao"] if prestador else ""
        if not widgets.confirmar(
            self, f'Excluir o prestador "{nome}"? Essa ação não pode ser desfeita.'
        ):
            return
        try:
            self.repositorio.excluir_prestador(self.prestador_ativo_id)
        except ValueError as exc:
            # Tem nota emitida -- exclusao definitiva bloqueada de proposito
            # (docs/auditoria.md, Bloco 4.1). Oferece inativar em vez de so'
            # mostrar o erro e travar o usuario.
            if widgets.confirmar(
                self,
                f"{exc}\n\nDeseja inativar este prestador em vez de excluir? "
                "Ele some da lista ativa, mas o histórico de notas e os arquivos continuam intactos, "
                "e dá pra reativar depois (marque \"Mostrar inativos\").",
                "Inativar em vez de excluir?",
            ):
                self.repositorio.inativar_prestador(self.prestador_ativo_id)
            else:
                return
        except Exception as exc:  # noqa: BLE001
            widgets.mostrar_erro(self, exc, "Não deu pra excluir")
            return
        self._carregar_prestadores(selecionar_primeiro=True)

    def _reativar_prestador_ativo(self) -> None:
        if self.prestador_ativo_id is None:
            return
        self.repositorio.reativar_prestador(self.prestador_ativo_id)
        self._carregar_prestadores()
