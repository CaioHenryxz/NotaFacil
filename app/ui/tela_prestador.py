"""Tela 1 — Cadastro de prestador (espec-mvp-emissor-nfse.md, secao 2 item 1).

Fluxo: importar o .pfx -> ler o certificado (extrai CNPJ/CPF de dentro dele)
-> se for CNPJ, completa razao social/endereco pela BrasilAPI -> confirma IM,
regime e municipio -> escolhe nome de exibicao e cor -> testa a conexao em
homologacao -> salva.

So fala com o backend via app.repo e app.core (nunca com sqlite3/keyring/
httpx diretamente) — regra da Etapa 2.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QColorDialog, QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QLineEdit,
    QPushButton, QVBoxLayout, QWidget,
)

from app import repo
from app.core import brasilapi, documentos, onboarding
from app.fiscal import assinador
from app.ui import tema, widgets

_OPCOES_REGIME = [
    ("Não optante pelo Simples Nacional", "1"),
    ("Optante — MEI", "2"),
    ("Optante — ME ou EPP (Simples Nacional)", "3"),
]

_OPCOES_REGIME_ESPECIAL = [
    ("Nenhum", "0"),
    ("Cooperativa", "1"),
    ("Estimativa", "2"),
    ("Microempresa Municipal", "3"),
    ("Notário ou Registrador", "4"),
    ("Profissional Autônomo", "5"),
    ("Sociedade de Profissionais", "6"),
]


class TelaCadastroPrestador(QWidget):
    prestador_criado = Signal(int)

    def __init__(self, repositorio: repo.Repositorio, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.repositorio = repositorio
        self._senha_certificado: Optional[str] = None
        self._caminho_pfx: Optional[str] = None
        self._cor_escolhida = tema.CORES_PRESTADOR_SUGERIDAS[0]
        self._municipio_ibge: Optional[str] = None

        self._montar_layout()

    # ------------------------------------------------------------------
    def _montar_layout(self) -> None:
        raiz = QVBoxLayout(self)
        raiz.addWidget(widgets.titulo("Cadastrar prestador"))
        raiz.addWidget(widgets.subtitulo(
            "Cada prestador (médico, oficina, sócio) tem seu próprio certificado e sua própria pasta."
        ))

        cartao_cert = widgets.Cartao()
        layout_cert = QVBoxLayout(cartao_cert)
        layout_cert.addWidget(widgets.subtitulo("1. Certificado digital A1 (.pfx)"))

        linha_arquivo = QHBoxLayout()
        self.campo_arquivo = QLineEdit()
        self.campo_arquivo.setReadOnly(True)
        self.campo_arquivo.setPlaceholderText("Nenhum arquivo selecionado")
        botao_escolher = QPushButton("Escolher arquivo .pfx…")
        botao_escolher.clicked.connect(self._escolher_arquivo)
        linha_arquivo.addWidget(self.campo_arquivo, stretch=1)
        linha_arquivo.addWidget(botao_escolher)
        layout_cert.addLayout(linha_arquivo)

        linha_senha = QHBoxLayout()
        self.campo_senha = QLineEdit()
        self.campo_senha.setEchoMode(QLineEdit.EchoMode.Password)
        self.campo_senha.setPlaceholderText("Senha do certificado")
        botao_ler = QPushButton("Ler certificado")
        botao_ler.clicked.connect(self._ler_certificado)
        linha_senha.addWidget(self.campo_senha, stretch=1)
        linha_senha.addWidget(botao_ler)
        layout_cert.addLayout(linha_senha)

        self.rotulo_certificado = widgets.subtitulo("")
        self.rotulo_certificado.setWordWrap(True)
        layout_cert.addWidget(self.rotulo_certificado)

        # Resposta direta pra "onde fica meu certificado?" (docs/auditoria.md,
        # Bloco 7 item 4): o programa nunca copia o arquivo pra lugar
        # nenhum -- ele fica exatamente onde foi escolhido acima (mostrado no
        # campo "Arquivo"), e so' esse computador enxerga o arquivo/senha.
        aviso_privacidade = widgets.subtitulo(
            "🔒 O arquivo do certificado fica só neste computador, exatamente onde você escolheu "
            "acima (veja o campo \"Arquivo\"). O programa não copia, não sobe pra nuvem e não envia "
            "pra nenhum servidor — nem a Receita nem nós vemos o arquivo ou a senha."
        )
        aviso_privacidade.setWordWrap(True)
        layout_cert.addWidget(aviso_privacidade)
        raiz.addWidget(cartao_cert)

        cartao_dados = widgets.Cartao()
        formulario = QFormLayout(cartao_dados)

        linha_doc = QHBoxLayout()
        self.campo_documento = QLineEdit()
        self.campo_documento.setPlaceholderText("CNPJ ou CPF, só números")
        self.botao_buscar_cnpj = QPushButton("Buscar dados (CNPJ)")
        self.botao_buscar_cnpj.clicked.connect(self._buscar_dados_cnpj)
        linha_doc.addWidget(self.campo_documento, stretch=1)
        linha_doc.addWidget(self.botao_buscar_cnpj)
        formulario.addRow("CNPJ/CPF do prestador:", linha_doc)

        self.campo_nome_exibicao = QLineEdit()
        self.campo_nome_exibicao.setPlaceholderText('Ex.: "Dr. João Cardoso"')
        formulario.addRow("Nome de exibição:", self.campo_nome_exibicao)

        self.campo_im = QLineEdit()
        self.campo_im.setPlaceholderText("Inscrição municipal")
        self.campo_im.setMaxLength(15)  # TSInscMun, tiposSimples_v1.01.xsd
        formulario.addRow("Inscrição municipal:", self.campo_im)

        self.campo_municipio = QLineEdit()
        self.campo_municipio.setPlaceholderText("Código IBGE do município (7 dígitos)")
        formulario.addRow("Município (código IBGE):", self.campo_municipio)

        self.combo_regime = QComboBox()
        for rotulo, _codigo in _OPCOES_REGIME:
            self.combo_regime.addItem(rotulo)
        self.combo_regime.setCurrentIndex(2)
        formulario.addRow("Regime (Simples Nacional):", self.combo_regime)
        aviso_regime = widgets.subtitulo(
            "Se for optante (MEI ou ME/EPP), o ISS já vai embutido no DAS mensal — o campo de "
            "alíquota nos serviços deste prestador fica travado automaticamente."
        )
        aviso_regime.setWordWrap(True)
        formulario.addRow("", aviso_regime)

        self.combo_regime_especial = QComboBox()
        for rotulo, _codigo in _OPCOES_REGIME_ESPECIAL:
            self.combo_regime_especial.addItem(rotulo)
        formulario.addRow("Regime especial de tributação:", self.combo_regime_especial)

        linha_cor = QHBoxLayout()
        self.ponto_cor = widgets.PontoCor(self._cor_escolhida, diametro=22)
        botao_cor = QPushButton("Escolher cor…")
        botao_cor.clicked.connect(self._escolher_cor)
        linha_cor.addWidget(self.ponto_cor)
        linha_cor.addWidget(botao_cor)
        linha_cor.addStretch(1)
        formulario.addRow("Cor deste prestador:", linha_cor)

        raiz.addWidget(cartao_dados)

        linha_botoes = QHBoxLayout()
        self.botao_testar = QPushButton("Testar conexão (homologação)")
        self.botao_testar.clicked.connect(self._testar_conexao)
        self.botao_salvar = QPushButton("Salvar prestador")
        self.botao_salvar.clicked.connect(self._salvar)
        linha_botoes.addWidget(self.botao_testar)
        linha_botoes.addStretch(1)
        linha_botoes.addWidget(self.botao_salvar)
        raiz.addLayout(linha_botoes)
        raiz.addStretch(1)

    # ------------------------------------------------------------------
    def _escolher_arquivo(self) -> None:
        caminho, _filtro = QFileDialog.getOpenFileName(
            self, "Escolher certificado A1", "", "Certificado (*.pfx *.p12)"
        )
        if caminho:
            self._caminho_pfx = caminho
            self.campo_arquivo.setText(caminho)

    def _ler_certificado(self) -> None:
        if not self._caminho_pfx:
            widgets.mostrar_erro(self, "Escolha o arquivo .pfx primeiro.")
            return
        senha = self.campo_senha.text()
        if not senha:
            widgets.mostrar_erro(self, "Digite a senha do certificado.")
            return
        try:
            info = onboarding.ler_certificado(self._caminho_pfx, senha)
        except Exception as exc:  # noqa: BLE001 — traduzido pra mensagem clara
            widgets.mostrar_erro(self, exc, "Certificado não pôde ser lido")
            return

        self._senha_certificado = senha
        if info.documento:
            self.campo_documento.setText(info.documento)
        if not self.campo_nome_exibicao.text() and info.nome_titular:
            self.campo_nome_exibicao.setText(info.nome_titular.split(":")[0])
        self.rotulo_certificado.setText(
            f"Certificado lido: {info.nome_titular or '(sem nome)'} — válido até {info.valido_ate}."
        )

    def _buscar_dados_cnpj(self) -> None:
        doc = brasilapi.somente_digitos(self.campo_documento.text())
        if len(doc) != 14:
            widgets.mostrar_erro(
                self,
                "A busca automática só funciona para CNPJ (14 números). "
                "Para CPF, preencha os campos manualmente.",
            )
            return
        # Roda numa thread separada -- docs/auditoria.md, Bloco 3/7.2: antes
        # disso, BrasilAPI fora do ar/lenta travava a janela inteira.
        self.botao_buscar_cnpj.setEnabled(False)
        self.botao_buscar_cnpj.setText("Buscando…")
        self._thread_busca_cnpj = widgets.executar_em_segundo_plano(
            self, lambda: onboarding.buscar_dados_por_cnpj(doc),
            self._ao_buscar_cnpj_sucesso, self._ao_buscar_cnpj_erro,
        )

    def _ao_buscar_cnpj_sucesso(self, dados) -> None:
        self.botao_buscar_cnpj.setEnabled(True)
        self.botao_buscar_cnpj.setText("Buscar dados (CNPJ)")
        if not self.campo_nome_exibicao.text():
            self.campo_nome_exibicao.setText(dados.nome_fantasia or dados.razao_social)
        self._municipio_ibge = dados.codigo_municipio_ibge
        self.campo_municipio.setText(dados.codigo_municipio_ibge)
        widgets.mostrar_info(
            self,
            f"{dados.razao_social}\n{dados.endereco_formatado}\nSituação: {dados.situacao_cadastral}",
            "Dados encontrados",
        )

    def _ao_buscar_cnpj_erro(self, exc: BaseException) -> None:
        self.botao_buscar_cnpj.setEnabled(True)
        self.botao_buscar_cnpj.setText("Buscar dados (CNPJ)")
        widgets.mostrar_erro(self, exc, "Não encontrei esse CNPJ")

    def _escolher_cor(self) -> None:
        cor = QColorDialog.getColor(parent=self)
        if cor.isValid():
            self._cor_escolhida = cor.name()
            self.ponto_cor.definir_cor(self._cor_escolhida)

    def _regime_selecionado(self) -> str:
        return _OPCOES_REGIME[self.combo_regime.currentIndex()][1]

    def _regime_especial_selecionado(self) -> str:
        return _OPCOES_REGIME_ESPECIAL[self.combo_regime_especial.currentIndex()][1]

    def _testar_conexao(self) -> None:
        if not (self._caminho_pfx and self._senha_certificado):
            widgets.mostrar_erro(self, "Leia o certificado primeiro (passo 1).")
            return
        self.botao_testar.setEnabled(False)
        self.botao_testar.setText("Testando…")
        # Roda numa thread separada -- docs/auditoria.md, Bloco 7 item 2 (um
        # dos 3 pontos de travamento confirmados na auditoria).
        self._thread_testar = widgets.executar_em_segundo_plano(
            self,
            lambda: onboarding.testar_conexao(self._caminho_pfx, self._senha_certificado, ambiente="homologacao"),
            self._ao_testar_sucesso, self._ao_testar_erro,
        )

    def _ao_testar_sucesso(self, _resultado) -> None:
        self.botao_testar.setEnabled(True)
        self.botao_testar.setText("Testar conexão (homologação)")
        widgets.mostrar_info(
            self,
            "O certificado foi aceito pelo sistema da Receita (ambiente de testes). Pode salvar o prestador.",
            "Conexão OK",
        )

    def _ao_testar_erro(self, exc: BaseException) -> None:
        self.botao_testar.setEnabled(True)
        self.botao_testar.setText("Testar conexão (homologação)")
        widgets.mostrar_erro(self, exc, "Conexão falhou")

    def _validar_campos(self) -> Optional[str]:
        if not self._caminho_pfx or not self._senha_certificado:
            return "Leia o certificado (passo 1) antes de salvar."
        try:
            documentos.exigir_documento_valido(self.campo_documento.text())
        except documentos.DocumentoInvalido as exc:
            return str(exc)
        if not self.campo_nome_exibicao.text().strip():
            return "Digite um nome de exibição para este prestador."
        im = self.campo_im.text().strip()
        if not im:
            return "Digite a inscrição municipal."
        # TSInscMun (tiposSimples_v1.01.xsd): string livre de 1 a 15
        # caracteres -- o leiaute NACIONAL nao padroniza mais que isso de
        # proposito, porque cada prefeitura define seu proprio formato de
        # IM (docs/auditoria.md, Bloco 2.5: nao ha base solida pra travar
        # um formato mais especifico, ex. "so numeros"/"6 digitos", sem
        # confirmar cidade a cidade). O unico limite que da pra confirmar
        # contra o XSD oficial e' o de tamanho.
        if len(im) > 15:
            return "A inscrição municipal tem no máximo 15 caracteres (padrão do leiaute nacional)."
        if not self.campo_municipio.text().strip().isdigit() or len(self.campo_municipio.text().strip()) != 7:
            return "O código do município (IBGE) precisa ter 7 números."
        return None

    def _salvar(self) -> None:
        erro = self._validar_campos()
        if erro:
            widgets.mostrar_erro(self, erro)
            return

        doc = documentos.exigir_documento_valido(self.campo_documento.text())
        try:
            prestador_id = self.repositorio.criar_prestador(
                nome_exibicao=self.campo_nome_exibicao.text().strip(),
                cnpj=doc,
                im=self.campo_im.text().strip(),
                codigo_municipio=self.campo_municipio.text().strip(),
                regime=self._regime_selecionado(),
                regime_especial_tributacao=self._regime_especial_selecionado(),
                caminho_pfx=self._caminho_pfx,
                cor=self._cor_escolhida,
            )
            assinador.salvar_senha(prestador_id, self._senha_certificado)
        except Exception as exc:  # noqa: BLE001
            widgets.mostrar_erro(self, exc, "Não deu pra salvar")
            return

        widgets.mostrar_info(self, f"Prestador \"{self.campo_nome_exibicao.text()}\" cadastrado com sucesso!")
        self.prestador_criado.emit(prestador_id)
        self._limpar()

    def _limpar(self) -> None:
        self._caminho_pfx = None
        self._senha_certificado = None
        self.campo_arquivo.clear()
        self.campo_senha.clear()
        self.campo_documento.clear()
        self.campo_nome_exibicao.clear()
        self.campo_im.clear()
        self.campo_municipio.clear()
        self.rotulo_certificado.setText("")
        self.combo_regime.setCurrentIndex(2)
        self.combo_regime_especial.setCurrentIndex(0)
