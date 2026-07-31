"""Envio de e-mail (Etapa 3, espec §2 item 8 e item 4 desta etapa):
"envia o PDF ao tomador assim que a nota é emitida... falha de e-mail NÃO
derruba a emissão — só marca 'e-mail não enviado' no histórico com botão
'Reenviar'".

Usa smtplib (stdlib, R$ 0) com o SMTP configurado pelo próprio usuário
(app.core.email_config) — mesmo princípio da espec §4: sem servidor nosso no
meio, o e-mail sai "de" quem o tomador já conhece.
"""
from __future__ import annotations

import smtplib
from email.message import EmailMessage
from pathlib import Path
from typing import Dict, Iterable, Optional, Union

from app import repo
from app.core import email_config

CaminhoLike = Union[str, Path]

_TIPOS_MIME = {
    "pdf": ("application", "pdf"),
    "xml": ("text", "xml"),
    "csv": ("text", "csv"),
    "zip": ("application", "zip"),
}


class ErroEnvioEmail(Exception):
    """SMTP não configurado, credenciais erradas, ou falha de conexão."""


def _anexar(msg: EmailMessage, caminho: CaminhoLike) -> None:
    caminho = Path(caminho)
    dados = caminho.read_bytes()
    subtipo = caminho.suffix.lstrip(".").lower() or "octet-stream"
    maintype, subtype = _TIPOS_MIME.get(subtipo, ("application", "octet-stream"))
    msg.add_attachment(dados, maintype=maintype, subtype=subtype, filename=caminho.name)


def _enviar_smtp(
    repositorio: repo.Repositorio, destinatario: str, assunto: str, corpo: str,
    anexos: Optional[Iterable[CaminhoLike]] = None,
) -> None:
    smtp = email_config.obter_smtp(repositorio)
    if not smtp.host or not smtp.usuario:
        raise ErroEnvioEmail("O e-mail SMTP ainda não foi configurado na aba Configurações.")

    msg = EmailMessage()
    msg["Subject"] = assunto
    msg["From"] = smtp.usuario
    msg["To"] = destinatario
    msg.set_content(corpo)
    for caminho in anexos or []:
        _anexar(msg, caminho)

    with smtplib.SMTP(smtp.host, smtp.porta, timeout=30) as servidor:
        servidor.starttls()
        servidor.login(smtp.usuario, smtp.senha)
        servidor.send_message(msg)


def enviar_nota_email(repositorio: repo.Repositorio, prestador: Dict, tomador: Dict, nota: Dict) -> None:
    """Envio automático pós-emissão. NUNCA levanta exceção pra fora — quem
    chama (core/fila.py) não precisa (nem deve) tratar erro de e-mail; o
    resultado fica só marcado em notas.email_status/email_erro."""
    if not tomador.get("email"):
        return  # sem e-mail cadastrado nao e falha, so nao ha o que enviar

    anexo = nota.get("pdf_path") or nota.get("xml_path")
    corpo = (
        f"Olá {tomador['nome']},\n\n"
        f"Segue em anexo a nota fiscal de serviço (NFS-e {nota['numero_dps']}) "
        f"no valor de R$ {nota['valor']}.\n\n"
        f"Atenciosamente,\n{prestador['nome_exibicao']}"
    )
    try:
        _enviar_smtp(
            repositorio, tomador["email"],
            f"Nota Fiscal de Serviço - {prestador['nome_exibicao']}",
            corpo, anexos=[anexo] if anexo else [],
        )
    except Exception as exc:  # noqa: BLE001 — traduzido pra tela, nunca propaga
        repositorio.marcar_email_falhou(nota["prestador_id"], nota["id"], erro=str(exc))
        return
    repositorio.marcar_email_enviado(nota["prestador_id"], nota["id"])


def reenviar_nota_email(repositorio: repo.Repositorio, prestador: Dict, tomador: Dict, nota: Dict) -> None:
    """Botão "Reenviar" do Histórico — mesma lógica do envio automático, mas
    quem chama já sabe que havia um e-mail cadastrado (a tela só habilita o
    botão nesse caso)."""
    enviar_nota_email(repositorio, prestador, tomador, nota)


def enviar_fechamento_email(
    repositorio: repo.Repositorio, destinatario: str, prestador_nome: str, mes_nome: str,
    anexos: Iterable[CaminhoLike],
) -> None:
    """Botão "Fechar mês" → "Enviar ao contador". Diferente do envio pós-
    emissão: aqui a exceção SOBE — a tela precisa saber na hora se falhou
    pra avisar quem clicou, não é um evento de fundo."""
    _enviar_smtp(
        repositorio, destinatario, f"Fechamento {mes_nome} — {prestador_nome}",
        f"Segue em anexo o resumo e os XMLs de {mes_nome} de {prestador_nome}.",
        anexos=anexos,
    )
