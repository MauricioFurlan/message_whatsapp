# -*- coding: utf-8 -*-
"""
Testes do histórico persistente de envios (stats_log.py).

Cobre a contagem hoje/semana/mês e a persistência via arquivo (append +
leitura), incluindo o caso de log inexistente e linhas corrompidas.

Rodar:
    python -m unittest tests.test_stats_log -v
"""

import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stats_log import contar_envios, registrar_envio, obter_estatisticas


class TestContarEnvios(unittest.TestCase):
    def test_conta_apenas_hoje(self):
        agora = datetime(2026, 8, 19, 15, 0, 0)  # quarta-feira
        timestamps = [
            "2026-08-19 09:00:00",
            "2026-08-19 10:00:00",
            "2026-08-18 09:00:00",  # ontem
        ]
        counts = contar_envios(timestamps, agora)
        self.assertEqual(counts["hoje"], 2)

    def test_semana_e_segunda_a_domingo_contendo_agora(self):
        # 2026-08-19 é quarta-feira -> semana começa em 2026-08-17 (segunda)
        agora = datetime(2026, 8, 19, 15, 0, 0)
        timestamps = [
            "2026-08-17 08:00:00",  # segunda desta semana
            "2026-08-19 08:00:00",  # hoje
            "2026-08-16 08:00:00",  # domingo da semana anterior
        ]
        counts = contar_envios(timestamps, agora)
        self.assertEqual(counts["semana"], 2)

    def test_mes_conta_o_mes_calendario_inteiro(self):
        agora = datetime(2026, 8, 19, 15, 0, 0)
        timestamps = [
            "2026-08-01 08:00:00",
            "2026-08-31 23:59:59",
            "2026-07-31 08:00:00",  # mês anterior
        ]
        counts = contar_envios(timestamps, agora)
        self.assertEqual(counts["mes"], 2)

    def test_timestamps_invalidos_sao_ignorados(self):
        agora = datetime(2026, 8, 19, 15, 0, 0)
        counts = contar_envios(["não é data", "", "2026-08-19"], agora)
        self.assertEqual(counts, {"hoje": 0, "semana": 0, "mes": 0})

    def test_lista_vazia(self):
        agora = datetime(2026, 8, 19, 15, 0, 0)
        self.assertEqual(contar_envios([], agora), {"hoje": 0, "semana": 0, "mes": 0})


class TestPersistencia(unittest.TestCase):
    def test_registrar_e_ler_de_volta(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sub" / "envios_stats.jsonl"
            registrar_envio("2026-08-19 09:00:00", path=path)
            registrar_envio("2026-08-19 10:00:00", path=path)

            counts = obter_estatisticas(agora=datetime(2026, 8, 19, 15, 0, 0), path=path)
            self.assertEqual(counts["hoje"], 2)

    def test_log_inexistente_retorna_zeros(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nao_existe.jsonl"
            counts = obter_estatisticas(agora=datetime(2026, 8, 19, 15, 0, 0), path=path)
            self.assertEqual(counts, {"hoje": 0, "semana": 0, "mes": 0})

    def test_linha_corrompida_e_ignorada_sem_quebrar_leitura(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "envios_stats.jsonl"
            registrar_envio("2026-08-19 09:00:00", path=path)
            with open(path, "a", encoding="utf-8") as f:
                f.write("isso não é json\n")
            registrar_envio("2026-08-19 10:00:00", path=path)

            counts = obter_estatisticas(agora=datetime(2026, 8, 19, 15, 0, 0), path=path)
            self.assertEqual(counts["hoje"], 2)


if __name__ == "__main__":
    unittest.main()
