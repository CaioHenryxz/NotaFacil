"""Testes de app/core/fila.py com a API do governo simulada (nunca toca em
certificado ou rede de verdade) — espec-mvp-emissor-nfse.md, secao 2 item 7:
"API do governo fora do ar -> nota fica pendente e o app tenta de novo
sozinho (backoff: 5 min, 30 min, 2 h) ate emitir"."""
import datetime
import tempfile
import unittest
from pathlib import Path

from app import repo
from app.core import fila, mensagens
from app.fiscal import api_nacional


class FakeApi:
    """Dublê do emissor: decide por chamada se a API 'caiu' (ErroRede),
    rejeitou (ErroValidacao) ou aceitou, sem tocar em rede/certificado."""

    def __init__(self, script):
        # script: lista de resultados a devolver em chamadas sucessivas,
        # ex.: ["rede", "rede", "ok"] ou ["validacao"]
        self.script = list(script)
        self.chamadas = 0

    def __call__(self, prestador, tomador, nota, modelo):
        self.chamadas += 1
        resultado = self.script.pop(0)
        if resultado == "rede":
            raise api_nacional.ErroRede("simulado: timeout/5xx")
        if resultado == "validacao":
            raise api_nacional.ErroValidacao("E0310: codigo de tributacao invalido")
        return api_nacional.RespostaEmissao(
            chave_acesso=f"CHAVE-{nota['id']}",
            xml_nfse=f"<NFSe id='{nota['id']}'/>".encode("utf-8"),
        )


def _reconciliador_nunca_encontra(prestador, nota):
    """Fake do `reconciliador` (docs/auditoria.md, Bloco 6.1) pros testes de
    retry que NAO sao sobre reconciliacao — simula "consultei e nao, essa
    DPS realmente nao foi aceita ainda", pra `processar_fila` seguir pro
    reenvio normal em vez de tentar carregar um certificado de verdade."""
    return api_nacional.RespostaConsultaDps(encontrada=False)


class TestBackoff(unittest.TestCase):
    def test_sequencia_5min_30min_2h_depois_6h(self):
        self.assertEqual(fila.proximo_atraso(1), datetime.timedelta(minutes=5))
        self.assertEqual(fila.proximo_atraso(2), datetime.timedelta(minutes=30))
        self.assertEqual(fila.proximo_atraso(3), datetime.timedelta(hours=2))
        self.assertEqual(fila.proximo_atraso(4), datetime.timedelta(hours=6))
        self.assertEqual(fila.proximo_atraso(9), datetime.timedelta(hours=6))


class TestProcessarFila(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.pasta_base = Path(self._tmp.name) / "notas"
        self.repositorio = repo.Repositorio(Path(self._tmp.name) / "teste.db")

        self.prestador_id = self.repositorio.criar_prestador(
            nome_exibicao="Prestador Teste", cnpj="11111111000111",
            im="111", codigo_municipio="3549904",
        )
        self.tomador_id = self.repositorio.criar_tomador(
            self.prestador_id, doc="11111111111", nome="Tomador Teste"
        )
        self.modelo_id = self.repositorio.criar_modelo_servico(
            self.prestador_id, descricao="Servico de teste",
            cod_tributacao_nacional="010101", cod_tributacao_municipal="0101010000",
            cod_nbs="107011900", valor_padrao="100.00",
        )

    def tearDown(self):
        self.repositorio.fechar()
        self._tmp.cleanup()

    def _criar_nota(self):
        return self.repositorio.criar_nota(
            self.prestador_id, tomador_id=self.tomador_id, modelo_id=self.modelo_id, valor="100.00"
        )

    def test_sucesso_de_primeira_marca_emitida_e_salva_arquivo(self):
        nota_id = self._criar_nota()
        resultados = fila.processar_fila(
            self.repositorio, self.pasta_base, emissor=FakeApi(["ok"])
        )
        self.assertEqual(resultados[0]["status"], "emitida")
        nota = self.repositorio.obter_nota(self.prestador_id, nota_id)
        self.assertEqual(nota["status"], repo.STATUS_EMITIDA)
        self.assertTrue(Path(nota["xml_path"]).exists())

    def test_api_caindo_reagenda_com_backoff_ate_emitir(self):
        nota_id = self._criar_nota()
        api = FakeApi(["rede", "rede", "rede", "ok"])

        agora = datetime.datetime(2026, 9, 1, 10, 0, 0)
        fila.processar_fila(self.repositorio, self.pasta_base, emissor=api, agora=agora)
        nota = self.repositorio.obter_nota(self.prestador_id, nota_id)
        self.assertEqual(nota["status"], repo.STATUS_PENDENTE)
        self.assertEqual(nota["tentativas"], 1)
        primeira_proxima = datetime.datetime.fromisoformat(nota["proxima_tentativa_em"])
        self.assertEqual(primeira_proxima, agora + datetime.timedelta(minutes=5))

        # antes da hora: nao tenta de novo
        fila.processar_fila(
            self.repositorio, self.pasta_base, emissor=api, agora=agora + datetime.timedelta(minutes=1)
        )
        self.assertEqual(api.chamadas, 1, "nao deveria tentar de novo antes de proxima_tentativa_em")

        # 2a tentativa (30 min)
        agora2 = primeira_proxima + datetime.timedelta(seconds=1)
        fila.processar_fila(
            self.repositorio, self.pasta_base, emissor=api, agora=agora2,
            reconciliador=_reconciliador_nunca_encontra,
        )
        nota = self.repositorio.obter_nota(self.prestador_id, nota_id)
        segunda_proxima = datetime.datetime.fromisoformat(nota["proxima_tentativa_em"])
        self.assertEqual(segunda_proxima, agora2 + datetime.timedelta(minutes=30))
        self.assertEqual(nota["tentativas"], 2)

        # 3a tentativa (2h)
        agora3 = segunda_proxima + datetime.timedelta(seconds=1)
        fila.processar_fila(
            self.repositorio, self.pasta_base, emissor=api, agora=agora3,
            reconciliador=_reconciliador_nunca_encontra,
        )
        nota = self.repositorio.obter_nota(self.prestador_id, nota_id)
        terceira_proxima = datetime.datetime.fromisoformat(nota["proxima_tentativa_em"])
        self.assertEqual(terceira_proxima, agora3 + datetime.timedelta(hours=2))
        self.assertEqual(nota["tentativas"], 3)

        # 4a tentativa: API volta, emite
        agora4 = terceira_proxima + datetime.timedelta(seconds=1)
        resultados = fila.processar_fila(
            self.repositorio, self.pasta_base, emissor=api, agora=agora4,
            reconciliador=_reconciliador_nunca_encontra,
        )
        self.assertEqual(resultados[0]["status"], "emitida")
        nota = self.repositorio.obter_nota(self.prestador_id, nota_id)
        self.assertEqual(nota["status"], repo.STATUS_EMITIDA)
        self.assertEqual(nota["tentativas"], 4)
        self.assertEqual(api.chamadas, 4)

    def test_erro_de_validacao_marca_rejeitada_com_motivo(self):
        nota_id = self._criar_nota()
        fila.processar_fila(self.repositorio, self.pasta_base, emissor=FakeApi(["validacao"]))
        nota = self.repositorio.obter_nota(self.prestador_id, nota_id)
        self.assertEqual(nota["status"], repo.STATUS_REJEITADA)
        self.assertIn("E0310", nota["motivo_rejeicao"])
        self.assertIsNone(nota["proxima_tentativa_em"])

    def test_rejeitada_nao_e_pega_de_novo_pela_fila(self):
        nota_id = self._criar_nota()
        api = FakeApi(["validacao"])
        fila.processar_fila(self.repositorio, self.pasta_base, emissor=api)
        fila.processar_fila(self.repositorio, self.pasta_base, emissor=api)
        self.assertEqual(api.chamadas, 1, "nota rejeitada nao pode ser reprocessada pela fila")


class FakeCancelador:
    """Dublê do `cancelador` de app/core/fila.py — mesma ideia do FakeApi:
    decide por chamada o que a Sefin Nacional 'respondeu', sem tocar em
    certificado/rede de verdade (docs/auditoria.md, Bloco 4.4)."""

    def __init__(self, script):
        self.script = list(script)
        self.chamadas = 0

    def __call__(self, prestador, nota):
        self.chamadas += 1
        resultado = self.script.pop(0)
        if resultado == "rede":
            raise api_nacional.ErroRede("simulado: timeout/5xx")
        if resultado == "fora_do_prazo":
            raise api_nacional.ErroValidacao("E0822")
        if resultado == "ja_cancelada":
            raise api_nacional.ErroValidacao("E0840")
        return api_nacional.RespostaCancelamento(protocolo=f"PROTOCOLO-{nota['id']}", confirmado_em="2026-07-22T10:00:00-03:00")


class TestCancelamento(unittest.TestCase):
    """Os 4 testes obrigatorios do plano de correcao do cancelamento
    (docs/auditoria.md, Bloco 4.4): sucesso, sem internet, ja cancelada, fora
    do prazo. Nenhum toca em certificado/rede real — so' o `cancelador` e'
    trocado por um dublê, igual o `emissor` da emissao."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.pasta_base = Path(self._tmp.name) / "notas"
        self.repositorio = repo.Repositorio(Path(self._tmp.name) / "teste.db")

        self.prestador_id = self.repositorio.criar_prestador(
            nome_exibicao="Prestador Teste", cnpj="11111111000111",
            im="111", codigo_municipio="3549904",
        )
        self.tomador_id = self.repositorio.criar_tomador(
            self.prestador_id, doc="11111111111", nome="Tomador Teste"
        )
        self.modelo_id = self.repositorio.criar_modelo_servico(
            self.prestador_id, descricao="Servico de teste",
            cod_tributacao_nacional="010101", cod_tributacao_municipal="0101010000",
            cod_nbs="107011900", valor_padrao="100.00",
        )
        # nota precisa estar EMITIDA (com chave de acesso e arquivo) antes de
        # poder ser cancelada -- emite de verdade via a fila normal primeiro.
        self.nota_id = self.repositorio.criar_nota(
            self.prestador_id, tomador_id=self.tomador_id, modelo_id=self.modelo_id, valor="100.00"
        )
        fila.processar_fila(self.repositorio, self.pasta_base, emissor=FakeApi(["ok"]))
        nota = self.repositorio.obter_nota(self.prestador_id, self.nota_id)
        assert nota["status"] == repo.STATUS_EMITIDA, "setup: a nota precisa estar emitida antes dos testes de cancelamento"

    def tearDown(self):
        self.repositorio.fechar()
        self._tmp.cleanup()

    def test_1_cancelar_com_sucesso_marca_cancelada_e_move_arquivo(self):
        nota_antes = self.repositorio.obter_nota(self.prestador_id, self.nota_id)
        caminho_original = Path(nota_antes["xml_path"])
        self.assertTrue(caminho_original.exists())

        resultado = fila.solicitar_cancelamento(
            self.repositorio, self.prestador_id, self.nota_id,
            cod_motivo="1", cancelador=FakeCancelador(["ok"]),
        )
        self.assertEqual(resultado["status"], repo.STATUS_CANCELADA)

        nota = self.repositorio.obter_nota(self.prestador_id, self.nota_id)
        self.assertEqual(nota["status"], repo.STATUS_CANCELADA)
        self.assertEqual(nota["protocolo_cancelamento"], f"PROTOCOLO-{self.nota_id}")
        self.assertIsNotNone(nota["cancelamento_confirmado_em"])
        # arquivo MOVIDO pra Canceladas/, nunca apagado
        self.assertFalse(caminho_original.exists())
        self.assertTrue(Path(nota["xml_path"]).exists())
        self.assertIn("Canceladas", str(Path(nota["xml_path"]).parent))

    def test_2_sem_internet_fica_cancelamento_pendente_nunca_cancelada(self):
        cancelador = FakeCancelador(["rede", "ok"])

        resultado = fila.solicitar_cancelamento(
            self.repositorio, self.prestador_id, self.nota_id,
            cod_motivo="1", cancelador=cancelador,
        )
        self.assertEqual(resultado["status"], repo.STATUS_CANCELAMENTO_PENDENTE)
        nota = self.repositorio.obter_nota(self.prestador_id, self.nota_id)
        self.assertEqual(nota["status"], repo.STATUS_CANCELAMENTO_PENDENTE)
        self.assertNotEqual(nota["status"], repo.STATUS_CANCELADA)
        self.assertIsNotNone(nota["proxima_tentativa_em"])

        # ciclo automatico do agendador tenta de novo mais tarde e da certo
        proxima = datetime.datetime.fromisoformat(nota["proxima_tentativa_em"])
        fila.processar_cancelamentos(
            self.repositorio, cancelador=cancelador, agora=proxima + datetime.timedelta(seconds=1)
        )
        nota = self.repositorio.obter_nota(self.prestador_id, self.nota_id)
        self.assertEqual(nota["status"], repo.STATUS_CANCELADA)
        self.assertEqual(cancelador.chamadas, 2)

    def test_3_cancelar_nota_ja_cancelada_e_bloqueado_sem_chamar_rede(self):
        cancelador = FakeCancelador(["ok"])
        resultado = fila.solicitar_cancelamento(
            self.repositorio, self.prestador_id, self.nota_id, cod_motivo="1", cancelador=cancelador,
        )
        self.assertEqual(resultado["status"], repo.STATUS_CANCELADA)
        self.assertEqual(cancelador.chamadas, 1)

        with self.assertRaises(ValueError):
            fila.solicitar_cancelamento(
                self.repositorio, self.prestador_id, self.nota_id, cod_motivo="1", cancelador=cancelador,
            )
        # o bloqueio e' local (repositorio.iniciar_cancelamento) -- nao chega
        # nem a tentar falar com o governo de novo
        self.assertEqual(cancelador.chamadas, 1, "cancelar nota ja cancelada nao pode gerar nova chamada de rede")

        nota = self.repositorio.obter_nota(self.prestador_id, self.nota_id)
        self.assertEqual(nota["status"], repo.STATUS_CANCELADA)

    def test_4_fora_do_prazo_volta_pra_emitida_com_mensagem_clara(self):
        resultado = fila.solicitar_cancelamento(
            self.repositorio, self.prestador_id, self.nota_id,
            cod_motivo="1", cancelador=FakeCancelador(["fora_do_prazo"]),
        )
        self.assertEqual(resultado["status"], repo.STATUS_EMITIDA)

        nota = self.repositorio.obter_nota(self.prestador_id, self.nota_id)
        # nunca fica "cancelada" nem preso em cancelamento_pendente -- a nota
        # continua valida, e' isso mesmo que deveria acontecer
        self.assertEqual(nota["status"], repo.STATUS_EMITIDA)
        self.assertIsNone(nota["proxima_tentativa_em"])
        self.assertIn("E0822", nota["erro_cancelamento"])

        mensagem = mensagens.traduzir_erro_cancelamento(nota["erro_cancelamento"])
        self.assertNotIn("E0822", mensagem, "codigo tecnico nao pode vazar pro usuario final")
        self.assertIn("prazo", mensagem.lower())

    def test_evento_ja_vinculado_e0840_tambem_volta_pra_emitida(self):
        resultado = fila.solicitar_cancelamento(
            self.repositorio, self.prestador_id, self.nota_id,
            cod_motivo="1", cancelador=FakeCancelador(["ja_cancelada"]),
        )
        self.assertEqual(resultado["status"], repo.STATUS_EMITIDA)
        mensagem = mensagens.traduzir_erro_cancelamento(resultado["erro_cancelamento"])
        self.assertNotIn("E0840", mensagem)


class TestRetencaoNaFila(unittest.TestCase):
    """Retenções na fonte (docs/auditoria.md, Bloco 1.6/2.4) — caso real:
    convênio (Unimed, Bradesco Saúde) retendo IRRF de médico PJ. Confere que
    o R$ retido sai calculado corretamente (percentual * valor da nota) e que
    a mensalidade automática herda o padrão do tomador."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.pasta_base = Path(self._tmp.name) / "notas"
        self.repositorio = repo.Repositorio(Path(self._tmp.name) / "teste.db")
        self.prestador_id = self.repositorio.criar_prestador(
            nome_exibicao="Dr. Teste", cnpj="11111111000111", im="111", codigo_municipio="3549904",
        )
        self.modelo_id = self.repositorio.criar_modelo_servico(
            self.prestador_id, descricao="Consulta", cod_tributacao_nacional="040101",
            cod_tributacao_municipal="0401010000", cod_nbs="105011900", valor_padrao="1000.00",
        )

    def tearDown(self):
        self.repositorio.fechar()
        self._tmp.cleanup()

    def test_valor_retido_calculado_a_partir_do_percentual(self):
        tomador_id = self.repositorio.criar_tomador(self.prestador_id, doc="12345678000199", nome="Unimed SJC")
        nota_id = self.repositorio.criar_nota(
            self.prestador_id, tomador_id=tomador_id, modelo_id=self.modelo_id, valor="1000.00",
            retencoes={"retem_irrf": True, "aliquota_irrf": "1.5"},
        )
        prestador = self.repositorio.obter_prestador(self.prestador_id)
        tomador = self.repositorio.obter_tomador(self.prestador_id, tomador_id)
        nota = self.repositorio.obter_nota(self.prestador_id, nota_id)
        modelo = self.repositorio.obter_modelo(self.prestador_id, self.modelo_id)

        dados = fila.dados_dps_de_nota(prestador, tomador, nota, modelo)
        self.assertEqual(dados.servico.valor_retido_irrf, "15.00")  # 1000 * 1.5%

    def test_sem_retencao_valor_retido_e_none(self):
        tomador_id = self.repositorio.criar_tomador(self.prestador_id, doc="12345678000199", nome="Paciente Particular")
        nota_id = self.repositorio.criar_nota(
            self.prestador_id, tomador_id=tomador_id, modelo_id=self.modelo_id, valor="300.00",
        )
        prestador = self.repositorio.obter_prestador(self.prestador_id)
        tomador = self.repositorio.obter_tomador(self.prestador_id, tomador_id)
        nota = self.repositorio.obter_nota(self.prestador_id, nota_id)
        modelo = self.repositorio.obter_modelo(self.prestador_id, self.modelo_id)

        dados = fila.dados_dps_de_nota(prestador, tomador, nota, modelo)
        self.assertIsNone(dados.servico.valor_retido_irrf)
        self.assertIsNone(dados.servico.valor_retido_pis)
        self.assertEqual(dados.servico.tipo_retencao_issqn, "1")

    def test_retem_iss_liga_tpretissqn_2(self):
        tomador_id = self.repositorio.criar_tomador(
            self.prestador_id, doc="12345678000199", nome="Unimed SJC", retencoes={"retem_iss": True},
        )
        nota_id = self.repositorio.criar_nota(
            self.prestador_id, tomador_id=tomador_id, modelo_id=self.modelo_id, valor="1000.00",
            retencoes={"retem_iss": True},
        )
        prestador = self.repositorio.obter_prestador(self.prestador_id)
        tomador = self.repositorio.obter_tomador(self.prestador_id, tomador_id)
        nota = self.repositorio.obter_nota(self.prestador_id, nota_id)
        modelo = self.repositorio.obter_modelo(self.prestador_id, self.modelo_id)

        dados = fila.dados_dps_de_nota(prestador, tomador, nota, modelo)
        self.assertEqual(dados.servico.tipo_retencao_issqn, "2")

    def test_mensalidade_automatica_herda_retencao_padrao_do_tomador(self):
        tomador_id = self.repositorio.criar_tomador(
            self.prestador_id, doc="12345678000199", nome="Unimed SJC",
            retencoes={"retem_irrf": True, "aliquota_irrf": "1.5"},
        )
        self.repositorio.criar_recorrencia(
            self.prestador_id, tomador_id=tomador_id, modelo_id=self.modelo_id, valor="1000.00", dia_do_mes=15,
        )
        hoje = datetime.date(2026, 8, 15)
        criadas = fila.criar_notas_das_recorrencias_do_dia(self.repositorio, hoje)
        self.assertEqual(len(criadas), 1)
        nota = self.repositorio.obter_nota(self.prestador_id, criadas[0])
        self.assertEqual(nota["retem_irrf"], 1)
        self.assertEqual(nota["aliquota_irrf"], "1.5")


if __name__ == "__main__":
    unittest.main()
