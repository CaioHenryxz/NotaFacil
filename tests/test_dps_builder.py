"""Testes de app/fiscal/dps_builder.py — foco na regra fiscal do Simples
Nacional (docs/auditoria.md, Bloco 2.3): prestador optante (MEI ou ME/EPP)
NUNCA pode sair com `pAliq` na nota quando não há retenção — o ISS dele vai
embutido no DAS, não "por fora" nota a nota (ver docstring de
`_pAliq_deve_ser_omitido` pra base normativa completa: regras E1302/E0625/
E0631 do Anexo I do leiaute nacional + LC 123/2006)."""
import unittest

from app.fiscal import dps_builder as db


def _dados(opcao_simples_nacional, aliquota_iss, tipo_retencao_issqn="1"):
    return db.DadosDPS(
        ambiente="homologacao",
        prestador=db.Prestador(
            documento="11222333000181", inscricao_municipal="123456", codigo_municipio="3549904",
            opcao_simples_nacional=opcao_simples_nacional,
        ),
        tomador=db.Tomador(documento="12345678000199", nome="Unimed SJC"),
        servico=db.Servico(
            codigo_tributacao_nacional="040101", codigo_tributacao_municipal="0401010000",
            codigo_nbs="105011900", descricao="Consulta médica",
            codigo_municipio_prestacao="3549904", valor="300.00",
            aliquota_iss=aliquota_iss, tipo_retencao_issqn=tipo_retencao_issqn,
        ),
    )


class TestPAliqDeveSerOmitido(unittest.TestCase):
    """Testes unitarios diretos do helper, sem precisar montar XML."""

    def test_nao_optante_nunca_omite(self):
        dados = _dados("1", "2.00")
        self.assertFalse(db._pAliq_deve_ser_omitido(dados.prestador, dados.servico))

    def test_mei_sem_retencao_omite(self):
        dados = _dados("2", "2.00")
        self.assertTrue(db._pAliq_deve_ser_omitido(dados.prestador, dados.servico))

    def test_me_epp_sem_retencao_omite(self):
        dados = _dados("3", "2.00")
        self.assertTrue(db._pAliq_deve_ser_omitido(dados.prestador, dados.servico))

    def test_mei_com_retencao_pelo_tomador_nao_omite(self):
        dados = _dados("2", "1.80", tipo_retencao_issqn="2")
        self.assertFalse(db._pAliq_deve_ser_omitido(dados.prestador, dados.servico))

    def test_me_epp_com_retencao_pelo_intermediario_nao_omite(self):
        dados = _dados("3", "1.80", tipo_retencao_issqn="3")
        self.assertFalse(db._pAliq_deve_ser_omitido(dados.prestador, dados.servico))


class TestMontarDpsXmlSimplesNacional(unittest.TestCase):
    """Testes de ponta a ponta: monta o XML de verdade e confere o que sai."""

    def _tem_paliq(self, dados) -> bool:
        xml = db.serializar(db.montar_dps_xml(dados)).decode("utf-8")
        return "<pAliq>" in xml

    def test_nao_optante_com_aliquota_gera_paliq(self):
        self.assertTrue(self._tem_paliq(_dados("1", "2.00")))

    def test_nao_optante_sem_aliquota_nao_gera_paliq(self):
        # município já parametriza — comportamento antigo preservado
        self.assertFalse(self._tem_paliq(_dados("1", None)))

    def test_mei_com_aliquota_digitada_nao_gera_paliq(self):
        # o caso do achado da auditoria: secretária digitou "2%" sem saber
        # que não devia — o XML tem que ignorar isso mesmo assim
        self.assertFalse(self._tem_paliq(_dados("2", "2.00")))

    def test_me_epp_com_aliquota_digitada_nao_gera_paliq(self):
        self.assertFalse(self._tem_paliq(_dados("3", "2.00")))

    def test_me_epp_com_retencao_e_aliquota_gera_paliq(self):
        # regras E0619/E0621: com retenção, pAliq volta a ser obrigatório
        # mesmo pro optante
        self.assertTrue(self._tem_paliq(_dados("3", "1.80", tipo_retencao_issqn="2")))

    def test_opsimpnac_e_regesptrib_sempre_presentes_independente_do_regime(self):
        for opcao in ("1", "2", "3"):
            dados = _dados(opcao, "2.00")
            dados.prestador.regime_especial_tributacao = "6"  # Sociedade de Profissionais
            xml = db.serializar(db.montar_dps_xml(dados)).decode("utf-8")
            self.assertIn(f"<opSimpNac>{opcao}</opSimpNac>", xml)
            self.assertIn("<regEspTrib>6</regEspTrib>", xml)

    def test_tribissqn_e_tpretissqn_sempre_presentes(self):
        xml = db.serializar(db.montar_dps_xml(_dados("3", "2.00"))).decode("utf-8")
        self.assertIn("<tribISSQN>1</tribISSQN>", xml)
        self.assertIn("<tpRetISSQN>1</tpRetISSQN>", xml)


def _dados_com_retencao(**retencao_kwargs):
    return db.DadosDPS(
        ambiente="homologacao",
        prestador=db.Prestador(
            documento="11222333000181", inscricao_municipal="123456", codigo_municipio="3549904",
            opcao_simples_nacional="3",
        ),
        tomador=db.Tomador(documento="12345678000199", nome="Unimed SJC"),
        servico=db.Servico(
            codigo_tributacao_nacional="040101", codigo_tributacao_municipal="0401010000",
            codigo_nbs="105011900", descricao="Consulta médica",
            codigo_municipio_prestacao="3549904", valor="1000.00",
            **retencao_kwargs,
        ),
    )


class TestTribFed(unittest.TestCase):
    """Testes do grupo de retenção federal (docs/auditoria.md, Bloco 1.6/2.4)
    — caso real: convênio (Unimed, Bradesco Saúde) retendo IRRF de médico PJ."""

    def _xml(self, dados) -> str:
        return db.serializar(db.montar_dps_xml(dados)).decode("utf-8")

    def test_sem_nenhuma_retencao_nao_gera_tribfed(self):
        xml = self._xml(_dados_com_retencao())
        self.assertNotIn("<tribFed>", xml)

    def test_irrf_retido_gera_vretirrf(self):
        xml = self._xml(_dados_com_retencao(valor_retido_irrf="15.00"))
        self.assertIn("<tribFed>", xml)
        self.assertIn("<vRetIRRF>15.00</vRetIRRF>", xml)
        self.assertNotIn("<vRetCSLL>", xml)

    def test_pis_cofins_csll_somam_dentro_de_vretcsll(self):
        # regra contraintuitiva da NT-007: PIS + COFINS + CSLL retidos vao
        # SOMADOS num unico campo vRetCSLL, apesar do nome.
        xml = self._xml(_dados_com_retencao(
            valor_retido_pis="6.50", valor_retido_cofins="30.00", valor_retido_csll="10.00",
        ))
        self.assertIn("<vRetCSLL>46.50</vRetCSLL>", xml)

    def test_tp_ret_pis_cofins_suspenso_ate_decisao_do_cst(self):
        """docs/auditoria-2.md, Onda 1 item 2: validacao de schema real
        revelou que tpRetPisCofins so' e' valido DENTRO do subgrupo
        <piscofins>, que por sua vez EXIGE um <CST> que este app ainda nao
        decidiu como preencher -- entao o campo fica SUSPENSO (nao emitido)
        ate essa decisao, pra nunca gerar XML invalido. Ver
        `_montar_trib_fed` pro comentario completo."""
        xml = self._xml(_dados_com_retencao(
            valor_retido_pis="6.50", valor_retido_cofins="30.00", valor_retido_csll="10.00",
        ))
        self.assertNotIn("<tpRetPisCofins>", xml)
        self.assertNotIn("<piscofins>", xml)

    def test_codigo_tp_ret_pis_cofins_mapeia_as_8_combinacoes(self):
        """A logica de mapeamento (TSTipoRetPISCofins, tiposSimples_v1.01.xsd)
        esta correta e testada aqui diretamente, mesmo sem uso ativo no XML
        agora (ver teste acima) -- fica pronta pra quando o CST for decidido."""
        self.assertEqual(db._codigo_tp_ret_pis_cofins(False, False, False), "0")
        self.assertEqual(db._codigo_tp_ret_pis_cofins(True, True, True), "3")
        self.assertEqual(db._codigo_tp_ret_pis_cofins(True, True, False), "4")
        self.assertEqual(db._codigo_tp_ret_pis_cofins(True, False, False), "5")
        self.assertEqual(db._codigo_tp_ret_pis_cofins(False, True, False), "6")
        self.assertEqual(db._codigo_tp_ret_pis_cofins(False, True, True), "7")
        self.assertEqual(db._codigo_tp_ret_pis_cofins(False, False, True), "8")
        self.assertEqual(db._codigo_tp_ret_pis_cofins(True, False, True), "9")

    def test_inss_retido_gera_vretcp(self):
        xml = self._xml(_dados_com_retencao(valor_retido_inss="11.00"))
        self.assertIn("<vRetCP>11.00</vRetCP>", xml)

    def test_todas_as_retencoes_juntas(self):
        xml = self._xml(_dados_com_retencao(
            valor_retido_irrf="15.00", valor_retido_pis="6.50",
            valor_retido_cofins="30.00", valor_retido_csll="10.00", valor_retido_inss="11.00",
        ))
        self.assertIn("<vRetIRRF>15.00</vRetIRRF>", xml)
        self.assertIn("<vRetCSLL>46.50</vRetCSLL>", xml)
        self.assertIn("<vRetCP>11.00</vRetCP>", xml)

    def test_vpis_vcofins_nunca_sao_gerados(self):
        # vPIS/vCOFINS (valor DEVIDO, do grupo IBSCBS) sao campos DIFERENTES
        # de vRetCSLL (valor RETIDO) -- este builder nao gera IBSCBS hoje
        # (docs/auditoria.md, Bloco 1.2 -- validacao suspensa), entao
        # vPIS/vCOFINS nunca devem aparecer, com ou sem retencao.
        xml = self._xml(_dados_com_retencao(
            valor_retido_pis="6.50", valor_retido_cofins="30.00", valor_retido_csll="10.00",
        ))
        self.assertNotIn("<vPIS>", xml)
        self.assertNotIn("<vCOFINS>", xml)


if __name__ == "__main__":
    unittest.main()
