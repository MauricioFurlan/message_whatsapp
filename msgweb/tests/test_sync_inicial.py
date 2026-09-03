"""
Testes da abertura da sessão do WhatsApp Web (antes da primeira mensagem).

Motivação (log do cliente, versão 1.4.5):

  1. "Sessão não encontrada. Escaneie o QR Code no navegador..." aparecia mesmo
     com a sessão salva. Em 25/08 13:00:21 essa mensagem foi seguida de "Login
     realizado com sucesso" às 13:00:24 — 3 segundos depois. Em 26/08 14:47:57
     e 14:54:51, 6 e 5 segundos. Ninguém escaneia um QR Code nesse tempo: a
     janela de detecção era de 8s fixos e o WhatsApp Web demora mais que isso
     para desenhar a lista de conversas num início frio.

  2. Em 26/08 o login saiu às 14:37:37 e a primeira mensagem foi disparada às
     14:37:39, 2 segundos depois de um QR novo. Os 8 contatos daquela sessão
     deram timeout, nenhum envio saiu: o app estava de pé mas ainda baixando o
     histórico do celular, e nesse estado o link direto da conversa não abre.

O que estes testes fixam:
  - só se fala em QR Code quando o QR está desenhado na tela;
  - sessão salva que demora mais de 8s a carregar não é confundida com sessão
    perdida;
  - o envio espera as conversas carregarem antes de começar;
  - a espera termina sozinha quando a lista para de crescer, e desiste (sem
    travar o envio) se a sincronização não estabilizar.

Executa com:
    venv\\Scripts\\python.exe -m unittest tests.test_sync_inicial -v
"""

import logging
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import whatsapp_sender  # noqa: E402
from whatsapp_sender import WhatsAppSender  # noqa: E402


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


class FakeEl:
    def __init__(self, visivel=True, texto=""):
        self._visivel = visivel
        self.text = texto

    def is_displayed(self):
        return self._visivel


class FakeDriverSessao:
    """
    Driver de abertura de sessão, controlado por linha do tempo.

    pane_em / qr_em: instante (do relógio falso) a partir do qual #pane-side e
    o canvas do QR passam a existir. None = nunca aparece.
    conversas(t): quantas conversas há na lista no instante t.
    texto_body(t): texto da página (para o aviso de sincronização).
    """

    def __init__(self, clock, pane_em=None, qr_em=None, conversas=None, texto_body=None):
        self.clock = clock
        self.pane_em = pane_em
        self.qr_em = qr_em
        self._conversas = conversas or (lambda t: 0)
        self._texto_body = texto_body or (lambda t: "")

    def _existe(self, quando):
        return quando is not None and self.clock.monotonic() >= quando

    def find_element(self, by, selector):
        if selector == "#pane-side":
            if self._existe(self.pane_em):
                return FakeEl()
            raise Exception("no such element: #pane-side")
        if selector == "body":
            return FakeEl(texto=self._texto_body(self.clock.monotonic()))
        raise Exception(f"no such element: {selector}")

    def find_elements(self, by, selector):
        if "canvas" in selector or "qrcode" in selector:
            return [FakeEl()] if self._existe(self.qr_em) else []
        if "listitem" in selector or "role=\"row\"" in selector:
            n = self._conversas(self.clock.monotonic())
            return [FakeEl() for _ in range(n)]
        return []


class SessaoInicialTest(unittest.TestCase):
    def setUp(self):
        logging.getLogger("whatsapp_sender_file").setLevel(logging.CRITICAL)
        self.clock = FakeTime()
        self._time_original = whatsapp_sender.time
        whatsapp_sender.time = self.clock
        self._isleep_original = WhatsAppSender._interruptible_sleep

        def sleep_falso(_self, segundos):
            self.clock.sleep(segundos)
            return False

        WhatsAppSender._interruptible_sleep = sleep_falso
        self.addCleanup(self._restaurar)

    def _restaurar(self):
        whatsapp_sender.time = self._time_original
        WhatsAppSender._interruptible_sleep = self._isleep_original

    def novo_sender(self, driver):
        self.logs = []
        sender = WhatsAppSender(
            excel_path="fake.xlsx",
            config={},
            log_callback=self.logs.append,
        )
        sender._driver = driver
        return sender

    # --- 1. detecção de QR ------------------------------------------------- #
    def test_qr_na_tela_so_com_canvas_visivel(self):
        """Sem canvas do QR, _qr_na_tela é False mesmo sem lista de conversas."""
        sender = self.novo_sender(FakeDriverSessao(self.clock, pane_em=None, qr_em=None))
        self.assertFalse(sender._qr_na_tela())

    def test_qr_na_tela_detecta_canvas(self):
        sender = self.novo_sender(FakeDriverSessao(self.clock, qr_em=0))
        self.assertTrue(sender._qr_na_tela())

    def test_janela_de_deteccao_cobre_inicio_frio(self):
        """
        O caso do log: sessão salva, mas o #pane-side leva 15s para aparecer.

        Com os 8s antigos isso era anunciado como "Sessão não encontrada".
        A janela atual tem que ser maior que esse tempo de carga.
        """
        self.assertGreater(
            WhatsAppSender._SESSION_DETECT_TIMEOUT, 8,
            "a janela de detecção precisa ser maior que os 8s que causaram o alarme falso",
        )
        driver = FakeDriverSessao(self.clock, pane_em=15, qr_em=None)
        sender = self.novo_sender(driver)

        # Simula o laço de detecção do start(): espera pane OU QR.
        achou_pane = False
        achou_qr = False
        fim = self.clock.monotonic() + WhatsAppSender._SESSION_DETECT_TIMEOUT
        while self.clock.monotonic() < fim:
            try:
                driver.find_element(None, "#pane-side")
                achou_pane = True
                break
            except Exception:
                pass
            if sender._qr_na_tela():
                achou_qr = True
                break
            sender._interruptible_sleep(0.5)

        self.assertTrue(achou_pane, "sessão salva lenta deve ser detectada como ativa")
        self.assertFalse(achou_qr, "não pode acusar QR Code quando não há QR na tela")

    # --- 2. espera de sincronização ---------------------------------------- #
    def test_espera_conversas_carregarem(self):
        """A espera só termina quando a lista para de crescer."""
        # Conversas entram até t=20s; depois estabiliza em 40.
        def conversas(t):
            if t < 5:
                return 0
            return min(40, int((t - 5) * 2))

        sender = self.novo_sender(FakeDriverSessao(self.clock, pane_em=0, conversas=conversas))
        sender._aguardar_sincronizacao(apos_qr=True)

        # Terminou depois que a lista estabilizou, não antes.
        self.assertGreaterEqual(
            self.clock.monotonic(), 25,
            "não pode declarar pronto enquanto a lista ainda cresce",
        )
        self.assertLess(self.clock.monotonic(), WhatsAppSender._SYNC_TIMEOUT_APOS_QR)
        self.assertTrue(
            any("pronto" in m for m in self.logs),
            f"esperava log de pronto, veio: {self.logs}",
        )

    def test_aviso_de_sincronizacao_segura_o_inicio(self):
        """Enquanto o WhatsApp diz que está sincronizando, não começa a enviar."""
        # Lista cheia e parada desde o começo, mas o aviso fica até t=30s.
        sender = self.novo_sender(FakeDriverSessao(
            self.clock,
            pane_em=0,
            conversas=lambda t: 40,
            texto_body=lambda t: "sincronizando mensagens" if t < 30 else "conversas",
        ))
        sender._aguardar_sincronizacao(apos_qr=True)

        self.assertGreaterEqual(
            self.clock.monotonic(), 30,
            "o aviso de sincronização precisa segurar o início do envio",
        )

    def test_nao_trava_o_envio_se_nunca_estabilizar(self):
        """Sincronização eterna: avisa e segue, respeitando o limite."""
        sender = self.novo_sender(FakeDriverSessao(
            self.clock,
            pane_em=0,
            conversas=lambda t: int(t),  # cresce para sempre
        ))
        sender._aguardar_sincronizacao(apos_qr=True)

        self.assertGreaterEqual(self.clock.monotonic(), WhatsAppSender._SYNC_TIMEOUT_APOS_QR)
        self.assertTrue(
            any("ainda parece estar carregando" in m for m in self.logs),
            f"esperava aviso de que seguiu mesmo assim, veio: {self.logs}",
        )

    def test_sessao_ja_ativa_espera_menos(self):
        """Sem QR novo, não há histórico a baixar: a espera é bem menor."""
        self.assertLess(
            WhatsAppSender._SYNC_TIMEOUT_SESSAO_ATIVA,
            WhatsAppSender._SYNC_TIMEOUT_APOS_QR,
        )
        sender = self.novo_sender(FakeDriverSessao(
            self.clock, pane_em=0, conversas=lambda t: 40,
        ))
        sender._aguardar_sincronizacao(apos_qr=False)
        self.assertLess(self.clock.monotonic(), WhatsAppSender._SYNC_TIMEOUT_SESSAO_ATIVA)

    def test_stop_interrompe_a_espera(self):
        """Pedido de parada durante a sincronização sai na hora."""
        sender = self.novo_sender(FakeDriverSessao(
            self.clock, pane_em=0, conversas=lambda t: int(t),
        ))
        sender._stop_event.set()
        sender._aguardar_sincronizacao(apos_qr=True)
        self.assertLess(
            self.clock.monotonic(), 5,
            "com stop pedido, a espera não pode consumir o timeout inteiro",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
