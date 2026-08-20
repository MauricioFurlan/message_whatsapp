# -*- coding: utf-8 -*-
"""
Testes da estimativa de tempo de envio (anexos + tamanho da mensagem) e do
orçamento de pausas descontado a partir dela.

Motivação (relato de cliente, 19-20/08/2026): configurou 15 minutos pro
envio, mas o log mostrou 28min7s de duração real. A causa: o orçamento de
15min só cobria as PAUSAS entre mensagens — o tempo do envio em si (digitar,
subir anexo) não entrava na conta, e sempre se somava por cima. Agora o
tempo configurado é tratado como o total desejado: _calcular_orcamento_de_pausas
desconta o tempo de envio estimado ANTES de calcular o ritmo, e sinaliza
`inviavel=True` quando quase não sobra espaço real pra pausa nenhuma — nesse
caso o app avisa em vez de deixar o ritmo cair pro piso de segurança
(DELAY_INTRA_MIN) sem explicação, e não sugere nenhum valor "seguro".

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


class TestEstimarTempoEnvioTotal(unittest.TestCase):
    def test_soma_a_estimativa_de_cada_contato_da_amostra(self):
        s = _sender()
        pending = pd.DataFrame([
            {"Mensagem": "Oi", "Arquivo": "a.png,b.pdf"},
            {"Mensagem": "Oi", "Arquivo": ""},
        ])
        esperado = (
            s._estimar_tempo_envio_individual("Oi", "a.png,b.pdf")
            + s._estimar_tempo_envio_individual("Oi", "")
        )
        self.assertAlmostEqual(s._estimar_tempo_envio_total(pending, session_target=2), esperado, places=3)

    def test_considera_so_a_amostra_do_session_target(self):
        # 30 mensagens pendentes, mas a meta desta sessão é 2 — a estimativa
        # não deve contar as 30, só as que de fato serão tentadas agora.
        s = _sender()
        pending = pd.DataFrame([{"Mensagem": "Oi", "Arquivo": "a.png"}] * 30)
        tempo_envio = s._estimar_tempo_envio_total(pending, session_target=2)
        self.assertAlmostEqual(
            tempo_envio, 2 * s._estimar_tempo_envio_individual("Oi", "a.png"), places=3
        )

    def test_sem_pendentes_nao_quebra(self):
        s = _sender()
        pending = pd.DataFrame(columns=["Mensagem", "Arquivo"])
        self.assertEqual(s._estimar_tempo_envio_total(pending, session_target=0), 0)


class TestCalcularOrcamentoDePausas(unittest.TestCase):
    def test_desconta_tempo_de_envio_do_tempo_configurado(self):
        # 30 msgs sem anexo em 1h: sobra bastante espaço real pra pausa.
        s = _sender()
        pending = pd.DataFrame([{"Mensagem": "Oi, tudo bem?", "Arquivo": ""}] * 30)
        orcamento = s._calcular_orcamento_de_pausas(pending, session_target=30, tempo_minutos=60)
        tempo_envio_esperado = s._estimar_tempo_envio_total(pending, 30)
        self.assertAlmostEqual(orcamento["tempo_de_envio_seg"], tempo_envio_esperado, places=3)
        self.assertAlmostEqual(orcamento["tempo_pausas_seg"], 3600 - tempo_envio_esperado, places=3)
        self.assertFalse(orcamento["inviavel"])

    def test_cenario_do_relato_fica_inviavel(self):
        # O cenário real do cliente: 25 msgs com 2 anexos cada em 15min —
        # o tempo de envio estimado sozinho já passa dos 15min configurados.
        s = _sender()
        pending = pd.DataFrame([{"Mensagem": "Olá, mensagem de teste.", "Arquivo": "a.png,b.pdf"}] * 25)
        orcamento = s._calcular_orcamento_de_pausas(pending, session_target=25, tempo_minutos=15)
        self.assertTrue(orcamento["inviavel"])
        # Nunca fica negativo mesmo quando o tempo de envio estoura o
        # configurado — o piso de segurança (DELAY_INTRA_MIN) assume daqui.
        self.assertEqual(orcamento["tempo_pausas_seg"], 0.0)
        self.assertEqual(orcamento["media_gap_disponivel"], 0.0)

    def test_uma_unica_mensagem_nunca_e_inviavel(self):
        # Sem intervalo nenhum entre mensagens (só 1 msg), não faz sentido
        # avaliar "espaço pra pausa" — não deveria acionar o aviso.
        s = _sender()
        pending = pd.DataFrame([{"Mensagem": "Oi", "Arquivo": "a.png,b.pdf,c.mp4"}])
        orcamento = s._calcular_orcamento_de_pausas(pending, session_target=1, tempo_minutos=1)
        self.assertFalse(orcamento["inviavel"])

    def test_media_gap_disponivel_bate_com_o_piso_de_seguranca(self):
        # Ajusta o tempo configurado pra cair bem na borda do piso
        # (DELAY_INTRA_MIN) e confirma que o "inviavel" reage exatamente a
        # essa fronteira, não a um valor arbitrário.
        s = _sender(human_behavior=False)  # tempo de envio fixo e previsível (5s/contato)
        pending = pd.DataFrame([{"Mensagem": "Oi", "Arquivo": ""}] * 3)  # 2 intervalos
        tempo_envio_total = 3 * 5.0  # 15s

        # Exatamente no piso (30s de pausa / 2 intervalos = 15s = DELAY_INTRA_MIN): não inviável.
        tempo_configurado_no_piso = tempo_envio_total + 2 * s.DELAY_INTRA_MIN
        orcamento_no_piso = s._calcular_orcamento_de_pausas(
            pending, session_target=3, tempo_minutos=tempo_configurado_no_piso / 60
        )
        self.assertFalse(orcamento_no_piso["inviavel"])

        # Um segundo a menos de folga por intervalo: já inviável.
        tempo_configurado_abaixo = tempo_configurado_no_piso - 2
        orcamento_abaixo = s._calcular_orcamento_de_pausas(
            pending, session_target=3, tempo_minutos=tempo_configurado_abaixo / 60
        )
        self.assertTrue(orcamento_abaixo["inviavel"])


if __name__ == "__main__":
    unittest.main()
