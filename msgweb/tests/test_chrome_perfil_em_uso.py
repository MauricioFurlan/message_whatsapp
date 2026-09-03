"""
Testes da abertura do Chrome quando o perfil do app já está em uso.

Relato (26/08/2026): com uma janela do Chrome já aberta no WhatsApp Web, o
programa abriu QUATRO janelas do Chrome e terminou com:

    ERRO: Não foi possível iniciar o Chrome: Message: session not created:
    Chrome instance exited. Examine ChromeDriver verbose log to determine the
    cause.

Causa: um segundo Chrome lançado com o mesmo `--user-data-dir` não abre uma
instância nova — ele entrega o pedido para a que já está rodando e encerra o
próprio processo. O ChromeDriver, esperando esse processo, reporta "Chrome
instance exited". As quatro janelas vinham dos fallbacks em cascata
(webdriver-manager -> chromedriver.exe local -> chromedriver do PATH): cada um
lançava mais um Chrome para morrer do mesmo jeito, porque trocar de
chromedriver não tem relação nenhuma com o problema.

Agravante: o código apagava `SingletonLock`/`SingletonSocket`/`SingletonCookie`
antes de tentar. Isso só faz sentido para lock órfão — com um Chrome vivo
usando o perfil, é mexer no estado de um processo em funcionamento.

O que estes testes fixam:
  1. perfil em uso é detectado ANTES de lançar qualquer Chrome;
  2. os arquivos de lock não são apagados quando o perfil está em uso;
  3. erro de perfil em uso não cai nos fallbacks (nada de janela extra);
  4. erro de chromedriver incompatível CONTINUA caindo nos fallbacks;
  5. a mensagem que chega ao usuário diz o que fazer.

Executa com:
    venv\\Scripts\\python.exe -m unittest tests.test_chrome_perfil_em_uso -v
"""

import logging
import os
import sys
import tempfile
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

import whatsapp_sender  # noqa: E402
from whatsapp_sender import WhatsAppSender, ChromeProfileInUseError  # noqa: E402


class PerfilEmUsoTest(unittest.TestCase):
    def setUp(self):
        logging.getLogger("whatsapp_sender_file").setLevel(logging.CRITICAL)
        self.logs = []
        self.sender = WhatsAppSender(
            excel_path="fake.xlsx",
            config={},
            log_callback=self.logs.append,
        )
        # Nenhum teste aqui pode lançar Chrome de verdade.
        self.chromes_lancados = []

        self._tmp = tempfile.TemporaryDirectory()
        self.perfil = os.path.join(self._tmp.name, "chrome_profile")
        os.makedirs(self.perfil, exist_ok=True)
        self.addCleanup(self._tmp.cleanup)

        self._cwd = os.getcwd()
        os.chdir(self._tmp.name)
        self.addCleanup(lambda: os.chdir(self._cwd))

        # taskkill e webdriver_manager não têm o que fazer num teste.
        self._run_original = whatsapp_sender.subprocess.run
        whatsapp_sender.subprocess.run = lambda *a, **k: None
        self.addCleanup(self._restaurar_run)

        # ChromeDriverManager().install() baixa binario da internet. Aqui o que
        # importa e quantas vezes o Chrome e lancado, nao de onde veio o driver.
        import types
        fake_mod = types.ModuleType("webdriver_manager.chrome")
        fake_mod.ChromeDriverManager = lambda *a, **k: types.SimpleNamespace(
            install=lambda: "chromedriver-de-teste"
        )
        self._mod_original = sys.modules.get("webdriver_manager.chrome")
        sys.modules["webdriver_manager.chrome"] = fake_mod
        self.addCleanup(self._restaurar_modulo)

    def _restaurar_modulo(self):
        if self._mod_original is None:
            sys.modules.pop("webdriver_manager.chrome", None)
        else:
            sys.modules["webdriver_manager.chrome"] = self._mod_original

    def _restaurar_run(self):
        whatsapp_sender.subprocess.run = self._run_original

    def _criar_locks(self):
        for nome in ("SingletonLock", "SingletonSocket", "SingletonCookie"):
            Path(self.perfil, nome).write_text("x", encoding="utf-8")

    def _locks_existentes(self):
        return sorted(
            n for n in ("SingletonLock", "SingletonSocket", "SingletonCookie")
            if Path(self.perfil, n).exists()
        )

    def _fingir_chrome_aberto(self, pids):
        WhatsAppSender._pids_chrome_no_perfil = staticmethod(lambda _dir: list(pids))
        self.addCleanup(self._restaurar_pids)

    def _restaurar_pids(self):
        WhatsAppSender._pids_chrome_no_perfil = PerfilEmUsoTest._pids_original

    # --- 1 e 2: detecção antecipada e locks preservados -------------------- #
    def test_perfil_em_uso_falha_antes_de_abrir_chrome(self):
        self._criar_locks()
        self._fingir_chrome_aberto([4242])

        with self.assertRaises(ChromeProfileInUseError) as ctx:
            self.sender._init_driver()

        self.assertEqual(
            self.chromes_lancados, [],
            "nenhum Chrome pode ter sido lançado quando o perfil já está em uso",
        )
        self.assertIn("4242", str(ctx.exception))
        self.assertIn("Feche", str(ctx.exception))

    def test_locks_do_perfil_em_uso_nao_sao_apagados(self):
        """Apagar o SingletonLock de um perfil vivo mexe num Chrome em uso."""
        self._criar_locks()
        self._fingir_chrome_aberto([4242])

        with self.assertRaises(ChromeProfileInUseError):
            self.sender._init_driver()

        self.assertEqual(
            self._locks_existentes(),
            ["SingletonCookie", "SingletonLock", "SingletonSocket"],
        )

    # --- 3: sem fallback em cascata para erro de perfil -------------------- #
    def test_erro_de_perfil_nao_tenta_outros_chromedrivers(self):
        """
        Era daqui que vinham as janelas extras: o erro subia para o `except` e
        o código tentava mais dois chromedrivers, lançando mais dois Chromes.
        """
        self._fingir_chrome_aberto([])  # a checagem prévia não pega este caso

        erro = Exception(
            "session not created: Chrome instance exited. Examine ChromeDriver "
            "verbose log to determine the cause."
        )

        def chrome_falso(*a, **k):
            self.chromes_lancados.append(k.get("options"))
            raise erro

        whatsapp_sender.webdriver.Chrome = chrome_falso
        self.addCleanup(self._restaurar_chrome)

        with self.assertRaises(ChromeProfileInUseError):
            self.sender._init_driver()

        self.assertEqual(
            len(self.chromes_lancados), 1,
            f"deveria desistir na primeira tentativa, tentou "
            f"{len(self.chromes_lancados)}x (cada uma abre uma janela)",
        )

    # --- 4: fallback preservado para o que ele existe para resolver -------- #
    def test_erro_de_chromedriver_incompativel_ainda_usa_fallback(self):
        self._fingir_chrome_aberto([])

        def chrome_falso(*a, **k):
            self.chromes_lancados.append(k.get("options"))
            raise Exception(
                "session not created: This version of ChromeDriver only "
                "supports Chrome version 140"
            )

        whatsapp_sender.webdriver.Chrome = chrome_falso
        self.addCleanup(self._restaurar_chrome)

        with self.assertRaises(RuntimeError) as ctx:
            self.sender._init_driver()

        self.assertNotIsInstance(ctx.exception, ChromeProfileInUseError)
        self.assertGreater(
            len(self.chromes_lancados), 1,
            "chromedriver incompatível é exatamente o caso que o fallback resolve",
        )

    def _restaurar_chrome(self):
        whatsapp_sender.webdriver.Chrome = PerfilEmUsoTest._chrome_original

    # --- 5: classificação da mensagem -------------------------------------- #
    def test_classificacao_das_mensagens_de_erro(self):
        perfil = [
            "session not created: Chrome instance exited.",
            "session not created: probably user data directory is already in use",
            "cannot create default profile directory",
        ]
        outros = [
            "session not created: This version of ChromeDriver only supports Chrome version 140",
            "'chromedriver' executable needs to be in PATH",
            "Timed out receiving message from renderer",
        ]
        for msg in perfil:
            self.assertTrue(
                WhatsAppSender._erro_de_perfil_em_uso(Exception(msg)), msg,
            )
        for msg in outros:
            self.assertFalse(
                WhatsAppSender._erro_de_perfil_em_uso(Exception(msg)), msg,
            )

    # --- 6: a mensagem chega ao usuário, não o traceback do Selenium ------- #
    def test_start_mostra_instrucao_em_vez_do_erro_cru(self):
        self.sender._init_driver = lambda: (_ for _ in ()).throw(
            ChromeProfileInUseError(
                "Já existe uma janela do Chrome aberta pelo programa (processo 4242). "
                "Feche essa janela do Chrome e clique em Iniciar novamente."
            )
        )
        self.sender._load_contacts = lambda: (_ for _ in ()).throw(
            AssertionError("não deveria chegar a carregar contatos")
        )
        # start() checa pendentes antes de abrir o browser; encurtamos até lá.
        import pandas as pd
        df = pd.DataFrame([{
            "Nome": "Ana", "Número": "19994229146", "Mensagem": "Oi",
            "Enviado": "", "DataEnvio": "", "Invalido": "", "Motivo": "", "Arquivo": "",
        }])
        self.sender._load_contacts = lambda: df.copy()

        self.sender.start()

        texto = " ".join(self.logs)
        self.assertIn("Feche essa janela do Chrome", texto)
        self.assertNotIn("session not created", texto)
        self.assertEqual(self.sender.get_status()["state"], "erro")


PerfilEmUsoTest._pids_original = WhatsAppSender.__dict__["_pids_chrome_no_perfil"]
PerfilEmUsoTest._chrome_original = whatsapp_sender.webdriver.Chrome


if __name__ == "__main__":
    unittest.main(verbosity=2)
