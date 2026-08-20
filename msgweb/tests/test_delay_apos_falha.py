# -*- coding: utf-8 -*-
"""
Regressão: o delay intra-burst ("Aguardando Xs...") só deve acontecer depois
de um envio REAL — nunca depois de um contato que falhou.

Bug relatado (log real do cliente, 19-20/08/2026): configurou 15 minutos,
mas o envio levou quase 28. Uma das causas: contatos que falhavam DEPOIS de
já ter tentado enviar (anexo não encontrado, número rejeitado, timeout, "Falha
ao enviar mensagem") ainda esperavam o delay entre mensagens como se tivessem
enviado — o código só checava `enviados_burst < burst_size`, que continua
verdadeiro logo após uma falha (nada foi incrementado). Diferente da
validação prévia (mensagem vazia/número ausente), que já pulava o delay via
`continue`.

Rodar:
    venv\\Scripts\\python.exe -m unittest tests.test_delay_apos_falha -v
"""

import logging
import os
import sys
import unittest

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import whatsapp_sender


class FakeDriverSessao:
    """Driver falso suficiente para o start() achar sessão ativa e seguir sem Chrome real."""

    def get(self, url):
        pass

    def find_element(self, by, selector):
        return object()  # find_element sem erro = "#pane-side" existe = sessão ativa

    def quit(self):
        pass


class TestDelayApenasAposEnvioReal(unittest.TestCase):
    def setUp(self):
        logging.getLogger("whatsapp_sender_file").setLevel(logging.CRITICAL)
        self._orig_isleep = whatsapp_sender.WhatsAppSender._interruptible_sleep
        whatsapp_sender.WhatsAppSender._interruptible_sleep = lambda self, s: False
        self._orig_registrar_envio = whatsapp_sender.stats_log.registrar_envio
        self._orig_registrar_rejeitado = whatsapp_sender.stats_log.registrar_rejeitado
        whatsapp_sender.stats_log.registrar_envio = lambda *a, **k: None
        whatsapp_sender.stats_log.registrar_rejeitado = lambda *a, **k: None
        self.addCleanup(self._restore)

    def _restore(self):
        whatsapp_sender.WhatsAppSender._interruptible_sleep = self._orig_isleep
        whatsapp_sender.stats_log.registrar_envio = self._orig_registrar_envio
        whatsapp_sender.stats_log.registrar_rejeitado = self._orig_registrar_rejeitado

    def _rodar_um_burst(self, resultados):
        """
        resultados: lista de 'ok' | 'falha', um por contato — todos forçados
        para dentro de UMA ÚNICA leva (burst_size = len(resultados)), pra
        isolar exatamente o delay intra-burst sem depender de como
        _generate_burst_plan divide aleatoriamente as levas.
        """
        contatos = [
            {
                "Nome": f"Contato{i}", "Número": f"1199999{i:04d}",
                "Mensagem": "Olá, mensagem de teste.", "Arquivo": "",
                "Enviado": "", "DataEnvio": "", "Invalido": "",
            }
            for i in range(len(resultados))
        ]
        estado = {"df": pd.DataFrame(contatos)}
        por_numero = {c["Número"]: r for c, r in zip(contatos, resultados)}
        logs = []

        sender = whatsapp_sender.WhatsAppSender(
            excel_path="fake.xlsx",
            config={"total_msgs": len(resultados), "tempo_minutos": 1, "human_behavior": False},
            log_callback=logs.append,
        )
        sender._init_driver = lambda: FakeDriverSessao()
        sender._load_contacts = lambda: estado["df"].copy()
        sender._save_contacts = lambda df: estado.update({"df": df})
        sender._wait_for_business_hours = lambda: None
        sender._generate_burst_plan = lambda total_msgs, tempo_minutos: [
            {"burst_size": len(resultados), "intra_delay": 20.0, "pause_after": 0.0}
        ]

        def fake_send(pessoa, numero, mensagem, arquivo=""):
            return por_numero[numero] == "ok"

        sender._send_message = fake_send
        sender.start()
        return logs

    def test_falha_no_meio_do_burst_nao_espera_delay(self):
        logs = self._rodar_um_burst(["ok", "falha", "ok"])

        # Âncora na tentativa do 2º contato (falha real, sem exceção, não
        # gera linha própria de log — só df/notify) e na linha "Enviando" do 3º.
        idx_tentativa_falha = next(
            i for i, l in enumerate(logs) if l.startswith("Enviando para Contato1")
        )
        idx_terceiro_envio = next(
            i for i, l in enumerate(logs) if l.startswith("Enviando para Contato2")
        )
        entre = logs[idx_tentativa_falha + 1:idx_terceiro_envio]
        aguardando_entre = [l for l in entre if l.startswith("Aguardando")]
        self.assertEqual(
            aguardando_entre, [],
            f"Não deveria haver 'Aguardando...' entre a falha e o próximo envio, mas achou: {aguardando_entre}\n"
            f"Logs completos: {logs}",
        )

    def test_envio_real_ainda_espera_o_delay_normalmente(self):
        # Garante que a correção não removeu o delay nos casos que DEVEM
        # esperar — só nos casos de falha.
        logs = self._rodar_um_burst(["ok", "ok"])
        idx_primeiro_sucesso = next(i for i, l in enumerate(logs) if "mensagem enviada com sucesso" in l)
        idx_segundo_envio = next(i for i, l in enumerate(logs) if l.startswith("Enviando para Contato1"))
        entre = logs[idx_primeiro_sucesso + 1:idx_segundo_envio]
        self.assertTrue(
            any(l.startswith("Aguardando") for l in entre),
            f"Esperava um 'Aguardando...' entre dois envios reais. Logs: {logs}",
        )

    def test_ultima_falha_do_burst_tambem_nao_espera(self):
        # A falha é a ÚLTIMA tentativa da leva (não sobra ninguém depois) —
        # garante que o fim do burst/pausa entre rajadas não mascare o bug.
        logs = self._rodar_um_burst(["ok", "falha"])
        idx_tentativa_falha = next(
            i for i, l in enumerate(logs) if l.startswith("Enviando para Contato1")
        )
        depois = logs[idx_tentativa_falha + 1:]
        aguardando_depois = [l for l in depois if l.startswith("Aguardando")]
        self.assertEqual(aguardando_depois, [], f"Logs: {logs}")


if __name__ == "__main__":
    unittest.main()
