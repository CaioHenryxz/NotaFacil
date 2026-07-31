"""Tema visual do app: fonte generosa, contraste alto, zero jargao —
publico e a secretaria (espec-mvp-emissor-nfse.md, publico principal), nao
um desenvolvedor. Nada de terceira dependencia de estilo: so QSS puro.
"""
from __future__ import annotations

from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import QApplication

FONTE_FAMILIA = "Segoe UI"
FONTE_TAMANHO_BASE = 13
FONTE_TAMANHO_TITULO = 20
FONTE_TAMANHO_GRANDE = 16

COR_FUNDO = "#F5F6F8"
COR_CARTAO = "#FFFFFF"
COR_TEXTO = "#1F2430"
COR_TEXTO_SECUNDARIO = "#5B6270"
COR_BORDA = "#E1E4E9"
COR_PRIMARIA = "#2F6FED"
COR_PRIMARIA_HOVER = "#255ACB"
COR_SUCESSO = "#1E8E5A"
COR_ALERTA = "#C77C11"
COR_ERRO = "#C43D3D"

CORES_STATUS = {
    "pendente": "#C77C11",
    "emitida": "#1E8E5A",
    "rejeitada": "#C43D3D",
    "cancelada": "#8A8F98",
}

RUBRICAS_STATUS = {
    "pendente": "Pendente",
    "emitida": "Emitida",
    "rejeitada": "Rejeitada",
    "cancelada": "Cancelada",
}

CORES_PRESTADOR_SUGERIDAS = [
    "#2F6FED", "#1E8E5A", "#C77C11", "#C43D3D",
    "#8A4FD1", "#0F9AA8", "#D1497A", "#4C5B6B",
]

_QSS = f"""
QWidget {{
    background-color: {COR_FUNDO};
    color: {COR_TEXTO};
    font-family: "{FONTE_FAMILIA}";
    font-size: {FONTE_TAMANHO_BASE}pt;
}}
QMainWindow {{
    background-color: {COR_FUNDO};
}}
QLabel#titulo {{
    font-size: {FONTE_TAMANHO_TITULO}pt;
    font-weight: 600;
}}
QLabel#subtitulo {{
    font-size: {FONTE_TAMANHO_GRANDE}pt;
    color: {COR_TEXTO_SECUNDARIO};
}}
QFrame#cartao {{
    background-color: {COR_CARTAO};
    border: 1px solid {COR_BORDA};
    border-radius: 10px;
}}
QPushButton {{
    background-color: {COR_PRIMARIA};
    color: white;
    border: none;
    border-radius: 6px;
    padding: 10px 18px;
    font-size: {FONTE_TAMANHO_BASE}pt;
    font-weight: 600;
}}
QPushButton:hover {{
    background-color: {COR_PRIMARIA_HOVER};
}}
QPushButton:disabled {{
    background-color: #B7C2D6;
    color: #EEF1F6;
}}
QPushButton#secundario {{
    background-color: transparent;
    color: {COR_PRIMARIA};
    border: 1px solid {COR_PRIMARIA};
}}
QPushButton#secundario:hover {{
    background-color: #E8F0FE;
}}
QPushButton#perigo {{
    background-color: {COR_ERRO};
}}
QPushButton#perigo:hover {{
    background-color: #A83232;
}}
QPushButton#perigo:disabled, QPushButton#secundario:disabled {{
    background-color: #B7C2D6;
    color: #EEF1F6;
    border: none;
}}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit {{
    background-color: white;
    border: 1px solid {COR_BORDA};
    border-radius: 6px;
    padding: 8px;
    min-height: 22px;
}}
QLineEdit:focus, QComboBox:focus {{
    border: 1px solid {COR_PRIMARIA};
}}
QTableWidget {{
    background-color: white;
    border: 1px solid {COR_BORDA};
    border-radius: 6px;
    gridline-color: {COR_BORDA};
}}
QHeaderView::section {{
    background-color: {COR_FUNDO};
    padding: 8px;
    border: none;
    border-bottom: 1px solid {COR_BORDA};
    font-weight: 600;
}}
QTabWidget::pane {{
    border: none;
}}
QTabBar::tab {{
    background: transparent;
    padding: 10px 16px;
    font-size: {FONTE_TAMANHO_BASE}pt;
    color: {COR_TEXTO_SECUNDARIO};
}}
QTabBar::tab:selected {{
    color: {COR_PRIMARIA};
    font-weight: 600;
    border-bottom: 3px solid {COR_PRIMARIA};
}}
"""


def aplicar_tema(app: QApplication) -> None:
    fonte = QFont(FONTE_FAMILIA, FONTE_TAMANHO_BASE)
    app.setFont(fonte)
    app.setStyleSheet(_QSS)


def cor_status(status: str) -> str:
    return CORES_STATUS.get(status, COR_TEXTO_SECUNDARIO)


def rotulo_status(status: str) -> str:
    return RUBRICAS_STATUS.get(status, status.capitalize())


def cor_contraste(hex_cor: str) -> str:
    """Preto ou branco — o que ler melhor em cima da cor de fundo dada."""
    cor = QColor(hex_cor)
    luminancia = (0.299 * cor.red() + 0.587 * cor.green() + 0.114 * cor.blue())
    return "#1F2430" if luminancia > 150 else "#FFFFFF"
