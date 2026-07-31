"""Testes de app/core/lote.py — Etapa 3 item 5: "importa CSV/XLSX (tomador,
serviço, valor) -> revisa -> emite tudo"."""
import tempfile
import unittest
import zipfile
from pathlib import Path

from app import repo
from app.core import lote

_CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/xl/workbook.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
    '<Override PartName="/xl/worksheets/sheet1.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
    "</Types>"
)
_WORKBOOK = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"></workbook>'
)


def _criar_xlsx_minimo(caminho: Path, cabecalho: list, linhas: list) -> None:
    """Monta um .xlsx minimo o bastante pra `lote._ler_xlsx` conseguir ler —
    nao e' um pacote OPC 100% valido (sem _rels), mas nosso leitor so olha
    sharedStrings.xml + worksheets/sheet*.xml, que e o que importa aqui."""
    textos = list(cabecalho)
    for linha in linhas:
        textos.extend(str(v) for v in linha)
    indice_texto = {t: i for i, t in enumerate(dict.fromkeys(textos))}

    shared = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="{len(indice_texto)}" '
        f'uniqueCount="{len(indice_texto)}">'
        + "".join(f"<si><t>{t}</t></si>" for t in indice_texto)
        + "</sst>"
    )

    def _linha_xml(numero: int, valores: list) -> str:
        celulas = []
        for col_idx, valor in enumerate(valores):
            letra = chr(ord("A") + col_idx)
            ref = f"{letra}{numero}"
            texto = str(valor)
            idx = indice_texto[texto]
            celulas.append(f'<c r="{ref}" t="s"><v>{idx}</v></c>')
        return f'<row r="{numero}">{"".join(celulas)}</row>'

    linhas_xml = [_linha_xml(1, cabecalho)]
    for i, linha in enumerate(linhas, start=2):
        linhas_xml.append(_linha_xml(i, linha))

    sheet = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<sheetData>{"".join(linhas_xml)}</sheetData></worksheet>'
    )

    with zipfile.ZipFile(caminho, "w") as z:
        z.writestr("[Content_Types].xml", _CONTENT_TYPES)
        z.writestr("xl/workbook.xml", _WORKBOOK)
        z.writestr("xl/sharedStrings.xml", shared)
        z.writestr("xl/worksheets/sheet1.xml", sheet)


class TestLerArquivo(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self._tmp.cleanup()

    def test_le_csv_com_ponto_e_virgula(self):
        caminho = Path(self._tmp.name) / "lote.csv"
        caminho.write_text("tomador;servico;valor\nUnimed SJC;Consulta;450,00\n", encoding="utf-8-sig")
        linhas = lote.ler_arquivo(str(caminho))
        self.assertEqual(linhas, [{"tomador": "Unimed SJC", "servico": "Consulta", "valor": "450,00"}])

    def test_le_csv_com_virgula(self):
        caminho = Path(self._tmp.name) / "lote.csv"
        caminho.write_text("tomador,servico,valor\nUnimed SJC,Consulta,450.00\n", encoding="utf-8-sig")
        linhas = lote.ler_arquivo(str(caminho))
        self.assertEqual(linhas[0]["valor"], "450.00")

    def test_le_xlsx_minimo(self):
        caminho = Path(self._tmp.name) / "lote.xlsx"
        _criar_xlsx_minimo(
            caminho, ["tomador", "servico", "valor"],
            [["Unimed SJC", "Consulta", "450.00"], ["Oficina do Ze", "Retifica", "1800.00"]],
        )
        linhas = lote.ler_arquivo(str(caminho))
        self.assertEqual(len(linhas), 2)
        self.assertEqual(linhas[0]["tomador"], "Unimed SJC")
        self.assertEqual(linhas[1]["valor"], "1800.00")

    def test_formato_nao_suportado(self):
        caminho = Path(self._tmp.name) / "lote.txt"
        caminho.write_text("qualquer coisa")
        with self.assertRaises(ValueError):
            lote.ler_arquivo(str(caminho))


class TestRevisarEEmitir(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = repo.Repositorio(Path(self._tmp.name) / "teste.db")
        self.pid = self.repo.criar_prestador(
            nome_exibicao="Prestador", cnpj="11111111000111", im="1", codigo_municipio="3549904",
        )
        self.repo.criar_tomador(self.pid, doc="11111111111", nome="Unimed SJC")
        self.repo.criar_modelo_servico(
            self.pid, descricao="Consulta", cod_tributacao_nacional="010101",
            cod_tributacao_municipal="0101010000", cod_nbs="107011900", valor_padrao="450.00",
        )

    def tearDown(self):
        self.repo.fechar()
        self._tmp.cleanup()

    def test_linha_valida_casa_tomador_e_modelo(self):
        linhas = lote.revisar(self.repo, self.pid, [
            {"tomador": "Unimed SJC", "servico": "Consulta", "valor": "500,00"},
        ])
        self.assertTrue(linhas[0].valida)
        self.assertEqual(linhas[0].valor, "500.00")

    def test_tomador_nao_cadastrado_gera_erro(self):
        linhas = lote.revisar(self.repo, self.pid, [
            {"tomador": "Fulano Inexistente", "servico": "Consulta", "valor": "100.00"},
        ])
        self.assertFalse(linhas[0].valida)
        self.assertIn("não encontrado", linhas[0].erro)

    def test_servico_nao_cadastrado_gera_erro(self):
        linhas = lote.revisar(self.repo, self.pid, [
            {"tomador": "Unimed SJC", "servico": "Servico Inexistente", "valor": "100.00"},
        ])
        self.assertFalse(linhas[0].valida)
        self.assertIn("não encontrado", linhas[0].erro)

    def test_valor_invalido_gera_erro(self):
        linhas = lote.revisar(self.repo, self.pid, [
            {"tomador": "Unimed SJC", "servico": "Consulta", "valor": "abacate"},
        ])
        self.assertFalse(linhas[0].valida)
        self.assertIn("Valor inválido", linhas[0].erro)

    def test_emitir_linhas_validas_ignora_invalidas(self):
        linhas = lote.revisar(self.repo, self.pid, [
            {"tomador": "Unimed SJC", "servico": "Consulta", "valor": "500.00"},
            {"tomador": "Nao Existe", "servico": "Consulta", "valor": "100.00"},
        ])
        criadas = lote.emitir_linhas_validas(self.repo, self.pid, linhas)
        self.assertEqual(len(criadas), 1)
        self.assertEqual(len(self.repo.listar_notas(self.pid)), 1)

    def test_emitir_linhas_validas_herda_retencao_padrao_do_tomador(self):
        """docs/auditoria-2.md, Onda 2 item 1 -- achado novo: antes desta
        correção, TODA nota importada em lote saía sem nenhuma retenção,
        mesmo pra um tomador (convênio) com IRRF configurado -- diferente
        da emissão avulsa e da mensalidade automática, que já herdavam
        certo. Prova que o lote agora se comporta igual aos outros dois
        caminhos."""
        tid = self.repo.criar_tomador(
            self.pid, doc="22222222000122", nome="Convenio Com Retencao",
            retencoes={"retem_irrf": True, "aliquota_irrf": "1.5"},
        )
        linhas = lote.revisar(self.repo, self.pid, [
            {"tomador": "Convenio Com Retencao", "servico": "Consulta", "valor": "1000.00"},
        ])
        criadas = lote.emitir_linhas_validas(self.repo, self.pid, linhas)
        nota = self.repo.obter_nota(self.pid, criadas[0])
        self.assertEqual(nota["retem_irrf"], 1)
        self.assertEqual(nota["aliquota_irrf"], "1.5")


if __name__ == "__main__":
    unittest.main()
