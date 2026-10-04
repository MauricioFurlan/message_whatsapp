# -*- coding: utf-8 -*-
"""
Campanha simulada não pode somar no histórico real de envios.

O histórico (`stats_log`, "Baixar histórico" na tela) mora na home do usuário,
fora da pasta de trabalho que o `AmbienteE2E` isola. Até 04/10/2026 cada
cenário e2e gravava lá: duas rodadas da suíte deixaram 1035 "envios" no dia
em que só uma mensagem de verdade tinha saído desta máquina.

Rodar:
    python -m unittest tests.e2e.test_e2e_historico -v
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

import stats_log
from tests.e2e.ambiente import AmbienteE2E
from tests.e2e import fake_whatsapp as fw


def _assinatura(path):
    return (path.stat().st_size, path.stat().st_mtime_ns) if path.exists() else None


class TestHistoricoIsolado(unittest.TestCase):

    def test_campanha_simulada_nao_toca_o_historico_real(self):
        real = stats_log.STATS_LOG_PATH
        antes = _assinatura(real)
        contatos = [
            {"Nome": f"Pessoa {i}", "Número": f"1999{i:07d}", "Mensagem": "Oi"}
            for i in range(1, 5)
        ]
        with AmbienteE2E(
            contatos=contatos, roteiro={"19990000002": fw.NUMERO_INVALIDO},
        ) as amb:
            amb.configurar()
            amb.iniciar_envio()
            amb.esperar_envio()
            # O histórico continua funcionando — só que no lugar do cenário,
            # e a tela (/stats) lê o mesmo lugar onde o envio gravou.
            stats = amb.cliente.get("/stats").json()
            self.assertEqual(stats["enviados"]["total"], 3)
            self.assertEqual(stats["rejeitados"]["total"], 1)
        self.assertEqual(_assinatura(real), antes,
                         "o e2e escreveu no histórico real da máquina")


if __name__ == "__main__":
    unittest.main()
