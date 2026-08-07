"""Envio de e-mail (Etapa 3, espec §2 item 8 e item 4 desta etapa):
"envia o PDF ao tomador assim que a nota é emitida... falha de e-mail NÃO
derruba a emissão — só marca 'e-mail não enviado' no histórico com botão
'Reenviar'".

Usa smtplib (stdlib, R$ 0) com o SMTP configurado pelo próprio usuário
(app.core.email_config) — mesmo princípio da espec §4: sem servidor nosso no
meio, o e-mail sai "de" quem o tomador já conhece.
"""
from __future__ import annotations

import datetime as dt
import smtplib
from email.message import EmailMessage
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Union

from app import repo
from app.core import email_config
from app.core.backoff import proximo_atraso

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


def enviar_nota_email(
    repositorio: repo.Repositorio, prestador: Dict, tomador: Dict, nota: Dict,
    *, agora: Optional[dt.datetime] = None,
) -> None:
    """Envio automático pós-emissão. NUNCA levanta exceção pra fora — quem
    chama (core/fila.py) não precisa (nem deve) tratar erro de e-mail; o
    resultado fica só marcado em notas.email_status/email_erro.

    `agora`: referência de tempo pro calculo do proximo retry em caso de
    falha (mesmo padrao de `fila.processar_fila`) -- default é o relógio
    real; `reprocessar_emails_falhados` passa o mesmo `agora` que usou pra
    decidir que esta nota estava pronta, pra nunca desalinhar os dois."""
    agora = agora or dt.datetime.now()
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
        # Retry automatico (item 2 da automacao pedida): mesmo backoff da
        # fila de emissao (5min -> 30min -> 2h -> 6h em diante), rodado pelo
        # ciclo do agendador (core/agendador.rodar_ciclo) via
        # `reprocessar_emails_falhados` abaixo -- a secretaria nao precisa
        # notar "Não enviado" no Histórico e clicar "Reenviar" na mão pra um
        # SMTP que caiu por um minuto.
        tentativas = (nota.get("email_tentativas") or 0) + 1
        proxima = agora + proximo_atraso(tentativas)
        repositorio.marcar_email_falhou(
            nota["prestador_id"], nota["id"], erro=str(exc), proxima_tentativa_em=proxima,
        )
        return
    repositorio.marcar_email_enviado(nota["prestador_id"], nota["id"])


def reenviar_nota_email(repositorio: repo.Repositorio, prestador: Dict, tomador: Dict, nota: Dict) -> None:
    """Botão "Reenviar" do Histórico — mesma lógica do envio automático, mas
    quem chama já sabe que havia um e-mail cadastrado (a tela só habilita o
    botão nesse caso)."""
    enviar_nota_email(repositorio, prestador, tomador, nota)


def reprocessar_emails_falhados(
    repositorio: repo.Repositorio, *, agora: Optional[dt.datetime] = None,
) -> List[Dict]:
    """Motor do retry automatico (item 2 da automacao pedida) -- roda a cada
    ciclo do agendador (core/agendador.rodar_ciclo), mesmo espirito de
    `fila.processar_fila`: varre toda nota com e-mail "falhou" pronta pra
    tentar de novo (backoff já vencido) e reenvia sozinha, sem clique
    nenhum. Devolve um resultado por nota tentada, pra quem chamou poder
    contar quantas foram recuperadas."""
    agora = agora or dt.datetime.now()
    resultados: List[Dict] = []
    for nota in repositorio.listar_notas_email_falhou_prontas_para_tentar(agora):
        prestador = repositorio.obter_prestador(nota["prestador_id"])
        tomador = repositorio.obter_tomador(nota["prestador_id"], nota["tomador_id"])
        if prestador is None or tomador is None:
            continue  # prestador/tomador excluido depois da nota -- nao ha' mais pra quem reenviar
        enviar_nota_email(repositorio, prestador, tomador, nota, agora=agora)
        nota_atualizada = repositorio.obter_nota(nota["prestador_id"], nota["id"])
        resultados.append({"nota_id": nota["id"], "email_status": nota_atualizada["email_status"]})
    return resultados


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
