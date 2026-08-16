"""
Testes da FASE DE NAVEGAÇÃO do envio (abrir a conversa) e da sua retentativa.

Motivação (log de 15/08/2026, planilha de teste com o MESMO número em todas as
linhas): 2 de 22 envios falharam com "timeout ao abrir a conversa" e o contato
foi marcado como INVÁLIDO. O número era válido — as outras 20 mensagens para ele
foram entregues na mesma rodada. A falha durou ~30s, exatamente o orçamento do
`#pane-side`: o WhatsApp Web não terminou de recarregar.

O que estes testes fixam:
  1. Retentativa NÃO pode duplicar mensagem nem anexo: quando a navegação falha
     e é repetida, nenhuma tecla foi digitada e nenhum arquivo foi anexado antes
     da nova tentativa.
  2. WhatsApp Web que não carrega vira WhatsAppNotLoadedError (contato segue
     pendente), não TimeoutException (que marca inválido).
  3. Conversa que não abre com o app carregado ainda tenta uma segunda vez e,
     persistindo, levanta TimeoutException (marcado como inválido).
  4. Sucesso na segunda tentativa envia a mensagem UMA única vez.

Executa com:
    venv\\Scripts\\python.exe -m unittest tests.test_nav_retry -v
"""

import logging
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from selenium.common.exceptions import TimeoutException  # noqa: E402

import whatsapp_sender  # noqa: E402
from whatsapp_sender import WhatsAppSender, WhatsAppNotLoadedError  # noqa: E402


class FakeTime:
    """Relógio falso: o tempo só avança quando o código dorme."""

    def __init__(self):
        self.agora = 0.0

    def sleep(self, segundos):
        self.agora += float(segundos or 0)

    def monotonic(self):
        return self.agora

    def time(self):
        return self.agora


class FakeInput:
    """Campo de texto do WhatsApp: registra tudo que foi digitado."""

    def __init__(self):
        self.calls = []

    def send_keys(self, value):
        self.calls.append(value)

    @property
    def text(self):
        return ""


class FakeFileInput:
    """input[type=file]: registra os caminhos anexados."""

    def __init__(self):
        self.anexados = []

    def send_keys(self, value):
        self.anexados.append(value)

    @property
    def text(self):
        return ""


class FakeDriverNav:
    """
    Driver que decide, por tentativa de navegação, se o WhatsApp "carrega".

    pane_por_tentativa: lista de bool — se o #pane-side aparece naquela tentativa.
    chat_por_tentativa: lista de bool — se o campo do chat aparece naquela tentativa.
    """

    def __init__(self, pane_por_tentativa, chat_por_tentativa):
        self.pane_por_tentativa = list(pane_por_tentativa)
        self.chat_por_tentativa = list(chat_por_tentativa)
        self.urls = []
        self.input = FakeInput()
        self.file_input = FakeFileInput()

    # --- helpers ---------------------------------------------------------- #
    @property
    def tentativa(self):
        # 1 na primeira navegação, 2 na segunda...
        return max(1, len(self.urls))

    def _flag(self, lista):
        i = self.tentativa - 1
        if not lista:
            return True
        return lista[i] if i < len(lista) else lista[-1]

    # --- API usada pelo sender -------------------------------------------- #
    def get(self, url):
        self.urls.append(url)

    def find_element(self, by, selector):
        if selector == "#pane-side":
            if self._flag(self.pane_por_tentativa):
                return object()
            raise Exception("no such element: #pane-side")
        if "contenteditable" in selector:
            if self._flag(self.chat_por_tentativa):
                return self.input
            raise Exception("no such element: campo do chat")
        return self.input

    def find_elements(self, by, selector):
        if "contenteditable" in selector:
            return [self.input] if self._flag(self.chat_por_tentativa) else []
        if 'input[type="file"]' in selector:
            return [self.file_input]
        return []

    def execute_script(self, *args, **kwargs):
        return None


class NavRetryTest(unittest.TestCase):
    def setUp(self):
        logging.getLogger("whatsapp_sender_file").setLevel(logging.CRITICAL)
        self.clock = FakeTime()
        self._time_original = whatsapp_sender.time
        whatsapp_sender.time = self.clock
        # _interruptible_sleep usa threading.Event.wait() (relógio real): sem
        # neutralizar, o teste esperaria os 60s de verdade. Ainda avança o
        # relógio falso, para os deadlines estourarem.
        self._isleep_original = WhatsAppSender._interruptible_sleep

        def sleep_falso(_self, segundos):
            self.clock.sleep(segundos)
            return False

        WhatsAppSender._interruptible_sleep = sleep_falso
        self.addCleanup(self._restaurar)

    def _restaurar(self):
        whatsapp_sender.time = self._time_original
        WhatsAppSender._interruptible_sleep = self._isleep_original

    def novo_sender(self, driver, human=False):
        sender = WhatsAppSender(
            excel_path="fake.xlsx",
            config={"human_behavior": human},
            log_callback=lambda msg: None,
        )
        sender._driver = driver
        # Confirmação de envio depende do DOM real; aqui só interessa a navegação.
        sender._confirm_message_sent = lambda texto, timeout=6.0: True
        return sender

    # --- 1. WhatsApp Web que não carrega ---------------------------------- #
    def test_pane_nunca_carrega_nao_marca_invalido(self):
        """#pane-side ausente => WhatsAppNotLoadedError (contato segue pendente)."""
        driver = FakeDriverNav(pane_por_tentativa=[False, False], chat_por_tentativa=[True])
        sender = self.novo_sender(driver)

        with self.assertRaises(WhatsAppNotLoadedError):
            sender._send_message("Ana", "19994229146", "Oi")

        # Não é TimeoutException: o laço de envio trata os dois de formas opostas
        self.assertNotIsInstance(WhatsAppNotLoadedError("x"), TimeoutException)

    def test_pane_nao_carrega_tenta_de_novo_sem_digitar_nada(self):
        """A retentativa recarrega a URL e NÃO digitou nem anexou nada antes."""
        driver = FakeDriverNav(pane_por_tentativa=[False, False], chat_por_tentativa=[True])
        sender = self.novo_sender(driver)

        with self.assertRaises(WhatsAppNotLoadedError):
            sender._send_message("Ana", "19994229146", "Oi")

        self.assertEqual(len(driver.urls), WhatsAppSender._NAV_MAX_ATTEMPTS)
        self.assertEqual(driver.input.calls, [], "nenhuma tecla pode ter sido digitada")
        self.assertEqual(driver.file_input.anexados, [], "nenhum anexo pode ter sido enviado")

    # --- 2. Conversa que não abre ----------------------------------------- #
    def test_chat_nunca_abre_ainda_marca_invalido(self):
        """App carregado + conversa que não abre => TimeoutException (inválido)."""
        driver = FakeDriverNav(pane_por_tentativa=[True], chat_por_tentativa=[False, False])
        sender = self.novo_sender(driver)

        with self.assertRaises(TimeoutException):
            sender._send_message("Ana", "19994229146", "Oi")

        self.assertEqual(len(driver.urls), WhatsAppSender._NAV_MAX_ATTEMPTS)
        self.assertEqual(driver.input.calls, [])
        self.assertEqual(driver.file_input.anexados, [])

    # --- 3. Sucesso na segunda tentativa ---------------------------------- #
    def test_sucesso_na_segunda_tentativa_envia_uma_vez(self):
        """Falhou a 1ª navegação, abriu na 2ª: um ENTER, uma mensagem."""
        driver = FakeDriverNav(pane_por_tentativa=[False, True], chat_por_tentativa=[True])
        sender = self.novo_sender(driver)

        self.assertTrue(sender._send_message("Ana", "19994229146", "Oi"))

        self.assertEqual(len(driver.urls), 2)
        enters = [c for c in driver.input.calls if c == "\ue007" or c == "\n"]
        self.assertEqual(len(enters), 1, f"ENTER deveria acontecer 1x: {driver.input.calls!r}")

    def test_sucesso_na_segunda_tentativa_anexa_uma_vez(self):
        """Com anexo: a retentativa de navegação não pode anexar duas vezes."""
        driver = FakeDriverNav(pane_por_tentativa=[False, True], chat_por_tentativa=[True])
        sender = self.novo_sender(driver)
        # Isola o envio de mídia: o que importa é quantas vezes ele é chamado.
        chamadas = []
        sender._send_media = lambda arquivo, pessoa, human: chamadas.append(arquivo)

        arquivo = os.path.abspath(__file__)  # um arquivo que existe de verdade
        self.assertTrue(sender._send_message("Ana", "19994229146", "Oi", arquivo))

        self.assertEqual(len(driver.urls), 2)
        self.assertEqual(chamadas, [arquivo], "anexo deveria ser enviado 1x")

    # --- 4. Caminho felizermanece intacto --------------------------------- #
    def test_navegacao_ok_navega_uma_vez(self):
        driver = FakeDriverNav(pane_por_tentativa=[True], chat_por_tentativa=[True])
        sender = self.novo_sender(driver)

        self.assertTrue(sender._send_message("Ana", "19994229146", "Oi"))
        self.assertEqual(len(driver.urls), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
