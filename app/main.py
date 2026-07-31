"""Ponto de entrada do Emissor NFS-e (desktop) — interface PySide6 sobre o
backend local (repo.py + app/core + app/fiscal).

Uso (rodar a partir da raiz do projeto):
    python -m app.main
"""
from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, ""):
    # Permite rodar este arquivo diretamente (ex.: "python app/main.py", ou o
    # atalho gravado pelo "Iniciar com o Windows" em core/inicializacao_windows.py)
    # sem depender de o processo ja ter sido iniciado com a raiz do projeto
    # no sys.path — sem isso, "from app import repo" abaixo falharia.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication, QMessageBox

from app import repo
from app.core.instancia_unica import InstanciaUnica
from app.ui import tema
from app.ui.main_window import JanelaPrincipal

PASTA_DADOS_APP = Path.home() / "Documentos" / "Emissor NFS-e"
PASTA_BASE_NOTAS_PADRAO = str(Path.home() / "Documentos" / "Notas Fiscais")


def main() -> None:
    PASTA_DADOS_APP.mkdir(parents=True, exist_ok=True)
    caminho_db = PASTA_DADOS_APP / "emissor.db"

    # Trava de instancia unica (docs/auditoria.md, Bloco 6.5/10) -- ANTES de
    # abrir o SQLite ou qualquer janela: se outra instancia ja estiver
    # rodando (inclusive minimizada na bandeja), avisa e fecha, em vez de
    # arriscar duas instancias escrevendo no mesmo banco ao mesmo tempo.
    trava = InstanciaUnica(PASTA_DADOS_APP / "instancia.lock")
    if not trava.obter():
        app_aviso = QApplication.instance() or QApplication(sys.argv)
        QMessageBox.warning(
            None, "Emissor NFS-e já está aberto",
            "O Emissor NFS-e já está rodando (talvez minimizado na bandeja do sistema, "
            "perto do relógio). Feche a instância atual antes de abrir outra.",
        )
        sys.exit(1)

    app = QApplication(sys.argv)
    app.setApplicationName("Emissor NFS-e")
    tema.aplicar_tema(app)

    repositorio = repo.Repositorio(caminho_db)
    janela = JanelaPrincipal(repositorio, PASTA_BASE_NOTAS_PADRAO)
    janela.show()

    codigo_saida = app.exec()
    repositorio.fechar()
    trava.liberar()
    sys.exit(codigo_saida)


if __name__ == "__main__":
    main()
