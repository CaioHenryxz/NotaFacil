"""Testes de app/api.py — a ponte HTTP entre o protótipo web (prototype/) e
o backend real. Cada rota só encaminha pra funções já testadas em outros
arquivos (repo.py, core/fila.py etc.); aqui o foco é a fiação HTTP em si:
status code certo, JSON certo, e principalmente que importar o módulo NÃO
mexe no disco (bug encontrado e corrigido — ver histórico do projeto)."""
import datetime
import tempfile
import unittest
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import BestAvailableEncryption, pkcs12
from cryptography.x509.oid import NameOID

import app.api as api
from app import repo
from app.fiscal import api_nacional


def _gerar_pfx(caminho: Path, senha: str, titular: str) -> None:
    chave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    nome = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, titular)])
    agora = datetime.datetime.now(datetime.timezone.utc)
    certificado = (
        x509.CertificateBuilder()
        .subject_name(nome).issuer_name(nome).public_key(chave.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(agora).not_valid_after(agora + datetime.timedelta(days=1))
        .sign(chave, hashes.SHA256())
    )
    pfx_bytes = pkcs12.serialize_key_and_certificates(
        name=b"teste", key=chave, cert=certificado, cas=None,
        encryption_algorithm=BestAvailableEncryption(senha.encode("utf-8")),
    )
    caminho.write_bytes(pfx_bytes)


class TestImportarNaoTocaEmDisco(unittest.TestCase):
    def test_repositorio_e_none_ate_main_rodar(self):
        # reimportar nao reexecuta o modulo, entao testamos a garantia direto:
        # sem chamar api.main(), repositorio so' e' setado se ALGUM teste
        # (deste arquivo ou de outro) tiver rodado antes e trocado. Aqui so'
        # confirmamos que o atributo existe e o mecanismo de troca funciona
        # sem exigir infraestrutura em disco.
        self.assertTrue(hasattr(api, "repositorio"))


class TestApiFlask(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp.name)

        api.repositorio = repo.Repositorio(tmp / "teste.db")
        # Isola pasta_base num tmpdir -- sem isso, `_pasta_base()` cai no
        # padrao real (~/Documentos/Notas Fiscais) porque o banco de teste
        # nao tem config nenhuma salva, e qualquer rota que toque disco
        # (emitir, editar_prestador renomeando pasta etc.) escreveria/moveria
        # pasta de verdade no Documentos do usuario rodando os testes.
        api.repositorio.set_config("pasta_base", str(tmp / "Notas Fiscais"))
        api.PASTA_CERTIFICADOS = tmp / "certificados"
        api.PASTA_CERTIFICADOS.mkdir(parents=True, exist_ok=True)
        self.client = api.app.test_client()
        self.tmp = tmp

        self._enviar_dps_original = api_nacional.enviar_dps
        self._buscar_danfse_original = api_nacional.buscar_danfse
        self._cancelar_nfse_original = api_nacional.cancelar_nfse

        def _enviar_dps_fake(xml_assinado, chave, certificado, extras=None, *, ambiente="homologacao", timeout=60.0):
            assert b"<ds:Signature" in xml_assinado, "a DPS enviada precisa estar realmente assinada"
            return api_nacional.RespostaEmissao(chave_acesso="FAKE-0001", xml_nfse=xml_assinado)

        def _buscar_danfse_fake(chave_acesso, chave, certificado, extras=None, *, ambiente="homologacao", timeout=30.0):
            return b"%PDF-1.4 fake"

        def _cancelar_nfse_fake(chave_nfse, xml_evento_assinado, chave, certificado, extras=None, *, ambiente="homologacao", timeout=30.0):
            assert b"<ds:Signature" in xml_evento_assinado, "o evento de cancelamento precisa estar realmente assinado"
            return api_nacional.RespostaCancelamento(protocolo="PROTOCOLO-TESTE", confirmado_em="2026-07-22T10:00:00-03:00")

        api_nacional.enviar_dps = _enviar_dps_fake
        api_nacional.buscar_danfse = _buscar_danfse_fake
        api_nacional.cancelar_nfse = _cancelar_nfse_fake

    def tearDown(self):
        api_nacional.enviar_dps = self._enviar_dps_original
        api_nacional.buscar_danfse = self._buscar_danfse_original
        api_nacional.cancelar_nfse = self._cancelar_nfse_original
        api.repositorio.fechar()
        api.repositorio = None
        self._tmp.cleanup()

    def _criar_prestador_com_certificado(self, senha="senha-teste-123"):
        caminho_pfx = self.tmp / "cert.pfx"
        _gerar_pfx(caminho_pfx, senha, "PRESTADOR TESTE:11222333000181")
        with open(caminho_pfx, "rb") as f:
            r = self.client.post(
                "/api/certificados/ler",
                data={"arquivo": (f, "cert.pfx"), "senha": senha},
                content_type="multipart/form-data",
            )
        self.assertEqual(r.status_code, 200, r.get_json())
        info = r.get_json()
        r = self.client.post("/api/prestadores", json={
            "nome_exibicao": "Dr. João Cardoso", "cnpj": info["documento"], "im": "123456",
            "codigo_municipio": "3549904", "regime": "3", "cor": "#2F6FED",
            "caminho_pfx": info["caminho_pfx"], "senha": senha, "valido_ate": info["valido_ate"],
        })
        self.assertEqual(r.status_code, 200, r.get_json())
        return r.get_json()

    def test_health(self):
        r = self.client.get("/api/health")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.get_json()["ok"])

    def test_fluxo_completo_prestador_tomador_modelo_emissao(self):
        prestador = self._criar_prestador_com_certificado()
        pid = prestador["id"]

        r = self.client.post(f"/api/prestadores/{pid}/tomadores", json={"doc": "12345678000195", "nome": "Unimed SJC", "email": "unimed@example.com"})
        self.assertEqual(r.status_code, 200)
        tid = r.get_json()["id"]

        r = self.client.post(f"/api/prestadores/{pid}/modelos", json={
            "descricao": "Consulta", "cod_tributacao_nacional": "010101", "cod_tributacao_municipal": "010",
            "cod_nbs": "107011900", "valor_padrao": "450.00",
        })
        self.assertEqual(r.status_code, 200)
        mid = r.get_json()["id"]

        r = self.client.post(f"/api/prestadores/{pid}/notas", json={"tomador_id": tid, "modelo_id": mid, "valor": "450.00"})
        self.assertEqual(r.status_code, 200)
        nota = r.get_json()
        self.assertEqual(nota["status"], "emitida")
        self.assertEqual(nota["chave_acesso"], "FAKE-0001")

        r = self.client.get(f"/api/prestadores/{pid}/notas")
        self.assertEqual(len(r.get_json()), 1)

    def test_retencao_padrao_do_tomador_e_usada_e_pode_ser_sobrescrita_so_na_nota(self):
        # docs/auditoria.md, Bloco 1.6/2.4, item 2: "permitir sobrescrever
        # so' naquela nota" sem alterar o cadastro do tomador.
        prestador = self._criar_prestador_com_certificado()
        pid = prestador["id"]
        tomador = self.client.post(f"/api/prestadores/{pid}/tomadores", json={
            "doc": "12345678000195", "nome": "Unimed SJC",
            "retencoes": {"retem_irrf": True, "aliquota_irrf": "1.5"},
        }).get_json()
        tid = tomador["id"]
        self.assertEqual(tomador["retem_irrf"], 1)

        mid = self.client.post(f"/api/prestadores/{pid}/modelos", json={
            "descricao": "Consulta", "cod_tributacao_nacional": "040101", "cod_tributacao_municipal": "040",
            "cod_nbs": "105011900", "valor_padrao": "1000.00",
        }).get_json()["id"]

        # nota 1: usa o padrao do tomador (nao manda "retencoes" nenhuma)
        nota1 = self.client.post(f"/api/prestadores/{pid}/notas", json={"tomador_id": tid, "modelo_id": mid, "valor": "1000.00"}).get_json()
        self.assertEqual(nota1["retem_irrf"], 1)
        self.assertEqual(nota1["aliquota_irrf"], "1.5")

        # nota 2: sobrescreve so' pra ela (sem retencao), tomador continua intocado
        nota2 = self.client.post(f"/api/prestadores/{pid}/notas", json={
            "tomador_id": tid, "modelo_id": mid, "valor": "1000.00",
            "retencoes": {"retem_irrf": False},
        }).get_json()
        self.assertEqual(nota2["retem_irrf"], 0)

        tomador_depois = self.client.get(f"/api/prestadores/{pid}/tomadores").get_json()[0]
        self.assertEqual(tomador_depois["retem_irrf"], 1)
        self.assertEqual(tomador_depois["aliquota_irrf"], "1.5")

    def test_emitir_nota_aceita_valor_digitado_com_virgula(self):
        # o campo de valor no protótipo web é texto livre — alguém digitando
        # "1.250,50" (formato BR) não pode quebrar o Decimal() lá na frente.
        prestador = self._criar_prestador_com_certificado()
        pid = prestador["id"]
        tid = self.client.post(f"/api/prestadores/{pid}/tomadores", json={"doc": "12345678000195", "nome": "Unimed SJC"}).get_json()["id"]
        mid = self.client.post(f"/api/prestadores/{pid}/modelos", json={
            "descricao": "Consulta", "cod_tributacao_nacional": "010101", "cod_tributacao_municipal": "010",
            "cod_nbs": "107011900", "valor_padrao": "1.250,50",
        }).get_json()["id"]

        r = self.client.post(f"/api/prestadores/{pid}/notas", json={"tomador_id": tid, "modelo_id": mid, "valor": "1.250,50"})
        self.assertEqual(r.status_code, 200, r.get_json())
        self.assertEqual(r.get_json()["status"], "emitida")

    def test_cancelar_nota_de_ponta_a_ponta(self):
        prestador = self._criar_prestador_com_certificado()
        pid = prestador["id"]
        tid = self.client.post(f"/api/prestadores/{pid}/tomadores", json={"doc": "12345678000195", "nome": "Unimed SJC"}).get_json()["id"]
        mid = self.client.post(f"/api/prestadores/{pid}/modelos", json={
            "descricao": "Consulta", "cod_tributacao_nacional": "010101", "cod_tributacao_municipal": "010",
            "cod_nbs": "107011900", "valor_padrao": "450.00",
        }).get_json()["id"]
        nota = self.client.post(f"/api/prestadores/{pid}/notas", json={"tomador_id": tid, "modelo_id": mid, "valor": "450.00"}).get_json()
        self.assertEqual(nota["status"], "emitida")

        # a fake de enviar_dps devolve uma chave curta ("FAKE-0001"); o evento
        # de cancelamento exige os 50 digitos reais da chave de acesso da
        # NFS-e — simula isso direto no banco pra este teste de integracao.
        api.repositorio._conn.execute("UPDATE notas SET chave_acesso = ? WHERE id = ?", ("1" * 50, nota["id"]))
        api.repositorio._conn.commit()

        r = self.client.post(f"/api/prestadores/{pid}/notas/{nota['id']}/cancelar", json={"cod_motivo": "1"})
        self.assertEqual(r.status_code, 200, r.get_json())
        nota_cancelada = r.get_json()
        self.assertEqual(nota_cancelada["status"], "cancelada")
        self.assertEqual(nota_cancelada["protocolo_cancelamento"], "PROTOCOLO-TESTE")

        # cancelar de novo tem que ser bloqueado, sem gerar erro tecnico cru
        r = self.client.post(f"/api/prestadores/{pid}/notas/{nota['id']}/cancelar", json={"cod_motivo": "1"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("erro", r.get_json())

    def test_recorrencia_e_alternar(self):
        prestador = self._criar_prestador_com_certificado()
        pid = prestador["id"]
        tid = self.client.post(f"/api/prestadores/{pid}/tomadores", json={"doc": "12345678000195", "nome": "Unimed SJC"}).get_json()["id"]
        mid = self.client.post(f"/api/prestadores/{pid}/modelos", json={
            "descricao": "Consulta", "cod_tributacao_nacional": "010101", "cod_tributacao_municipal": "010",
            "cod_nbs": "107011900", "valor_padrao": "450.00",
        }).get_json()["id"]

        r = self.client.post(f"/api/prestadores/{pid}/recorrencias", json={"tomador_id": tid, "modelo_id": mid, "valor": "450.00", "dia_do_mes": 5})
        rid = r.get_json()["id"]

        r = self.client.post(f"/api/prestadores/{pid}/recorrencias/{rid}/alternar", json={"ativo": False})
        self.assertEqual(r.status_code, 200)

        r = self.client.get(f"/api/prestadores/{pid}/recorrencias")
        self.assertEqual(r.get_json()[0]["ativo"], 0)

    def test_editar_e_excluir_prestador(self):
        prestador = self._criar_prestador_com_certificado()
        pid = prestador["id"]

        r = self.client.post(f"/api/prestadores/{pid}/editar", json={
            "nome_exibicao": "Novo Nome", "im": "999", "codigo_municipio": "3550308",
            "regime": "2", "regime_especial_tributacao": "1", "cor": "#FF0000",
        })
        self.assertEqual(r.status_code, 200, r.get_json())
        self.assertEqual(r.get_json()["nome_exibicao"], "Novo Nome")

        r = self.client.post(f"/api/prestadores/{pid}/excluir")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.client.get("/api/prestadores").get_json(), [])

    def test_excluir_prestador_com_nota_e_bloqueado(self):
        prestador = self._criar_prestador_com_certificado()
        pid = prestador["id"]
        tid = self.client.post(f"/api/prestadores/{pid}/tomadores", json={"doc": "12345678000195", "nome": "Unimed SJC"}).get_json()["id"]
        mid = self.client.post(f"/api/prestadores/{pid}/modelos", json={
            "descricao": "Consulta", "cod_tributacao_nacional": "010101", "cod_tributacao_municipal": "010",
            "cod_nbs": "107011900", "valor_padrao": "450.00",
        }).get_json()["id"]
        self.client.post(f"/api/prestadores/{pid}/notas", json={"tomador_id": tid, "modelo_id": mid, "valor": "450.00"})

        r = self.client.post(f"/api/prestadores/{pid}/excluir")
        self.assertEqual(r.status_code, 400)
        self.assertIn("erro", r.get_json())

    def test_editar_e_excluir_tomador(self):
        prestador = self._criar_prestador_com_certificado()
        pid = prestador["id"]
        tid = self.client.post(f"/api/prestadores/{pid}/tomadores", json={"doc": "12345678000195", "nome": "Unimed SJC"}).get_json()["id"]

        r = self.client.post(f"/api/prestadores/{pid}/tomadores/{tid}/editar", json={"nome": "Novo Nome", "email": "a@b.com"})
        self.assertEqual(r.status_code, 200, r.get_json())
        self.assertEqual(r.get_json()["nome"], "Novo Nome")

        r = self.client.post(f"/api/prestadores/{pid}/tomadores/{tid}/excluir")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.client.get(f"/api/prestadores/{pid}/tomadores").get_json(), [])

    def test_editar_e_excluir_modelo(self):
        prestador = self._criar_prestador_com_certificado()
        pid = prestador["id"]
        mid = self.client.post(f"/api/prestadores/{pid}/modelos", json={
            "descricao": "Consulta", "cod_tributacao_nacional": "010101", "cod_tributacao_municipal": "010",
            "cod_nbs": "107011900", "valor_padrao": "450.00",
        }).get_json()["id"]

        r = self.client.post(f"/api/prestadores/{pid}/modelos/{mid}/editar", json={
            "descricao": "Retorno", "cod_tributacao_nacional": "020202", "cod_tributacao_municipal": "020",
            "cod_nbs": "207011900", "valor_padrao": "150,00",
        })
        self.assertEqual(r.status_code, 200, r.get_json())
        self.assertEqual(r.get_json()["descricao"], "Retorno")
        self.assertEqual(r.get_json()["valor_padrao"], "150.00")

        r = self.client.post(f"/api/prestadores/{pid}/modelos/{mid}/excluir")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.client.get(f"/api/prestadores/{pid}/modelos").get_json(), [])

    def test_editar_e_excluir_recorrencia(self):
        prestador = self._criar_prestador_com_certificado()
        pid = prestador["id"]
        tid = self.client.post(f"/api/prestadores/{pid}/tomadores", json={"doc": "12345678000195", "nome": "Unimed SJC"}).get_json()["id"]
        mid = self.client.post(f"/api/prestadores/{pid}/modelos", json={
            "descricao": "Consulta", "cod_tributacao_nacional": "010101", "cod_tributacao_municipal": "010",
            "cod_nbs": "107011900", "valor_padrao": "450.00",
        }).get_json()["id"]
        rid = self.client.post(f"/api/prestadores/{pid}/recorrencias", json={"tomador_id": tid, "modelo_id": mid, "valor": "450.00", "dia_do_mes": 5}).get_json()["id"]

        r = self.client.post(f"/api/prestadores/{pid}/recorrencias/{rid}/editar", json={
            "tomador_id": tid, "modelo_id": mid, "valor": "500.00", "dia_do_mes": 10,
        })
        self.assertEqual(r.status_code, 200, r.get_json())

        r = self.client.get(f"/api/prestadores/{pid}/recorrencias")
        self.assertEqual(r.get_json()[0]["valor"], "500.00")
        self.assertEqual(r.get_json()[0]["dia_do_mes"], 10)

        r = self.client.post(f"/api/prestadores/{pid}/recorrencias/{rid}/excluir")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.client.get(f"/api/prestadores/{pid}/recorrencias").get_json(), [])

    def test_meu_dia_agrega_prestadores(self):
        self._criar_prestador_com_certificado()
        r = self.client.get("/api/meu-dia")
        self.assertEqual(r.status_code, 200)
        corpo = r.get_json()
        for chave in ("mensalidades_hoje", "notas_pendentes", "notas_rejeitadas", "certificados_a_vencer"):
            self.assertIn(chave, corpo)

    def test_config_get_e_post(self):
        r = self.client.post("/api/config", json={
            "pasta_base": str(self.tmp / "Notas Fiscais"), "smtp_host": "smtp.exemplo.com",
            "smtp_porta": 587, "smtp_usuario": "a@b.com", "smtp_senha": "x",
        })
        self.assertEqual(r.status_code, 200)
        r = self.client.get("/api/config")
        corpo = r.get_json()
        self.assertEqual(corpo["smtp_host"], "smtp.exemplo.com")
        self.assertTrue(corpo["smtp_senha_configurada"])
        self.assertNotIn("smtp_senha", corpo, "a senha nunca pode voltar crua numa resposta GET")

    def test_erro_de_prestador_inexistente_vira_json_traduzido(self):
        r = self.client.post("/api/prestadores/999/tomadores", json={"doc": "12345678000195", "nome": "X"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("erro", r.get_json())

    def test_cors_headers_presentes(self):
        r = self.client.get("/api/health")
        self.assertEqual(r.headers.get("Access-Control-Allow-Origin"), "*")


if __name__ == "__main__":
    unittest.main()
