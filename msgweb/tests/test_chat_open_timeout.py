"""
Testes da JANELA DE ESPERA da conversa abrir (_wait_chat_or_invalid_popup).

Motivação — medição do `log.txt` do cliente (24 a 26/08/2026, versão 1.4.5),
172 mensagens entregues e 52 contatos marcados como inválidos por timeout:

  disparo -> começou a digitar (sucesso na 1ª tentativa), n=150:
      mínimo 16s | mediana 31s | p90 36s | máximo 41s

O mínimo de 16s é o custo fixo de scroll + `driver.get` + `#pane-side`. Ou seja,
metade das aberturas BEM-SUCEDIDAS consumia ~15s dos 20s de janela, e a mais
lenta raspou o limite. Não sobrava margem: qualquer lentidão a mais marcava
como inválido um número perfeitamente bom. O 19978094539 falhou às 14:40, 14:50
e 14:56 de 26/08 e recebeu a mensagem normalmente às 15:18.

O que estes testes fixam:
  1. a janela cobre uma abertura lenta que antes estourava (30s);
  2. o campo de digitação é reconsultado com frequência, sem ficar refém das
     detecções caras de popup/bloqueio (que leem `.text` de vários elementos);
  3. popup de número inválido continua sendo detectado cedo, sem gastar a
     janela inteira;
  4. as retentativas (agora 3, com pausa entre elas) NÃO duplicam mensagem nem
     anexo — nada é entregue na fase de navegação;
  5. parada pedida durante a pausa entre tentativas sai na hora.

Executa com:
    venv\\Scripts\\python.exe -m unittest tests.test_chat_open_timeout -v
"""

import logging
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from selenium.common.exceptions import TimeoutException  # noqa: E402

import whatsapp_sender  # noqa: E402
from whatsapp_sender import WhatsAppSender, InvalidNumberError  # noqa: E402


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
    def __init__(self):
        self.calls = []

    def send_keys(self, value):
        self.calls.append(value)

    @property
    def text(self):
        return ""


class FakeModal:
    def __init__(self, texto):
        self.text = texto


class FakeDriverTempo:
    """
    Driver em que o chat abre num INSTANTE do relógio falso, e não numa
    tentativa específica.

    chat_abre_em: lista com o instante (segundos, relativo ao início daquela
      tentativa de navegação) em que o campo de digitação passa a existir.
      None = não abre nessa tentativa.
    popup_em: instante, relativo ao início da tentativa, em que o modal de
      número inválido aparece.
    """

    def __init__(self, clock, chat_abre_em=(None,), popup_em=None):
        self.clock = clock
        self.chat_abre_em = list(chat_abre_em)
        self.popup_em = popup_em
        self.urls = []
        self.input = FakeInput()
        self.inicio_tentativa = 0.0
        # Contadores para provar quem é consultado com que frequência.
        self.consultas_campo = 0
        self.consultas_caras = 0

    @property
    def _decorrido(self):
        return self.clock.monotonic() - self.inicio_tentativa

    def _alvo(self):
        i = max(0, len(self.urls) - 1)
        if i < len(self.chat_abre_em):
            return self.chat_abre_em[i]
        return self.chat_abre_em[-1]

    def get(self, url):
        self.urls.append(url)
        self.inicio_tentativa = self.clock.monotonic()

    def find_element(self, by, selector):
        if selector == "#pane-side":
            return object()
        if "contenteditable" in selector:
            alvo = self._alvo()
            if alvo is not None and self._decorrido >= alvo:
                return self.input
            raise Exception("no such element: campo do chat")
        return self.input

    def find_elements(self, by, selector):
        if "contenteditable" in selector:
            self.consultas_campo += 1
            alvo = self._alvo()
            if alvo is not None and self._decorrido >= alvo:
                return [self.input]
            return []
        if "dialog" in selector or "modal" in selector or "overlay" in selector:
            self.consultas_caras += 1
            if self.popup_em is not None and self._decorrido >= self.popup_em:
                return [FakeModal("O número de telefone compartilhado por meio de url é inválido.")]
            return []
        if 'input[type="file"]' in selector:
            return []
        return []

    def execute_script(self, *args, **kwargs):
        return None


class ChatOpenTimeoutTest(unittest.TestCase):
    def setUp(self):
        logging.getLogger("whatsapp_sender_file").setLevel(logging.CRITICAL)
        self.clock = FakeTime()
        self._time_original = whatsapp_sender.time
        whatsapp_sender.time = self.clock
        self._isleep_original = WhatsAppSender._interruptible_sleep
        self._parar_em = None

        def sleep_falso(_self, segundos):
            self.clock.sleep(segundos)
            if self._parar_em is not None and self.clock.monotonic() >= self._parar_em:
                _self._stop_event.set()
            return _self._stop_event.is_set()

        WhatsAppSender._interruptible_sleep = sleep_falso
        self.addCleanup(self._restaurar)

    def _restaurar(self):
        whatsapp_sender.time = self._time_original
        WhatsAppSender._interruptible_sleep = self._isleep_original

    def novo_sender(self, driver):
        sender = WhatsAppSender(
            excel_path="fake.xlsx",
            config={"human_behavior": False},
            log_callback=lambda msg: None,
        )
        sender._driver = driver
        sender._confirm_message_sent = lambda texto, timeout=6.0: True
        sender._detect_blocked_contact = lambda: ""
        return sender

    # --- 1. a janela cobre a abertura lenta -------------------------------- #
    def test_conversa_lenta_de_30s_agora_abre(self):
        """
        30s é o caso que a medição mostrou como real e que os 20s antigos
        matavam. Tem que passar na PRIMEIRA tentativa, sem reabrir a conversa.
        """
        self.assertGreater(
            WhatsAppSender._CHAT_OPEN_TIMEOUT, 30,
            "a janela precisa cobrir aberturas de 30s, medidas no log do cliente",
        )
        driver = FakeDriverTempo(self.clock, chat_abre_em=[30])
        sender = self.novo_sender(driver)

        self.assertTrue(sender._send_message("Ana", "19994229146", "Oi"))
        self.assertEqual(len(driver.urls), 1, "não deveria precisar reabrir a conversa")
        enters = [c for c in driver.input.calls if c in ("", "\n")]
        self.assertEqual(len(enters), 1, f"ENTER deveria acontecer 1x: {driver.input.calls!r}")

    # --- 2. frequência de verificação -------------------------------------- #
    def test_campo_e_reconsultado_muito_mais_que_as_deteccoes_caras(self):
        """
        As detecções de popup/bloqueio leem `.text` de vários elementos. Se
        rodassem a cada volta, o campo seria reconsultado poucas vezes dentro
        da janela — que é o que fazia a conversa "não abrir" mesmo tendo
        aberto.
        """
        driver = FakeDriverTempo(self.clock, chat_abre_em=[40])
        sender = self.novo_sender(driver)
        sender._send_message("Ana", "19994229146", "Oi")

        self.assertGreater(
            driver.consultas_campo, driver.consultas_caras * 3,
            f"campo consultado {driver.consultas_campo}x contra "
            f"{driver.consultas_caras}x das detecções caras — muito próximo",
        )
        # Dentro de 40s, com passo de 0.3s, o campo tem que ser visto dezenas de vezes.
        self.assertGreater(driver.consultas_campo, 50)

    # --- 3. popup continua detectado cedo ---------------------------------- #
    def test_popup_de_numero_invalido_detectado_sem_gastar_a_janela(self):
        """Número rejeitado não pode custar os 45s inteiros."""
        driver = FakeDriverTempo(self.clock, chat_abre_em=[None], popup_em=1)
        sender = self.novo_sender(driver)

        with self.assertRaises(InvalidNumberError):
            sender._send_message("Ana", "19994229146", "Oi")

        self.assertLess(
            self.clock.monotonic(), 15,
            "popup deveria ser detectado nos primeiros segundos",
        )
        self.assertEqual(len(driver.urls), 1, "número rejeitado não é retentado")

    # --- 4. retentativas não duplicam nada --------------------------------- #
    def test_sucesso_na_terceira_tentativa_envia_uma_vez(self):
        """Duas falhas e sucesso na 3ª: três navegações, um único ENTER."""
        self.assertEqual(WhatsAppSender._NAV_MAX_ATTEMPTS, 3)
        driver = FakeDriverTempo(self.clock, chat_abre_em=[None, None, 5])
        sender = self.novo_sender(driver)

        self.assertTrue(sender._send_message("Ana", "19994229146", "Oi"))
        self.assertEqual(len(driver.urls), 3)
        enters = [c for c in driver.input.calls if c in ("", "\n")]
        self.assertEqual(len(enters), 1, f"ENTER deveria acontecer 1x: {driver.input.calls!r}")

    def test_todas_as_tentativas_falham_sem_digitar_nem_anexar(self):
        driver = FakeDriverTempo(self.clock, chat_abre_em=[None])
        sender = self.novo_sender(driver)
        anexos = []
        sender._send_media = lambda arquivo, pessoa, human: anexos.append(arquivo)

        with self.assertRaises(TimeoutException):
            sender._send_message("Ana", "19994229146", "Oi", os.path.abspath(__file__))

        self.assertEqual(len(driver.urls), WhatsAppSender._NAV_MAX_ATTEMPTS)
        self.assertEqual(driver.input.calls, [], "nada pode ter sido digitado")
        self.assertEqual(anexos, [], "nada pode ter sido anexado")

    def test_ha_pausa_entre_as_tentativas(self):
        """
        As duas tentativas antigas eram coladas e caíam na mesma janela ruim do
        WhatsApp Web. Agora há um respiro crescente entre elas.
        """
        driver = FakeDriverTempo(self.clock, chat_abre_em=[None])
        sender = self.novo_sender(driver)

        with self.assertRaises(TimeoutException):
            sender._send_message("Ana", "19994229146", "Oi")

        minimo = (
            WhatsAppSender._NAV_MAX_ATTEMPTS * WhatsAppSender._CHAT_OPEN_TIMEOUT
            + sum(WhatsAppSender._NAV_RETRY_BACKOFF)
        )
        self.assertGreaterEqual(self.clock.monotonic(), minimo)

    # --- 5. parada durante a pausa ----------------------------------------- #
    def test_stop_durante_a_pausa_entre_tentativas(self):
        """Parar no meio do backoff não pode enviar nada nem seguir tentando."""
        driver = FakeDriverTempo(self.clock, chat_abre_em=[None, 5])
        sender = self.novo_sender(driver)
        # Stop logo depois da 1ª janela estourar, durante a pausa.
        self._parar_em = WhatsAppSender._CHAT_OPEN_TIMEOUT + 1

        self.assertFalse(sender._send_message("Ana", "19994229146", "Oi"))
        self.assertEqual(len(driver.urls), 1, "não pode reabrir depois do stop")
        self.assertEqual(driver.input.calls, [], "nada pode ter sido digitado")

    # --- 6. o ritmo das rajadas não foi tocado ----------------------------- #
    def test_estimativa_conta_digitacao_anexo_e_abertura(self):
        """
        A janela de espera em si continua sem mexer no ritmo das rajadas.

        A estimativa, porém, passou a somar a abertura da conversa — ver
        tests/test_aviso_lentidao.py, que documenta o porquê. Aqui só se fixa
        que os outros dois componentes (digitação e anexo) seguem intactos.
        """
        sender = self.novo_sender(FakeDriverTempo(self.clock))
        sender.config["human_behavior"] = False
        base = WhatsAppSender.TEMPO_ESTIMADO_ABERTURA_CHAT
        # Sem anexo e sem digitação humanizada: 5s fixos + abertura.
        self.assertEqual(sender._estimar_tempo_envio_individual("Oi", ""), base + 5.0)
        # Um anexo continua somando TEMPO_ESTIMADO_POR_ANEXO.
        self.assertEqual(
            sender._estimar_tempo_envio_individual("Oi", "a.png"),
            base + 5.0 + WhatsAppSender.TEMPO_ESTIMADO_POR_ANEXO,
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
