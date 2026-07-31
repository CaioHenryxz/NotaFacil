"""Orquestra o cadastro de um novo prestador (Etapa 2, tela 1): ler o
certificado, completar dados pela BrasilAPI e testar a conexao — tudo que a
tela de cadastro precisa, sem ela chamar fiscal/ ou httpx diretamente.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.fiscal import api_nacional, assinador
from app.core import brasilapi


@dataclass
class LeituraCertificado:
    documento: Optional[str]
    tipo_documento: Optional[str]  # "CNPJ", "CPF" ou None
    nome_titular: str
    valido_ate: str  # ISO (AAAA-MM-DD), pronto pra guardar em prestadores.cert_venc_em


def ler_certificado(caminho_pfx: str, senha: str) -> LeituraCertificado:
    """Abre o .pfx com a senha digitada na tela e devolve o que der pra
    extrair. Levanta excecao (traduzida por core.mensagens) se a senha
    estiver errada ou o arquivo nao for um .pfx valido."""
    _chave, certificado, _extras = assinador.carregar_pfx_com_senha(caminho_pfx, senha)
    info = assinador.inspecionar_certificado(certificado)
    return LeituraCertificado(
        documento=info.documento,
        tipo_documento=info.tipo_documento,
        nome_titular=info.nome_titular,
        valido_ate=info.valido_ate.isoformat(),
    )


def buscar_dados_por_cnpj(cnpj: str) -> brasilapi.DadosCnpj:
    """So funciona pra CNPJ — ver app/core/brasilapi.py sobre por que CPF
    nao tem equivalente publico."""
    return brasilapi.buscar_cnpj(cnpj)


def testar_conexao(caminho_pfx: str, senha: str, *, ambiente: str = "homologacao") -> None:
    """Nao retorna nada em caso de sucesso; levanta excecao (api_nacional.ErroRede)
    em caso de falha — a tela decide a mensagem via core.mensagens.traduzir_erro."""
    chave, certificado, extras = assinador.carregar_pfx_com_senha(caminho_pfx, senha)
    api_nacional.testar_conexao(chave, certificado, extras, ambiente=ambiente)
