"""Testes de app/core/agendador.py — o coração da Etapa 3: "PC desligado no
dia -> emite na próxima abertura" (espec-mvp-emissor-nfse.md, secao 4)."""
import datetime
import tempfile
import unittest
from pathlib import Path

from app import repo
from app.core import agendador
from app.fiscal import api_nacional


def _emissor_sempre_ok(prestador, tomador, nota, modelo):
    return api_nacional.RespostaEmissao(chave_acesso=f"CHAVE-{nota['id']}", xml_nfse=b"<NFSe/>")


class TestAgendadorCatchup(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.pasta_base = Path(self._tmp.name) / "notas"
        self.repo = repo.Repositorio(Path(self._tmp.name) / "teste.db")

        self.pid = self.repo.criar_prestador(
            nome_exibicao="Dr. Teste", cnpj="11111111000111", im="1", codigo_municipio="3549904",
        )
        self.tid = self.repo.criar_tomador(self.pid, doc="11111111111", nome="Tomador Teste")
        self.mid = self.repo.criar_modelo_servico(
            self.pid, descricao="Servico", cod_tributacao_nacional="010101",
            cod_tributacao_municipal="0101010000", cod_nbs="107011900", valor_padrao="100.00",
        )
        self.rec_id = self.repo.criar_recorrencia(
            self.pid, tomador_id=self.tid, modelo_id=self.mid, valor="100.00", dia_do_mes=5
        )

    def tearDown(self):
        self.repo.fechar()
        self._tmp.cleanup()

    def test_primeira_execucao_so_processa_hoje(self):
        # "hoje" != dia 5 -> nao ha mensalidade devida, nada e criado
        hoje = datetime.date(2026, 9, 10)
        resultado = agendador.rodar_ciclo(self.repo, self.pasta_base, emissor=_emissor_sempre_ok, hoje=hoje)
        self.assertEqual(resultado.notas_criadas_catchup, [])
        self.assertFalse(resultado.houve_atraso)

    def test_pc_desligado_no_dia_5_emite_ao_abrir_no_dia_8(self):
        """O cenario central da Etapa 3: recorrencia vence dia 5, o app so
        roda de novo no dia 8 (3 dias 'desligado') -> deve emitir a
        mensalidade atrasada e sinalizar isso pra UI notificar.

        Pra isso fazer sentido, o app precisa ja ter rodado uma vez antes
        (dia 3) — e' o que estabelece "ate' aqui ja foi conferido", a
        baseline que permite reconhecer o dia 5 como pulado. Sem essa
        baseline (1a execucao de todas), o agendador deliberadamente NAO sai
        catchando retroativo desde antes da instalacao do app."""
        agendador.rodar_ciclo(self.repo, self.pasta_base, emissor=_emissor_sempre_ok, hoje=datetime.date(2026, 9, 3))

        hoje = datetime.date(2026, 9, 8)
        resultado = agendador.rodar_ciclo(self.repo, self.pasta_base, emissor=_emissor_sempre_ok, hoje=hoje)

        self.assertEqual(len(resultado.notas_criadas_catchup), 1)
        self.assertTrue(resultado.houve_atraso)
        self.assertEqual(resultado.dias_atrasados, [datetime.date(2026, 9, 5)])
        self.assertEqual(resultado.emitidas_atrasadas, 1)

        nota = self.repo.obter_nota(self.pid, resultado.notas_criadas_catchup[0])
        self.assertEqual(nota["status"], repo.STATUS_EMITIDA)

    def test_nao_reprocessa_o_mesmo_dia_atrasado_duas_vezes(self):
        agendador.rodar_ciclo(self.repo, self.pasta_base, emissor=_emissor_sempre_ok, hoje=datetime.date(2026, 9, 3))
        agendador.rodar_ciclo(self.repo, self.pasta_base, emissor=_emissor_sempre_ok, hoje=datetime.date(2026, 9, 8))
        # app roda de novo no mesmo dia (ciclo do QTimer) -> nao deve duplicar
        resultado2 = agendador.rodar_ciclo(
            self.repo, self.pasta_base, emissor=_emissor_sempre_ok, hoje=datetime.date(2026, 9, 8)
        )
        self.assertEqual(resultado2.notas_criadas_catchup, [])

        notas = self.repo.listar_notas(self.pid)
        self.assertEqual(len(notas), 1, "so deveria existir 1 nota pra essa mensalidade")

    def test_dia_normal_sem_atraso_nao_sinaliza_atraso(self):
        resultado = agendador.rodar_ciclo(
            self.repo, self.pasta_base, emissor=_emissor_sempre_ok, hoje=datetime.date(2026, 9, 5)
        )
        self.assertEqual(len(resultado.notas_criadas_catchup), 1)
        self.assertFalse(resultado.houve_atraso, "emitir no proprio dia 5 nao e atraso")

    def test_avanco_dia_a_dia_no_mesmo_ciclo_de_15_min_nao_duplica(self):
        # dia 5: emite normal
        agendador.rodar_ciclo(self.repo, self.pasta_base, emissor=_emissor_sempre_ok, hoje=datetime.date(2026, 9, 5))
        # dia 6, 7: nada devido
        agendador.rodar_ciclo(self.repo, self.pasta_base, emissor=_emissor_sempre_ok, hoje=datetime.date(2026, 9, 6))
        agendador.rodar_ciclo(self.repo, self.pasta_base, emissor=_emissor_sempre_ok, hoje=datetime.date(2026, 9, 7))
        notas = self.repo.listar_notas(self.pid)
        self.assertEqual(len(notas), 1)


if __name__ == "__main__":
    unittest.main()
