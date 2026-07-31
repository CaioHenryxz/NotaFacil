"""Opção "Iniciar com o Windows" (Etapa 3 item 3) via Registro do Windows
(HKEY_CURRENT_USER\\...\\Run) — não precisa admin, não instala serviço.

Ainda sem PyInstaller (isso é Etapa 4), então o comando registrado roda o
interpretador Python do venv atual + main.py. Quando o app virar um .exe
empacotado, só este módulo precisa mudar.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

try:
    import winreg
except ImportError:  # pragma: no cover — so existe no Windows
    winreg = None  # type: ignore[assignment]

_CHAVE_REGISTRO = r"Software\Microsoft\Windows\CurrentVersion\Run"
_NOME_VALOR = "EmissorNFSe"


class IndisponivelNestaPlataforma(Exception):
    """winreg só existe no Windows — a espec é 100% Windows, mas o modulo
    nao derruba a importacao em outro SO (ex.: rodando testes em CI)."""


def _comando_de_inicializacao(caminho_main: Optional[Path] = None) -> str:
    executavel = Path(sys.executable)
    pythonw = executavel.with_name("pythonw.exe")
    interpretador = pythonw if pythonw.exists() else executavel
    caminho_main = caminho_main or Path(__file__).resolve().parent.parent / "main.py"
    return f'"{interpretador}" "{caminho_main}"'


def habilitar(caminho_main: Optional[Path] = None) -> None:
    if winreg is None:
        raise IndisponivelNestaPlataforma("winreg só existe no Windows.")
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _CHAVE_REGISTRO, 0, winreg.KEY_SET_VALUE) as chave:
        winreg.SetValueEx(chave, _NOME_VALOR, 0, winreg.REG_SZ, _comando_de_inicializacao(caminho_main))


def desabilitar() -> None:
    if winreg is None:
        raise IndisponivelNestaPlataforma("winreg só existe no Windows.")
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _CHAVE_REGISTRO, 0, winreg.KEY_SET_VALUE) as chave:
            winreg.DeleteValue(chave, _NOME_VALOR)
    except FileNotFoundError:
        pass


def esta_habilitado() -> bool:
    if winreg is None:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _CHAVE_REGISTRO, 0, winreg.KEY_READ) as chave:
            winreg.QueryValueEx(chave, _NOME_VALOR)
            return True
    except FileNotFoundError:
        return False
