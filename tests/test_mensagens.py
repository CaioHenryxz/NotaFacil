"""Testes de app/core/mensagens.py — a Etapa 2 exige "erros da API traduzidos
para mensagens compreensiveis". Aqui garantimos que a traducao acontece e que
nunca vaza jargao tecnico (HTTP, XML, schema) pro texto final."""
import unittest

from app.core import mensagens
from app.fiscal import api_nacional, assinador


class TestTraduzirErro(unittest.TestCase):
    def test_erro_validacao_com_trecho_conhecido(self):
        texto = mensagens.traduzir_erro(api_nacional.ErroValidacao("E0310: nao existe"))
        self.assertIn("tipo de servico", texto.lower())
        self.assertNotIn("E0310", texto)

    def test_erro_validacao_sem_trecho_conhecido_ainda_assim_traduz(self):
        texto = mensagens.traduzir_erro(api_nacional.ErroValidacao("XPTO123: outro erro qualquer"))
        self.assertIn("rejeitou", texto.lower())

    def test_erro_rede_nao_assusta_o_usuario(self):
        texto = mensagens.traduzir_erro(api_nacional.ErroRede("Connection timed out"))
        self.assertIn("tentar de novo", texto.lower())
        self.assertNotIn("timed out", texto.lower())

    def test_certificado_nao_configurado(self):
        texto = mensagens.traduzir_erro(assinador.CertificadoNaoConfigurado("sem senha"))
        self.assertIn("certificado", texto.lower())

    def test_senha_ou_pfx_invalido_traduz_mensagem_da_lib_cryptography(self):
        # mensagem literal que python-cryptography levanta (senha errada ou
        # arquivo .pfx corrompido) — nao pode vazar crua pro usuario final.
        texto = mensagens.traduzir_erro(ValueError("Invalid password or PKCS12 data"))
        self.assertIn("certificado", texto.lower())
        self.assertNotIn("PKCS12", texto)

    def test_traduzir_motivo_rejeicao_a_partir_de_texto_salvo(self):
        texto = mensagens.traduzir_motivo_rejeicao("E0714: erro na assinatura")
        self.assertIn("assinatura", texto.lower())

    def test_motivo_http_403_explica_problema_de_certificado_nao_de_dados(self):
        texto = mensagens.traduzir_motivo_rejeicao("HTTP 403")
        self.assertIn("certificado", texto.lower())
        self.assertNotIn("HTTP 403", texto)

    def test_motivo_http_401_explica_problema_de_certificado_nao_de_dados(self):
        texto = mensagens.traduzir_motivo_rejeicao("HTTP 401")
        self.assertIn("certificado", texto.lower())

    def test_erro_desconhecido_tem_fallback_generico(self):
        texto = mensagens.traduzir_erro(RuntimeError("algo bem obscuro"))
        self.assertIn("algo bem obscuro", texto)


class TestMensagensDeAutomacao(unittest.TestCase):
    """Etapa 3: notificações da bandeja (item 1 e 2)."""

    def test_mensagem_catchup_singular(self):
        self.assertEqual(mensagens.mensagem_catchup(1), "1 mensalidade atrasada foi emitida agora.")

    def test_mensagem_catchup_plural(self):
        self.assertEqual(mensagens.mensagem_catchup(3), "3 mensalidades atrasadas foram emitidas agora.")

    def test_mensagem_ciclo_automatico_sem_nada_e_none(self):
        self.assertIsNone(mensagens.mensagem_ciclo_automatico(0, 0))

    def test_mensagem_ciclo_automatico_so_emitidas(self):
        self.assertEqual(mensagens.mensagem_ciclo_automatico(2, 0), "2 nota(s) emitida(s) agora.")

    def test_mensagem_ciclo_automatico_emitidas_e_rejeitadas(self):
        texto = mensagens.mensagem_ciclo_automatico(2, 1)
        self.assertIn("2 nota(s) emitida(s)", texto)
        self.assertIn("1 rejeitada(s)", texto)

    def test_mensagem_certificado_vencendo_dias_positivos(self):
        texto = mensagens.mensagem_certificado_vencendo("Dr. João", 7)
        self.assertIn("Dr. João", texto)
        self.assertIn("7 dias", texto)

    def test_mensagem_certificado_ja_vencido(self):
        texto = mensagens.mensagem_certificado_vencendo("Dr. João", 0)
        self.assertIn("já venceu", texto)


if __name__ == "__main__":
    unittest.main()
