"""Testes de docs/auditoria.md, Bloco 3 ("Entrada de dados"), um item por
classe:
  1. Valor monetário (app/core/valores.py)
  2. CNPJ/CPF — dígito verificador + BrasilAPI fora do ar sem travar a tela
  3. Nomes com acento/ç/apóstrofo/&/emoji não quebram XML nem arquivo/pasta
  4. Textos longos — limite do leiaute avisado antes da rejeição
  5. Datas — fuso/meia-noite e dia 29/30/31
"""
import datetime as dt
import unittest
from unittest import mock

import httpx

from app import repo
from app.core import brasilapi, documentos, pastas, valores
from app.fiscal import dps_builder as db


def _dados(nome_tomador="Unimed SJC", descricao="Consulta médica"):
    return db.DadosDPS(
        ambiente="homologacao",
        prestador=db.Prestador(documento="11222333000181", inscricao_municipal="123456", codigo_municipio="3549904"),
        tomador=db.Tomador(documento="12345678000199", nome=nome_tomador),
        servico=db.Servico(
            codigo_tributacao_nacional="040101", codigo_tributacao_municipal="0401010000",
            codigo_nbs="105011900", descricao=descricao,
            codigo_municipio_prestacao="3549904", valor="300.00",
        ),
    )


# --------------------------------------------------------------------------
# 1. Valor monetário
# --------------------------------------------------------------------------
class TestValorMonetario(unittest.TestCase):
    """Tabela: cada formato digitado x valor final (string pronta pro XML)."""

    TABELA_FORMATOS_VALIDOS = [
        ("1.500,00", "1500.00"),
        ("1500,00", "1500.00"),
        ("1500", "1500.00"),
        ("1500.00", "1500.00"),
        ("R$ 1.500,00", "1500.00"),
        ("R$1.500,00", "1500.00"),
        ("  1.500,00  ", "1500.00"),
        ("1.500", "1500.00"),  # milhar sem centavos
        ("1.234.567", "1234567.00"),  # dois pontos de milhar, todos com 3 digitos
        ("1500,5", "1500.50"),
        ("0,01", "0.01"),
        ("999999999999999", "999999999999999.00"),  # 15 digitos, teto do TSDec15V2
    ]

    TABELA_FORMATOS_REJEITADOS = [
        "",
        "   ",
        "0",
        "0,00",
        "-100",
        "-100,00",
        "1.500.00",  # ambiguo: dois pontos, ultimo grupo nao tem 3 digitos
        "1500,999",  # mais de 2 casas decimais -- nao arredonda mais sozinho
        "abc",
        "1.500,00,00",
        "9999999999999999",  # 16 digitos, estoura TSDec15V2 (max 15)
    ]

    def test_tabela_de_formatos_validos(self):
        for bruto, esperado in self.TABELA_FORMATOS_VALIDOS:
            with self.subTest(bruto=bruto):
                self.assertEqual(valores.normalizar_valor_monetario(bruto), esperado)

    def test_tabela_de_formatos_rejeitados(self):
        for bruto in self.TABELA_FORMATOS_REJEITADOS:
            with self.subTest(bruto=bruto):
                with self.assertRaises(valores.ValorInvalido):
                    valores.normalizar_valor_monetario(bruto)

    def test_mensagem_de_erro_e_legivel_sem_jargao_tecnico(self):
        with self.assertRaises(valores.ValorInvalido) as ctx:
            valores.normalizar_valor_monetario("R$ abc")
        texto = str(ctx.exception)
        self.assertNotIn("InvalidOperation", texto)
        self.assertNotIn("Decimal", texto)

    def test_dps_builder_gera_o_valor_exato_pro_xml(self):
        dados = _dados()
        dados.servico.valor = valores.normalizar_valor_monetario("R$ 1.500,00")
        xml = db.montar_dps_xml(dados)
        v_serv = xml.find(f".//{{{db.NS}}}vServ")
        self.assertEqual(v_serv.text, "1500.00")


# --------------------------------------------------------------------------
# 2. CNPJ / CPF
# --------------------------------------------------------------------------
class TestDocumentos(unittest.TestCase):
    CNPJ_VALIDO = "11222333000181"
    CNPJ_INVALIDO = "11222333000180"  # ultimo digito trocado
    CPF_VALIDO = "11144477735"
    CPF_INVALIDO = "11144477736"

    def test_cnpj_valido_com_e_sem_mascara(self):
        self.assertTrue(documentos.validar_cnpj(self.CNPJ_VALIDO))
        self.assertTrue(documentos.validar_cnpj("11.222.333/0001-81"))

    def test_cnpj_invalido_e_rejeitado(self):
        self.assertFalse(documentos.validar_cnpj(self.CNPJ_INVALIDO))

    def test_cpf_valido_com_e_sem_mascara(self):
        self.assertTrue(documentos.validar_cpf(self.CPF_VALIDO))
        self.assertTrue(documentos.validar_cpf("111.444.777-35"))

    def test_cpf_invalido_e_rejeitado(self):
        self.assertFalse(documentos.validar_cpf(self.CPF_INVALIDO))

    def test_cpf_com_digitos_repetidos_e_sempre_invalido(self):
        # Passa no mod-11 mas nunca e' um CPF de verdade -- blacklist explicita.
        self.assertFalse(documentos.validar_cpf("111.111.111-11"))
        self.assertFalse(documentos.validar_cpf("00000000000"))

    def test_cnpj_alfanumerico_novo_formato_2026(self):
        # Exemplo oficial de divulgacao da Receita Federal do novo formato
        # (producao desde 06/07/2026).
        self.assertTrue(documentos.validar_cnpj("12.ABC.345/01DE-35"))

    def test_exigir_documento_valido_levanta_mensagem_clara(self):
        with self.assertRaises(documentos.DocumentoInvalido) as ctx:
            documentos.exigir_documento_valido(self.CPF_INVALIDO)
        texto = str(ctx.exception)
        self.assertIn("CPF", texto)
        self.assertNotIn("Traceback", texto)

    def test_documento_com_tamanho_errado_e_invalido(self):
        self.assertFalse(documentos.validar_cpf_ou_cnpj("123"))
        with self.assertRaises(documentos.DocumentoInvalido):
            documentos.exigir_documento_valido("123")


class TestBrasilApiForaDoAr(unittest.TestCase):
    """BrasilAPI indisponível não pode travar nem quebrar cru -- vira uma
    exceção traduzível (ErroConsultaCnpj), tratada como não-fatal."""

    def test_erro_de_rede_vira_excecao_tratavel_nao_crash_cru(self):
        with mock.patch("httpx.get", side_effect=httpx.ConnectTimeout("timeout")):
            with self.assertRaises(brasilapi.ErroConsultaCnpj):
                brasilapi.buscar_cnpj("11222333000181")

    def test_http_500_vira_excecao_tratavel(self):
        resposta_falsa = mock.Mock(status_code=500)
        with mock.patch("httpx.get", return_value=resposta_falsa):
            with self.assertRaises(brasilapi.ErroConsultaCnpj):
                brasilapi.buscar_cnpj("11222333000181")


class TestBuscaEmSegundoPlanoNaoTravaAJanela(unittest.TestCase):
    """docs/auditoria.md, Bloco 3/7.2: a busca de CNPJ rodava direto na
    thread da UI e travava a janela inteira se a rede estivesse lenta/fora
    do ar. `widgets.executar_em_segundo_plano` move isso pra uma QThread --
    aqui confirmamos que sucesso E falha chegam pelos callbacks certos."""

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def _rodar_ate_terminar(self, funcao):
        from PySide6.QtCore import QEventLoop, QTimer
        from app.ui import widgets

        resultado = {}
        loop = QEventLoop()

        def ao_suceder(valor):
            resultado["valor"] = valor
            loop.quit()

        def ao_falhar(exc):
            resultado["erro"] = exc
            loop.quit()

        QTimer.singleShot(5000, loop.quit)  # trava de seguranca do proprio teste
        thread = widgets.executar_em_segundo_plano(None, funcao, ao_suceder, ao_falhar)
        loop.exec()
        thread.wait(2000)
        return resultado

    def test_sucesso_chama_callback_de_sucesso(self):
        resultado = self._rodar_ate_terminar(lambda: 42)
        self.assertEqual(resultado.get("valor"), 42)
        self.assertNotIn("erro", resultado)

    def test_erro_de_rede_chama_callback_de_erro_sem_derrubar_a_app(self):
        def falha():
            raise brasilapi.ErroConsultaCnpj("BrasilAPI fora do ar")

        resultado = self._rodar_ate_terminar(falha)
        self.assertIsInstance(resultado.get("erro"), brasilapi.ErroConsultaCnpj)
        self.assertNotIn("valor", resultado)


# --------------------------------------------------------------------------
# 3. Nomes especiais não podem quebrar XML nem arquivo/pasta
# --------------------------------------------------------------------------
class TestNomesEspeciais(unittest.TestCase):
    NOME_TRICKY = "D'Ávila & Cia 🎉 — José François"

    def test_nome_com_acento_apostrofo_e_comercial_e_emoji_nao_quebra_xml(self):
        dados = _dados(nome_tomador=self.NOME_TRICKY)
        xml = db.montar_dps_xml(dados)
        serializado = db.serializar(xml)  # levantaria erro se tivesse char invalido
        self.assertIn("D'Ávila".encode("utf-8"), serializado)
        self.assertIn("&amp;".encode("utf-8"), serializado)  # "&" escapado pelo lxml

    def test_caractere_de_controle_e_removido_sem_quebrar_o_xml(self):
        nome_com_controle = "Maria\x07 da Silva\x0b"
        dados = _dados(nome_tomador=nome_com_controle)
        xml = db.montar_dps_xml(dados)  # nao pode levantar ValueError do lxml
        x_nome = xml.find(f".//{{{db.NS}}}xNome")
        self.assertNotIn("\x07", x_nome.text)
        self.assertNotIn("\x0b", x_nome.text)
        self.assertIn("Maria", x_nome.text)

    def test_nome_de_arquivo_com_caracteres_tricky_nao_quebra(self):
        base = pastas.nome_base_arquivo("123", self.NOME_TRICKY, "1500.00")
        self.assertNotRegex(base, r'[\\/:*?"<>|]')
        self.assertTrue(base)  # nao virou "sem-nome"

    def test_nome_de_arquivo_com_caractere_de_controle_e_removido(self):
        nome_com_controle = "Cliente\x00Malicioso\x1f"
        base = pastas.sanitizar_nome_arquivo(nome_com_controle)
        self.assertNotIn("\x00", base)
        self.assertNotIn("\x1f", base)

    def test_salvar_nota_com_nome_tricky_cria_arquivo_de_verdade(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            xml_path, _pdf = pastas.salvar_nota(
                tmp, "Dr. Teste", numero="1", nome_tomador=self.NOME_TRICKY,
                valor="300.00", data_emissao=dt.date(2026, 7, 22), xml_bytes=b"<x/>",
            )
            self.assertTrue(xml_path.exists())


# --------------------------------------------------------------------------
# 4. Textos longos — avisar antes da rejeição
# --------------------------------------------------------------------------
class TestTextosLongos(unittest.TestCase):
    def test_descricao_dentro_do_limite_passa(self):
        dados = _dados(descricao="A" * db.TAMANHO_MAXIMO_DESCRICAO_SERVICO)
        db.montar_dps_xml(dados)  # nao deve levantar

    def test_descricao_acima_do_limite_e_bloqueada_com_mensagem_clara(self):
        dados = _dados(descricao="A" * (db.TAMANHO_MAXIMO_DESCRICAO_SERVICO + 1))
        with self.assertRaises(db.CampoMuitoLongo) as ctx:
            db.montar_dps_xml(dados)
        self.assertIn(str(db.TAMANHO_MAXIMO_DESCRICAO_SERVICO), str(ctx.exception))

    def test_nome_tomador_dentro_do_limite_passa(self):
        dados = _dados(nome_tomador="A" * db.TAMANHO_MAXIMO_NOME)
        db.montar_dps_xml(dados)

    def test_nome_tomador_acima_do_limite_e_bloqueado(self):
        dados = _dados(nome_tomador="A" * (db.TAMANHO_MAXIMO_NOME + 1))
        with self.assertRaises(db.CampoMuitoLongo):
            db.montar_dps_xml(dados)


# --------------------------------------------------------------------------
# 5. Datas: fuso, meia-noite, dia 29/30/31
# --------------------------------------------------------------------------
class TestDatas(unittest.TestCase):
    def test_dhemi_e_dcompet_nunca_divergem_perto_da_meia_noite(self):
        instante_antes_da_meia_noite = dt.datetime(2026, 7, 22, 23, 59, 59, tzinfo=dt.timezone(dt.timedelta(hours=-3)))
        with mock.patch.object(db.dt, "datetime") as datetime_mock:
            datetime_mock.now.return_value = instante_antes_da_meia_noite
            dados = _dados()
            xml = db.montar_dps_xml(dados)
        dh_emi = xml.find(f".//{{{db.NS}}}dhEmi").text
        d_compet = xml.find(f".//{{{db.NS}}}dCompet").text
        self.assertEqual(dh_emi[:10], "2026-07-22")
        self.assertEqual(d_compet, "2026-07-22")

    def test_formatar_dhemi_usa_fuso_horario_com_horas_cheias(self):
        instante = dt.datetime(2026, 7, 22, 10, 0, 0, tzinfo=dt.timezone(dt.timedelta(hours=-3)))
        self.assertEqual(db._formatar_dhemi(instante), "2026-07-22T10:00:00-03:00")

    def test_recorrencia_aceita_dia_1_a_28(self):
        repositorio = repo.Repositorio(":memory:")
        prestador_id = repositorio.criar_prestador(
            nome_exibicao="Dr. Teste", cnpj="11222333000181", im="123", codigo_municipio="3549904",
        )
        tomador_id = repositorio.criar_tomador(prestador_id, doc="12345678901", nome="Paciente")
        modelo_id = repositorio.criar_modelo_servico(
            prestador_id, descricao="Consulta", cod_tributacao_nacional="040101",
            cod_tributacao_municipal="0401010000", cod_nbs="105011900", valor_padrao="300.00",
        )
        for dia in (1, 15, 28):
            with self.subTest(dia=dia):
                recorrencia_id = repositorio.criar_recorrencia(
                    prestador_id, tomador_id=tomador_id, modelo_id=modelo_id, valor="300.00", dia_do_mes=dia,
                )
                self.assertIsInstance(recorrencia_id, int)

    def test_recorrencia_rejeita_dia_29_30_31_e_0(self):
        repositorio = repo.Repositorio(":memory:")
        prestador_id = repositorio.criar_prestador(
            nome_exibicao="Dr. Teste", cnpj="11222333000181", im="123", codigo_municipio="3549904",
        )
        tomador_id = repositorio.criar_tomador(prestador_id, doc="12345678901", nome="Paciente")
        modelo_id = repositorio.criar_modelo_servico(
            prestador_id, descricao="Consulta", cod_tributacao_nacional="040101",
            cod_tributacao_municipal="0401010000", cod_nbs="105011900", valor_padrao="300.00",
        )
        for dia_invalido in (0, 29, 30, 31, -1):
            with self.subTest(dia=dia_invalido):
                with self.assertRaises(ValueError):
                    repositorio.criar_recorrencia(
                        prestador_id, tomador_id=tomador_id, modelo_id=modelo_id,
                        valor="300.00", dia_do_mes=dia_invalido,
                    )


if __name__ == "__main__":
    unittest.main()
