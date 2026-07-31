"""Testes de app/repo.py — a garantia mais importante do backend: dado de um
prestador nunca vaza pra outro (espec-mvp-emissor-nfse.md, secao 6)."""
import tempfile
import unittest
from pathlib import Path

from app import repo


class TestEscopoPorPrestador(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = repo.Repositorio(Path(self._tmp.name) / "teste.db")

        self.p1 = self.repo.criar_prestador(
            nome_exibicao="Dr. João Cardoso", cnpj="11111111000111",
            im="111", codigo_municipio="3549904",
        )
        self.p2 = self.repo.criar_prestador(
            nome_exibicao="Dra. Ana Lima", cnpj="22222222000122",
            im="222", codigo_municipio="3549904",
        )

    def tearDown(self):
        self.repo.fechar()
        self._tmp.cleanup()

    def test_tomadores_isolados_por_prestador(self):
        t1 = self.repo.criar_tomador(self.p1, doc="11111111111", nome="Paciente do Dr. João")
        t2 = self.repo.criar_tomador(self.p2, doc="22222222222", nome="Paciente da Dra. Ana")

        self.assertEqual(len(self.repo.listar_tomadores(self.p1)), 1)
        self.assertEqual(self.repo.listar_tomadores(self.p1)[0]["id"], t1)
        self.assertEqual(len(self.repo.listar_tomadores(self.p2)), 1)
        self.assertEqual(self.repo.listar_tomadores(self.p2)[0]["id"], t2)

    def test_obter_tomador_com_prestador_errado_nao_vaza_dado(self):
        t1 = self.repo.criar_tomador(self.p1, doc="11111111111", nome="Paciente do Dr. João")
        # pedir o tomador do p1 "atraves" do p2 tem que voltar vazio, nao o dado do outro prestador
        self.assertIsNone(self.repo.obter_tomador(self.p2, t1))
        self.assertIsNotNone(self.repo.obter_tomador(self.p1, t1))

    def test_notas_isoladas_por_prestador(self):
        t1 = self.repo.criar_tomador(self.p1, doc="11111111111", nome="Paciente 1")
        m1 = self.repo.criar_modelo_servico(
            self.p1, descricao="Consulta", cod_tributacao_nacional="010101",
            cod_tributacao_municipal="0101010000", cod_nbs="107011900", valor_padrao="200.00",
        )
        nota_id = self.repo.criar_nota(self.p1, tomador_id=t1, modelo_id=m1, valor="200.00")

        self.assertEqual(len(self.repo.listar_notas(self.p1)), 1)
        self.assertEqual(len(self.repo.listar_notas(self.p2)), 0)
        self.assertIsNone(self.repo.obter_nota(self.p2, nota_id), "nota do p1 nao pode aparecer pro p2")

    def test_numeracao_de_dps_e_independente_por_prestador(self):
        t1 = self.repo.criar_tomador(self.p1, doc="11111111111", nome="Paciente 1")
        t2 = self.repo.criar_tomador(self.p2, doc="22222222222", nome="Paciente 2")
        m1 = self.repo.criar_modelo_servico(
            self.p1, descricao="Consulta", cod_tributacao_nacional="010101",
            cod_tributacao_municipal="0101010000", cod_nbs="107011900", valor_padrao="200.00",
        )
        m2 = self.repo.criar_modelo_servico(
            self.p2, descricao="Consulta", cod_tributacao_nacional="010101",
            cod_tributacao_municipal="0101010000", cod_nbs="107011900", valor_padrao="300.00",
        )

        n1a = self.repo.criar_nota(self.p1, tomador_id=t1, modelo_id=m1, valor="200.00")
        n1b = self.repo.criar_nota(self.p1, tomador_id=t1, modelo_id=m1, valor="200.00")
        n2a = self.repo.criar_nota(self.p2, tomador_id=t2, modelo_id=m2, valor="300.00")

        self.assertEqual(self.repo.obter_nota(self.p1, n1a)["numero_dps"], "1")
        self.assertEqual(self.repo.obter_nota(self.p1, n1b)["numero_dps"], "2")
        # p2 comeca do 1 de novo — numeracao propria por prestador (espec, secao 6)
        self.assertEqual(self.repo.obter_nota(self.p2, n2a)["numero_dps"], "1")

    def test_config_nao_e_escopada_por_prestador(self):
        self.repo.set_config("pasta_base", "C:/Notas Fiscais")
        self.assertEqual(self.repo.get_config("pasta_base"), "C:/Notas Fiscais")
        self.repo.set_config("pasta_base", "D:/Outra Pasta")
        self.assertEqual(self.repo.get_config("pasta_base"), "D:/Outra Pasta")
        self.assertIsNone(self.repo.get_config("chave_inexistente"))


class TestRecorrencias(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = repo.Repositorio(Path(self._tmp.name) / "teste.db")
        self.p1 = self.repo.criar_prestador(
            nome_exibicao="Prestador Teste", cnpj="11111111000111", im="111", codigo_municipio="3549904",
        )
        self.t1 = self.repo.criar_tomador(self.p1, doc="11111111111", nome="Tomador Teste")
        self.m1 = self.repo.criar_modelo_servico(
            self.p1, descricao="Servico", cod_tributacao_nacional="010101",
            cod_tributacao_municipal="0101010000", cod_nbs="107011900", valor_padrao="100.00",
        )

    def tearDown(self):
        self.repo.fechar()
        self._tmp.cleanup()

    def test_atualizar_recorrencia_ativo_pausa_e_reativa(self):
        rec_id = self.repo.criar_recorrencia(
            self.p1, tomador_id=self.t1, modelo_id=self.m1, valor="100.00", dia_do_mes=5, ativo=True,
        )
        self.repo.atualizar_recorrencia_ativo(self.p1, rec_id, False)
        recs = self.repo.listar_recorrencias(self.p1, apenas_ativas=False)
        self.assertEqual(recs[0]["ativo"], 0)

        self.repo.atualizar_recorrencia_ativo(self.p1, rec_id, True)
        recs = self.repo.listar_recorrencias(self.p1, apenas_ativas=False)
        self.assertEqual(recs[0]["ativo"], 1)

    def test_pausada_some_da_listagem_apenas_ativas(self):
        rec_id = self.repo.criar_recorrencia(
            self.p1, tomador_id=self.t1, modelo_id=self.m1, valor="100.00", dia_do_mes=5, ativo=True,
        )
        self.repo.atualizar_recorrencia_ativo(self.p1, rec_id, False)
        self.assertEqual(self.repo.listar_recorrencias(self.p1, apenas_ativas=True), [])
        self.assertEqual(len(self.repo.listar_recorrencias(self.p1, apenas_ativas=False)), 1)


class TestTransicoesDeStatusDeNota(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = repo.Repositorio(Path(self._tmp.name) / "teste.db")
        self.p1 = self.repo.criar_prestador(
            nome_exibicao="Prestador Teste", cnpj="11111111000111", im="111", codigo_municipio="3549904",
        )
        self.t1 = self.repo.criar_tomador(self.p1, doc="11111111111", nome="Tomador Teste")
        self.m1 = self.repo.criar_modelo_servico(
            self.p1, descricao="Servico", cod_tributacao_nacional="010101",
            cod_tributacao_municipal="0101010000", cod_nbs="107011900", valor_padrao="100.00",
        )

    def tearDown(self):
        self.repo.fechar()
        self._tmp.cleanup()

    def test_marcar_emitida(self):
        nota_id = self.repo.criar_nota(self.p1, tomador_id=self.t1, modelo_id=self.m1, valor="100.00")
        self.repo.marcar_emitida(
            self.p1, nota_id, chave_acesso="CHAVE123", xml_conteudo="<NFSe/>",
            xml_path="C:/x.xml", pdf_path="C:/x.pdf",
        )
        nota = self.repo.obter_nota(self.p1, nota_id)
        self.assertEqual(nota["status"], repo.STATUS_EMITIDA)
        self.assertEqual(nota["chave_acesso"], "CHAVE123")
        self.assertIsNotNone(nota["emitida_em"])

    def test_marcar_rejeitada_guarda_motivo(self):
        nota_id = self.repo.criar_nota(self.p1, tomador_id=self.t1, modelo_id=self.m1, valor="100.00")
        self.repo.marcar_rejeitada(self.p1, nota_id, motivo="E0310: codigo de tributacao invalido")
        nota = self.repo.obter_nota(self.p1, nota_id)
        self.assertEqual(nota["status"], repo.STATUS_REJEITADA)
        self.assertIn("E0310", nota["motivo_rejeicao"])

    def test_marcar_para_retry_mantem_pendente(self):
        import datetime
        nota_id = self.repo.criar_nota(self.p1, tomador_id=self.t1, modelo_id=self.m1, valor="100.00")
        proxima = datetime.datetime.now() + datetime.timedelta(minutes=5)
        self.repo.marcar_para_retry(self.p1, nota_id, proxima_tentativa_em=proxima)
        nota = self.repo.obter_nota(self.p1, nota_id)
        self.assertEqual(nota["status"], repo.STATUS_PENDENTE)
        self.assertIsNotNone(nota["proxima_tentativa_em"])


class TestEditarEExcluirCadastros(unittest.TestCase):
    """CRUD completo dos cadastros (prestador/tomador/servico/mensalidade):
    editar sempre pode; excluir e' bloqueado quando existe nota emitida
    vinculada (documento fiscal nao pode ficar orfao de cadastro)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = repo.Repositorio(Path(self._tmp.name) / "teste.db")
        self.p1 = self.repo.criar_prestador(
            nome_exibicao="Prestador Teste", cnpj="11111111000111", im="111", codigo_municipio="3549904",
        )
        self.t1 = self.repo.criar_tomador(self.p1, doc="11111111111", nome="Tomador Teste")
        self.m1 = self.repo.criar_modelo_servico(
            self.p1, descricao="Servico", cod_tributacao_nacional="010101",
            cod_tributacao_municipal="0101010000", cod_nbs="107011900", valor_padrao="100.00",
        )

    def tearDown(self):
        self.repo.fechar()
        self._tmp.cleanup()

    # -- prestador ------------------------------------------------------
    def test_atualizar_prestador_muda_campos_mas_nao_cnpj(self):
        self.repo.atualizar_prestador(
            self.p1, nome_exibicao="Novo Nome", im="999", codigo_municipio="3550308",
            regime="2", regime_especial_tributacao="1", cor="#FF0000",
        )
        p = self.repo.obter_prestador(self.p1)
        self.assertEqual(p["nome_exibicao"], "Novo Nome")
        self.assertEqual(p["regime"], "2")
        self.assertEqual(p["cnpj"], "11111111000111")

    def test_excluir_prestador_sem_notas_remove_tudo_em_cascata(self):
        self.repo.excluir_prestador(self.p1)
        self.assertIsNone(self.repo.obter_prestador(self.p1))
        self.assertEqual(self.repo.listar_tomadores(self.p1), [])
        self.assertEqual(self.repo.listar_modelos_servico(self.p1), [])

    def test_excluir_prestador_com_nota_e_bloqueado(self):
        self.repo.criar_nota(self.p1, tomador_id=self.t1, modelo_id=self.m1, valor="100.00")
        with self.assertRaises(ValueError):
            self.repo.excluir_prestador(self.p1)
        self.assertIsNotNone(self.repo.obter_prestador(self.p1))

    # -- tomador ----------------------------------------------------------
    def test_atualizar_tomador(self):
        self.repo.atualizar_tomador(self.p1, self.t1, nome="Novo Nome", email="a@b.com")
        t = self.repo.obter_tomador(self.p1, self.t1)
        self.assertEqual(t["nome"], "Novo Nome")
        self.assertEqual(t["email"], "a@b.com")

    def test_excluir_tomador_sem_vinculo(self):
        self.repo.excluir_tomador(self.p1, self.t1)
        self.assertIsNone(self.repo.obter_tomador(self.p1, self.t1))

    def test_excluir_tomador_com_nota_e_bloqueado(self):
        self.repo.criar_nota(self.p1, tomador_id=self.t1, modelo_id=self.m1, valor="100.00")
        with self.assertRaises(ValueError):
            self.repo.excluir_tomador(self.p1, self.t1)

    def test_excluir_tomador_com_recorrencia_e_bloqueado(self):
        self.repo.criar_recorrencia(self.p1, tomador_id=self.t1, modelo_id=self.m1, valor="100.00", dia_do_mes=5)
        with self.assertRaises(ValueError):
            self.repo.excluir_tomador(self.p1, self.t1)

    # -- modelo de servico ------------------------------------------------
    def test_atualizar_modelo_servico(self):
        self.repo.atualizar_modelo_servico(
            self.p1, self.m1, descricao="Novo", cod_tributacao_nacional="020202",
            cod_tributacao_municipal="0202020000", cod_nbs="207011900", valor_padrao="200.00",
        )
        m = self.repo.obter_modelo(self.p1, self.m1)
        self.assertEqual(m["descricao"], "Novo")
        self.assertEqual(m["valor_padrao"], "200.00")

    def test_excluir_modelo_servico_sem_vinculo(self):
        self.repo.excluir_modelo_servico(self.p1, self.m1)
        self.assertIsNone(self.repo.obter_modelo(self.p1, self.m1))

    def test_excluir_modelo_servico_com_nota_e_bloqueado(self):
        self.repo.criar_nota(self.p1, tomador_id=self.t1, modelo_id=self.m1, valor="100.00")
        with self.assertRaises(ValueError):
            self.repo.excluir_modelo_servico(self.p1, self.m1)

    def test_excluir_modelo_servico_com_recorrencia_e_bloqueado(self):
        self.repo.criar_recorrencia(self.p1, tomador_id=self.t1, modelo_id=self.m1, valor="100.00", dia_do_mes=5)
        with self.assertRaises(ValueError):
            self.repo.excluir_modelo_servico(self.p1, self.m1)

    # -- recorrencia (mensalidade) -----------------------------------------
    def test_atualizar_recorrencia(self):
        rec_id = self.repo.criar_recorrencia(self.p1, tomador_id=self.t1, modelo_id=self.m1, valor="100.00", dia_do_mes=5)
        self.repo.atualizar_recorrencia(self.p1, rec_id, tomador_id=self.t1, modelo_id=self.m1, valor="150.00", dia_do_mes=10)
        r = self.repo.listar_recorrencias(self.p1, apenas_ativas=False)[0]
        self.assertEqual(r["valor"], "150.00")
        self.assertEqual(r["dia_do_mes"], 10)

    def test_excluir_recorrencia_sem_nota(self):
        rec_id = self.repo.criar_recorrencia(self.p1, tomador_id=self.t1, modelo_id=self.m1, valor="100.00", dia_do_mes=5)
        self.repo.excluir_recorrencia(self.p1, rec_id)
        self.assertEqual(self.repo.listar_recorrencias(self.p1, apenas_ativas=False), [])

    def test_excluir_recorrencia_com_nota_e_bloqueado(self):
        rec_id = self.repo.criar_recorrencia(self.p1, tomador_id=self.t1, modelo_id=self.m1, valor="100.00", dia_do_mes=5)
        self.repo.criar_nota(self.p1, tomador_id=self.t1, modelo_id=self.m1, valor="100.00", recorrencia_id=rec_id)
        with self.assertRaises(ValueError):
            self.repo.excluir_recorrencia(self.p1, rec_id)


class TestRetencoes(unittest.TestCase):
    """Retenções na fonte (docs/auditoria.md, Bloco 1.6/2.4) — caso real:
    convênio (Unimed, Bradesco Saúde) retendo IRRF de médico PJ."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = repo.Repositorio(Path(self._tmp.name) / "teste.db")
        self.p1 = self.repo.criar_prestador(
            nome_exibicao="Dr. Teste", cnpj="11111111000111", im="111", codigo_municipio="3549904",
        )

    def tearDown(self):
        self.repo.fechar()
        self._tmp.cleanup()

    def test_tomador_sem_retencao_tem_defaults_seguros(self):
        tid = self.repo.criar_tomador(self.p1, doc="12345678000199", nome="Paciente Particular")
        t = self.repo.obter_tomador(self.p1, tid)
        for campo in repo.CAMPOS_RETENCAO:
            if campo.startswith("retem_"):
                self.assertEqual(t[campo], 0)
            else:
                self.assertIsNone(t[campo])

    def test_criar_tomador_com_retencao_padrao(self):
        tid = self.repo.criar_tomador(
            self.p1, doc="11222333000199", nome="Unimed SJC",
            retencoes={"retem_irrf": True, "aliquota_irrf": "1.5", "retem_iss": True},
        )
        t = self.repo.obter_tomador(self.p1, tid)
        self.assertEqual(t["retem_irrf"], 1)
        self.assertEqual(t["aliquota_irrf"], "1.5")
        self.assertEqual(t["retem_iss"], 1)
        self.assertEqual(t["retem_pis"], 0)

    def test_atualizar_tomador_muda_retencao(self):
        tid = self.repo.criar_tomador(self.p1, doc="11222333000199", nome="Unimed SJC")
        self.repo.atualizar_tomador(
            self.p1, tid, nome="Unimed SJC", retencoes={"retem_irrf": True, "aliquota_irrf": "1.5"},
        )
        t = self.repo.obter_tomador(self.p1, tid)
        self.assertEqual(t["retem_irrf"], 1)
        self.assertEqual(t["aliquota_irrf"], "1.5")

    def test_nota_guarda_retencao_aplicada_independente_do_tomador(self):
        tid = self.repo.criar_tomador(
            self.p1, doc="11222333000199", nome="Unimed SJC",
            retencoes={"retem_irrf": True, "aliquota_irrf": "1.5"},
        )
        mid = self.repo.criar_modelo_servico(
            self.p1, descricao="Consulta", cod_tributacao_nacional="040101",
            cod_tributacao_municipal="0401010000", cod_nbs="105011900", valor_padrao="1000.00",
        )
        # sobrescrever so' nesta nota (docs/auditoria.md item 2): tomador
        # tem 1.5% de IRRF, mas esta nota especifica vai sem retencao nenhuma
        nid = self.repo.criar_nota(
            self.p1, tomador_id=tid, modelo_id=mid, valor="1000.00", retencoes={"retem_irrf": False},
        )
        nota = self.repo.obter_nota(self.p1, nid)
        self.assertEqual(nota["retem_irrf"], 0)
        # o tomador continua com o padrao dele, intocado
        tomador = self.repo.obter_tomador(self.p1, tid)
        self.assertEqual(tomador["retem_irrf"], 1)
        self.assertEqual(tomador["aliquota_irrf"], "1.5")


if __name__ == "__main__":
    unittest.main()
