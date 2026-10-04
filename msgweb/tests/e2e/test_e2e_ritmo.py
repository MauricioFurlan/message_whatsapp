# -*- coding: utf-8 -*-
"""
O tempo configurado é cumprido: a campanha termina perto do prazo mesmo
quando o envio real é mais lento ou mais rápido que a estimativa.

Relato do cliente (2026-10-03): "não está fiel o tempo estipulado". O plano de
rajadas era sorteado uma vez, em cima de uma estimativa fixa do custo de um
envio (40s para abrir a conversa), e as pausas eram executadas às cegas — todo
erro da estimativa caía inteiro no total. Agora cada pausa é reajustada contra
o prazo (`WhatsAppSender._replanejar_pausa`).

O relógio é o virtual do `AmbienteE2E`: a conversa "demorar 90s para abrir" é
o relógio andar 90s no `driver.get`, e uma campanha de uma hora roda em
milissegundos com a lógica de ritmo intacta.

Rodar:
    python -m unittest tests.e2e.test_e2e_ritmo -v
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from tests.e2e.ambiente import AmbienteE2E


def _contatos(n):
    return [
        {"Nome": f"Pessoa {i}", "Número": f"1999{i:07d}", "Mensagem": "Oi {nome}"}
        for i in range(1, n + 1)
    ]


def _abertura_custando(amb, segundos):
    """Cada conversa aberta custa `segundos` no relógio virtual."""
    original = amb.driver.get

    def _get(url):
        original(url)
        if "send?phone=" in url:
            amb.relogio.avancar(segundos)

    amb.driver.get = _get


def _duracao(amb):
    return amb._app_mod.state.sender._elapsed_seconds


class TestTempoConfiguradoECumprido(unittest.TestCase):
    TOLERANCIA = 0.05  # 5% da janela

    def _rodar(self, n, minutos, custo_abertura):
        with AmbienteE2E(contatos=_contatos(n)) as amb:
            _abertura_custando(amb, custo_abertura)
            amb.configurar(total_msgs=n, tempo_minutos=minutos)
            amb.iniciar_envio()
            amb.esperar_envio()
            self.assertEqual(len(amb.driver.enviadas), n)
            return _duracao(amb), amb.logs()

    def test_conversa_mais_lenta_que_a_estimativa_ainda_fecha_no_prazo(self):
        # 90s por abertura contra 40s estimados: sem o reajuste o envio
        # passava ~17min de uma janela de 60.
        janela = 60 * 60
        for _ in range(3):  # o plano é sorteado; vale para qualquer sorteio
            duracao, _ = self._rodar(20, 60, custo_abertura=90)
            self.assertAlmostEqual(duracao, janela, delta=janela * self.TOLERANCIA)

    def test_conversa_mais_rapida_que_a_estimativa_nao_termina_antes(self):
        janela = 60 * 60
        for _ in range(3):
            duracao, _ = self._rodar(20, 60, custo_abertura=5)
            self.assertAlmostEqual(duracao, janela, delta=janela * self.TOLERANCIA)

    def test_janela_impossivel_avisa_que_vai_passar_do_tempo(self):
        # 20 conversas de 90s não cabem em 10min: as pausas vão ao piso e o
        # usuário é avisado, em vez de descobrir olhando o relógio.
        duracao, logs = self._rodar(20, 10, custo_abertura=90)
        self.assertGreater(duracao, 10 * 60)
        textos = " ".join(str(l) for l in logs)
        self.assertIn("mais lento que o previsto", textos)
        self.assertIn("tempo configurado: 10min", textos)


class TestPisoDaPausa(unittest.TestCase):
    """Atrasado, a pausa encolhe até metade da planejada, nunca até 15s
    (decisão do usuário, 2026-10-04): rajadas quase coladas arriscam bloqueio,
    e passar do tempo configurado é o preço aceito."""

    def setUp(self):
        from whatsapp_sender import WhatsAppSender
        self.S = WhatsAppSender

    def test_atrasado_nao_desce_abaixo_da_metade_da_planejada(self):
        # Prazo já estourado: o orçamento é negativo.
        pausa = self.S._replanejar_pausa(200, 600, 0, -100, 10, 60)
        self.assertEqual(pausa, 100)

    def test_pausa_planejada_curta_ainda_respeita_delay_intra_min(self):
        pausa = self.S._replanejar_pausa(20, 600, 0, -100, 10, 60)
        self.assertEqual(pausa, self.S.DELAY_INTRA_MIN)

    def test_adiantado_continua_podendo_crescer(self):
        pausa = self.S._replanejar_pausa(200, 400, 0, 2000, 0, 60)
        self.assertEqual(pausa, 1000)


if __name__ == "__main__":
    unittest.main()
