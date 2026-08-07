"""API HTTP local pro protótipo web (prototype/) falar com o backend de
verdade — mesmo banco, mesmas regras, mesmos módulos que a interface PySide6
usa (app/repo.py, app/core/*, app/fiscal/*). Nada de lógica nova aqui: cada
rota só traduz JSON/HTTP pra uma chamada de função já existente e testada.

Isso NÃO faz parte do produto descrito na espec (docs/spec-mvp.md, secao 4:
"desktop burro, servidor quase inexistente") — é uma ponte local, só pro
protótipo de venda (prototype/) mostrar dados e ações reais em vez de
mockados. Por isso o Flask fica de fora do requirements.txt do app desktop
(ver requirements-api.txt) e este arquivo nunca é importado por app/main.py.

Uso:
    python -m app.api
Sobe em http://127.0.0.1:8000 — o front (prototype/, em localhost:5173)
já aponta pra essa URL (ver prototype/src/api.js).
"""
from __future__ import annotations

import datetime as dt
import uuid
from pathlib import Path
from typing import Any, Callable, Optional

from flask import Flask, jsonify, request

from app import repo
from app.core import (
    agendador,
    brasilapi,
    documentos,
    email as email_service,
    email_config,
    fila,
    mensagens,
    onboarding,
    pastas,
    valores,
)
from app.fiscal import assinador

PASTA_DADOS_APP = Path.home() / "Documentos" / "Emissor NFS-e"
PASTA_BASE_NOTAS_PADRAO = str(Path.home() / "Documentos" / "Notas Fiscais")
PASTA_CERTIFICADOS = PASTA_DADOS_APP / "certificados"

app = Flask(__name__)

# Deliberadamente None até `main()` (ou um teste) preencher — importar este
# módulo não pode ter efeito colateral em disco (nada de mkdir/sqlite3.connect
# só por causa de um `import app.api`). Mesmo padrão de app/main.py, que só
# toca disco dentro de main().
repositorio: Optional[repo.Repositorio] = None


def _pasta_base() -> str:
    return email_config.obter_pasta_base(repositorio, padrao=PASTA_BASE_NOTAS_PADRAO)


def _normalizar_valor(valor: Any) -> str:
    """Aceita o valor digitado em qualquer formato BR/US comum (vírgula ou
    ponto decimal, com ou sem separador de milhar, com ou sem "R$") e nunca
    deixa passar formato ambíguo, zero, negativo ou vazio — ver
    app/core/valores.py (docs/auditoria.md, Bloco 3)."""
    return valores.normalizar_valor_monetario(valor)


# --------------------------------------------------------------------------
# CORS (o front roda em localhost:5173, a API em localhost:8000 — origens
# diferentes). So' pra uso local: nao existe nenhum dado sensivel exposto
# pra fora desta maquina (Flask sobe so' em 127.0.0.1, nunca 0.0.0.0).
# --------------------------------------------------------------------------
@app.after_request
def _add_cors_headers(resposta):
    resposta.headers["Access-Control-Allow-Origin"] = "*"
    resposta.headers["Access-Control-Allow-Headers"] = "Content-Type"
    resposta.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return resposta


@app.route("/api/<path:_qualquer>", methods=["OPTIONS"])
def _preflight(_qualquer):
    return ("", 204)


def _rota(funcao: Callable[..., Any]):
    """Envolve toda rota: traduz exceção -> JSON de erro com mensagem em
    português claro (mesma tradução que a UI usa, app.core.mensagens), em
    vez de cada rota repetir o mesmo try/except."""

    def _wrapped(*args, **kwargs):
        try:
            resultado = funcao(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 — fronteira HTTP, traduz tudo
            return jsonify({"erro": mensagens.traduzir_erro(exc)}), 400
        if resultado is None:
            return jsonify({"ok": True})
        return jsonify(resultado)

    _wrapped.__name__ = funcao.__name__
    return _wrapped


@app.get("/api/health")
def health():
    return jsonify({"ok": True, "servico": "emissor-nfse-api"})


# --------------------------------------------------------------------------
# Certificado / onboarding de prestador
# --------------------------------------------------------------------------
@app.post("/api/certificados/ler")
@_rota
def ler_certificado():
    arquivo = request.files.get("arquivo")
    senha = request.form.get("senha", "")
    if arquivo is None or not senha:
        raise ValueError("Envie o arquivo .pfx e a senha.")

    caminho_pfx = PASTA_CERTIFICADOS / f"{uuid.uuid4().hex}.pfx"
    arquivo.save(caminho_pfx)

    info = onboarding.ler_certificado(str(caminho_pfx), senha)
    return {
        "caminho_pfx": str(caminho_pfx),
        "documento": info.documento,
        "tipo_documento": info.tipo_documento,
        "nome_titular": info.nome_titular,
        "valido_ate": info.valido_ate,
    }


@app.post("/api/certificados/testar-conexao")
@_rota
def testar_conexao_certificado():
    corpo = request.get_json(force=True)
    onboarding.testar_conexao(corpo["caminho_pfx"], corpo["senha"], ambiente="homologacao")
    return {"ok": True, "mensagem": "Certificado aceito pela Receita (ambiente de testes)."}


@app.get("/api/cnpj/<cnpj>")
@_rota
def buscar_cnpj(cnpj: str):
    dados = brasilapi.buscar_cnpj(cnpj)
    return {
        "cnpj": dados.cnpj,
        "razao_social": dados.razao_social,
        "nome_fantasia": dados.nome_fantasia,
        "endereco_formatado": dados.endereco_formatado,
        "codigo_municipio_ibge": dados.codigo_municipio_ibge,
        "email": dados.email,
        "telefone": dados.telefone,
        "situacao_cadastral": dados.situacao_cadastral,
    }


# --------------------------------------------------------------------------
# Prestadores
# --------------------------------------------------------------------------
@app.get("/api/prestadores")
@_rota
def listar_prestadores():
    apenas_ativos = request.args.get("apenas_ativos", "1") != "0"
    return repositorio.listar_prestadores(apenas_ativos=apenas_ativos)


@app.post("/api/prestadores")
@_rota
def criar_prestador():
    corpo = request.get_json(force=True)
    prestador_id = repositorio.criar_prestador(
        nome_exibicao=corpo["nome_exibicao"],
        cnpj=documentos.exigir_documento_valido(corpo["cnpj"]),
        im=corpo["im"],
        codigo_municipio=corpo["codigo_municipio"],
        regime=corpo.get("regime", "1"),
        regime_especial_tributacao=corpo.get("regime_especial_tributacao", "0"),
        caminho_pfx=corpo.get("caminho_pfx"),
        cor=corpo.get("cor"),
        cert_venc_em=corpo.get("valido_ate"),
    )
    senha = corpo.get("senha")
    if senha:
        assinador.salvar_senha(prestador_id, senha)
    return repositorio.obter_prestador(prestador_id)


@app.post("/api/prestadores/<int:prestador_id>/editar")
@_rota
def editar_prestador(prestador_id: int):
    corpo = request.get_json(force=True)
    novo_nome = corpo["nome_exibicao"]
    prestador_atual = repositorio.obter_prestador(prestador_id)
    pasta_nome = None
    if prestador_atual and novo_nome != prestador_atual["nome_exibicao"]:
        # Renomeia a pasta fisica de verdade -- docs/auditoria.md, Bloco 4.2:
        # antes, so' o nome_exibicao mudava e a pasta ficava orfa/duplicada.
        pasta_nome = pastas.renomear_pasta_prestador(_pasta_base(), prestador_atual, novo_nome)
    repositorio.atualizar_prestador(
        prestador_id,
        nome_exibicao=novo_nome,
        im=corpo["im"],
        codigo_municipio=corpo["codigo_municipio"],
        regime=corpo.get("regime", "1"),
        regime_especial_tributacao=corpo.get("regime_especial_tributacao", "0"),
        cor=corpo.get("cor"),
        pasta_nome=pasta_nome,
    )
    return repositorio.obter_prestador(prestador_id)


@app.post("/api/prestadores/<int:prestador_id>/inativar")
@_rota
def inativar_prestador(prestador_id: int):
    repositorio.inativar_prestador(prestador_id)


@app.post("/api/prestadores/<int:prestador_id>/reativar")
@_rota
def reativar_prestador(prestador_id: int):
    repositorio.reativar_prestador(prestador_id)


@app.post("/api/prestadores/<int:prestador_id>/excluir")
@_rota
def excluir_prestador(prestador_id: int):
    repositorio.excluir_prestador(prestador_id)


# --------------------------------------------------------------------------
# Tomadores
# --------------------------------------------------------------------------
@app.get("/api/prestadores/<int:prestador_id>/tomadores")
@_rota
def listar_tomadores(prestador_id: int):
    apenas_ativos = request.args.get("apenas_ativos", "1") != "0"
    return repositorio.listar_tomadores(prestador_id, apenas_ativos=apenas_ativos)


@app.post("/api/prestadores/<int:prestador_id>/tomadores")
@_rota
def criar_tomador(prestador_id: int):
    corpo = request.get_json(force=True)
    tomador_id = repositorio.criar_tomador(
        prestador_id,
        doc=documentos.exigir_documento_valido(corpo["doc"]),
        nome=corpo["nome"],
        email=corpo.get("email") or None,
        telefone=corpo.get("telefone") or None,
        endereco=corpo.get("endereco") or None,
        retencoes=corpo.get("retencoes"),
    )
    return repositorio.obter_tomador(prestador_id, tomador_id)


@app.post("/api/prestadores/<int:prestador_id>/tomadores/<int:tomador_id>/editar")
@_rota
def editar_tomador(prestador_id: int, tomador_id: int):
    corpo = request.get_json(force=True)
    repositorio.atualizar_tomador(
        prestador_id, tomador_id,
        nome=corpo["nome"],
        email=corpo.get("email") or None,
        telefone=corpo.get("telefone") or None,
        endereco=corpo.get("endereco") or None,
        retencoes=corpo.get("retencoes"),
    )
    return repositorio.obter_tomador(prestador_id, tomador_id)


@app.post("/api/prestadores/<int:prestador_id>/tomadores/<int:tomador_id>/excluir")
@_rota
def excluir_tomador(prestador_id: int, tomador_id: int):
    repositorio.excluir_tomador(prestador_id, tomador_id)


@app.post("/api/prestadores/<int:prestador_id>/tomadores/<int:tomador_id>/inativar")
@_rota
def inativar_tomador(prestador_id: int, tomador_id: int):
    repositorio.inativar_tomador(prestador_id, tomador_id)


@app.post("/api/prestadores/<int:prestador_id>/tomadores/<int:tomador_id>/reativar")
@_rota
def reativar_tomador(prestador_id: int, tomador_id: int):
    repositorio.reativar_tomador(prestador_id, tomador_id)


# --------------------------------------------------------------------------
# Modelos de serviço
# --------------------------------------------------------------------------
@app.get("/api/prestadores/<int:prestador_id>/modelos")
@_rota
def listar_modelos(prestador_id: int):
    return repositorio.listar_modelos_servico(prestador_id)


@app.post("/api/prestadores/<int:prestador_id>/modelos")
@_rota
def criar_modelo(prestador_id: int):
    corpo = request.get_json(force=True)
    modelo_id = repositorio.criar_modelo_servico(
        prestador_id,
        descricao=corpo["descricao"],
        cod_tributacao_nacional=corpo["cod_tributacao_nacional"],
        cod_tributacao_municipal=corpo["cod_tributacao_municipal"],
        cod_nbs=corpo["cod_nbs"],
        valor_padrao=_normalizar_valor(corpo["valor_padrao"]),
        aliquota=corpo.get("aliquota") or None,
    )
    return repositorio.obter_modelo(prestador_id, modelo_id)


@app.post("/api/prestadores/<int:prestador_id>/modelos/<int:modelo_id>/editar")
@_rota
def editar_modelo(prestador_id: int, modelo_id: int):
    corpo = request.get_json(force=True)
    repositorio.atualizar_modelo_servico(
        prestador_id, modelo_id,
        descricao=corpo["descricao"],
        cod_tributacao_nacional=corpo["cod_tributacao_nacional"],
        cod_tributacao_municipal=corpo["cod_tributacao_municipal"],
        cod_nbs=corpo["cod_nbs"],
        valor_padrao=_normalizar_valor(corpo["valor_padrao"]),
        aliquota=corpo.get("aliquota") or None,
    )
    return repositorio.obter_modelo(prestador_id, modelo_id)


@app.post("/api/prestadores/<int:prestador_id>/modelos/<int:modelo_id>/excluir")
@_rota
def excluir_modelo(prestador_id: int, modelo_id: int):
    repositorio.excluir_modelo_servico(prestador_id, modelo_id)


# --------------------------------------------------------------------------
# Mensalidades (recorrências)
# --------------------------------------------------------------------------
@app.get("/api/prestadores/<int:prestador_id>/recorrencias")
@_rota
def listar_recorrencias(prestador_id: int):
    return repositorio.listar_recorrencias(prestador_id, apenas_ativas=False)


@app.post("/api/prestadores/<int:prestador_id>/recorrencias")
@_rota
def criar_recorrencia(prestador_id: int):
    corpo = request.get_json(force=True)
    recorrencia_id = repositorio.criar_recorrencia(
        prestador_id,
        tomador_id=corpo["tomador_id"],
        modelo_id=corpo["modelo_id"],
        valor=_normalizar_valor(corpo["valor"]),
        dia_do_mes=int(corpo["dia_do_mes"]),
        ativo=bool(corpo.get("ativo", True)),
    )
    return {"id": recorrencia_id}


@app.post("/api/prestadores/<int:prestador_id>/recorrencias/<int:recorrencia_id>/alternar")
@_rota
def alternar_recorrencia(prestador_id: int, recorrencia_id: int):
    corpo = request.get_json(force=True)
    repositorio.atualizar_recorrencia_ativo(prestador_id, recorrencia_id, bool(corpo["ativo"]))
    return {"ok": True}


@app.post("/api/prestadores/<int:prestador_id>/recorrencias/<int:recorrencia_id>/editar")
@_rota
def editar_recorrencia(prestador_id: int, recorrencia_id: int):
    corpo = request.get_json(force=True)
    repositorio.atualizar_recorrencia(
        prestador_id, recorrencia_id,
        tomador_id=corpo["tomador_id"],
        modelo_id=corpo["modelo_id"],
        valor=_normalizar_valor(corpo["valor"]),
        dia_do_mes=int(corpo["dia_do_mes"]),
    )
    return {"ok": True}


@app.post("/api/prestadores/<int:prestador_id>/recorrencias/<int:recorrencia_id>/excluir")
@_rota
def excluir_recorrencia(prestador_id: int, recorrencia_id: int):
    repositorio.excluir_recorrencia(prestador_id, recorrencia_id)


# --------------------------------------------------------------------------
# Notas / Histórico / Emissão avulsa
# --------------------------------------------------------------------------
@app.get("/api/prestadores/<int:prestador_id>/notas")
@_rota
def listar_notas(prestador_id: int):
    status = request.args.get("status") or None
    return repositorio.listar_notas_detalhado(prestador_id, status)


@app.post("/api/prestadores/<int:prestador_id>/notas")
@_rota
def emitir_nota_avulsa(prestador_id: int):
    corpo = request.get_json(force=True)
    # "permitir sobrescrever so' naquela nota" (docs/auditoria.md, Bloco
    # 1.6/2.4, item 2): comeca do padrao do tomador (retencoes fixas por
    # convenio) e deixa o corpo da requisicao sobrescrever campo a campo,
    # sem alterar o cadastro do tomador.
    tomador = repositorio.obter_tomador(prestador_id, corpo["tomador_id"])
    retencoes = {campo: (tomador or {}).get(campo) for campo in repo.CAMPOS_RETENCAO}
    retencoes.update(corpo.get("retencoes") or {})
    nota_id = repositorio.criar_nota(
        prestador_id, tomador_id=corpo["tomador_id"], modelo_id=corpo["modelo_id"],
        valor=_normalizar_valor(corpo["valor"]), retencoes=retencoes,
    )
    fila.processar_fila(repositorio, _pasta_base())
    nota = repositorio.obter_nota(prestador_id, nota_id)
    if nota["status"] == repo.STATUS_REJEITADA:
        nota["motivo_rejeicao_traduzido"] = mensagens.traduzir_motivo_rejeicao(nota["motivo_rejeicao"])
    return nota


@app.get("/api/prestadores/<int:prestador_id>/tomadores/<int:tomador_id>/alerta-valor")
@_rota
def alerta_valor(prestador_id: int, tomador_id: int):
    """Item 3 da automação pedida: antes de emitir, avisa (sem bloquear) se
    o valor digitado fugir muito do que esse tomador+serviço costuma pagar
    — pega cedo o erro de digitação (docs/auditoria.md, Bloco 3) em vez de
    só descobrir na rejeição ou no extrato do mês."""
    modelo_id = request.args.get("modelo_id", type=int)
    valor = request.args.get("valor", "")
    try:
        valor_normalizado = _normalizar_valor(valor) if valor else None
    except valores.ValorInvalido:
        valor_normalizado = None  # ainda digitando -- so' nao ha' o que checar agora, nao e' erro
    if modelo_id is None or valor_normalizado is None:
        return {"alerta": None}
    historico = repositorio.historico_valores_tomador(prestador_id, tomador_id, modelo_id)
    alerta = valores.valor_foge_do_padrao(valor_normalizado, historico)
    return {"alerta": alerta}


@app.post("/api/prestadores/<int:prestador_id>/notas/<int:nota_id>/cancelar")
@_rota
def cancelar_nota(prestador_id: int, nota_id: int):
    corpo = request.get_json(force=True)
    resultado = fila.solicitar_cancelamento(
        repositorio, prestador_id, nota_id,
        cod_motivo=corpo["cod_motivo"], motivo_texto=corpo.get("motivo_texto"),
    )
    nota = repositorio.obter_nota(prestador_id, nota_id)
    if nota.get("erro_cancelamento"):
        nota["erro_cancelamento_traduzido"] = mensagens.traduzir_erro_cancelamento(nota["erro_cancelamento"])
    return nota


@app.post("/api/prestadores/<int:prestador_id>/notas/<int:nota_id>/reenviar-email")
@_rota
def reenviar_email(prestador_id: int, nota_id: int):
    nota = repositorio.obter_nota(prestador_id, nota_id)
    prestador = repositorio.obter_prestador(prestador_id)
    tomador = repositorio.obter_tomador(prestador_id, nota["tomador_id"])
    email_service.reenviar_nota_email(repositorio, prestador, tomador, nota)
    return repositorio.obter_nota(prestador_id, nota_id)


# --------------------------------------------------------------------------
# Meu Dia
# --------------------------------------------------------------------------
@app.get("/api/meu-dia")
@_rota
def meu_dia():
    dados = repositorio.dados_meu_dia(dt.date.today())
    for rejeitada in dados["notas_rejeitadas"]:
        rejeitada["motivo_traduzido"] = mensagens.traduzir_motivo_rejeicao(rejeitada["motivo_rejeicao"] or "")
    return dados


@app.post("/api/meu-dia/emitir-todas")
@_rota
def emitir_todas():
    hoje = dt.date.today()
    criadas = fila.criar_notas_das_recorrencias_do_dia(repositorio, hoje)
    resultados = fila.processar_fila(repositorio, _pasta_base()) if criadas else []
    return {
        "criadas": len(criadas),
        "emitidas": sum(1 for r in resultados if r["status"] == "emitida"),
        "rejeitadas": sum(1 for r in resultados if r["status"] == "rejeitada"),
        "pendentes": sum(1 for r in resultados if r["status"] == "pendente"),
    }


@app.post("/api/agendador/ciclo")
@_rota
def rodar_ciclo_agendador():
    """Dispara manualmente o mesmo ciclo do QTimer de 15 min do app desktop
    (core/agendador.py) — util pro protótipo demonstrar a automação sem
    esperar."""
    resultado = agendador.rodar_ciclo(repositorio, _pasta_base())
    return {
        "notas_criadas_catchup": len(resultado.notas_criadas_catchup),
        "dias_atrasados": [d.isoformat() for d in resultado.dias_atrasados],
        "total_emitidas": resultado.total_emitidas,
        "total_rejeitadas": resultado.total_rejeitadas,
        "emitidas_atrasadas": resultado.emitidas_atrasadas,
    }


# --------------------------------------------------------------------------
# Configurações
# --------------------------------------------------------------------------
@app.get("/api/config")
@_rota
def obter_config():
    smtp = email_config.obter_smtp(repositorio)
    return {
        "pasta_base": _pasta_base(),
        "smtp_host": smtp.host,
        "smtp_porta": smtp.porta,
        "smtp_usuario": smtp.usuario,
        "smtp_senha_configurada": bool(smtp.senha),
    }


@app.post("/api/config")
@_rota
def salvar_config():
    corpo = request.get_json(force=True)
    if corpo.get("pasta_base"):
        email_config.salvar_pasta_base(repositorio, corpo["pasta_base"])
    email_config.salvar_smtp(
        repositorio,
        host=corpo.get("smtp_host", ""),
        porta=int(corpo.get("smtp_porta", 587)),
        usuario=corpo.get("smtp_usuario", ""),
        senha=corpo.get("smtp_senha", ""),
    )
    return {"ok": True}


# --------------------------------------------------------------------------
# Navegador de pastas (só protótipo: o navegador não tem como abrir o
# seletor nativo do SO e devolver um caminho absoluto de verdade — mas como
# este backend roda na MESMA máquina do navegador nesta demo, dá pra montar
# um "Escolher pasta" visual em HTML puro listando o sistema de arquivos
# local, sem precisar de nenhuma dependência nova. O app desktop de verdade
# já resolve isso nativamente com QFileDialog, ver app/ui/tela_configuracoes.py.
# --------------------------------------------------------------------------
def _pasta_existente_mais_proxima(caminho: Path) -> Path:
    """`caminho` pedido pode nao existir ainda (ex.: pasta base padrao,
    'Documentos/Notas Fiscais', antes da primeira nota ser emitida) -- sobe
    ate achar um ancestral que exista, pra sempre ter o que listar."""
    caminho = caminho.expanduser()
    while not caminho.is_dir():
        pai = caminho.parent
        if pai == caminho:  # chegou na raiz sem achar nada -- desiste pra home
            return Path.home()
        caminho = pai
    return caminho


@app.get("/api/pastas/listar")
@_rota
def listar_pastas():
    pedido = request.args.get("caminho") or _pasta_base()
    caminho = _pasta_existente_mais_proxima(Path(pedido))
    subpastas = []
    try:
        for item in sorted(caminho.iterdir(), key=lambda p: p.name.lower()):
            try:
                if item.is_dir() and not item.name.startswith("."):
                    subpastas.append({"nome": item.name, "caminho": str(item)})
            except OSError:
                continue  # link quebrado ou sem permissao pra stat -- so' ignora
    except PermissionError:
        pass  # pasta sem permissao de leitura -- devolve vazio, nao quebra
    pai = str(caminho.parent) if caminho.parent != caminho else None
    return {"caminho": str(caminho), "pai": pai, "pastas": subpastas}


@app.post("/api/pastas/criar")
@_rota
def criar_pasta():
    corpo = request.get_json(force=True)
    nome = (corpo.get("nome") or "").strip()
    if not nome or "/" in nome or "\\" in nome:
        raise ValueError("Digite um nome de pasta válido.")
    nova = Path(corpo["caminho_pai"]).expanduser() / nome
    nova.mkdir(exist_ok=True)
    return {"caminho": str(nova)}


def main() -> None:
    global repositorio
    PASTA_DADOS_APP.mkdir(parents=True, exist_ok=True)
    PASTA_CERTIFICADOS.mkdir(parents=True, exist_ok=True)
    repositorio = repo.Repositorio(PASTA_DADOS_APP / "emissor.db")
    print(f"Banco de dados: {PASTA_DADOS_APP / 'emissor.db'}")
    app.run(host="127.0.0.1", port=8000, debug=False, threaded=False)


if __name__ == "__main__":
    main()
