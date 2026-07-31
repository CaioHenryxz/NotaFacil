"""Testes da leitura de certificado em app/fiscal/assinador.py: extrair
CNPJ/CPF de dentro do .pfx pro cadastro de prestador (Etapa 2, tela 1)."""
import datetime
import tempfile
import unittest
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import BestAvailableEncryption, pkcs12
from cryptography.x509.oid import NameOID, ObjectIdentifier

from app.fiscal import assinador


def _gerar_certificado(common_name: str, atributos_extras=None):
    chave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    atributos = [x509.NameAttribute(NameOID.COMMON_NAME, common_name)]
    if atributos_extras:
        atributos.extend(atributos_extras)
    nome = x509.Name(atributos)
    agora = datetime.datetime.now(datetime.timezone.utc)
    certificado = (
        x509.CertificateBuilder()
        .subject_name(nome).issuer_name(nome).public_key(chave.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(agora).not_valid_after(agora + datetime.timedelta(days=30))
        .sign(chave, hashes.SHA256())
    )
    return chave, certificado


class TestExtracaoPorCN(unittest.TestCase):
    def test_extrai_cnpj_do_cn_no_padrao_nome_dois_pontos_documento(self):
        _chave, cert = _gerar_certificado("EMPRESA TESTE LTDA:11222333000181")
        info = assinador.inspecionar_certificado(cert)
        self.assertEqual(info.documento, "11222333000181")
        self.assertEqual(info.tipo_documento, "CNPJ")

    def test_extrai_cpf_do_cn(self):
        _chave, cert = _gerar_certificado("FULANO DE TAL:12345678909")
        info = assinador.inspecionar_certificado(cert)
        self.assertEqual(info.documento, "12345678909")
        self.assertEqual(info.tipo_documento, "CPF")

    def test_cn_sem_documento_nao_quebra(self):
        _chave, cert = _gerar_certificado("Certificado de Teste Sem Documento")
        info = assinador.inspecionar_certificado(cert)
        self.assertIsNone(info.documento)
        self.assertIsNone(info.tipo_documento)
        self.assertEqual(info.nome_titular, "Certificado de Teste Sem Documento")

    def test_valido_ate_e_a_data_de_expiracao(self):
        _chave, cert = _gerar_certificado("Teste:12345678909")
        info = assinador.inspecionar_certificado(cert)
        self.assertEqual(info.valido_ate, cert.not_valid_after_utc.date())


class TestExtracaoPorOidIcpBrasil(unittest.TestCase):
    def test_oid_de_cnpj_tem_prioridade_sobre_o_cn(self):
        atributo_oid = x509.NameAttribute(ObjectIdentifier("2.16.76.1.3.3"), "99888777000166")
        _chave, cert = _gerar_certificado("NOME QUALQUER:11222333000181", [atributo_oid])
        info = assinador.inspecionar_certificado(cert)
        self.assertEqual(info.documento, "99888777000166")
        self.assertEqual(info.tipo_documento, "CNPJ")


class TestCarregarPfxComSenha(unittest.TestCase):
    def test_abre_pfx_com_senha_correta(self):
        chave, cert = _gerar_certificado("Teste:11222333000181")
        with tempfile.TemporaryDirectory() as tmp:
            caminho = Path(tmp) / "cert.pfx"
            pfx_bytes = pkcs12.serialize_key_and_certificates(
                name=b"teste", key=chave, cert=cert, cas=None,
                encryption_algorithm=BestAvailableEncryption(b"senha-correta"),
            )
            caminho.write_bytes(pfx_bytes)
            chave_lida, cert_lido, extras = assinador.carregar_pfx_com_senha(str(caminho), "senha-correta")
            self.assertIsNotNone(chave_lida)
            self.assertEqual(cert_lido.serial_number, cert.serial_number)

    def test_senha_errada_levanta_erro_claro(self):
        chave, cert = _gerar_certificado("Teste:11222333000181")
        with tempfile.TemporaryDirectory() as tmp:
            caminho = Path(tmp) / "cert.pfx"
            pfx_bytes = pkcs12.serialize_key_and_certificates(
                name=b"teste", key=chave, cert=cert, cas=None,
                encryption_algorithm=BestAvailableEncryption(b"senha-correta"),
            )
            caminho.write_bytes(pfx_bytes)
            with self.assertRaises(Exception):
                assinador.carregar_pfx_com_senha(str(caminho), "senha-errada")


if __name__ == "__main__":
    unittest.main()
