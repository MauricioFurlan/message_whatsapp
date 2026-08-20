# -*- coding: utf-8 -*-
"""
Testes de WhatsAppSender._fmt_duracao — formata a duração real do envio
(instante do 1º contato até "finalizado") mostrada no painel ao concluir.

Rodar:
    python -m unittest tests.test_duracao_envio -v
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from whatsapp_sender import WhatsAppSender


class TestFmtDuracao(unittest.TestCase):
    def test_poucos_segundos(self):
        self.assertEqual(WhatsAppSender._fmt_duracao(8), "8s")

    def test_zero_segundos(self):
        self.assertEqual(WhatsAppSender._fmt_duracao(0), "0s")

    def test_minutos_e_segundos(self):
        self.assertEqual(WhatsAppSender._fmt_duracao(65), "1min 5s")

    def test_minutos_exatos_sem_segundos_sobrando(self):
        self.assertEqual(WhatsAppSender._fmt_duracao(120), "2min")

    def test_horas_e_minutos(self):
        self.assertEqual(WhatsAppSender._fmt_duracao(3661), "1h 1min")

    def test_horas_exatas(self):
        self.assertEqual(WhatsAppSender._fmt_duracao(3600), "1h 0min")

    def test_negativo_trava_em_zero(self):
        # Não deveria acontecer na prática (elapsed sempre >= 0), mas a
        # função não deve devolver duração negativa por segurança.
        self.assertEqual(WhatsAppSender._fmt_duracao(-5), "0s")

    def test_arredonda_fracoes_de_segundo(self):
        self.assertEqual(WhatsAppSender._fmt_duracao(59.6), "1min")


if __name__ == "__main__":
    unittest.main()
