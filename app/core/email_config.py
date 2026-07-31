"""Guarda as configuracoes de e-mail SMTP do usuario (espec-mvp, secao 2 item 8:
"por enquanto so guardar; o envio automatico e a Etapa 3"). Host/porta/usuario
ficam no `config` do banco (repo.py); a senha vai pro keyring, mesma logica
de protecao usada pro certificado A1 — nunca em texto no banco.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import keyring

from app import repo

SERVICO_KEYRING = "emissor-nfse"
USUARIO_KEYRING_SMTP = "smtp"


@dataclass
class ConfigSmtp:
    host: str = ""
    porta: int = 587
    usuario: str = ""
    senha: str = ""


def salvar_smtp(repositorio: repo.Repositorio, *, host: str, porta: int, usuario: str, senha: str) -> None:
    repositorio.set_config("smtp_host", host)
    repositorio.set_config("smtp_porta", str(porta))
    repositorio.set_config("smtp_usuario", usuario)
    if senha:
        keyring.set_password(SERVICO_KEYRING, USUARIO_KEYRING_SMTP, senha)


def obter_smtp(repositorio: repo.Repositorio) -> ConfigSmtp:
    return ConfigSmtp(
        host=repositorio.get_config("smtp_host", "") or "",
        porta=int(repositorio.get_config("smtp_porta", "587") or "587"),
        usuario=repositorio.get_config("smtp_usuario", "") or "",
        senha=keyring.get_password(SERVICO_KEYRING, USUARIO_KEYRING_SMTP) or "",
    )


def obter_pasta_base(repositorio: repo.Repositorio, *, padrao: str) -> str:
    return repositorio.get_config("pasta_base", padrao) or padrao


def salvar_pasta_base(repositorio: repo.Repositorio, pasta: str) -> None:
    repositorio.set_config("pasta_base", pasta)
