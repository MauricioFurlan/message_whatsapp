# -*- coding: utf-8 -*-
"""
Testes do histórico persistente de envios/rejeitados (stats_log.py).

Cobre a contagem hoje/semana/mês/total por tipo de evento (enviado vs.
rejeitado) e a persistência via arquivo (append + leitura), incluindo o
caso de log inexistente, linhas corrompidas e entradas antigas sem o
campo "tipo" (gravadas antes de rejeitados existirem — tratadas como
"enviado").

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

from stats_log import contar_eventos, registrar_envio, registrar_rejeitado, obter_estatisticas, _agrupar_por_mes


class TestContarEventos(unittest.TestCase):
    def test_separa_enviados_e_rejeitados(self):
        agora = datetime(2026, 8, 19, 15, 0, 0)
        eventos = [
            ("2026-08-19 09:00:00", "enviado"),
            ("2026-08-19 10:00:00", "enviado"),
            ("2026-08-19 11:00:00", "rejeitado"),
        ]
        counts = contar_eventos(eventos, agora)
        self.assertEqual(counts["enviados"]["hoje"], 2)
        self.assertEqual(counts["rejeitados"]["hoje"], 1)

    def test_semana_e_segunda_a_domingo_contendo_agora(self):
        # 2026-08-19 é quarta-feira -> semana começa em 2026-08-17 (segunda)
        agora = datetime(2026, 8, 19, 15, 0, 0)
        eventos = [
            ("2026-08-17 08:00:00", "enviado"),  # segunda desta semana
            ("2026-08-19 08:00:00", "enviado"),  # hoje
            ("2026-08-16 08:00:00", "enviado"),  # domingo da semana anterior
        ]
        counts = contar_eventos(eventos, agora)
        self.assertEqual(counts["enviados"]["semana"], 2)

    def test_mes_conta_o_mes_calendario_inteiro(self):
        agora = datetime(2026, 8, 19, 15, 0, 0)
        eventos = [
            ("2026-08-01 08:00:00", "enviado"),
            ("2026-08-31 23:59:59", "enviado"),
            ("2026-07-31 08:00:00", "enviado"),  # mês anterior
        ]
        counts = contar_eventos(eventos, agora)
        self.assertEqual(counts["enviados"]["mes"], 2)

    def test_total_ignora_data_e_soma_tudo_do_log(self):
        agora = datetime(2026, 8, 19, 15, 0, 0)
        eventos = [
            ("2026-08-19 08:00:00", "enviado"),
            ("2026-01-01 08:00:00", "enviado"),  # bem fora do mês/semana atual
            ("2025-12-31 08:00:00", "enviado"),
        ]
        counts = contar_eventos(eventos, agora)
        self.assertEqual(counts["enviados"]["total"], 3)
        self.assertEqual(counts["enviados"]["mes"], 1)

    def test_timestamps_invalidos_sao_ignorados(self):
        agora = datetime(2026, 8, 19, 15, 0, 0)
        eventos = [("não é data", "enviado"), ("", "enviado"), ("2026-08-19", "enviado")]
        counts = contar_eventos(eventos, agora)
        self.assertEqual(counts["enviados"], {"hoje": 0, "semana": 0, "mes": 0, "total": 0})

    def test_lista_vazia(self):
        agora = datetime(2026, 8, 19, 15, 0, 0)
        counts = contar_eventos([], agora)
        vazio = {"hoje": 0, "semana": 0, "mes": 0, "total": 0}
        self.assertEqual(counts, {"enviados": vazio, "rejeitados": vazio})


class TestAgruparPorMes(unittest.TestCase):
    def test_agrupa_por_mes_civil_separando_enviados_e_rejeitados(self):
        eventos = [
            ("2026-08-05 08:00:00", "enviado"),
            ("2026-08-31 08:00:00", "enviado"),
            ("2026-08-19 08:00:00", "rejeitado"),
            ("2026-09-01 08:00:00", "enviado"),
        ]
        por_mes = _agrupar_por_mes(eventos)
        self.assertEqual(por_mes, [
            {"mes": "2026-09", "mes_extenso": "Setembro/2026", "enviados": 1, "rejeitados": 0},
            {"mes": "2026-08", "mes_extenso": "Agosto/2026", "enviados": 2, "rejeitados": 1},
        ])

    def test_ordem_do_mais_recente_para_o_mais_antigo_mesmo_cruzando_ano(self):
        eventos = [
            ("2025-12-15 08:00:00", "enviado"),
            ("2026-01-05 08:00:00", "enviado"),
            ("2026-08-19 08:00:00", "enviado"),
        ]
        meses = [m["mes"] for m in _agrupar_por_mes(eventos)]
        self.assertEqual(meses, ["2026-08", "2026-01", "2025-12"])

    def test_lista_vazia_nao_gera_meses(self):
        self.assertEqual(_agrupar_por_mes([]), [])

    def test_timestamps_invalidos_sao_ignorados(self):
        eventos = [("não é data", "enviado"), ("2026-08-19 08:00:00", "enviado")]
        por_mes = _agrupar_por_mes(eventos)
        self.assertEqual(len(por_mes), 1)
        self.assertEqual(por_mes[0]["enviados"], 1)

    def test_obter_estatisticas_expoe_por_mes_do_historico_completo(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "envios_stats.jsonl"
            registrar_envio("2026-07-10 09:00:00", path=path)
            registrar_envio("2026-08-19 09:00:00", path=path)

            stats = obter_estatisticas(agora=datetime(2026, 8, 19, 15, 0, 0), path=path)
            # Mês corrente (filtro "mes") só enxerga agosto...
            self.assertEqual(stats["enviados"]["mes"], 1)
            # ...mas o detalhamento por_mes preserva julho, que já saiu do "mes" corrente.
            self.assertEqual(
                [m["mes"] for m in stats["por_mes"]],
                ["2026-08", "2026-07"],
            )


class TestPersistencia(unittest.TestCase):
    def test_registrar_e_ler_de_volta_por_tipo(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sub" / "envios_stats.jsonl"
            registrar_envio("2026-08-19 09:00:00", path=path)
            registrar_envio("2026-08-19 10:00:00", path=path)
            registrar_rejeitado("2026-08-19 11:00:00", path=path)

            counts = obter_estatisticas(agora=datetime(2026, 8, 19, 15, 0, 0), path=path)
            self.assertEqual(counts["enviados"]["hoje"], 2)
            self.assertEqual(counts["rejeitados"]["hoje"], 1)

    def test_entrada_antiga_sem_tipo_e_tratada_como_enviado(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "envios_stats.jsonl"
            with open(path, "w", encoding="utf-8") as f:
                f.write('{"ts": "2026-08-19 09:00:00"}\n')

            counts = obter_estatisticas(agora=datetime(2026, 8, 19, 15, 0, 0), path=path)
            self.assertEqual(counts["enviados"]["hoje"], 1)
            self.assertEqual(counts["rejeitados"]["hoje"], 0)

    def test_log_inexistente_retorna_zeros(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nao_existe.jsonl"
            counts = obter_estatisticas(agora=datetime(2026, 8, 19, 15, 0, 0), path=path)
            vazio = {"hoje": 0, "semana": 0, "mes": 0, "total": 0}
            self.assertEqual(counts, {"enviados": vazio, "rejeitados": vazio, "por_mes": []})

    def test_linha_corrompida_e_ignorada_sem_quebrar_leitura(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "envios_stats.jsonl"
            registrar_envio("2026-08-19 09:00:00", path=path)
            with open(path, "a", encoding="utf-8") as f:
                f.write("isso não é json\n")
            registrar_envio("2026-08-19 10:00:00", path=path)

            counts = obter_estatisticas(agora=datetime(2026, 8, 19, 15, 0, 0), path=path)
            self.assertEqual(counts["enviados"]["hoje"], 2)


if __name__ == "__main__":
    unittest.main()
