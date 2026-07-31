"""Testes de app/fiscal/danfse_builder.py — geração LOCAL do DANFSe
(NT SE/CGNFS-e nº 008/2026, v1.02). Cobre especialmente: (a) a regra crítica
de nunca inventar/completar dado que não esteja no XML da NFS-e, (b) a
lógica exata de vPis/vCofins/tpRetPisCofins da v1.02, (c) supressão de
blocos (tomador ausente, destinatário == tomador)."""
import unittest
from io import BytesIO

from pypdf import PdfReader

from app.fiscal import danfse_builder as db

NS = "http://www.sped.fazenda.gov.br/nfse"


def _xml_nfse(
    *, tp_amb="1", tp_ret_pis_cofins=None, v_ret_csll=None, v_pis=None, v_cofins=None,
    com_toma=True, com_dest=False,
) -> bytes:
    toma = (
        "<toma><CNPJ>12345678000199</CNPJ><xNome>Unimed SJC</xNome></toma>"
        if com_toma else "<toma></toma>"
    )
    dest = (
        "<dest><CNPJ>99999999000199</CNPJ><xNome>Outro Destinatário</xNome></dest>"
        if com_dest else ""
    )
    trib_fed = ""
    if any(v is not None for v in (tp_ret_pis_cofins, v_ret_csll, v_pis, v_cofins)):
        campos = []
        if tp_ret_pis_cofins is not None:
            campos.append(f"<tpRetPisCofins>{tp_ret_pis_cofins}</tpRetPisCofins>")
        if v_ret_csll is not None:
            campos.append(f"<vRetCSLL>{v_ret_csll}</vRetCSLL>")
        if v_pis is not None:
            campos.append(f"<vPis>{v_pis}</vPis>")
        if v_cofins is not None:
            campos.append(f"<vCofins>{v_cofins}</vCofins>")
        trib_fed = f"<tribFed>{''.join(campos)}</tribFed>"

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<NFSe xmlns="{NS}">
  <infNFSe Id="X">
    <id>35260711222333000181000053500000000123456781</id>
    <nNFSe>123456781</nNFSe>
    <cStat>100</cStat>
    <dhProc>2026-07-23T14:05:00-03:00</dhProc>
    <ambGer>Sistema Nacional NFS-e</ambGer>
    {dest}
    <valores><vLiq>965.00</vLiq></valores>
    <DPS>
      <infDPS Id="Y">
        <tpAmb>{tp_amb}</tpAmb>
        <dhEmi>2026-07-23T14:04:50-03:00</dhEmi>
        <serie>1</serie>
        <nDPS>1</nDPS>
        <dCompet>2026-07-23</dCompet>
        <tpEmit>1</tpEmit>
        <prest><CNPJ>11222333000181</CNPJ><IM>437791</IM><xNome>Dr. Teste</xNome>
          <regTrib><opSimpNac>3</opSimpNac><regEspTrib>0</regEspTrib></regTrib>
        </prest>
        {toma}
        <serv><locPrest><cLocPrestacao>3549904</cLocPrestacao></locPrest>
          <cServ><cTribNac>040101</cTribNac><cTribMun>0401010000</cTribMun>
          <xDescServ>Consulta</xDescServ><cNBS>105011900</cNBS></cServ>
        </serv>
        <valores><vServPrest><vServ>1000.00</vServ></vServPrest>
          <trib><tribMun><tribISSQN>1</tribISSQN><tpRetISSQN>1</tpRetISSQN></tribMun>
          {trib_fed}
          <totTrib><indTotTrib>0</indTotTrib></totTrib></trib>
        </valores>
      </infDPS>
    </DPS>
  </infNFSe>
</NFSe>"""
    return xml.encode("utf-8")


def _texto_pdf(pdf_bytes: bytes) -> str:
    return PdfReader(BytesIO(pdf_bytes)).pages[0].extract_text() or ""


class TestExtracaoNuncaInventa(unittest.TestCase):
    def test_campos_basicos_extraidos_corretamente(self):
        dados = db.extrair_dados(db.carregar_nfse(_xml_nfse()))
        self.assertEqual(dados.chave_acesso, "35260711222333000181000053500000000123456781")
        self.assertEqual(dados.numero_nfse, "123456781")
        self.assertEqual(dados.prest_nome, "Dr. Teste")
        self.assertEqual(dados.toma_nome, "Unimed SJC")
        self.assertEqual(dados.v_serv, "1.000,00")

    def test_campo_ausente_no_xml_vira_none_nunca_um_valor_fabricado(self):
        dados = db.extrair_dados(db.carregar_nfse(_xml_nfse()))
        self.assertIsNone(dados.prest_fone)  # nao esta no XML de teste
        self.assertIsNone(dados.v_ret_irrf)  # sem tribFed no XML de teste

    def test_sem_chave_de_acesso_levanta_erro_claro(self):
        xml_sem_chave = _xml_nfse().replace(
            b"<id>35260711222333000181000053500000000123456781</id>", b"<id></id>"
        )
        with self.assertRaises(db.DadosIncompletosParaDanfse):
            db.montar_danfse_pdf(xml_sem_chave)


class TestSupressaoDeBlocos(unittest.TestCase):
    def test_tomador_ausente_e_marcado_para_supressao(self):
        dados = db.extrair_dados(db.carregar_nfse(_xml_nfse(com_toma=False)))
        self.assertFalse(dados.tem_tomador)
        pdf = db.montar_danfse_pdf(_xml_nfse(com_toma=False))
        texto = _texto_pdf(pdf)
        self.assertIn("TOMADOR/ADQUIRENTE DA OPERAÇÃO NÃO IDENTIFICADO NA NFS-e", texto)

    def test_destinatario_igual_ao_tomador_por_padrao(self):
        dados = db.extrair_dados(db.carregar_nfse(_xml_nfse()))  # sem <dest>
        self.assertTrue(dados.destinatario_e_o_tomador)
        pdf = db.montar_danfse_pdf(_xml_nfse())
        texto = _texto_pdf(pdf)
        self.assertIn("O DESTINATÁRIO É O PRÓPRIO TOMADOR/ADQUIRENTE DA OPERAÇÃO", texto)

    def test_intermediario_sempre_suprimido(self):
        """docs/auditoria-2.md, Onda 2 item 5: bloco obrigatorio (NT 2.1.6)
        que faltava inteiro no PDF -- este app nunca gera dado de
        intermediario, entao usa sempre a supressao da Nota 2."""
        pdf = db.montar_danfse_pdf(_xml_nfse())
        texto = _texto_pdf(pdf)
        self.assertIn("INTERMEDIÁRIO DA OPERAÇÃO NÃO IDENTIFICADO NA NFS-e", texto)


class TestLogicaPisCofinsV102(unittest.TestCase):
    """NT-008 v1.02: mudança explícita "Ajuste no tratamento dos campos
    vPis, vCofins e tpRetPisCofins" — a parte mais crítica deste pedido."""

    def test_tp_ret_pis_cofins_1_zera_vpis_e_vcofins_proprios(self):
        dados = db.extrair_dados(db.carregar_nfse(_xml_nfse(
            tp_ret_pis_cofins="1", v_ret_csll="1.00", v_pis="0.65", v_cofins="3.00",
        )))
        self.assertEqual(dados.v_pis_proprio, "0,00")
        self.assertEqual(dados.v_cofins_proprio, "0,00")

    def test_tp_ret_pis_cofins_1_soma_csll_pis_cofins_em_contribuicoes_retidas(self):
        dados = db.extrair_dados(db.carregar_nfse(_xml_nfse(
            tp_ret_pis_cofins="1", v_ret_csll="1.00", v_pis="0.65", v_cofins="3.00",
        )))
        # 1.00 + 0.65 + 3.00 = 4.65
        self.assertEqual(dados.contribuicoes_sociais_retidas, "4,65")

    def test_tp_ret_pis_cofins_diferente_de_1_mostra_vpis_vcofins_normalmente(self):
        dados = db.extrair_dados(db.carregar_nfse(_xml_nfse(
            tp_ret_pis_cofins="2", v_ret_csll="1.00", v_pis="0.65", v_cofins="3.00",
        )))
        self.assertEqual(dados.v_pis_proprio, "0,65")
        self.assertEqual(dados.v_cofins_proprio, "3,00")

    def test_tp_ret_pis_cofins_diferente_de_1_contribuicoes_retidas_e_so_vretcsll(self):
        dados = db.extrair_dados(db.carregar_nfse(_xml_nfse(
            tp_ret_pis_cofins="2", v_ret_csll="1.00", v_pis="0.65", v_cofins="3.00",
        )))
        self.assertEqual(dados.contribuicoes_sociais_retidas, "1,00")

    def test_campo_pis_ausente_no_xml_continua_none_mesmo_com_retencao(self):
        # tpRetPisCofins=1 mas SEM vPis no XML -- nunca fabrica 0,00 pra um
        # campo que nem existe (so' zera o que de fato esta' la').
        dados = db.extrair_dados(db.carregar_nfse(_xml_nfse(tp_ret_pis_cofins="1")))
        self.assertIsNone(dados.v_pis_proprio)
        self.assertIsNone(dados.contribuicoes_sociais_retidas)

    def test_descricao_tp_ret_pis_cofins_1_e_retido_conforme_nt_008_v102(self):
        """Citação direta da NT: 'Quando tpRetPisCofins = 1 (PIS/COFINS
        Retido)' -- 1 significa RETIDO, não "não retido"."""
        dados = db.extrair_dados(db.carregar_nfse(_xml_nfse(tp_ret_pis_cofins="1")))
        self.assertIn("Retido", dados.descricao_tp_ret_pis_cofins)
        self.assertNotIn("Não Retido", dados.descricao_tp_ret_pis_cofins)


class TestGerarPdfCompleto(unittest.TestCase):
    def test_pdf_gerado_e_bem_formado_e_tem_os_dados_essenciais(self):
        pdf = db.montar_danfse_pdf(_xml_nfse())
        leitor = PdfReader(BytesIO(pdf))
        self.assertEqual(len(leitor.pages), 1)
        texto = _texto_pdf(pdf)
        self.assertIn("35260711222333000181000053500000000123456781", texto)
        self.assertIn("Dr. Teste", texto)
        self.assertIn("1.000,00", texto)

    def test_homologacao_mostra_aviso_sem_validade_juridica(self):
        pdf_homologacao = db.montar_danfse_pdf(_xml_nfse(tp_amb="2"))
        pdf_producao = db.montar_danfse_pdf(_xml_nfse(tp_amb="1"))
        self.assertIn("NFS-e SEM VALIDADE JURÍDICA", _texto_pdf(pdf_homologacao))
        self.assertNotIn("NFS-e SEM VALIDADE JURÍDICA", _texto_pdf(pdf_producao))

    def test_cancelada_adiciona_marca_dagua(self):
        pdf_normal = db.montar_danfse_pdf(_xml_nfse())
        pdf_cancelada = db.montar_danfse_pdf(_xml_nfse(), cancelada=True)
        self.assertNotIn("CANCELADA", _texto_pdf(pdf_normal))
        self.assertIn("CANCELADA", _texto_pdf(pdf_cancelada))

    def test_substituida_adiciona_marca_dagua_diferente(self):
        pdf_substituida = db.montar_danfse_pdf(_xml_nfse(), substituida=True)
        self.assertIn("SUBSTITUÍDA", _texto_pdf(pdf_substituida))


if __name__ == "__main__":
    unittest.main()
