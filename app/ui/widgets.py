"""Widgets pequenos reaproveitados por varias telas — nada daqui acessa
banco/API, so apresentacao."""
from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal
from typing import Callable, Optional

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QCheckBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

from app.core import pastas
from app.ui import tema

# Retencoes na fonte (docs/auditoria.md, Bloco 1.6/2.4) -- mesma lista usada
# no protototipo web (prototype/src/App.jsx, RETENCOES_TRIBUTOS), linguagem
# leiga, sem nome de campo do XML.
_RETENCOES_TRIBUTOS = [
    ("retem_irrf", "aliquota_irrf", "IRRF (Imposto de Renda)"),
    ("retem_pis", "aliquota_pis", "PIS"),
    ("retem_cofins", "aliquota_cofins", "COFINS"),
    ("retem_csll", "aliquota_csll", "CSLL"),
    ("retem_inss", "aliquota_inss", "INSS / contribuição previdenciária"),
]


class Cartao(QFrame):
    """Painel branco arredondado — a unidade visual basica das telas."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("cartao")
        self.setFrameShape(QFrame.Shape.NoFrame)


class PontoCor(QWidget):
    """Bolinha colorida (cor do prestador) — usada no seletor do topo e em
    qualquer lista que precise indicar de qual prestador a linha e."""

    def __init__(self, cor_hex: str = "#8A8F98", diametro: int = 14, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._cor = QColor(cor_hex)
        self._diametro = diametro
        self.setFixedSize(diametro, diametro)

    def definir_cor(self, cor_hex: str) -> None:
        self._cor = QColor(cor_hex)
        self.update()

    def paintEvent(self, evento) -> None:  # noqa: N802 (Qt override)
        pintor = QPainter(self)
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
        pintor.setBrush(self._cor)
        pintor.setPen(Qt.PenStyle.NoPen)
        pintor.drawEllipse(0, 0, self._diametro, self._diametro)


class Selo(QLabel):
    """Etiqueta colorida de status (Pendente/Emitida/Rejeitada/Cancelada)."""

    def __init__(self, status: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.definir_status(status)

    def definir_status(self, status: str) -> None:
        cor = tema.cor_status(status)
        self.setText(tema.rotulo_status(status))
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet(
            f"background-color: {cor}; color: white; border-radius: 9px; "
            f"padding: 3px 10px; font-weight: 600; font-size: 10pt;"
        )
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)


def titulo(texto: str) -> QLabel:
    rotulo = QLabel(texto)
    rotulo.setObjectName("titulo")
    return rotulo


def subtitulo(texto: str) -> QLabel:
    rotulo = QLabel(texto)
    rotulo.setObjectName("subtitulo")
    return rotulo


def linha_horizontal() -> QFrame:
    linha = QFrame()
    linha.setFrameShape(QFrame.Shape.HLine)
    linha.setStyleSheet(f"color: {tema.COR_BORDA};")
    return linha


def botao_secundario(texto: str) -> QPushButton:
    botao = QPushButton(texto)
    botao.setObjectName("secundario")
    return botao


def botao_perigo(texto: str) -> QPushButton:
    botao = QPushButton(texto)
    botao.setObjectName("perigo")
    return botao


def mostrar_erro(pai: QWidget, excecao_ou_texto, titulo_janela: str = "Não deu certo") -> None:
    from app.core import mensagens

    texto = (
        mensagens.traduzir_erro(excecao_ou_texto)
        if isinstance(excecao_ou_texto, BaseException)
        else str(excecao_ou_texto)
    )
    caixa = QMessageBox(pai)
    caixa.setIcon(QMessageBox.Icon.Warning)
    caixa.setWindowTitle(titulo_janela)
    caixa.setText(texto)
    caixa.exec()


def mostrar_info(pai: QWidget, texto: str, titulo_janela: str = "Pronto") -> None:
    caixa = QMessageBox(pai)
    caixa.setIcon(QMessageBox.Icon.Information)
    caixa.setWindowTitle(titulo_janela)
    caixa.setText(texto)
    caixa.exec()


def confirmar(pai: QWidget, texto: str, titulo_janela: str = "Confirmar") -> bool:
    resposta = QMessageBox.question(
        pai, titulo_janela, texto,
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.No,
    )
    return resposta == QMessageBox.StandardButton.Yes


class CampoValorMonetario(QLineEdit):
    """Mascara de valor monetario: o usuario so' digita numeros -- cada
    digito entra como centavo, o campo formata sozinho em "R$ 1.234,56" a
    cada tecla. Elimina de vez a ambiguidade de separador decimal/milhar na
    origem (docs/auditoria.md, Bloco 3, item 1: "use mascara na digitacao
    pra eliminar ambiguidade") em vez de tentar adivinhar depois o que "1.500"
    ou "1.500,00" queriam dizer."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._centavos = 0
        self.textEdited.connect(self._ao_editar)
        self._atualizar_texto()

    def _ao_editar(self, texto: str) -> None:
        digitos = re.sub(r"\D", "", texto)
        self._centavos = int(digitos) if digitos else 0
        self._atualizar_texto()

    def _atualizar_texto(self) -> None:
        self.blockSignals(True)
        self.setText(f"R$ {pastas.formatar_valor_br(Decimal(self._centavos) / 100)}" if self._centavos else "")
        self.blockSignals(False)
        self.setCursorPosition(len(self.text()))

    def valor_decimal(self) -> Decimal:
        return Decimal(self._centavos) / 100

    def valor_normalizado(self) -> str:
        """String pronta pro backend ("1234.56")."""
        return f"{self.valor_decimal():.2f}"

    def definir_valor(self, valor) -> None:
        d = Decimal(str(valor)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        self._centavos = int(d * 100)
        self._atualizar_texto()

    def limpar(self) -> None:
        self._centavos = 0
        self._atualizar_texto()


class _WorkerThread(QThread):
    """Roda uma funcao sem argumentos fora da thread da UI -- ver
    `executar_em_segundo_plano` pra motivo e uso."""

    sucesso = Signal(object)
    erro = Signal(object)

    def __init__(self, funcao: Callable[[], object], parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._funcao = funcao

    def run(self) -> None:  # noqa: N802 (Qt override)
        try:
            resultado = self._funcao()
        except Exception as exc:  # noqa: BLE001 -- repassa pro callback de erro, nao propaga na thread
            self.erro.emit(exc)
        else:
            self.sucesso.emit(resultado)


def executar_em_segundo_plano(
    pai: QWidget, funcao: Callable[[], object],
    ao_suceder: Callable[[object], None], ao_falhar: Callable[[BaseException], None],
) -> QThread:
    """Roda `funcao` (sem argumentos, tipicamente uma chamada de rede) numa
    QThread em vez de bloquear a UI -- docs/auditoria.md, Bloco 3/Bloco 7
    item 2: "BrasilAPI fora do ar" travava a janela inteira porque a busca de
    CNPJ rodava direto na thread principal. Quem chama PRECISA guardar o
    retorno numa referencia do objeto pai (ex.: `self._thread_busca = ...`)
    -- sem isso o Python coleta a thread antes dela terminar."""
    thread = _WorkerThread(funcao, pai)
    thread.sucesso.connect(ao_suceder)
    thread.erro.connect(ao_falhar)
    thread.finished.connect(thread.deleteLater)
    thread.start()
    return thread


def executar_com_nova_conexao(
    pai: QWidget, caminho_db: str, funcao: Callable[["repo.Repositorio"], object],
    ao_suceder: Callable[[object], None], ao_falhar: Callable[[BaseException], None],
) -> QThread:
    """Como `executar_em_segundo_plano`, mas abre uma CONEXAO SQLITE NOVA
    (exclusiva da thread) e fecha no final -- docs/auditoria.md, Bloco 7 item
    2: emitir nota, emitir em lote, testar conexao e reenviar e-mail ainda
    travavam a janela inteira porque rodavam direto na thread principal.

    Por que uma conexao nova, e nao reaproveitar `self.repositorio`: o modulo
    `sqlite3` por padrao proibe usar a MESMA conexao a partir de uma thread
    diferente da que a criou (`check_same_thread`) -- e mesmo se isso fosse
    desligado, a thread principal roda um ciclo automatico da fila a cada 15
    min (ver app/ui/main_window.py) que poderia coincidir bem no instante em
    que esta chamada estivesse gravando algo, arriscando corromper o SQLite
    de verdade. Uma conexao por thread, com o WAL ja ligado (app/repo.py),
    evita isso sem precisar de nenhum lock manual entre threads."""
    from app import repo as _repo

    def _trabalho():
        repositorio = _repo.Repositorio(caminho_db)
        try:
            return funcao(repositorio)
        finally:
            repositorio.fechar()

    return executar_em_segundo_plano(pai, _trabalho, ao_suceder, ao_falhar)


class PainelRetencoes(QWidget):
    """Retenções na fonte (docs/auditoria.md, Bloco 1.6/2.4) — reaproveitado
    no cadastro do tomador (padrão, "a regra costuma ser fixa por convênio")
    e na emissão avulsa (sobrescrever só naquela nota). Linguagem leiga:
    checkbox + percentual, nunca o nome do campo do XML."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._campos: dict[str, tuple[QCheckBox, QLineEdit]] = {}

        for campo_retem, campo_aliquota, rotulo in _RETENCOES_TRIBUTOS:
            linha = QHBoxLayout()
            caixa = QCheckBox(rotulo)
            campo_pct = QLineEdit()
            campo_pct.setPlaceholderText("% na nota")
            campo_pct.setMaximumWidth(90)
            campo_pct.setEnabled(False)
            caixa.toggled.connect(campo_pct.setEnabled)
            linha.addWidget(caixa, stretch=1)
            linha.addWidget(campo_pct)
            layout.addLayout(linha)
            self._campos[campo_retem] = (caixa, campo_pct)

        layout.addWidget(linha_horizontal())
        self.caixa_iss = QCheckBox("ISS (usa a alíquota já cadastrada no serviço, não precisa digitar de novo)")
        layout.addWidget(self.caixa_iss)

    def valores(self) -> dict:
        dados = {"retem_iss": self.caixa_iss.isChecked()}
        for campo_retem, campo_aliquota, _rotulo in _RETENCOES_TRIBUTOS:
            caixa, campo_pct = self._campos[campo_retem]
            dados[campo_retem] = caixa.isChecked()
            dados[campo_aliquota] = campo_pct.text().strip() or None
        return dados

    def definir_valores(self, dados: dict) -> None:
        dados = dados or {}
        for campo_retem, campo_aliquota, _rotulo in _RETENCOES_TRIBUTOS:
            caixa, campo_pct = self._campos[campo_retem]
            caixa.setChecked(bool(dados.get(campo_retem)))
            campo_pct.setText(dados.get(campo_aliquota) or "")
        self.caixa_iss.setChecked(bool(dados.get("retem_iss")))
