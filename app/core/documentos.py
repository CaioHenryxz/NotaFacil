"""Validacao de digito verificador de CPF/CNPJ -- docs/auditoria.md, Bloco 3:
"Nao valida digito verificador em nenhum lugar do codigo... um CNPJ ou CPF
com o numero certo de digitos mas matematicamente invalido passa por toda
validacao do app". Pro CNPJ (tomador PJ/convenio) existia uma rede de
seguranca incidental via BrasilAPI, mas so' se o usuario clicasse em
"Buscar"; pro CPF (paciente pessoa fisica, o caso mais comum) nao existia
nenhuma.

CNPJ ALFANUMERICO (Receita Federal, producao desde 06/07/2026 -- ja vigente
quando este codigo foi escrito, jul/2026): o novo formato mistura letras e
numeros nos 12 primeiros caracteres; os 2 digitos verificadores continuam
sempre numericos. O algoritmo abaixo usa valor ASCII (ord(char) - 48) em vez
do digito puro pra cada uma das 12 posicoes, o que da o mesmo resultado de
sempre pra CNPJ 100% numerico (ord('0')-48 == 0, ord('9')-48 == 9) e ainda
funciona pros novos CNPJs com letra -- um unico algoritmo cobre os dois
formatos, nao precisa de "modo alfanumerico" separado.
"""
from __future__ import annotations

import re


class DocumentoInvalido(ValueError):
    """Mensagem ja pronta pra mostrar na tela -- nao precisa de traducao."""


_PESOS_CNPJ_DV1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
_PESOS_CNPJ_DV2 = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
_PESOS_CPF_DV1 = [10, 9, 8, 7, 6, 5, 4, 3, 2]
_PESOS_CPF_DV2 = [11, 10, 9, 8, 7, 6, 5, 4, 3, 2]


def limpar_documento(doc: str) -> str:
    """Remove mascara (.-/espacos) e maiusculiza -- MANTEM letras, porque o
    CNPJ alfanumerico usa letras nas 12 primeiras posicoes (so' os 2 digitos
    verificadores finais sao sempre numericos)."""
    return re.sub(r"[^0-9A-Za-z]", "", doc or "").upper()


def _digito_verificador(valores: list, pesos: list) -> int:
    soma = sum(v * p for v, p in zip(valores, pesos))
    resto = soma % 11
    return 0 if resto < 2 else 11 - resto


def validar_cnpj(doc: str) -> bool:
    """Aceita tanto o CNPJ 100% numerico classico quanto o novo formato
    alfanumerico (letras nas 12 primeiras posicoes)."""
    limpo = limpar_documento(doc)
    if len(limpo) != 14:
        return False
    corpo, dv_informado = limpo[:12], limpo[12:]
    if not dv_informado.isdigit():
        return False
    if not re.fullmatch(r"[0-9A-Z]{12}", corpo):
        return False
    valores = [ord(c) - 48 for c in corpo]
    dv1 = _digito_verificador(valores, _PESOS_CNPJ_DV1)
    dv2 = _digito_verificador(valores + [dv1], _PESOS_CNPJ_DV2)
    return dv_informado == f"{dv1}{dv2}"


def validar_cpf(doc: str) -> bool:
    limpo = limpar_documento(doc)
    if len(limpo) != 11 or not limpo.isdigit():
        return False
    if limpo == limpo[0] * 11:  # 111.111.111-11 etc. -- passa no mod-11 mas nunca e' valido
        return False
    digitos = [int(c) for c in limpo]
    dv1 = _digito_verificador(digitos[:9], _PESOS_CPF_DV1)
    dv2 = _digito_verificador(digitos[:9] + [dv1], _PESOS_CPF_DV2)
    return digitos[9] == dv1 and digitos[10] == dv2


def validar_cpf_ou_cnpj(doc: str) -> bool:
    """Decide pelo tamanho (11 = CPF, 14 = CNPJ) e valida o digito
    verificador correspondente. Documento com outro tamanho e' sempre invalido."""
    limpo = limpar_documento(doc)
    if len(limpo) == 11:
        return validar_cpf(limpo)
    if len(limpo) == 14:
        return validar_cnpj(limpo)
    return False


def exigir_documento_valido(doc: str) -> str:
    """Limpa e valida; devolve o documento limpo (mascara removida, letras
    maiusculas) ou levanta `DocumentoInvalido` com mensagem pronta pra tela."""
    limpo = limpar_documento(doc)
    if len(limpo) not in (11, 14):
        raise DocumentoInvalido(f'Digite um CNPJ (14 caracteres) ou CPF (11 números) válido. Recebi "{doc}".')
    if not validar_cpf_ou_cnpj(limpo):
        tipo = "CPF" if len(limpo) == 11 else "CNPJ"
        raise DocumentoInvalido(f"Este {tipo} não é válido (dígito verificador não confere). Confira o número.")
    return limpo
