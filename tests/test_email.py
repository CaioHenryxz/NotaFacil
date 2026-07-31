"""Testes de app/core/email.py — espec Etapa 3 item 4: "falha de e-mail NÃO
derruba a emissão — só marca 'e-mail não enviado' com botão 'Reenviar'".
Nenhum destes testes toca em SMTP de verdade (smtplib.SMTP e substituido)."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app import repo
from app.core import email as email_service
from app.core import email_config


class TestEnviarNotaEmail(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = repo.Repositorio(Path(self._tmp.name) / "teste.db")
        self.pid = self.repo.criar_prestador(
            nome_exibicao="Prestador Teste", cnpj="11111111000111", im="1", codigo_municipio="3549904",
        )
        self.tid = self.repo.criar_tomador(self.pid, doc="11111111111", nome="Tomador Teste", email="tomador@example.com")
        self.mid = self.repo.criar_modelo_servico(
            self.pid, descricao="Servico", cod_tributacao_nacional="010101",
            cod_tributacao_municipal="0101010000", cod_nbs="107011900", valor_padrao="100.00",
        )
        self.nota_id = self.repo.criar_nota(self.pid, tomador_id=self.tid, modelo_id=self.mid, valor="100.00")

        self.xml_path = Path(self._tmp.name) / "nota.xml"
        self.xml_path.write_bytes(b"<NFSe/>")
        self.repo.marcar_emitida(
            self.pid, self.nota_id, chave_acesso="CHAVE1", xml_conteudo="<NFSe/>", xml_path=str(self.xml_path),
        )

    def tearDown(self):
        self.repo.fechar()
        self._tmp.cleanup()

    def _prestador_tomador_nota(self):
        return (
            self.repo.obter_prestador(self.pid),
            self.repo.obter_tomador(self.pid, self.tid),
            self.repo.obter_nota(self.pid, self.nota_id),
        )

    def test_sem_smtp_configurado_marca_falha_sem_levantar_excecao(self):
        prestador, tomador, nota = self._prestador_tomador_nota()
        email_service.enviar_nota_email(self.repo, prestador, tomador, nota)  # nao deve levantar
        nota_atualizada = self.repo.obter_nota(self.pid, self.nota_id)
        self.assertEqual(nota_atualizada["email_status"], repo.EMAIL_FALHOU)
        self.assertIn("SMTP", nota_atualizada["email_erro"])

    def test_tomador_sem_email_nao_e_marcado_como_falha(self):
        tid_sem_email = self.repo.criar_tomador(self.pid, doc="22222222222", nome="Sem Email")
        nota_id = self.repo.criar_nota(self.pid, tomador_id=tid_sem_email, modelo_id=self.mid, valor="50.00")
        self.repo.marcar_emitida(self.pid, nota_id, chave_acesso="C2", xml_conteudo="<NFSe/>", xml_path=str(self.xml_path))

        prestador = self.repo.obter_prestador(self.pid)
        tomador = self.repo.obter_tomador(self.pid, tid_sem_email)
        nota = self.repo.obter_nota(self.pid, nota_id)
        email_service.enviar_nota_email(self.repo, prestador, tomador, nota)

        nota_atualizada = self.repo.obter_nota(self.pid, nota_id)
        self.assertEqual(nota_atualizada["email_status"], repo.EMAIL_NAO_ENVIADO, "sem e-mail nao e falha, e' um no-op")

    @patch("smtplib.SMTP")
    def test_sucesso_com_smtp_configurado_marca_enviado(self, smtp_mock):
        email_config.salvar_smtp(self.repo, host="smtp.example.com", porta=587, usuario="a@example.com", senha="123")
        instancia = MagicMock()
        smtp_mock.return_value.__enter__.return_value = instancia

        prestador, tomador, nota = self._prestador_tomador_nota()
        email_service.enviar_nota_email(self.repo, prestador, tomador, nota)

        instancia.starttls.assert_called_once()
        instancia.login.assert_called_once_with("a@example.com", "123")
        instancia.send_message.assert_called_once()
        nota_atualizada = self.repo.obter_nota(self.pid, self.nota_id)
        self.assertEqual(nota_atualizada["email_status"], repo.EMAIL_ENVIADO)
        self.assertIsNone(nota_atualizada["email_erro"])

    @patch("smtplib.SMTP")
    def test_falha_de_conexao_marca_falhou_com_motivo(self, smtp_mock):
        email_config.salvar_smtp(self.repo, host="smtp.example.com", porta=587, usuario="a@example.com", senha="123")
        smtp_mock.side_effect = OSError("conexao recusada")

        prestador, tomador, nota = self._prestador_tomador_nota()
        email_service.enviar_nota_email(self.repo, prestador, tomador, nota)

        nota_atualizada = self.repo.obter_nota(self.pid, self.nota_id)
        self.assertEqual(nota_atualizada["email_status"], repo.EMAIL_FALHOU)
        self.assertIn("conexao recusada", nota_atualizada["email_erro"])

    @patch("smtplib.SMTP")
    def test_reenviar_apos_falha_funciona(self, smtp_mock):
        # 1a tentativa: sem SMTP configurado -> falha
        prestador, tomador, nota = self._prestador_tomador_nota()
        email_service.enviar_nota_email(self.repo, prestador, tomador, nota)
        self.assertEqual(self.repo.obter_nota(self.pid, self.nota_id)["email_status"], repo.EMAIL_FALHOU)

        # configura o SMTP e reenvia (botao "Reenviar" do Historico)
        email_config.salvar_smtp(self.repo, host="smtp.example.com", porta=587, usuario="a@example.com", senha="123")
        instancia = MagicMock()
        smtp_mock.return_value.__enter__.return_value = instancia
        nota_atual = self.repo.obter_nota(self.pid, self.nota_id)
        email_service.reenviar_nota_email(self.repo, prestador, tomador, nota_atual)

        self.assertEqual(self.repo.obter_nota(self.pid, self.nota_id)["email_status"], repo.EMAIL_ENVIADO)


if __name__ == "__main__":
    unittest.main()
