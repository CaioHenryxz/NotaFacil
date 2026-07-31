"""Testes de app/fiscal/api_nacional.py — foco em _extrair_mensagem_erro, que
decide o que vira `notas.motivo_rejeicao` quando a Receita responde 4xx.
Um corpo de erro nao-JSON (pagina de erro de um proxy/IIS, por exemplo) nunca
pode vazar cru pra tela (bug real: um 403 do IIS aparecia como o motivo
completo em HTML pro usuario)."""
import unittest

import httpx

from app.fiscal import api_nacional


class TestExtrairMensagemErro(unittest.TestCase):
    def test_corpo_json_lista_vira_codigo_e_descricao(self):
        resposta = httpx.Response(400, json=[{"Codigo": "E0310", "Descricao": "erro tal"}])
        self.assertEqual(api_nacional._extrair_mensagem_erro(resposta), "E0310: erro tal")

    def test_corpo_json_dict_vira_codigo_e_descricao(self):
        resposta = httpx.Response(400, json={"Codigo": "E0714", "Descricao": "assinatura invalida"})
        self.assertEqual(api_nacional._extrair_mensagem_erro(resposta), "E0714: assinatura invalida")

    def test_corpo_html_de_erro_de_infraestrutura_nao_vaza_cru(self):
        html = '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>403 - Forbidden</title></head><body>Access is denied.</body></html>'
        resposta = httpx.Response(403, content=html.encode("iso-8859-1"))
        self.assertEqual(api_nacional._extrair_mensagem_erro(resposta), "HTTP 403")

    def test_corpo_texto_curto_sem_html_e_preservado(self):
        resposta = httpx.Response(400, content=b"CNPJ invalido")
        self.assertEqual(api_nacional._extrair_mensagem_erro(resposta), "CNPJ invalido")

    def test_corpo_vazio_vira_apenas_status(self):
        resposta = httpx.Response(500, content=b"")
        self.assertEqual(api_nacional._extrair_mensagem_erro(resposta), "HTTP 500")


if __name__ == "__main__":
    unittest.main()
