"""
Histórico persistente de mensagens enviadas — sem dependência de Selenium.

Existe porque uploads/contatos.xlsx é sobrescrito a cada novo upload (ver
CLAUDE.md, "The Excel file is the only source of truth"): não dá para
responder "quantas mensagens enviei essa semana/mês" olhando só a planilha
atual, já que campanhas antigas não sobrevivem a um novo upload.

Cada envio bem-sucedido acrescenta uma linha JSON em STATS_LOG_PATH
(uma chamada de registrar_envio() por mensagem, feita pelo sender). O
arquivo cresce indefinidamente ao longo do uso normal, o que é aceitável
para o volume esperado de uso local de um único usuário.
"""

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable

STATS_LOG_PATH = Path("uploads/envios_stats.jsonl")


def registrar_envio(timestamp: str, path: Path = STATS_LOG_PATH) -> None:
    """Acrescenta um registro de envio ao log persistente."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": timestamp}) + "\n")


def _ler_timestamps(path: Path) -> list[str]:
    if not path.exists():
        return []
    timestamps = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                timestamps.append(json.loads(line)["ts"])
            except (json.JSONDecodeError, KeyError):
                continue
    return timestamps


def contar_envios(timestamps: Iterable[str], agora: datetime) -> dict:
    """
    Conta timestamps ("%Y-%m-%d %H:%M:%S") por dia/semana/mês corrente,
    relativos a 'agora'. Semana = segunda a domingo (ISO) contendo 'agora'.
    """
    hoje = agora.date()
    inicio_semana = hoje - timedelta(days=hoje.weekday())

    hoje_count = semana_count = mes_count = 0
    for ts in timestamps:
        try:
            d = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S").date()
        except ValueError:
            continue
        if d == hoje:
            hoje_count += 1
        if inicio_semana <= d <= hoje:
            semana_count += 1
        if d.year == hoje.year and d.month == hoje.month:
            mes_count += 1

    return {"hoje": hoje_count, "semana": semana_count, "mes": mes_count}


def obter_estatisticas(agora: datetime = None, path: Path = STATS_LOG_PATH) -> dict:
    """Lê o log persistente e retorna as contagens hoje/semana/mês."""
    agora = agora or datetime.now()
    return contar_envios(_ler_timestamps(path), agora)
