"""Organizacao em disco das notas emitidas (espec-mvp-emissor-nfse.md, secao 5b).

    PastaBase\\<Prestador>\\<Ano>\\<MM - Mes>\\Emitidas\\
                                          \\Canceladas\\

O app so CRIA e MOVE arquivos, nunca apaga — cancelar = mover pra Canceladas/
(espec: "O app cria e move arquivos, nunca apaga. Cancelou -> move pra
Canceladas\\. Reemitiu -> novo arquivo, o antigo permanece.").

Nomes sanitizados (remove os proibidos do Windows \\/:*?"<>|, limita tamanho).
Acentos NAO sao removidos — NTFS/Explorer lidam bem com Unicode, e o proprio
exemplo da espec usa nomes acentuados ("Dr. Joao Cardoso"); "resolve acento"
na espec e tratado aqui como normalizacao (NFC), nao como remocao.
"""
from __future__ import annotations

import re
import shutil
import unicodedata
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Optional, Tuple, Union

# \\/:*?"<>| -- proibidos no Windows. \x00-\x1f -- caracteres de controle:
# tambem invalidos em nome de arquivo/pasta no Windows, mas nao estavam
# sendo removidos aqui (docs/auditoria.md, Bloco 3, item 3 -- "nao podem
# quebrar... o nome de arquivo/pasta"; um controle colado sem querer de
# outro sistema passava direto pra `Path.mkdir`/`write_bytes`).
_CARACTERES_PROIBIDOS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')

_MESES = [
    "01 - Janeiro", "02 - Fevereiro", "03 - Março", "04 - Abril",
    "05 - Maio", "06 - Junho", "07 - Julho", "08 - Agosto",
    "09 - Setembro", "10 - Outubro", "11 - Novembro", "12 - Dezembro",
]

CaminhoLike = Union[str, Path]


def sanitizar_nome_arquivo(nome: str, limite: int = 150) -> str:
    """Remove caracteres proibidos no Windows, normaliza acentuacao (NFC),
    colapsa espacos e corta o tamanho. Nomes vazios viram 'sem-nome'."""
    nome = unicodedata.normalize("NFC", nome)
    nome = _CARACTERES_PROIBIDOS.sub("", nome)
    nome = re.sub(r"\s+", " ", nome).strip()
    nome = nome.rstrip(". ")  # Windows nao aceita nome de arquivo/pasta terminado em ponto/espaco
    if not nome:
        nome = "sem-nome"
    return nome[:limite]


def nome_pasta_mes(mes: int) -> str:
    if not 1 <= mes <= 12:
        raise ValueError(f"Mes invalido: {mes}")
    return _MESES[mes - 1]


def formatar_valor_br(valor) -> str:
    """1500.5 -> '1.500,50' (separador de milhar '.', decimal ',')."""
    d = Decimal(str(valor)).quantize(Decimal("0.01"))
    negativo = d < 0
    inteiro, _, centavos = f"{abs(d):.2f}".partition(".")
    grupos = []
    while len(inteiro) > 3:
        grupos.insert(0, inteiro[-3:])
        inteiro = inteiro[:-3]
    grupos.insert(0, inteiro)
    inteiro_fmt = ".".join(grupos)
    return f"{'-' if negativo else ''}{inteiro_fmt},{centavos}"


def nome_base_arquivo(numero: str, nome_tomador: str, valor, sufixo: Optional[str] = None) -> str:
    """'NFSe <numero> - <tomador> - R$ <valor>' — mesma base pro .pdf e o .xml
    (espec: "PDF e XML sempre juntos, mesmo nome-base")."""
    tomador = sanitizar_nome_arquivo(nome_tomador, limite=80)
    base = f"NFSe {numero} - {tomador} - R$ {formatar_valor_br(valor)}"
    if sufixo:
        base += f" ({sanitizar_nome_arquivo(sufixo, limite=20)})"
    return sanitizar_nome_arquivo(base, limite=180)


def nome_pasta_prestador(nome_exibicao: str, pasta_nome: Optional[str] = None) -> str:
    return sanitizar_nome_arquivo(pasta_nome or nome_exibicao, limite=100)


def pasta_prestador(pasta_base: CaminhoLike, nome_exibicao: str, pasta_nome: Optional[str] = None) -> Path:
    return Path(pasta_base) / nome_pasta_prestador(nome_exibicao, pasta_nome)


def renomear_pasta_prestador(pasta_base: CaminhoLike, prestador_atual: dict, novo_nome_exibicao: str) -> str:
    """Renomeia FISICAMENTE a pasta do prestador no disco quando o nome de
    exibicao muda (docs/auditoria.md, Bloco 4.2): antes desta funcao, a
    pasta era sempre recalculada dinamicamente a partir de `nome_exibicao` —
    corrigir um nome digitado errado ("Dr. Joao" -> "Dr. João") fazia as
    notas NOVAS carem numa pasta diferente das antigas, sem aviso nenhum,
    partindo o historico em duas pastas.

    Devolve o `pasta_nome` (ja sanitizado) que deve ser persistido no
    cadastro do prestador (`repo.atualizar_prestador(..., pasta_nome=...)`)
    -- a partir dai esse valor passa a ser a referencia fisica travada
    (`pasta_prestador` sempre prioriza `pasta_nome` sobre `nome_exibicao`),
    entao uma futura edicao de nome sempre passa por esta funcao de novo e o
    caminho fisico nunca fica orfao."""
    origem = pasta_prestador(pasta_base, prestador_atual["nome_exibicao"], prestador_atual.get("pasta_nome"))
    novo_pasta_nome = sanitizar_nome_arquivo(novo_nome_exibicao, limite=100)
    destino = Path(pasta_base) / novo_pasta_nome

    if origem == destino or not origem.exists():
        # Nada pra mover (nome nao mudou, ou o prestador ainda nao emitiu
        # nada e a pasta nunca chegou a existir) -- so' passa a usar o novo nome.
        return novo_pasta_nome
    if destino.exists():
        raise FileExistsError(
            f'Já existe uma pasta "{novo_pasta_nome}" em {pasta_base} — escolha um nome de exibição diferente.'
        )
    destino.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(origem), str(destino))
    return novo_pasta_nome


def pasta_mes(pasta_base: CaminhoLike, nome_exibicao: str, ano: int, mes: int, pasta_nome: Optional[str] = None) -> Path:
    return pasta_prestador(pasta_base, nome_exibicao, pasta_nome) / str(ano) / nome_pasta_mes(mes)


def pasta_emitidas(pasta_base: CaminhoLike, nome_exibicao: str, ano: int, mes: int, pasta_nome: Optional[str] = None) -> Path:
    return pasta_mes(pasta_base, nome_exibicao, ano, mes, pasta_nome) / "Emitidas"


def pasta_canceladas(pasta_base: CaminhoLike, nome_exibicao: str, ano: int, mes: int, pasta_nome: Optional[str] = None) -> Path:
    return pasta_mes(pasta_base, nome_exibicao, ano, mes, pasta_nome) / "Canceladas"


def salvar_nota(
    pasta_base: CaminhoLike,
    nome_exibicao: str,
    *,
    numero: str,
    nome_tomador: str,
    valor,
    data_emissao: date,
    xml_bytes: bytes,
    pdf_bytes: Optional[bytes] = None,
    sufixo: Optional[str] = None,
    pasta_nome: Optional[str] = None,
) -> Tuple[Path, Optional[Path]]:
    """Grava XML (e PDF, se houver) em Emitidas/, criando as pastas que
    faltarem. Nunca apaga nada."""
    pasta = pasta_emitidas(pasta_base, nome_exibicao, data_emissao.year, data_emissao.month, pasta_nome)
    pasta.mkdir(parents=True, exist_ok=True)
    base = nome_base_arquivo(numero, nome_tomador, valor, sufixo)

    xml_path = pasta / f"{base}.xml"
    xml_path.write_bytes(xml_bytes)

    pdf_path = None
    if pdf_bytes is not None:
        pdf_path = pasta / f"{base}.pdf"
        pdf_path.write_bytes(pdf_bytes)

    return xml_path, pdf_path


def cancelar_nota(xml_path: CaminhoLike, pdf_path: Optional[CaminhoLike] = None) -> Tuple[Path, Optional[Path]]:
    """Move o XML (e o PDF, se existir) de Emitidas/ pra Canceladas/ do mesmo
    mes. NUNCA apaga — so move (espec §5b)."""
    xml_path = Path(xml_path)
    pasta_do_mes = xml_path.parent.parent  # .../Emitidas -> .../<MM - Mes>
    destino = pasta_do_mes / "Canceladas"
    destino.mkdir(parents=True, exist_ok=True)

    novo_xml = destino / xml_path.name
    shutil.move(str(xml_path), str(novo_xml))

    novo_pdf = None
    if pdf_path is not None:
        pdf_path = Path(pdf_path)
        if pdf_path.exists():
            novo_pdf = destino / pdf_path.name
            shutil.move(str(pdf_path), str(novo_pdf))

    return novo_xml, novo_pdf


def arvore(pasta: CaminhoLike, prefixo: str = "") -> str:
    """Representacao em texto da arvore de pastas/arquivos — usada pelo
    demo.py pra mostrar o resultado da organizacao em disco."""
    pasta = Path(pasta)
    linhas = [f"{prefixo}{pasta.name}/"]
    itens = sorted(pasta.iterdir(), key=lambda p: (p.is_file(), p.name)) if pasta.is_dir() else []
    for i, item in enumerate(itens):
        ultimo = i == len(itens) - 1
        ramo = "└── " if ultimo else "├── "
        sub_prefixo = prefixo + ("    " if ultimo else "│   ")
        if item.is_dir():
            sub = arvore(item, sub_prefixo).splitlines()
            linhas.append(f"{prefixo}{ramo}{item.name}/")
            linhas.extend(sub[1:])
        else:
            linhas.append(f"{prefixo}{ramo}{item.name}")
    return "\n".join(linhas)
