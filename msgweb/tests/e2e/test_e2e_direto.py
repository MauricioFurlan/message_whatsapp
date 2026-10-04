# -*- coding: utf-8 -*-
"""
Modo "envio direto": sem rajadas, todos os pendentes, 15-30s entre mensagens.

Regras decididas pelo usuário (2026-10-03/04):
1. Ligado, desliga a rajada e envia para TODOS os pendentes, ignorando a
   quantidade configurada.
2. Intervalo sorteado entre 15 e 30s a cada mensagem, não configurável.
3. Falha se comporta como na rajada: não espera o intervalo, não gasta vaga.
4. Horário comercial continua respeitado.
5. Aviso de risco na tela (ver tests/test_modo_direto_ui.js) e no log.
6. O alarme de entrega, que nas rajadas lê a lista durante as pausas longas,
   aqui lê dentro do intervalo a cada `_VERIFICACAO_DIRETO_A_CADA` envios —
   sem isso ele ficaria mudo justamente no modo mais arriscado.

Rodar:
    python -m unittest tests.e2e.test_e2e_direto -v
"""

import os
import re
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from tests.e2e.ambiente import AmbienteE2E
from tests.e2e import fake_whatsapp as fw


def _contatos(n):
    return [
        {"Nome": f"Pessoa {i}", "Número": f"1999{i:07d}", "Mensagem": "Oi {nome}"}
        for i in range(1, n + 1)
    ]


def _intervalos(logs):
    return [
        int(m.group(1))
        for m in (re.search(r"Aguardando (\d+)s\.\.\.", str(l)) for l in logs)
        if m
    ]


class TestEnvioDireto(unittest.TestCase):

    def test_envia_para_todos_os_pendentes_ignorando_a_quantidade(self):
        with AmbienteE2E(contatos=_contatos(8)) as amb:
            amb.configurar(total_msgs=3, tempo_minutos=5, modo_envio="direto")
            amb.iniciar_envio()
            amb.esperar_envio()
            self.assertEqual(len(amb.driver.enviadas), 8)

    def test_intervalo_entre_15_e_30s_e_sem_pausa_longa(self):
        with AmbienteE2E(contatos=_contatos(12)) as amb:
            amb.configurar(modo_envio="direto")
            amb.iniciar_envio()
            amb.esperar_envio()
            intervalos = _intervalos(amb.logs())
            # 12 envios, 11 intervalos entre eles — nenhuma pausa de leva.
            self.assertEqual(len(intervalos), 11)
            for s in intervalos:
                self.assertGreaterEqual(s, 15)
                self.assertLessEqual(s, 30)
            textos = " ".join(str(l) for l in amb.logs())
            self.assertNotIn("Pausa de", textos)
            self.assertNotIn("Executando leva", textos)

    def test_falha_nao_espera_o_intervalo(self):
        with AmbienteE2E(
            contatos=_contatos(4),
            roteiro={"19990000002": fw.NUMERO_INVALIDO},
        ) as amb:
            amb.configurar(modo_envio="direto")
            amb.iniciar_envio()
            amb.esperar_envio()
            self.assertEqual(amb.linha("Pessoa 2")["Invalido"], "X")
            self.assertEqual(len(amb.driver.enviadas), 3)
            # Só envio real espera, e nunca depois do último contato: o
            # intervalo vem depois da Pessoa 1 e da Pessoa 3 — nem depois da
            # falha (Pessoa 2), nem depois da Pessoa 4, que fecha a lista.
            self.assertEqual(len(_intervalos(amb.logs())), 2)

    def test_risco_registrado_no_log_e_fim_sem_tempo_configurado(self):
        with AmbienteE2E(contatos=_contatos(2)) as amb:
            amb.configurar(modo_envio="direto")
            amb.iniciar_envio()
            amb.esperar_envio()
            textos = " ".join(str(l) for l in amb.logs())
            self.assertIn("Configuração atualizada: envio direto", textos)
            self.assertIn("Começando o envio direto", textos)
            self.assertIn("bloquear o seu número", textos)
            self.assertIn("(modo direto)", textos)
            self.assertNotIn("tempo configurado:", textos)

    def test_horario_comercial_conferido_a_cada_mensagem(self):
        from whatsapp_sender import WhatsAppSender
        chamadas = []
        original = WhatsAppSender._aguardar_horario_comercial_medindo

        def _espiao(self_):
            chamadas.append(1)
            return original(self_)

        with patch.object(WhatsAppSender, "_aguardar_horario_comercial_medindo", _espiao):
            with AmbienteE2E(contatos=_contatos(5)) as amb:
                amb.configurar(modo_envio="direto")
                amb.iniciar_envio()
                amb.esperar_envio()
        self.assertGreaterEqual(len(chamadas), 5)

    def test_alarme_de_entrega_le_a_lista_a_cada_10_envios(self):
        from whatsapp_sender import WhatsAppSender
        leituras = []
        with patch.object(
            WhatsAppSender, "_ler_entregas",
            lambda self_, orcamento: leituras.append(orcamento),
        ):
            with AmbienteE2E(contatos=_contatos(25)) as amb:
                amb.configurar(modo_envio="direto")
                amb.iniciar_envio()
                amb.esperar_envio()
        # Depois do 10º e do 20º envio; o 25º não tem intervalo depois.
        self.assertEqual(len(leituras), 2)
        # A leitura cabe dentro do intervalo, nunca o estoura.
        for orcamento in leituras:
            self.assertLess(orcamento, WhatsAppSender.DIRETO_INTERVALO_MAX)

    def test_rajadas_continuam_sendo_o_padrao(self):
        with AmbienteE2E(contatos=_contatos(8)) as amb:
            amb.configurar(total_msgs=3, tempo_minutos=5)
            amb.iniciar_envio()
            amb.esperar_envio()
            self.assertEqual(len(amb.driver.enviadas), 3)


class TestConfigEEstimativa(unittest.TestCase):

    def test_modo_sobrevive_ao_reinicio(self):
        with AmbienteE2E(contatos=_contatos(2)) as amb:
            amb.configurar(modo_envio="direto")
            cfg = amb.cliente.get("/status").json()["config"]
            self.assertEqual(cfg["modo_envio"], "direto")
            app = amb._app_mod
            app.state.config["modo_envio"] = "rajadas"
            app._restaurar_config_do_disco()
            self.assertEqual(app.state.config["modo_envio"], "direto")

    def test_modo_desconhecido_e_recusado(self):
        with AmbienteE2E(contatos=_contatos(2)) as amb:
            r = amb.cliente.post("/config", json={"modo_envio": "turbo"})
            self.assertEqual(r.status_code, 422)

    def test_estimativa_conta_todos_os_pendentes_mais_o_intervalo(self):
        with AmbienteE2E(contatos=_contatos(10)) as amb:
            amb.configurar(modo_envio="direto")
            r = amb.cliente.get("/estimate", params={"modo_envio": "direto"}).json()
            self.assertEqual(r["status"], "ok")
            self.assertEqual(r["pendentes"], 10)
            self.assertEqual(r["session_target"], 10)
            # 9 intervalos de 22,5s em média, além do envio em si.
            self.assertGreater(r["tempo_total_estimado_seg"], 9 * 22.5)


if __name__ == "__main__":
    unittest.main()
