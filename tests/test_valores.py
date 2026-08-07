"""Testes de app/core/valores.valor_foge_do_padrao — item 3 da automação
pedida: alerta (nunca bloqueia) quando o valor digitado foge muito do que
aquele tomador+serviço costuma pagar (docs/auditoria.md, Bloco 3: pega cedo
o erro de digitação tipo "R$300 virar R$3.000 por um zero a mais")."""
import unittest

from app.core import valores


class TestValorForaDoPadrao(unittest.TestCase):
    def test_sem_historico_nenhum_nao_ha_padrao_pra_comparar(self):
        self.assertIsNone(valores.valor_foge_do_padrao("3000.00", []))

    def test_historico_com_1_nota_ainda_nao_e_suficiente(self):
        # 1 nota so' nao e' "padrao" -- e' so' a primeira, nao pode acusar
        # a segunda de estar errada sem base nenhuma.
        self.assertIsNone(valores.valor_foge_do_padrao("3000.00", ["300.00"]))

    def test_valor_dentro_do_padrao_nao_alerta(self):
        historico = ["300.00", "300.00", "310.00"]
        self.assertIsNone(valores.valor_foge_do_padrao("305.00", historico))

    def test_valor_10x_maior_alerta(self):
        historico = ["300.00", "300.00", "300.00"]
        alerta = valores.valor_foge_do_padrao("3000.00", historico)
        self.assertIsNotNone(alerta)
        self.assertEqual(alerta["media_historica"], "300.00")
        self.assertEqual(alerta["quantidade_notas"], 3)
        self.assertGreater(alerta["percentual_diferenca"], 800)

    def test_valor_bem_menor_tambem_alerta(self):
        # nao e' so' valor MAIOR que pode ser erro de digitacao -- esquecer
        # um digito faz o valor cair tambem.
        historico = ["1000.00", "1000.00"]
        alerta = valores.valor_foge_do_padrao("100.00", historico)
        self.assertIsNotNone(alerta)

    def test_reajuste_moderado_nao_dispara_alerta_falso(self):
        # um reajuste real (ex.: +15%) nao pode ser tratado como erro de
        # digitacao -- so' desvios grandes (>50%) alertam.
        historico = ["300.00", "300.00", "300.00"]
        self.assertIsNone(valores.valor_foge_do_padrao("345.00", historico))

    def test_limite_customizado_e_respeitado(self):
        from decimal import Decimal
        historico = ["300.00", "300.00"]
        # 20% de diferenca, com limite bem apertado de 10% -> deve alertar
        alerta = valores.valor_foge_do_padrao("360.00", historico, limite=Decimal("0.10"))
        self.assertIsNotNone(alerta)


if __name__ == "__main__":
    unittest.main()
