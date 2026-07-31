"""Testes de app/core/fechamento.py — Etapa 3 item 6, espec §2 item 9b:
"gera Resumo-<mês>.csv e um ZIP com os XMLs dentro da pasta do mês"."""
import datetime
import tempfile
import unittest
import zipfile
from pathlib import Path

from app import repo
from app.core import fechamento, pastas


class TestFecharMes(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.pasta_base = Path(self._tmp.name) / "Notas Fiscais"
        self.repo = repo.Repositorio(Path(self._tmp.name) / "teste.db")
        self.pid = self.repo.criar_prestador(
            nome_exibicao="Dr. Teste", cnpj="11111111000111", im="1", codigo_municipio="3549904",
        )
        self.tid = self.repo.criar_tomador(self.pid, doc="11111111111", nome="Tomador Teste")
        self.mid = self.repo.criar_modelo_servico(
            self.pid, descricao="Servico", cod_tributacao_nacional="010101",
            cod_tributacao_municipal="0101010000", cod_nbs="107011900", valor_padrao="100.00",
        )

    def tearDown(self):
        self.repo.fechar()
        self._tmp.cleanup()

    def _emitir_nota_de_mentira(self, valor: str, mes_emitida: str) -> int:
        nota_id = self.repo.criar_nota(self.pid, tomador_id=self.tid, modelo_id=self.mid, valor=valor)
        xml_path, _ = pastas.salvar_nota(
            self.pasta_base, "Dr. Teste", numero=str(nota_id), nome_tomador="Tomador Teste",
            valor=valor, data_emissao=datetime.date.fromisoformat(f"{mes_emitida}-01"),
            xml_bytes=b"<NFSe/>",
        )
        self.repo.marcar_emitida(
            self.pid, nota_id, chave_acesso=f"CHAVE-{nota_id}", xml_conteudo="<NFSe/>",
            xml_path=str(xml_path), emitida_em=datetime.datetime.fromisoformat(f"{mes_emitida}-05T10:00:00"),
        )
        return nota_id

    def test_gera_resumo_e_zip_com_as_notas_do_mes(self):
        self._emitir_nota_de_mentira("100.00", "2026-09")
        self._emitir_nota_de_mentira("200.00", "2026-09")
        self._emitir_nota_de_mentira("300.00", "2026-10")  # mes diferente, nao deve entrar

        resultado = fechamento.fechar_mes(self.repo, self.pid, self.pasta_base, 2026, 9)

        self.assertEqual(resultado.quantidade_notas, 2)
        self.assertTrue(resultado.resumo_path.exists())
        self.assertTrue(resultado.zip_path.exists())
        self.assertEqual(resultado.mes_nome, "Setembro")

        conteudo_csv = resultado.resumo_path.read_text(encoding="utf-8-sig")
        self.assertIn("100.00", conteudo_csv)
        self.assertIn("200.00", conteudo_csv)
        self.assertNotIn("300.00", conteudo_csv)

        with zipfile.ZipFile(resultado.zip_path) as z:
            self.assertEqual(len(z.namelist()), 2)

    def test_mes_sem_notas_retorna_zero(self):
        resultado = fechamento.fechar_mes(self.repo, self.pid, self.pasta_base, 2026, 1)
        self.assertEqual(resultado.quantidade_notas, 0)

    def test_arquivos_ficam_dentro_da_pasta_do_mes(self):
        self._emitir_nota_de_mentira("100.00", "2026-09")
        resultado = fechamento.fechar_mes(self.repo, self.pid, self.pasta_base, 2026, 9)
        pasta_esperada = pastas.pasta_mes(self.pasta_base, "Dr. Teste", 2026, 9)
        self.assertEqual(resultado.resumo_path.parent, pasta_esperada)
        self.assertEqual(resultado.zip_path.parent, pasta_esperada)


if __name__ == "__main__":
    unittest.main()
