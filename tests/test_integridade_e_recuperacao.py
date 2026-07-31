"""Testes de docs/auditoria.md, Blocos 4 (editar/deletar/cancelar -- integridade)
e 6 (falhas e recuperacao), um item por classe:
  1. Inativar (nunca apagar) tomador/prestador com notas
  2. Renomear prestador renomeia a pasta fisica sem perder arquivos
  3. Editar modelo de servico NAO altera notas ja emitidas
  4. Nenhuma operacao apaga arquivo fiscal (auditoria + prova em disco)
  5. Emissao duplicada: clique duplo em "Emitir todas" / mensalidade 2x no dia
  6. Numeracao da DPS sem furo/repeticao mesmo com falha no meio do envio
  7. RECONCILIACAO: consulta de status antes de reenviar (nunca duplica)
  8. Certificado com senha errada/expirado/.pfx corrompido -> mensagem clara
  9. Traducao de codigos de rejeicao da API
  10. Retomada da fila ao reabrir + SQLite corrompido/lock + instancia unica
"""
import ast
import datetime as dt
import sqlite3
import tempfile
import unittest
from pathlib import Path

from app import repo
from app.core import fila, mensagens, pastas
from app.fiscal import api_nacional


def _prestador_tomador_modelo(repositorio):
    prestador_id = repositorio.criar_prestador(
        nome_exibicao="Dr. Teste", cnpj="11222333000181", im="123", codigo_municipio="3549904",
    )
    tomador_id = repositorio.criar_tomador(prestador_id, doc="12345678901", nome="Paciente Um")
    modelo_id = repositorio.criar_modelo_servico(
        prestador_id, descricao="Consulta", cod_tributacao_nacional="040101",
        cod_tributacao_municipal="0401010000", cod_nbs="105011900", valor_padrao="300.00",
    )
    return prestador_id, tomador_id, modelo_id


# --------------------------------------------------------------------------
# 1. Inativar, nunca apagar
# --------------------------------------------------------------------------
class TestInativarNaoApagar(unittest.TestCase):
    def setUp(self):
        self.repositorio = repo.Repositorio(":memory:")
        self.prestador_id, self.tomador_id, self.modelo_id = _prestador_tomador_modelo(self.repositorio)

    def test_tomador_com_nota_nao_pode_ser_excluido_mas_pode_ser_inativado(self):
        self.repositorio.criar_nota(self.prestador_id, tomador_id=self.tomador_id, modelo_id=self.modelo_id, valor="100.00")
        with self.assertRaises(ValueError):
            self.repositorio.excluir_tomador(self.prestador_id, self.tomador_id)
        # nao apagou nada -- continua existindo
        self.assertIsNotNone(self.repositorio.obter_tomador(self.prestador_id, self.tomador_id))

        self.repositorio.inativar_tomador(self.prestador_id, self.tomador_id)
        tomador = self.repositorio.obter_tomador(self.prestador_id, self.tomador_id)
        self.assertEqual(tomador["ativo"], 0)
        self.assertNotIn(tomador, self.repositorio.listar_tomadores(self.prestador_id))  # some da lista ativa
        self.assertIn(tomador["id"], [t["id"] for t in self.repositorio.listar_tomadores(self.prestador_id, apenas_ativos=False)])

    def test_reativar_tomador_volta_pra_lista_ativa(self):
        self.repositorio.inativar_tomador(self.prestador_id, self.tomador_id)
        self.repositorio.reativar_tomador(self.prestador_id, self.tomador_id)
        ids_ativos = [t["id"] for t in self.repositorio.listar_tomadores(self.prestador_id)]
        self.assertIn(self.tomador_id, ids_ativos)

    def test_inativar_tomador_pausa_mensalidades_ativas(self):
        recorrencia_id = self.repositorio.criar_recorrencia(
            self.prestador_id, tomador_id=self.tomador_id, modelo_id=self.modelo_id, valor="100.00", dia_do_mes=5,
        )
        self.repositorio.inativar_tomador(self.prestador_id, self.tomador_id)
        recorrencias = self.repositorio.listar_recorrencias(self.prestador_id, apenas_ativas=False)
        r = next(r for r in recorrencias if r["id"] == recorrencia_id)
        self.assertEqual(r["ativo"], 0)

    def test_prestador_com_nota_nao_pode_ser_excluido_mas_pode_ser_inativado(self):
        self.repositorio.criar_nota(self.prestador_id, tomador_id=self.tomador_id, modelo_id=self.modelo_id, valor="100.00")
        with self.assertRaises(ValueError):
            self.repositorio.excluir_prestador(self.prestador_id)
        self.assertIsNotNone(self.repositorio.obter_prestador(self.prestador_id))

        self.repositorio.inativar_prestador(self.prestador_id)
        prestador = self.repositorio.obter_prestador(self.prestador_id)
        self.assertEqual(prestador["ativo"], 0)
        self.assertNotIn(prestador, self.repositorio.listar_prestadores())
        self.assertIn(prestador["id"], [p["id"] for p in self.repositorio.listar_prestadores(apenas_ativos=False)])

    def test_reativar_prestador_volta_pra_lista_ativa(self):
        self.repositorio.inativar_prestador(self.prestador_id)
        self.repositorio.reativar_prestador(self.prestador_id)
        self.assertIn(self.prestador_id, [p["id"] for p in self.repositorio.listar_prestadores()])

    def test_tomador_sem_vinculo_ainda_pode_ser_excluido_de_verdade(self):
        # inativar nao substitui a exclusao real quando ela e' segura (sem
        # nota/mensalidade nenhuma vinculada) -- so' bloqueia quando ha' risco
        # de perder historico.
        self.repositorio.excluir_tomador(self.prestador_id, self.tomador_id)
        self.assertIsNone(self.repositorio.obter_tomador(self.prestador_id, self.tomador_id))


# --------------------------------------------------------------------------
# 2. Renomear prestador renomeia a pasta sem perder arquivos
# --------------------------------------------------------------------------
class TestRenomearPastaPrestador(unittest.TestCase):
    def test_renomeia_pasta_fisica_preservando_arquivos(self):
        with tempfile.TemporaryDirectory() as tmp:
            prestador = {"nome_exibicao": "Dr. Joao Cardoso", "pasta_nome": None}
            xml_path, _ = pastas.salvar_nota(
                tmp, prestador["nome_exibicao"], numero="1", nome_tomador="Paciente",
                valor="300.00", data_emissao=dt.date(2026, 7, 20), xml_bytes=b"<x>original</x>",
            )
            self.assertTrue(xml_path.exists())

            novo_pasta_nome = pastas.renomear_pasta_prestador(tmp, prestador, "Dr. João Cardoso")

            self.assertFalse(xml_path.exists())  # caminho antigo nao existe mais
            novo_caminho = Path(tmp) / novo_pasta_nome / "2026" / "07 - Julho" / "Emitidas" / xml_path.name
            self.assertTrue(novo_caminho.exists())
            self.assertEqual(novo_caminho.read_bytes(), b"<x>original</x>")  # conteudo preservado

    def test_pasta_travada_nao_muda_de_novo_sozinha(self):
        """Depois de renomear (persistindo pasta_nome), uma nova emissao usa
        o pasta_nome travado, nao volta a seguir o nome_exibicao."""
        with tempfile.TemporaryDirectory() as tmp:
            prestador = {"nome_exibicao": "Dr. Joao", "pasta_nome": None}
            pastas.salvar_nota(
                tmp, prestador["nome_exibicao"], numero="1", nome_tomador="Paciente",
                valor="300.00", data_emissao=dt.date(2026, 7, 20), xml_bytes=b"<x/>",
            )
            pasta_nome_travado = pastas.renomear_pasta_prestador(tmp, prestador, "Dr. João Cardoso")
            prestador_atualizado = {"nome_exibicao": "Dr. João Cardoso", "pasta_nome": pasta_nome_travado}

            # Emissao seguinte, mesmo pasta_nome (simulando o que fila.py faz)
            xml_path2, _ = pastas.salvar_nota(
                tmp, prestador_atualizado["nome_exibicao"], numero="2", nome_tomador="Paciente",
                valor="300.00", data_emissao=dt.date(2026, 7, 21), xml_bytes=b"<x2/>",
                pasta_nome=prestador_atualizado["pasta_nome"],
            )
            self.assertIn(pasta_nome_travado, str(xml_path2))

    def test_sem_pasta_fisica_ainda_so_atualiza_o_nome(self):
        # Prestador recem-criado, nunca emitiu nada -- nao ha pasta pra mover.
        with tempfile.TemporaryDirectory() as tmp:
            prestador = {"nome_exibicao": "Dr. Novo", "pasta_nome": None}
            novo_nome = pastas.renomear_pasta_prestador(tmp, prestador, "Dr. Novo Silva")
            self.assertEqual(novo_nome, "Dr. Novo Silva")

    def test_conflito_de_nome_nao_perde_a_pasta_antiga(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "Dr. Ana").mkdir()
            prestador = {"nome_exibicao": "Dr. Joao", "pasta_nome": None}
            pastas.salvar_nota(
                tmp, prestador["nome_exibicao"], numero="1", nome_tomador="Paciente",
                valor="300.00", data_emissao=dt.date(2026, 7, 20), xml_bytes=b"<x/>",
            )
            with self.assertRaises(FileExistsError):
                pastas.renomear_pasta_prestador(tmp, prestador, "Dr. Ana")
            # a pasta original do Dr. Joao continua intacta
            self.assertTrue((Path(tmp) / "Dr. Joao" / "2026" / "07 - Julho" / "Emitidas").exists())


# --------------------------------------------------------------------------
# 3. Editar modelo de servico nao altera notas ja emitidas
# --------------------------------------------------------------------------
class TestEditarModeloNaoAlteraNotasEmitidas(unittest.TestCase):
    def test_nota_emitida_preserva_valor_e_xml_apos_editar_o_modelo(self):
        repositorio = repo.Repositorio(":memory:")
        prestador_id, tomador_id, modelo_id = _prestador_tomador_modelo(repositorio)
        nota_id = repositorio.criar_nota(prestador_id, tomador_id=tomador_id, modelo_id=modelo_id, valor="300.00")
        repositorio.marcar_emitida(
            prestador_id, nota_id, chave_acesso="CHAVE-1",
            xml_conteudo="<xDescServ>Consulta</xDescServ><vServ>300.00</vServ>",
            xml_path="/fake/path.xml",
        )

        repositorio.atualizar_modelo_servico(
            prestador_id, modelo_id, descricao="Retorno (nome mudou)", cod_tributacao_nacional="040101",
            cod_tributacao_municipal="0401010000", cod_nbs="105011900", valor_padrao="999.00",
        )

        nota = repositorio.obter_nota(prestador_id, nota_id)
        self.assertEqual(nota["valor"], "300.00")  # nao virou 999.00
        self.assertIn("Consulta", nota["xml_conteudo"])
        self.assertNotIn("Retorno", nota["xml_conteudo"])


# --------------------------------------------------------------------------
# 4. Nenhuma operacao apaga arquivo fiscal -- auditoria + prova
# --------------------------------------------------------------------------
class TestNenhumaOperacaoApagaArquivoFiscal(unittest.TestCase):
    def test_auditoria_estatica_sem_remocao_de_arquivo_no_codigo_fiscal(self):
        """Percorre a AST de todo modulo que mexe com nota/arquivo (repo,
        fila, pastas) procurando qualquer chamada de remocao de arquivo
        (os.remove, Path.unlink, shutil.rmtree). A UNICA excecao esperada e'
        `api_nacional.py` apagando os .pem TEMPORARIOS do mTLS -- nunca XML/PDF."""
        arquivos_fiscais = [
            Path("app/repo.py"), Path("app/core/fila.py"), Path("app/core/pastas.py"),
        ]
        chamadas_de_remocao = {"remove", "unlink", "rmtree"}
        encontrados = []
        for caminho in arquivos_fiscais:
            arvore = ast.parse(caminho.read_text(encoding="utf-8"))
            for no in ast.walk(arvore):
                if isinstance(no, ast.Call) and isinstance(no.func, ast.Attribute):
                    if no.func.attr in chamadas_de_remocao:
                        encontrados.append(f"{caminho}:{no.lineno} — {no.func.attr}")
        self.assertEqual(encontrados, [], f"Chamada de remocao de arquivo encontrada onde nao deveria: {encontrados}")

    def test_cancelar_move_o_arquivo_em_vez_de_apagar(self):
        with tempfile.TemporaryDirectory() as tmp:
            xml_path, _ = pastas.salvar_nota(
                tmp, "Dr. Teste", numero="1", nome_tomador="Paciente",
                valor="300.00", data_emissao=dt.date(2026, 7, 20), xml_bytes=b"<x/>",
            )
            novo_xml, _ = pastas.cancelar_nota(xml_path)
            self.assertFalse(xml_path.exists())  # saiu de Emitidas/
            self.assertTrue(novo_xml.exists())    # mas continua existindo em Canceladas/
            self.assertIn("Canceladas", str(novo_xml))

    def test_excluir_tomador_prestador_notas_nao_mexe_no_disco(self):
        """Excluir registros do BANCO (quando permitido, sem nota vinculada)
        nunca deveria, e nunca deve passar a, tocar em arquivo no disco --
        ambas as coisas sao camadas completamente separadas."""
        with tempfile.TemporaryDirectory() as tmp:
            repositorio = repo.Repositorio(":memory:")
            prestador_id, tomador_id, modelo_id = _prestador_tomador_modelo(repositorio)
            xml_path, _ = pastas.salvar_nota(
                tmp, "Dr. Teste", numero="1", nome_tomador="Paciente",
                valor="300.00", data_emissao=dt.date(2026, 7, 20), xml_bytes=b"<x/>",
            )
            # tomador sem nota vinculada no BANCO (a nota acima e' so' arquivo
            # solto, criado direto por pastas.py, sem passar por repo.criar_nota)
            repositorio.excluir_tomador(prestador_id, tomador_id)
            self.assertTrue(xml_path.exists())  # arquivo continua no disco


# --------------------------------------------------------------------------
# 5. Emissao duplicada: clique duplo / mensalidade 2x no mesmo dia
# --------------------------------------------------------------------------
class TestEmissaoDuplicada(unittest.TestCase):
    def setUp(self):
        self.repositorio = repo.Repositorio(":memory:")
        self.prestador_id, self.tomador_id, self.modelo_id = _prestador_tomador_modelo(self.repositorio)
        self.repositorio.criar_recorrencia(
            self.prestador_id, tomador_id=self.tomador_id, modelo_id=self.modelo_id, valor="300.00", dia_do_mes=20,
        )

    def test_criar_notas_do_dia_duas_vezes_seguidas_nao_duplica(self):
        hoje = dt.date(2026, 7, 20)
        primeira = fila.criar_notas_das_recorrencias_do_dia(self.repositorio, hoje)
        segunda = fila.criar_notas_das_recorrencias_do_dia(self.repositorio, hoje)
        self.assertEqual(len(primeira), 1)
        self.assertEqual(len(segunda), 0)  # a segunda chamada nao cria nada novo
        notas = self.repositorio.listar_notas(self.prestador_id)
        self.assertEqual(len(notas), 1)

    def test_ja_emitida_no_mes_fica_verdadeiro_assim_que_a_primeira_nota_e_criada(self):
        """`ja_emitida_no_mes` precisa virar True so' de existir uma nota
        'pendente' -- ANTES dela sequer ser enviada -- senao um segundo
        clique bem rapido (antes do primeiro terminar de processar a fila)
        ainda criaria uma segunda nota."""
        hoje = dt.date(2026, 7, 20)
        fila.criar_notas_das_recorrencias_do_dia(self.repositorio, hoje)
        dados = self.repositorio.dados_meu_dia(hoje)
        m = dados["mensalidades_hoje"][0]
        self.assertTrue(m["ja_emitida_no_mes"])


# --------------------------------------------------------------------------
# 6. Numeracao da DPS sem furo/repeticao mesmo com falha no meio do envio
# --------------------------------------------------------------------------
class TestNumeracaoDps(unittest.TestCase):
    def setUp(self):
        self.repositorio = repo.Repositorio(":memory:")
        self.prestador_id, self.tomador_id, self.modelo_id = _prestador_tomador_modelo(self.repositorio)

    def _criar(self):
        return self.repositorio.criar_nota(self.prestador_id, tomador_id=self.tomador_id, modelo_id=self.modelo_id, valor="100.00")

    def test_numeracao_sequencial_sem_furo(self):
        ids = [self._criar() for _ in range(5)]
        numeros = [self.repositorio.obter_nota(self.prestador_id, i)["numero_dps"] for i in ids]
        self.assertEqual(numeros, ["1", "2", "3", "4", "5"])

    def test_colisao_de_numero_e_absorvida_sem_erro_tecnico(self):
        """Simula duas 'emissoes quase simultaneas': insere manualmente uma
        nota com o proximo numero ANTES de `criar_nota` calcular o dele (ex.:
        outra conexao ganhou a corrida) -- `criar_nota` deve se recuperar
        sozinho recalculando, nunca vazar um IntegrityError cru."""
        primeiro_id = self._criar()  # numero_dps = "1"
        # Insere direto por baixo dos panos simulando a corrida: alguem mais
        # ja pegou o numero "2" bem no instante em que criar_nota ia usa-lo.
        r = repo._normalizar_retencoes(None)
        colunas = ", ".join(repo.CAMPOS_RETENCAO)
        interrogacoes = ", ".join("?" * len(repo.CAMPOS_RETENCAO))
        self.repositorio._conn.execute(
            f"""INSERT INTO notas (prestador_id, tomador_id, modelo_id, valor, serie, numero_dps, status, {colunas})
               VALUES (?, ?, ?, ?, ?, ?, ?, {interrogacoes})""",
            (
                self.prestador_id, self.tomador_id, self.modelo_id, "50.00", "1", "2", repo.STATUS_PENDENTE,
                *(r[c] for c in repo.CAMPOS_RETENCAO),
            ),
        )
        self.repositorio._conn.commit()

        novo_id = self._criar()  # tentaria "2" de novo, precisa recalcular pra "3"
        nova_nota = self.repositorio.obter_nota(self.prestador_id, novo_id)
        self.assertEqual(nova_nota["numero_dps"], "3")

    def test_numero_repetido_explicito_ainda_levanta_erro_de_integridade(self):
        """Quando o numero e' passado EXPLICITAMENTE (nao autogerado), uma
        colisao de verdade deve continuar sendo um erro real -- nao faz
        sentido "corrigir sozinho" um numero que o chamador escolheu."""
        self.repositorio.criar_nota(
            self.prestador_id, tomador_id=self.tomador_id, modelo_id=self.modelo_id,
            valor="100.00", numero_dps="42",
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.repositorio.criar_nota(
                self.prestador_id, tomador_id=self.tomador_id, modelo_id=self.modelo_id,
                valor="100.00", numero_dps="42",
            )


# --------------------------------------------------------------------------
# 7. RECONCILIACAO -- consulta de status antes de reenviar
# --------------------------------------------------------------------------
class FakeReconciliador:
    def __init__(self, resposta):
        self.resposta = resposta
        self.chamadas = 0

    def __call__(self, prestador, nota):
        self.chamadas += 1
        return self.resposta


class FakeEmissorNuncaDeveriaSerChamado:
    def __call__(self, prestador, tomador, nota, modelo):
        raise AssertionError("emissor NAO deveria ser chamado quando a reconciliacao ja encontrou a nota")


class TestReconciliacao(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.pasta_base = Path(self._tmp.name) / "notas"
        self.repositorio = repo.Repositorio(Path(self._tmp.name) / "teste.db")
        self.prestador_id, self.tomador_id, self.modelo_id = _prestador_tomador_modelo(self.repositorio)

    def tearDown(self):
        self.repositorio.fechar()
        self._tmp.cleanup()

    def _criar_nota_como_se_ja_tivesse_falhado_uma_vez(self):
        """Simula o cenario exato do achado critico: a nota ja foi tentada
        uma vez (a internet caiu DEPOIS do governo processar, ANTES da
        resposta voltar) e ficou pendente de novo, esperando retry."""
        nota_id = self.repositorio.criar_nota(
            self.prestador_id, tomador_id=self.tomador_id, modelo_id=self.modelo_id, valor="300.00",
        )
        self.repositorio.incrementar_tentativa(self.prestador_id, nota_id)  # tentativas = 1
        self.repositorio.marcar_para_retry(
            self.prestador_id, nota_id, proxima_tentativa_em=dt.datetime(2020, 1, 1),  # ja no passado, pronta pra tentar
        )
        return nota_id

    def test_nota_ja_aceita_pelo_governo_e_reconciliada_sem_reenviar(self):
        nota_id = self._criar_nota_como_se_ja_tivesse_falhado_uma_vez()
        reconciliador = FakeReconciliador(api_nacional.RespostaConsultaDps(
            encontrada=True, chave_acesso="CHAVE-RECUPERADA", xml_nfse=b"<NFSe>reconciliada</NFSe>",
        ))

        resultados = fila.processar_fila(
            self.repositorio, self.pasta_base,
            emissor=FakeEmissorNuncaDeveriaSerChamado(), reconciliador=reconciliador,
            enviar_email=False,
        )

        self.assertEqual(reconciliador.chamadas, 1)
        self.assertEqual(resultados[0]["status"], "emitida")
        self.assertTrue(resultados[0].get("reconciliada"))
        nota = self.repositorio.obter_nota(self.prestador_id, nota_id)
        self.assertEqual(nota["status"], repo.STATUS_EMITIDA)
        self.assertEqual(nota["chave_acesso"], "CHAVE-RECUPERADA")
        self.assertIn("reconciliada", nota["xml_conteudo"])

    def test_nota_nao_encontrada_segue_fluxo_normal_de_reenvio(self):
        nota_id = self._criar_nota_como_se_ja_tivesse_falhado_uma_vez()
        reconciliador = FakeReconciliador(api_nacional.RespostaConsultaDps(encontrada=False))
        chamadas_emissor = []

        def emissor_ok(prestador, tomador, nota, modelo):
            chamadas_emissor.append(nota["id"])
            return api_nacional.RespostaEmissao(chave_acesso="CHAVE-NOVA", xml_nfse=b"<NFSe>nova</NFSe>")

        resultados = fila.processar_fila(
            self.repositorio, self.pasta_base,
            emissor=emissor_ok, reconciliador=reconciliador, enviar_email=False,
        )

        self.assertEqual(reconciliador.chamadas, 1)
        self.assertEqual(chamadas_emissor, [nota_id])  # reenviou de verdade, so' porque nao achou
        self.assertEqual(resultados[0]["status"], "emitida")
        self.assertEqual(resultados[0]["chave_acesso"], "CHAVE-NOVA")

    def test_falha_na_propria_reconciliacao_so_reagenda_nunca_reenvia(self):
        nota_id = self._criar_nota_como_se_ja_tivesse_falhado_uma_vez()

        def reconciliador_com_erro(prestador, nota):
            raise api_nacional.ErroRede("timeout consultando DPS")

        resultados = fila.processar_fila(
            self.repositorio, self.pasta_base,
            emissor=FakeEmissorNuncaDeveriaSerChamado(), reconciliador=reconciliador_com_erro,
            enviar_email=False,
        )
        self.assertEqual(resultados[0]["status"], "pendente")
        nota = self.repositorio.obter_nota(self.prestador_id, nota_id)
        self.assertEqual(nota["status"], repo.STATUS_PENDENTE)  # nunca virou emitida por engano

    def test_primeira_tentativa_nunca_reconcilia(self):
        """tentativas == 1 (primeira vez de verdade) nao tem porque
        reconciliar -- nunca houve uma tentativa anterior que pudesse ter
        sido aceita sem o app saber."""
        nota_id = self.repositorio.criar_nota(
            self.prestador_id, tomador_id=self.tomador_id, modelo_id=self.modelo_id, valor="300.00",
        )
        reconciliador = FakeReconciliador(api_nacional.RespostaConsultaDps(encontrada=True, chave_acesso="X"))

        def emissor_ok(prestador, tomador, nota, modelo):
            return api_nacional.RespostaEmissao(chave_acesso="CHAVE-1", xml_nfse=b"<NFSe/>")

        fila.processar_fila(
            self.repositorio, self.pasta_base, emissor=emissor_ok, reconciliador=reconciliador, enviar_email=False,
        )
        self.assertEqual(reconciliador.chamadas, 0)


# --------------------------------------------------------------------------
# 8. Certificado: senha errada / expirado / .pfx corrompido -> mensagem clara
# --------------------------------------------------------------------------
class TestMensagensCertificado(unittest.TestCase):
    def test_pfx_corrompido_nao_mostra_stacktrace(self):
        from app.fiscal import assinador
        with tempfile.NamedTemporaryFile(suffix=".pfx", delete=False) as f:
            f.write(b"isto definitivamente nao e' um arquivo pkcs12 valido")
            caminho = f.name
        try:
            with self.assertRaises(ValueError) as ctx:
                assinador.carregar_pfx_com_senha(caminho, "qualquer-senha")
            texto = mensagens.traduzir_erro(ctx.exception)
            self.assertNotIn("Traceback", texto)
            self.assertIn("certificado", texto.lower())
        finally:
            Path(caminho).unlink()

    def test_certificado_expirado_e_bloqueado_antes_de_assinar_com_mensagem_clara(self):
        from app.fiscal import assinador
        classe_erro = assinador.CertificadoExpirado
        erro = classe_erro("Este certificado venceu em 01/01/2020. Renove o certificado A1 (ou importe um novo) antes de emitir.")
        texto = mensagens.traduzir_erro(erro)
        self.assertIn("venceu", texto)
        self.assertNotIn("Traceback", texto)
        self.assertNotIn("Algo deu errado", texto)

    def test_senha_errada_da_mensagem_clara_nao_tecnica(self):
        erro = ValueError("Invalid password or PKCS12 data")
        texto = mensagens.traduzir_erro(erro)
        self.assertIn("senha", texto.lower())
        self.assertNotIn("PKCS12", texto)


# --------------------------------------------------------------------------
# 9. Traducao de codigos de rejeicao
# --------------------------------------------------------------------------
class TestTraducaoDeCodigosDeRejeicao(unittest.TestCase):
    CODIGOS_QUE_PRECISAM_TRADUCAO = [
        "E0001", "E0037", "E0082", "E0098", "E0160", "E0190", "E0330", "E0404",
        "E0429", "E0617", "E0625", "E0700", "E0715", "E1268", "E1300",
    ]

    def test_codigos_ampliados_tem_traducao_clara(self):
        for codigo in self.CODIGOS_QUE_PRECISAM_TRADUCAO:
            with self.subTest(codigo=codigo):
                texto = mensagens.traduzir_motivo_rejeicao(f"{codigo}: descricao tecnica original da receita")
                self.assertNotEqual(texto, f"A Receita rejeitou esta nota: {codigo}: descricao tecnica original da receita")

    def test_codigo_desconhecido_ainda_cai_no_fallback_legivel(self):
        texto = mensagens.traduzir_motivo_rejeicao("E9999: erro nunca visto antes")
        self.assertIn("A Receita rejeitou esta nota", texto)


# --------------------------------------------------------------------------
# 10. Retomada da fila + SQLite corrompido/lock + instancia unica
# --------------------------------------------------------------------------
class TestRetomadaERecuperacao(unittest.TestCase):
    def test_nota_pendente_e_retomada_ao_reabrir_o_app(self):
        """Fecha o app (so' fecha a conexao -- SQLite persiste em disco) com
        uma nota pendente, "reabre" (nova conexao no MESMO arquivo) e
        confirma que a fila ainda encontra a nota pra tentar de novo."""
        with tempfile.TemporaryDirectory() as tmp:
            caminho_db = Path(tmp) / "emissor.db"
            repositorio1 = repo.Repositorio(caminho_db)
            prestador_id, tomador_id, modelo_id = _prestador_tomador_modelo(repositorio1)
            nota_id = repositorio1.criar_nota(prestador_id, tomador_id=tomador_id, modelo_id=modelo_id, valor="300.00")
            repositorio1.fechar()  # simula fechar o app

            repositorio2 = repo.Repositorio(caminho_db)  # simula reabrir o app
            pendentes = repositorio2.listar_notas_pendentes_prontas_para_tentar(dt.datetime.now())
            self.assertIn(nota_id, [n["id"] for n in pendentes])
            repositorio2.fechar()

    def test_banco_corrompido_da_mensagem_clara_nao_tecnica(self):
        erro = sqlite3.DatabaseError("database disk image is malformed")
        texto = mensagens.traduzir_erro(erro)
        self.assertIn("corrompido", texto.lower())
        self.assertNotIn("malformed", texto)

    def test_banco_ocupado_da_mensagem_clara_sobre_outra_instancia(self):
        erro = sqlite3.OperationalError("database is locked")
        texto = mensagens.traduzir_erro(erro)
        self.assertIn("outra", texto.lower())
        self.assertNotIn("OperationalError", texto)

    def test_repositorio_abre_em_modo_wal(self):
        with tempfile.TemporaryDirectory() as tmp:
            caminho_db = Path(tmp) / "teste.db"
            repositorio = repo.Repositorio(caminho_db)
            modo = repositorio._conn.execute("PRAGMA journal_mode").fetchone()[0]
            self.assertEqual(modo.lower(), "wal")
            repositorio.fechar()

    def test_instancia_unica_bloqueia_segunda_tentativa(self):
        from app.core.instancia_unica import InstanciaUnica
        with tempfile.TemporaryDirectory() as tmp:
            caminho_lock = Path(tmp) / "instancia.lock"
            primeira = InstanciaUnica(caminho_lock)
            segunda = InstanciaUnica(caminho_lock)
            try:
                self.assertTrue(primeira.obter())
                self.assertFalse(segunda.obter())  # segunda instancia nao consegue
            finally:
                primeira.liberar()
                segunda.liberar()

    def test_instancia_unica_libera_e_permite_nova_instancia_depois(self):
        from app.core.instancia_unica import InstanciaUnica
        with tempfile.TemporaryDirectory() as tmp:
            caminho_lock = Path(tmp) / "instancia.lock"
            primeira = InstanciaUnica(caminho_lock)
            self.assertTrue(primeira.obter())
            primeira.liberar()

            segunda = InstanciaUnica(caminho_lock)
            try:
                self.assertTrue(segunda.obter())  # agora consegue, a primeira ja liberou
            finally:
                segunda.liberar()


if __name__ == "__main__":
    unittest.main()
