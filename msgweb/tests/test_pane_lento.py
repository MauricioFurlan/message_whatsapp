"""
Testes do arranque frio: quando o WhatsApp Web ainda não subiu.

Motivação — o cliente descreveu como "manda 2 mensagens e desconecta". No
`log.txt` é o primeiro envio de 01/09/2026, com o WhatsApp Web voltando de ~20h
offline: 4 envios em 17 minutos, três deles precedidos de
`WhatsApp Web não carregou (#pane-side) em 60s`. Ele parou o programa, reabriu,
e a execução seguinte funcionou.

Duas coisas estavam erradas.

1. **O remédio era o veneno.** A retentativa chamava `driver.get` de novo, na
   hora, sem pausa. Recarregar joga fora o carregamento em andamento e faz o
   WhatsApp Web recomeçar o boot do zero — justamente o que não se quer numa
   página que está apenas lenta. Os tempos do log mostram três boots empilhados:
   65s, 61s, 61s, colados. Agora as tentativas do meio apenas SEGUEM ESPERANDO,
   o que transforma 2x60s picotados em espera contínua pelo mesmo preço, e só a
   última recarrega (uma página travada, e não lenta, ainda precisa do reload).

2. **O portão de sincronização é cego.** `_aguardar_sincronizacao` libera quando
   a lista de conversas para de crescer por 6s; mas depois de uma noite offline
   a lista volta inteira do IndexedDB e nasce estável. Ele deu o mesmo veredito
   ("67 conversa(s), estável por 6s", em 10-15s) em TODA sessão do log — na de
   6% de falha e na de 67%. `_aquecer_navegacao` mede outra coisa: o gesto que o
   envio faz de verdade, um `driver.get` mais a espera do `#pane-side`.

Executa com:
    venv\\Scripts\\python.exe -m unittest tests.test_pane_lento -v
"""

import logging
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import whatsapp_sender  # noqa: E402
from whatsapp_sender import WhatsAppSender, WhatsAppNotLoadedError  # noqa: E402


class FakeTime:
    """Relógio falso: o tempo só anda quando o código dorme."""

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


class DriverAppLento:
    """
    Driver em que o `#pane-side` só aparece depois de `pane_em` segundos
    CONTADOS DO INÍCIO DO TESTE — ou seja, o app está subindo em segundo plano
    e o tempo corre independente de quantas vezes se navegue.

    `reload_atrasa`: quanto cada `driver.get` seguinte empurra esse instante
    para frente. É o comportamento real que se quer punir — recarregar reinicia
    o boot. `None` significa "o reload não muda nada", usado para simular
    página travada em vez de lenta.
    """

    def __init__(self, clock, pane_em, reload_atrasa=None):
        self.clock = clock
        self.pane_em = float(pane_em)
        self.reload_atrasa = reload_atrasa
        self.urls = []
        self.input = FakeInput()

    def get(self, url):
        self.urls.append(url)
        if self.reload_atrasa is not None and len(self.urls) > 1:
            self.pane_em = self.clock.monotonic() + float(self.reload_atrasa)

    @property
    def _pane_pronto(self):
        return self.clock.monotonic() >= self.pane_em

    def find_element(self, by, selector):
        if selector == "#pane-side":
            if self._pane_pronto:
                return object()
            raise Exception("no such element: #pane-side")
        if "contenteditable" in selector:
            return self.input
        return self.input

    def find_elements(self, by, selector):
        if "contenteditable" in selector:
            return [self.input] if self._pane_pronto else []
        return []

    def execute_script(self, *args, **kwargs):
        return None


class BaseTempoFalso(unittest.TestCase):
    def setUp(self):
        logging.getLogger("whatsapp_sender_file").setLevel(logging.CRITICAL)
        self.clock = FakeTime()
        self._time_original = whatsapp_sender.time
        whatsapp_sender.time = self.clock
        self._isleep_original = WhatsAppSender._interruptible_sleep

        def sleep_falso(_self, segundos):
            self.clock.sleep(segundos)
            return _self._stop_event.is_set()

        WhatsAppSender._interruptible_sleep = sleep_falso
        self.addCleanup(self._restaurar)

    def _restaurar(self):
        whatsapp_sender.time = self._time_original
        WhatsAppSender._interruptible_sleep = self._isleep_original

    def novo_sender(self, driver, **cfg):
        config = {"human_behavior": False}
        config.update(cfg)
        sender = WhatsAppSender(
            excel_path="fake.xlsx",
            config=config,
            log_callback=lambda msg: None,
        )
        sender._driver = driver
        sender._confirm_message_sent = lambda texto, timeout=6.0: True
        sender._detect_blocked_contact = lambda: ""
        return sender


class RetryDoPaneTest(BaseTempoFalso):
    def test_app_lento_agora_e_esperado_em_vez_de_recarregado(self):
        """
        O caso do cliente: o app leva ~100s para subir, mais que os 75s de UMA
        tentativa. Antes, cada recarga reiniciava o boot e ele nunca terminava.
        Agora a 2ª tentativa segue esperando e o envio acontece.
        """
        driver = DriverAppLento(self.clock, pane_em=100, reload_atrasa=100)
        sender = self.novo_sender(driver)

        self.assertTrue(sender._send_message("Ana", "19994229146", "Oi"))
        self.assertEqual(
            len(driver.urls), 1,
            "a 2ª tentativa não pode renavegar — o reload reinicia o boot",
        )

    def test_a_ultima_tentativa_ainda_recarrega(self):
        """
        Página travada (e não lenta) continua precisando do reload: se a espera
        contínua não resolveu, a última tentativa tem que renavegar.
        """
        driver = DriverAppLento(self.clock, pane_em=10 ** 6)
        sender = self.novo_sender(driver)

        with self.assertRaises(WhatsAppNotLoadedError):
            sender._send_message("Ana", "19994229146", "Oi")

        self.assertEqual(
            len(driver.urls), 2,
            "esperado: navegação inicial + um reload de última instância",
        )

    def test_nada_e_digitado_quando_o_app_nao_sobe(self):
        """
        Invariante da fase de navegação: nada é entregue nela, então esperar ou
        recarregar não pode duplicar mensagem.
        """
        driver = DriverAppLento(self.clock, pane_em=10 ** 6)
        sender = self.novo_sender(driver)

        with self.assertRaises(WhatsAppNotLoadedError):
            sender._send_message("Ana", "19994229146", "Oi")

        self.assertEqual(driver.input.calls, [])

    def test_espera_continua_cobre_bem_mais_que_uma_janela(self):
        """
        O ganho concreto: a espera contínua antes do reload de última instância
        tem que passar de uma janela só, senão nada mudou de verdade.
        """
        driver = DriverAppLento(self.clock, pane_em=10 ** 6)
        sender = self.novo_sender(driver)
        with self.assertRaises(WhatsAppNotLoadedError):
            sender._send_message("Ana", "19994229146", "Oi")

        # Duas janelas inteiras de espera contínua antes de qualquer reload.
        self.assertGreaterEqual(
            self.clock.monotonic(), 2 * WhatsAppSender._PANE_LOAD_TIMEOUT
        )


class AquecimentoTest(BaseTempoFalso):
    def test_libera_de_imediato_quando_o_app_esta_quente(self):
        driver = DriverAppLento(self.clock, pane_em=0)
        sender = self.novo_sender(driver)

        self.assertTrue(sender._aquecer_navegacao())
        self.assertEqual(len(driver.urls), 1, "app quente não precisa de 2ª medição")

    def test_espera_o_app_frio_antes_de_liberar(self):
        """
        Arranque frio: a primeira medição é lenta demais, e só depois de o app
        terminar de subir o envio é liberado.
        """
        driver = DriverAppLento(self.clock, pane_em=60)
        sender = self.novo_sender(driver)

        self.assertTrue(sender._aquecer_navegacao())
        self.assertGreater(
            len(driver.urls), 1,
            "uma medição lenta tem que levar a outra medição",
        )

    def test_nunca_bloqueia_o_envio(self):
        """
        Máquina cronicamente lenta: o aquecimento desiste e devolve False, mas
        não pode travar o envio para sempre.
        """
        driver = DriverAppLento(self.clock, pane_em=10 ** 6)
        sender = self.novo_sender(driver)

        self.assertFalse(sender._aquecer_navegacao())
        self.assertLessEqual(
            len(driver.urls), WhatsAppSender._AQUECIMENTO_MAX_TENTATIVAS
        )

    def test_nao_abre_conversa_de_ninguem(self):
        """
        O aquecimento navega para o WhatsApp Web puro. Um `send?phone=` marcaria
        como lida a conversa de um contato que ninguém mandou abrir.
        """
        driver = DriverAppLento(self.clock, pane_em=0)
        sender = self.novo_sender(driver)
        sender._aquecer_navegacao()

        for url in driver.urls:
            self.assertNotIn("send?phone", url)
            self.assertNotIn("text=", url)

    def test_para_na_hora_quando_o_usuario_pede(self):
        driver = DriverAppLento(self.clock, pane_em=10 ** 6)
        sender = self.novo_sender(driver)
        sender._stop_event.set()

        self.assertFalse(sender._aquecer_navegacao())
        self.assertEqual(driver.urls, [], "com stop pedido, nem navega")


class CustoDaFalhaDeAppTest(unittest.TestCase):
    def test_falha_de_app_tem_custo_proprio(self):
        """
        Uma falha de app custa 3 janelas de #pane-side; uma de conversa custa
        3 janelas de chat mais a navegação. São números diferentes e o aviso ao
        usuário usa cada um no seu caso.
        """
        app = WhatsAppSender._custo_estimado_de_uma_falha("app")
        chat = WhatsAppSender._custo_estimado_de_uma_falha("chat")

        self.assertNotEqual(app, chat)
        self.assertGreaterEqual(
            app, WhatsAppSender._NAV_MAX_ATTEMPTS * WhatsAppSender._PANE_LOAD_TIMEOUT
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
