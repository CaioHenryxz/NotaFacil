"""Testes de app/core/pastas.py: sanitizacao de nomes e organizacao em disco
(espec-mvp-emissor-nfse.md, secao 5b)."""
import datetime
import tempfile
import unittest
from pathlib import Path

from app.core import pastas


class TestSanitizacao(unittest.TestCase):
    def test_remove_caracteres_proibidos_do_windows(self):
        sujo = 'Clinica: "Dr. João" / Cardoso <SP> | teste?*'
        limpo = pastas.sanitizar_nome_arquivo(sujo)
        for proibido in '\\/:*?"<>|':
            self.assertNotIn(proibido, limpo)

    def test_preserva_acentos(self):
        self.assertEqual(pastas.sanitizar_nome_arquivo("Dr. João Cardoso"), "Dr. João Cardoso")
        self.assertIn("Março", pastas.nome_pasta_mes(3))

    def test_colapsa_espacos_e_remove_ponto_final(self):
        self.assertEqual(pastas.sanitizar_nome_arquivo("Nome   Com   Espaços.  "), "Nome Com Espaços")

    def test_nome_vazio_apos_sanitizar(self):
        self.assertEqual(pastas.sanitizar_nome_arquivo('///:::'), "sem-nome")

    def test_limite_de_tamanho(self):
        nome = "a" * 300
        self.assertEqual(len(pastas.sanitizar_nome_arquivo(nome, limite=50)), 50)

    def test_mes_invalido(self):
        with self.assertRaises(ValueError):
            pastas.nome_pasta_mes(13)


class TestFormatacaoValor(unittest.TestCase):
    def test_formata_com_separador_de_milhar_e_virgula_decimal(self):
        self.assertEqual(pastas.formatar_valor_br("1500.5"), "1.500,50")
        self.assertEqual(pastas.formatar_valor_br(1000000), "1.000.000,00")
        self.assertEqual(pastas.formatar_valor_br("9.9"), "9,90")

    def test_nome_base_arquivo(self):
        base = pastas.nome_base_arquivo("12", "Unimed SJC", "1500.00")
        self.assertEqual(base, "NFSe 12 - Unimed SJC - R$ 1.500,00")


class TestOrganizacaoEmDisco(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.pasta_base = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_salvar_nota_cria_estrutura_emitidas(self):
        xml_path, pdf_path = pastas.salvar_nota(
            self.pasta_base, "Dr. João Cardoso",
            numero="7", nome_tomador="Unimed SJC", valor="1500.00",
            data_emissao=datetime.date(2026, 9, 15),
            xml_bytes=b"<xml/>",
        )
        esperado = (
            self.pasta_base / "Dr. João Cardoso" / "2026" / "09 - Setembro" / "Emitidas"
            / "NFSe 7 - Unimed SJC - R$ 1.500,00.xml"
        )
        self.assertEqual(xml_path, esperado)
        self.assertTrue(xml_path.exists())
        self.assertEqual(xml_path.read_bytes(), b"<xml/>")
        self.assertIsNone(pdf_path)

    def test_pdf_e_xml_ficam_juntos_mesmo_nome_base(self):
        xml_path, pdf_path = pastas.salvar_nota(
            self.pasta_base, "Oficina do Zé", numero="1", nome_tomador="Cliente X",
            valor="100.00", data_emissao=datetime.date(2026, 1, 5),
            xml_bytes=b"<xml/>", pdf_bytes=b"%PDF-1.4",
        )
        self.assertEqual(xml_path.with_suffix(".pdf"), pdf_path)
        self.assertTrue(pdf_path.exists())

    def test_cancelar_move_para_canceladas_sem_apagar(self):
        xml_path, pdf_path = pastas.salvar_nota(
            self.pasta_base, "Dra. Ana Lima", numero="3", nome_tomador="Paciente Y",
            valor="250.00", data_emissao=datetime.date(2026, 3, 10),
            xml_bytes=b"<xml/>", pdf_bytes=b"%PDF-1.4",
        )
        novo_xml, novo_pdf = pastas.cancelar_nota(xml_path, pdf_path)

        self.assertFalse(xml_path.exists(), "arquivo original nao pode continuar em Emitidas/")
        self.assertFalse(pdf_path.exists())
        self.assertTrue(novo_xml.exists())
        self.assertTrue(novo_pdf.exists())
        self.assertEqual(novo_xml.parent.name, "Canceladas")
        self.assertEqual(novo_xml.name, xml_path.name)

    def test_reemissao_novo_numero_nao_sobrescreve_antigo(self):
        antigo, _ = pastas.salvar_nota(
            self.pasta_base, "P", numero="1", nome_tomador="T", valor="10.00",
            data_emissao=datetime.date(2026, 1, 1), xml_bytes=b"antigo",
        )
        novo, _ = pastas.salvar_nota(
            self.pasta_base, "P", numero="2", nome_tomador="T", valor="10.00",
            data_emissao=datetime.date(2026, 1, 1), xml_bytes=b"novo",
        )
        self.assertNotEqual(antigo, novo)
        self.assertTrue(antigo.exists())
        self.assertEqual(antigo.read_bytes(), b"antigo")


if __name__ == "__main__":
    unittest.main()
