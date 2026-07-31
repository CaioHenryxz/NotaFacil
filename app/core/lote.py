"""Emissão em lote (Etapa 3 item 5, espec §2 item 6): "importa CSV/XLSX
(tomador, serviço, valor) -> revisa -> emite tudo".

Leitor de .xlsx feito só com a biblioteca padrão (zipfile + xml.etree) —
um .xlsx é um zip de XML por baixo — pra não precisar de openpyxl, que não
está na lista fechada de dependências (espec §7).
"""
from __future__ import annotations

import csv
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Dict, List, Optional

from app import repo

_NS_XLSX = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


@dataclass
class LinhaLote:
    numero_linha: int
    tomador_texto: str
    servico_texto: str
    valor_texto: str
    tomador_id: Optional[int] = None
    modelo_id: Optional[int] = None
    valor: Optional[str] = None
    erro: Optional[str] = None

    @property
    def valida(self) -> bool:
        return self.erro is None


def ler_arquivo(caminho: str) -> List[Dict[str, str]]:
    """Lê CSV ou XLSX (colunas: tomador, servico/serviço, valor) e devolve
    uma lista de dicts com chaves em minúsculo."""
    caminho_p = Path(caminho)
    sufixo = caminho_p.suffix.lower()
    if sufixo == ".csv":
        return _ler_csv(caminho_p)
    if sufixo == ".xlsx":
        return _ler_xlsx(caminho_p)
    raise ValueError(f'Formato "{sufixo}" não é suportado — use .csv ou .xlsx.')


def _ler_csv(caminho: Path) -> List[Dict[str, str]]:
    with open(caminho, "r", encoding="utf-8-sig", newline="") as f:
        amostra = f.read(4096)
        f.seek(0)
        try:
            dialeto = csv.Sniffer().sniff(amostra, delimiters=",;")
        except csv.Error:
            dialeto = csv.excel
        leitor = csv.DictReader(f, dialect=dialeto)
        return [{(k or "").strip().lower(): (v or "").strip() for k, v in linha.items()} for linha in leitor]


def _indice_coluna(letra: str) -> int:
    indice = 0
    for ch in letra:
        indice = indice * 26 + (ord(ch.upper()) - ord("A") + 1)
    return indice


def _ler_xlsx(caminho: Path) -> List[Dict[str, str]]:
    with zipfile.ZipFile(caminho) as z:
        strings_compartilhadas: List[str] = []
        if "xl/sharedStrings.xml" in z.namelist():
            raiz = ET.fromstring(z.read("xl/sharedStrings.xml"))
            for si in raiz.findall("m:si", _NS_XLSX):
                texto = "".join(t.text or "" for t in si.findall(".//m:t", _NS_XLSX))
                strings_compartilhadas.append(texto)

        nome_planilha = next((n for n in sorted(z.namelist()) if n.startswith("xl/worksheets/sheet")), None)
        if nome_planilha is None:
            raise ValueError("Não encontrei nenhuma planilha dentro do arquivo .xlsx.")
        raiz_planilha = ET.fromstring(z.read(nome_planilha))

        linhas_brutas: List[Dict[str, str]] = []
        for linha in raiz_planilha.findall(".//m:row", _NS_XLSX):
            celulas: Dict[str, str] = {}
            for celula in linha.findall("m:c", _NS_XLSX):
                ref = celula.get("r", "")
                coluna = "".join(ch for ch in ref if ch.isalpha())
                valor_node = celula.find("m:v", _NS_XLSX)
                if valor_node is None:
                    celulas[coluna] = ""
                    continue
                texto = valor_node.text or ""
                if celula.get("t") == "s":
                    texto = strings_compartilhadas[int(texto)]
                celulas[coluna] = texto
            linhas_brutas.append(celulas)

    if not linhas_brutas:
        return []
    colunas_ordenadas = sorted({c for linha in linhas_brutas for c in linha}, key=_indice_coluna)
    cabecalho = [linhas_brutas[0].get(c, "").strip().lower() for c in colunas_ordenadas]
    resultado = []
    for linha in linhas_brutas[1:]:
        registro = {cabecalho[i]: linha.get(col, "").strip() for i, col in enumerate(colunas_ordenadas) if cabecalho[i]}
        if any(v for v in registro.values()):
            resultado.append(registro)
    return resultado


def _parse_valor(texto: str) -> Optional[Decimal]:
    limpo = texto.replace("R$", "").strip().replace(".", "").replace(",", ".") if "," in texto else texto.replace("R$", "").strip()
    try:
        valor = Decimal(limpo)
    except InvalidOperation:
        return None
    return valor if valor > 0 else None


def revisar(repositorio: repo.Repositorio, prestador_id: int, linhas_brutas: List[Dict[str, str]]) -> List[LinhaLote]:
    """Casa cada linha com um tomador e um modelo já cadastrados (por nome
    exato, sem diferenciar maiúsculas/minúsculas). Não cria cadastro novo
    sozinho — nomes que não baterem ficam com erro, pra revisão manual antes
    de qualquer nota ser criada."""
    tomadores = {t["nome"].strip().lower(): t for t in repositorio.listar_tomadores(prestador_id)}
    modelos = {m["descricao"].strip().lower(): m for m in repositorio.listar_modelos_servico(prestador_id)}

    linhas: List[LinhaLote] = []
    for i, bruta in enumerate(linhas_brutas, start=2):  # linha 1 = cabeçalho
        tomador_texto = bruta.get("tomador", "")
        servico_texto = bruta.get("servico") or bruta.get("serviço", "")
        valor_texto = bruta.get("valor", "")

        linha = LinhaLote(
            numero_linha=i, tomador_texto=tomador_texto,
            servico_texto=servico_texto, valor_texto=valor_texto,
        )

        tomador = tomadores.get(tomador_texto.lower())
        modelo = modelos.get(servico_texto.lower())
        valor = _parse_valor(valor_texto) if valor_texto else None

        if not tomador_texto:
            linha.erro = "Falta o nome do tomador"
        elif tomador is None:
            linha.erro = f'Tomador "{tomador_texto}" não encontrado — cadastre antes de importar'
        elif not servico_texto:
            linha.erro = "Falta o serviço"
        elif modelo is None:
            linha.erro = f'Serviço "{servico_texto}" não encontrado — cadastre o modelo antes'
        elif valor is None:
            linha.erro = f'Valor inválido: "{valor_texto}"'
        else:
            linha.tomador_id = tomador["id"]
            linha.modelo_id = modelo["id"]
            linha.valor = f"{valor:.2f}"

        linhas.append(linha)
    return linhas


def emitir_linhas_validas(repositorio: repo.Repositorio, prestador_id: int, linhas: List[LinhaLote]) -> List[int]:
    """Cria uma nota 'pendente' pra cada linha válida — a emissão de verdade
    acontece no próximo `core.fila.processar_fila`, igual à emissão avulsa.

    Herda as retenções PADRÃO do tomador (docs/auditoria-2.md, Onda 2 item 1
    -- achado novo: antes desta correção, notas importadas em lote SEMPRE
    saíam sem nenhuma retenção, mesmo pra um tomador com IRRF/PIS/COFINS/
    CSLL/INSS configurado, porque `criar_nota` era chamado sem `retencoes`
    -- diferente da emissão avulsa (`app/api.py`) e da mensalidade
    automática (`core/fila.criar_notas_das_recorrencias_do_dia`), que já
    faziam essa herança corretamente). Lote não tem UI de "sobrescrever só
    nesta nota" (é processamento em lote, sem revisão campo a campo), então
    sempre usa o padrão do tomador, igual à mensalidade automática."""
    criadas = []
    for linha in linhas:
        if not linha.valida:
            continue
        tomador = repositorio.obter_tomador(prestador_id, linha.tomador_id)
        retencoes = {campo: tomador[campo] for campo in repo.CAMPOS_RETENCAO} if tomador else None
        nota_id = repositorio.criar_nota(
            prestador_id, tomador_id=linha.tomador_id, modelo_id=linha.modelo_id, valor=linha.valor,
            retencoes=retencoes,
        )
        criadas.append(nota_id)
    return criadas
