"""Testes de app/core/inicializacao_windows.py (Etapa 3 item 3: "opção
'Iniciar com o Windows'"). Estes testes escrevem de verdade na chave Run do
usuário atual (HKCU) — por isso SEMPRE removem a entrada de teste no
tearDown, mesmo se o teste falhar no meio."""
import unittest

from app.core import inicializacao_windows as iw


@unittest.skipIf(iw.winreg is None, "winreg só existe no Windows")
class TestInicializacaoWindows(unittest.TestCase):
    def tearDown(self):
        iw.desabilitar()

    def test_habilitar_e_depois_esta_habilitado(self):
        iw.desabilitar()
        self.assertFalse(iw.esta_habilitado())
        iw.habilitar()
        self.assertTrue(iw.esta_habilitado())

    def test_desabilitar_remove_a_entrada(self):
        iw.habilitar()
        self.assertTrue(iw.esta_habilitado())
        iw.desabilitar()
        self.assertFalse(iw.esta_habilitado())

    def test_desabilitar_sem_ter_habilitado_nao_da_erro(self):
        iw.desabilitar()
        iw.desabilitar()  # idempotente

    def test_comando_registrado_referencia_main_py(self):
        iw.habilitar()
        comando = iw._comando_de_inicializacao()
        self.assertIn("main.py", comando)


if __name__ == "__main__":
    unittest.main()
