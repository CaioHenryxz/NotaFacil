"""Testes do painel "Meu Dia" (Etapa 2, tela 3): repo.dados_meu_dia (leitura
agregada de todos os prestadores) e fila.criar_notas_das_recorrencias_do_dia
(botao [Emitir todas])."""
import datetime
import tempfile
import unittest
from pathlib import Path

from app import repo
from app.core import fila


class TestDadosMeuDia(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = repo.Repositorio(Path(self._tmp.name) / "teste.db")
        # "hoje" precisa ser a data real: notas.criada_em usa datetime('now') do
        # proprio SQLite, entao a checagem "emitida hoje" so bate com a data real.
        self.hoje = datetime.date.today()
        self.outro_dia = (self.hoje.day % 28) + 1

        self.p1 = self.repo.criar_prestador(
            nome_exibicao="Dr. João Cardoso", cnpj="11111111000111", im="1",
            codigo_municipio="3549904", cor="#2F6FED",
            cert_venc_em=(self.hoje + datetime.timedelta(days=10)).isoformat(),
        )
        self.p2 = self.repo.criar_prestador(
            nome_exibicao="Dra. Ana Lima", cnpj="22222222000122", im="2",
            codigo_municipio="3549904", cor="#C77C11",
            cert_venc_em=(self.hoje + datetime.timedelta(days=200)).isoformat(),
        )
        self.t1 = self.repo.criar_tomador(self.p1, doc="11111111111", nome="Paciente 1")
        self.t2 = self.repo.criar_tomador(self.p2, doc="22222222222", nome="Paciente 2")
        self.m1 = self.repo.criar_modelo_servico(
            self.p1, descricao="Consulta", cod_tributacao_nacional="010101",
            cod_tributacao_municipal="0101010000", cod_nbs="107011900", valor_padrao="200.00",
        )
        self.m2 = self.repo.criar_modelo_servico(
            self.p2, descricao="Exame", cod_tributacao_nacional="010101",
            cod_tributacao_municipal="0101010000", cod_nbs="107011900", valor_padrao="300.00",
        )

    def tearDown(self):
        self.repo.fechar()
        self._tmp.cleanup()

    def test_mensalidades_de_hoje_juntam_todos_os_prestadores(self):
        self.repo.criar_recorrencia(self.p1, tomador_id=self.t1, modelo_id=self.m1, valor="200.00", dia_do_mes=self.hoje.day)
        self.repo.criar_recorrencia(self.p2, tomador_id=self.t2, modelo_id=self.m2, valor="300.00", dia_do_mes=self.hoje.day)
        self.repo.criar_recorrencia(self.p1, tomador_id=self.t1, modelo_id=self.m1, valor="200.00", dia_do_mes=self.outro_dia)  # outro dia

        dados = self.repo.dados_meu_dia(self.hoje)
        self.assertEqual(len(dados["mensalidades_hoje"]), 2)
        prestadores = {m["prestador_nome"] for m in dados["mensalidades_hoje"]}
        self.assertEqual(prestadores, {"Dr. João Cardoso", "Dra. Ana Lima"})

    def test_ja_emitida_no_mes_fica_marcada(self):
        rec_id = self.repo.criar_recorrencia(self.p1, tomador_id=self.t1, modelo_id=self.m1, valor="200.00", dia_do_mes=self.hoje.day)
        self.repo.criar_nota(self.p1, tomador_id=self.t1, modelo_id=self.m1, valor="200.00", recorrencia_id=rec_id)

        dados = self.repo.dados_meu_dia(self.hoje)
        self.assertTrue(dados["mensalidades_hoje"][0]["ja_emitida_no_mes"])

    def test_notas_pendentes_e_rejeitadas_agregam_prestadores(self):
        n1 = self.repo.criar_nota(self.p1, tomador_id=self.t1, modelo_id=self.m1, valor="200.00")
        n2 = self.repo.criar_nota(self.p2, tomador_id=self.t2, modelo_id=self.m2, valor="300.00")
        self.repo.marcar_rejeitada(self.p2, n2, motivo="E0310: teste")

        dados = self.repo.dados_meu_dia(self.hoje)
        self.assertEqual(len(dados["notas_pendentes"]), 1)
        self.assertEqual(dados["notas_pendentes"][0]["prestador_nome"], "Dr. João Cardoso")
        self.assertEqual(len(dados["notas_rejeitadas"]), 1)
        self.assertEqual(dados["notas_rejeitadas"][0]["motivo_rejeicao"], "E0310: teste")

    def test_certificados_a_vencer_respeita_janela_de_dias(self):
        dados = self.repo.dados_meu_dia(self.hoje, dias_alerta_certificado=30)
        nomes = {c["prestador_nome"] for c in dados["certificados_a_vencer"]}
        self.assertEqual(nomes, {"Dr. João Cardoso"})  # p2 vence em 200 dias, fora da janela


class TestCriarNotasDasRecorrenciasDoDia(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = repo.Repositorio(Path(self._tmp.name) / "teste.db")
        self.hoje = datetime.date.today()
        self.p1 = self.repo.criar_prestador(
            nome_exibicao="Prestador", cnpj="11111111000111", im="1", codigo_municipio="3549904",
        )
        self.t1 = self.repo.criar_tomador(self.p1, doc="11111111111", nome="Tomador")
        self.m1 = self.repo.criar_modelo_servico(
            self.p1, descricao="Servico", cod_tributacao_nacional="010101",
            cod_tributacao_municipal="0101010000", cod_nbs="107011900", valor_padrao="150.00",
        )
        self.rec = self.repo.criar_recorrencia(
            self.p1, tomador_id=self.t1, modelo_id=self.m1, valor="150.00", dia_do_mes=self.hoje.day
        )

    def tearDown(self):
        self.repo.fechar()
        self._tmp.cleanup()

    def test_cria_uma_nota_por_mensalidade_devida(self):
        criadas = fila.criar_notas_das_recorrencias_do_dia(self.repo, self.hoje)
        self.assertEqual(len(criadas), 1)
        nota = self.repo.obter_nota(self.p1, criadas[0])
        self.assertEqual(nota["recorrencia_id"], self.rec)
        self.assertEqual(nota["status"], repo.STATUS_PENDENTE)

    def test_clicar_duas_vezes_nao_duplica_a_nota(self):
        primeira = fila.criar_notas_das_recorrencias_do_dia(self.repo, self.hoje)
        segunda = fila.criar_notas_das_recorrencias_do_dia(self.repo, self.hoje)
        self.assertEqual(len(primeira), 1)
        self.assertEqual(len(segunda), 0, "nao deveria criar de novo no mesmo dia")


if __name__ == "__main__":
    unittest.main()
