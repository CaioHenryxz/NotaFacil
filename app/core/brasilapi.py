"""Busca de dados de CNPJ na BrasilAPI (gratuita, sem chave) — espec-mvp,
secao 2 item 2: "CNPJ/CPF -> busca automatica dos dados na BrasilAPI/ReceitaWS
(gratuitas). Usuario so confirma."

Aviso honesto sobre CPF: nao existe (nem pode existir, por LGPD) uma API
publica gratuita que devolva "nome de uma pessoa dado o CPF" — isso seria uma
lista telefonica reversa de dado sensivel. BrasilAPI e ReceitaWS so cobrem
CNPJ (dado publico de registro empresarial). Pra tomador/prestador pessoa
fisica (CPF), o nome continua sendo digitado por quem cadastra — e assim em
qualquer emissor do mercado, nao e uma lacuna deste MVP.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

import httpx

URL_BASE = "https://brasilapi.com.br/api/cnpj/v1"


class CnpjNaoEncontrado(Exception):
    """CNPJ com formato valido mas nao encontrado na Receita (BrasilAPI 404)."""


class ErroConsultaCnpj(Exception):
    """Falha de rede/timeout consultando a BrasilAPI — tentar de novo ou preencher a mao."""


@dataclass
class DadosCnpj:
    cnpj: str
    razao_social: str
    nome_fantasia: str
    logradouro: str
    numero: str
    bairro: str
    municipio: str
    uf: str
    cep: str
    codigo_municipio_ibge: str  # 7 digitos — o que a DPS precisa em cLocEmi/cLocPrestacao
    email: Optional[str]
    telefone: Optional[str]
    situacao_cadastral: str

    @property
    def endereco_formatado(self) -> str:
        partes = [p for p in [self.logradouro, self.numero, self.bairro, f"{self.municipio}/{self.uf}"] if p]
        return ", ".join(partes)


def somente_digitos(doc: str) -> str:
    return re.sub(r"\D", "", doc)


def buscar_cnpj(cnpj: str, *, timeout: float = 15.0) -> DadosCnpj:
    cnpj_limpo = somente_digitos(cnpj)
    if len(cnpj_limpo) != 14:
        raise ValueError(f"CNPJ precisa ter 14 digitos, recebi {len(cnpj_limpo)}: {cnpj!r}")

    try:
        resposta = httpx.get(f"{URL_BASE}/{cnpj_limpo}", timeout=timeout)
    except httpx.TransportError as exc:
        raise ErroConsultaCnpj(str(exc)) from exc

    if resposta.status_code == 404:
        raise CnpjNaoEncontrado(f"CNPJ {cnpj_limpo} nao encontrado na Receita Federal.")
    if resposta.status_code >= 400:
        raise ErroConsultaCnpj(f"BrasilAPI retornou HTTP {resposta.status_code} para o CNPJ {cnpj_limpo}.")

    dados = resposta.json()
    return DadosCnpj(
        cnpj=cnpj_limpo,
        razao_social=dados.get("razao_social") or "",
        nome_fantasia=dados.get("nome_fantasia") or "",
        logradouro=dados.get("logradouro") or "",
        numero=dados.get("numero") or "",
        bairro=dados.get("bairro") or "",
        municipio=dados.get("municipio") or "",
        uf=dados.get("uf") or "",
        cep=dados.get("cep") or "",
        codigo_municipio_ibge=str(dados.get("codigo_municipio_ibge") or ""),
        email=dados.get("email") or None,
        telefone=(dados.get("ddd_telefone_1") or None),
        situacao_cadastral=dados.get("descricao_situacao_cadastral") or "",
    )
