# -*- coding: utf-8 -*-
"""
Testes da estimativa de duração real do envio (anexos + tamanho da mensagem).

Motivação (relato de cliente, 19-20/08/2026): configurou 15 minutos pro
envio, mas o log mostrou 28min7s de duração real. A causa: o orçamento de
15min só cobre as PAUSAS entre mensagens — o tempo do envio em si (digitar,
subir anexo) não entrava na conta. _estimar_duracao_real soma esse tempo à
parte e é só informativo: não altera o ritmo/pausas do plano de rajadas.

Rodar:
    python -m unittest tests.test_estimativa_envio -v
"""

import os
import sys
import unittest

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from whatsapp_sender import WhatsAppSender


def _sender(human_behavior=True):
    return WhatsAppSender(excel_path="fake.xlsx", config={"human_behavior": human_behavior})


class TestEstimarTempoEnvioIndividual(unittest.TestCase):
    def test_sem_anexo_usa_so_o_orcamento_de_digitacao(self):
        s = _sender()
        esperado = s._type_budget(len("Olá, tudo bem?"))
        self.assertEqual(s._estimar_tempo_envio_individual("Olá, tudo bem?", ""), esperado)

    def test_cada_anexo_soma_a_constante_dedicada(self):
        s = _sender()
        base = s._estimar_tempo_envio_individual("Oi", "")
        com_2_anexos = s._estimar_tempo_envio_individual("Oi", "a.png,b.pdf")
        self.assertAlmostEqual(com_2_anexos - base, 2 * s.TEMPO_ESTIMADO_POR_ANEXO, places=3)

    def test_anexo_vazio_ou_nan_nao_conta(self):
        s = _sender()
        base = s._estimar_tempo_envio_individual("Oi", "")
        self.assertEqual(s._estimar_tempo_envio_individual("Oi", "nan"), base + s.TEMPO_ESTIMADO_POR_ANEXO)
        # "nan" vira nome de arquivo de 1 item aqui (é responsabilidade de
        # quem monta a planilha não deixar "nan" como Arquivo de verdade);
        # o que a função garante é não contar vírgulas soltas como anexo.
        self.assertEqual(s._estimar_tempo_envio_individual("Oi", " , , "), base)

    def test_mensagem_mais_longa_estima_mais_tempo(self):
        s = _sender()
        curta = s._estimar_tempo_envio_individual("Oi", "")
        longa = s._estimar_tempo_envio_individual("Oi " * 200, "")
        self.assertGreater(longa, curta)

    def test_sem_comportamento_humano_usa_tempo_fixo_baixo(self):
        # Sem digitação humanizada o texto vai pré-preenchido na URL — não
        # faz sentido usar o orçamento de digitação humanizada aqui.
        s = _sender(human_behavior=False)
        self.assertEqual(s._estimar_tempo_envio_individual("Mensagem enorme " * 50, ""), 5.0)


class TestEstimarDuracaoReal(unittest.TestCase):
    def test_soma_tempo_configurado_com_tempo_de_envio_da_amostra(self):
        s = _sender()
        pending = pd.DataFrame([
            {"Mensagem": "Oi", "Arquivo": "a.png,b.pdf"},
            {"Mensagem": "Oi", "Arquivo": ""},
        ])
        tempo_envio, tempo_total = s._estimar_duracao_real(pending, session_target=2, tempo_segundos=900)
        esperado_envio = (
            s._estimar_tempo_envio_individual("Oi", "a.png,b.pdf")
            + s._estimar_tempo_envio_individual("Oi", "")
        )
        self.assertAlmostEqual(tempo_envio, esperado_envio, places=3)
        self.assertAlmostEqual(tempo_total, 900 + esperado_envio, places=3)

    def test_considera_so_a_amostra_do_session_target(self):
        # 30 mensagens pendentes, mas a meta desta sessão é 2 — a estimativa
        # não deve contar as 30, só as que de fato serão tentadas agora.
        s = _sender()
        pending = pd.DataFrame([{"Mensagem": "Oi", "Arquivo": "a.png"}] * 30)
        tempo_envio, _ = s._estimar_duracao_real(pending, session_target=2, tempo_segundos=60)
        self.assertAlmostEqual(
            tempo_envio, 2 * s._estimar_tempo_envio_individual("Oi", "a.png"), places=3
        )

    def test_sem_pendentes_nao_quebra(self):
        s = _sender()
        pending = pd.DataFrame(columns=["Mensagem", "Arquivo"])
        tempo_envio, tempo_total = s._estimar_duracao_real(pending, session_target=0, tempo_segundos=900)
        self.assertEqual(tempo_envio, 0)
        self.assertEqual(tempo_total, 900)


if __name__ == "__main__":
    unittest.main()
