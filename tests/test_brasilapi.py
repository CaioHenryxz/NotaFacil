"""Testes de app/core/brasilapi.py — sem tocar na rede de verdade (httpx.get
e substituido por um dublê)."""
import unittest
from unittest.mock import patch

from app.core import brasilapi


class _RespostaFalsa:
    def __init__(self, status_code, corpo=None, texto=""):
        self.status_code = status_code
        self._corpo = corpo or {}
        self.text = texto

    def json(self):
        return self._corpo


class TestSomenteDigitos(unittest.TestCase):
    def test_remove_pontuacao(self):
        self.assertEqual(brasilapi.somente_digitos("12.345.678/0001-99"), "12345678000199")

    def test_cnpj_com_tamanho_errado_levanta_value_error(self):
        with self.assertRaises(ValueError):
            brasilapi.buscar_cnpj("123")


class TestBuscarCnpj(unittest.TestCase):
    def test_sucesso_normaliza_campos(self):
        corpo = {
            "razao_social": "EMPRESA TESTE LTDA", "nome_fantasia": "TESTE",
            "logradouro": "RUA A", "numero": "10", "bairro": "CENTRO",
            "municipio": "SAO JOSE DOS CAMPOS", "uf": "SP", "cep": "12200000",
            "codigo_municipio_ibge": 3549904, "email": "a@b.com", "ddd_telefone_1": "1234567890",
            "descricao_situacao_cadastral": "ATIVA",
        }
        with patch("httpx.get", return_value=_RespostaFalsa(200, corpo)):
            dados = brasilapi.buscar_cnpj("12.345.678/0001-99")
        self.assertEqual(dados.cnpj, "12345678000199")
        self.assertEqual(dados.codigo_municipio_ibge, "3549904")
        self.assertIn("RUA A", dados.endereco_formatado)
        self.assertIn("SAO JOSE DOS CAMPOS/SP", dados.endereco_formatado)

    def test_404_levanta_cnpj_nao_encontrado(self):
        with patch("httpx.get", return_value=_RespostaFalsa(404)):
            with self.assertRaises(brasilapi.CnpjNaoEncontrado):
                brasilapi.buscar_cnpj("12345678000199")

    def test_erro_5xx_levanta_erro_consulta(self):
        with patch("httpx.get", return_value=_RespostaFalsa(500, texto="erro interno")):
            with self.assertRaises(brasilapi.ErroConsultaCnpj):
                brasilapi.buscar_cnpj("12345678000199")

    def test_falha_de_rede_levanta_erro_consulta(self):
        import httpx as httpx_mod
        with patch("httpx.get", side_effect=httpx_mod.ConnectError("sem rede")):
            with self.assertRaises(brasilapi.ErroConsultaCnpj):
                brasilapi.buscar_cnpj("12345678000199")


if __name__ == "__main__":
    unittest.main()
