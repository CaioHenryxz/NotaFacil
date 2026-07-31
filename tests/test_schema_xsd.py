"""Valida o XML de verdade (montado + assinado por app/fiscal/dps_builder.py)
contra o XSD OFICIAL do Sistema Nacional NFS-e (tests/fixtures/xsd_nfse_v1.01/).

Por que este arquivo existe (docs/auditoria-2.md, seção 8): nenhuma
verificação anterior deste projeto rodava validação de schema de verdade —
todas eram "leitura visual" do XML gerado. Foi assim que o bug do
`cTribMun` (gerado com 10 dígitos; o XSD oficial exige exatamente 3,
`TCCodTribMun` em tiposSimples_v1.01.xsd) passou despercebido por várias
rodadas de auditoria. Este teste roda `lxml.etree.XMLSchema` de verdade, pra
não deixar esse tipo de bug se repetir silenciosamente.

Achado conhecido e IGNORADO de propósito (docs/auditoria-2.md, seção 8.2):
o campo `serie` (tipo `TSSerieDPS`, padrão `^0{0,4}\\d{1,5}$`) nunca valida
pra nenhum valor real, porque XML Schema não trata `^`/`$` como âncoras
(são literais nesse dialeto de regex — Anexo F da spec W3C) — bug de
autoria do XSD **oficial do governo**, não deste app. `_erros_ignorando_serie`
filtra especificamente esse (e só esse) antes de decidir se o documento
passou.
"""
import datetime
import unittest
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from lxml import etree

from app.fiscal import dps_builder as db

XSD_PATH = Path(__file__).parent / "fixtures" / "xsd_nfse_v1.01" / "DPS_v1.01.xsd"
_SCHEMA = etree.XMLSchema(etree.parse(str(XSD_PATH)))


def _gerar_par_chave_certificado():
    chave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    nome = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "TESTE:11222333000181")])
    agora = datetime.datetime.now(datetime.timezone.utc)
    certificado = (
        x509.CertificateBuilder()
        .subject_name(nome).issuer_name(nome).public_key(chave.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(agora).not_valid_after(agora + datetime.timedelta(days=1))
        .sign(chave, hashes.SHA256())
    )
    return chave, certificado


def _dados(cod_tributacao_municipal):
    return db.DadosDPS(
        ambiente="homologacao",
        prestador=db.Prestador(
            documento="11222333000181", inscricao_municipal="437791",
            codigo_municipio="3549904", opcao_simples_nacional="1",
        ),
        tomador=db.Tomador(documento="12345678000199", nome="Unimed Sao Jose dos Campos"),
        servico=db.Servico(
            codigo_tributacao_nacional="040101", codigo_tributacao_municipal=cod_tributacao_municipal,
            codigo_nbs="105011900", descricao="Consulta medica - clinica geral",
            codigo_municipio_prestacao="3549904", valor="300.00", aliquota_iss="2.00",
        ),
    )


def _erros_ignorando_serie_de(erros):
    """docs/auditoria-2.md, secao 8.2 -- o unico erro que este teste tolera."""
    return [erro for erro in erros if "}serie'" not in erro.message]


class TestSchemaXsdOficial(unittest.TestCase):
    """docs/auditoria-2.md, secao 8.1: cTribMun tem que ser OMITIDO ou ter
    exatamente 3 digitos -- nunca mais os 10 digitos do bug antigo."""

    @classmethod
    def setUpClass(cls):
        cls.chave, cls.certificado = _gerar_par_chave_certificado()

    def _validar(self, cod_tributacao_municipal):
        xml_bytes = db.montar_e_assinar(_dados(cod_tributacao_municipal), self.chave, self.certificado)
        xml_doc = etree.fromstring(xml_bytes)
        _SCHEMA.validate(xml_doc)
        return xml_bytes, list(_SCHEMA.error_log)

    def test_ctribmun_omitido_e_valido_contra_o_xsd_oficial(self):
        _, erros = self._validar(None)
        self.assertEqual(_erros_ignorando_serie_de(erros), [], erros)

    def test_ctribmun_string_vazia_e_valido_contra_o_xsd_oficial(self):
        _, erros = self._validar("")
        self.assertEqual(_erros_ignorando_serie_de(erros), [], erros)

    def test_ctribmun_com_3_digitos_e_valido_contra_o_xsd_oficial(self):
        xml_bytes, erros = self._validar("040")
        self.assertIn(b"<cTribMun>040</cTribMun>", xml_bytes)
        self.assertEqual(_erros_ignorando_serie_de(erros), [], erros)

    def test_ctribmun_com_10_digitos_e_invalido_regressao_do_bug_original(self):
        """Canário do bug original (docs/auditoria-2.md, secao 8.1): prova
        que o XSD oficial REALMENTE rejeita 10 digitos -- se algum dia essa
        asserção passar a falhar (ou seja, 10 dígitos virar válido), o XSD
        oficial mudou e esta suíte inteira precisa ser reconferida."""
        _, erros = self._validar("0401010000")
        erros_ctribmun = [e for e in erros if "cTribMun" in e.message]
        self.assertTrue(erros_ctribmun, "esperava um erro de schema pra cTribMun com 10 digitos")

    def test_documento_completo_bate_com_o_xsd_exceto_o_falso_positivo_de_serie(self):
        """Prova mais ampla: o XML inteiro (nao so' o campo cTribMun) segue
        valido contra o schema oficial -- unico erro tolerado e' o de
        `serie`, ja documentado como bug do XSD do governo (secao 8.2)."""
        _, erros = self._validar("040")
        self.assertEqual(len(erros), 1, erros)
        self.assertIn("serie", erros[0].message)


def _dados_com_retencao(**retencao_kwargs):
    return db.DadosDPS(
        ambiente="homologacao",
        prestador=db.Prestador(
            documento="11222333000181", inscricao_municipal="437791",
            codigo_municipio="3549904", opcao_simples_nacional="3",
        ),
        tomador=db.Tomador(documento="12345678000199", nome="Unimed Sao Jose dos Campos"),
        servico=db.Servico(
            codigo_tributacao_nacional="040101", codigo_tributacao_municipal="040",
            codigo_nbs="105011900", descricao="Consulta medica - clinica geral",
            codigo_municipio_prestacao="3549904", valor="1000.00",
            **retencao_kwargs,
        ),
    )


class TestSchemaXsdComRetencaoFederal(unittest.TestCase):
    """docs/auditoria-2.md, Onda 1 item 2: tpRetPisCofins so' e' valido
    DENTRO do subgrupo <piscofins> (que por sua vez exige <CST>, uma
    classificacao fiscal que este app ainda nao decidiu) -- por isso
    `_montar_trib_fed` para de emitir tpRetPisCofins como filho direto de
    tribFed (que e' invalido). Estes testes prova que o grupo tribFed
    continua 100% valido contra o XSD oficial com IRRF/CSLL/INSS retidos,
    mesmo sem tpRetPisCofins."""

    @classmethod
    def setUpClass(cls):
        cls.chave, cls.certificado = _gerar_par_chave_certificado()

    def _validar(self, dados):
        xml_bytes = db.montar_e_assinar(dados, self.chave, self.certificado)
        xml_doc = etree.fromstring(xml_bytes)
        _SCHEMA.validate(xml_doc)
        return xml_bytes, list(_SCHEMA.error_log)

    def test_irrf_retido_e_valido_contra_o_xsd_oficial(self):
        xml_bytes, erros = self._validar(_dados_com_retencao(valor_retido_irrf="15.00"))
        self.assertIn(b"<vRetIRRF>15.00</vRetIRRF>", xml_bytes)
        self.assertNotIn(b"<tpRetPisCofins>", xml_bytes)
        self.assertEqual(_erros_ignorando_serie_de(erros), [], erros)

    def test_pis_cofins_csll_somados_e_valido_contra_o_xsd_oficial(self):
        xml_bytes, erros = self._validar(_dados_com_retencao(
            valor_retido_pis="6.50", valor_retido_cofins="30.00", valor_retido_csll="10.00",
        ))
        self.assertIn(b"<vRetCSLL>46.50</vRetCSLL>", xml_bytes)
        self.assertNotIn(b"<tpRetPisCofins>", xml_bytes)
        self.assertEqual(_erros_ignorando_serie_de(erros), [], erros)

    def test_todas_as_retencoes_juntas_e_valido_contra_o_xsd_oficial(self):
        xml_bytes, erros = self._validar(_dados_com_retencao(
            valor_retido_irrf="15.00", valor_retido_pis="6.50",
            valor_retido_cofins="30.00", valor_retido_csll="10.00", valor_retido_inss="11.00",
        ))
        self.assertEqual(_erros_ignorando_serie_de(erros), [], erros)


if __name__ == "__main__":
    unittest.main()
