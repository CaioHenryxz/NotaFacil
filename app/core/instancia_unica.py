"""Trava de instancia unica (docs/auditoria.md, Bloco 6.5/10): o recurso de
"minimizar pra bandeja ao fechar" incentiva exatamente o cenario perigoso de
abrir uma segunda instancia por engano (usuario fecha a janela achando que
saiu, depois clica de novo no icone) -- duas instancias escrevendo no mesmo
SQLite ao mesmo tempo podiam gerar `sqlite3.OperationalError: database is
locked` (ja traduzido em app.core.mensagens, mas o ideal e' nem deixar
acontecer).

Usa `msvcrt.locking` (stdlib, so' Windows -- mesma suposicao de plataforma ja
feita em `app.fiscal.assinador` via keyring/DPAPI): um lock advisory sobre um
arquivo, liberado automaticamente pelo Windows mesmo se o processo morrer sem
chamar `liberar()` (crash, kill via Gerenciador de Tarefas etc.) -- nao fica
"travado pra sempre" por um processo que nao existe mais.
"""
from __future__ import annotations

import msvcrt
from pathlib import Path
from typing import Optional, Union


class InstanciaUnica:
    def __init__(self, caminho_lock: Union[str, Path]):
        self.caminho_lock = Path(caminho_lock)
        self._arquivo: Optional[object] = None

    def obter(self) -> bool:
        """Tenta travar. Devolve True se conseguiu (nenhuma outra instancia
        rodando), False se outra instancia ja segura a trava."""
        self.caminho_lock.parent.mkdir(parents=True, exist_ok=True)
        self._arquivo = open(self.caminho_lock, "a+")
        try:
            msvcrt.locking(self._arquivo.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            self._arquivo.close()
            self._arquivo = None
            return False
        return True

    def liberar(self) -> None:
        if self._arquivo is None:
            return
        try:
            self._arquivo.seek(0)
            msvcrt.locking(self._arquivo.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
        finally:
            self._arquivo.close()
            self._arquivo = None
