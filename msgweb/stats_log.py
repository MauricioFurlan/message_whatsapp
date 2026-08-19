"""
Histórico persistente de mensagens enviadas e rejeitadas — sem dependência
de Selenium.

Existe porque uploads/contatos.xlsx é sobrescrito a cada novo upload (ver
CLAUDE.md, "The Excel file is the only source of truth"): não dá para
responder "quantas mensagens enviei essa semana/mês" olhando só a planilha
atual, já que campanhas antigas não sobrevivem a um novo upload.

Cada envio bem-sucedido e cada contato rejeitado (inválido/bloqueado/falha —
mesma definição de "Inválidos" usada em WhatsAppSender._contar_invalido;
NÃO inclui duplicados, que são uma categoria à parte) acrescenta uma linha
JSON em STATS_LOG_PATH. O arquivo cresce indefinidamente ao longo do uso
normal, o que é aceitável para o volume esperado de uso local de um único
usuário.
"""

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable

STATS_LOG_PATH = Path("uploads/envios_stats.jsonl")

TIPO_ENVIADO = "enviado"
TIPO_REJEITADO = "rejeitado"


def _registrar(timestamp: str, tipo: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": timestamp, "tipo": tipo}) + "\n")


def registrar_envio(timestamp: str, path: Path = STATS_LOG_PATH) -> None:
    """Acrescenta um registro de envio bem-sucedido ao log persistente."""
    _registrar(timestamp, TIPO_ENVIADO, path)


def registrar_rejeitado(timestamp: str, path: Path = STATS_LOG_PATH) -> None:
    """Acrescenta um registro de contato rejeitado (inválido/bloqueado/falha)."""
    _registrar(timestamp, TIPO_REJEITADO, path)


def _ler_eventos(path: Path) -> list[tuple[str, str]]:
    """
    Lê (timestamp, tipo) de cada linha do log. Entradas antigas gravadas
    antes do campo "tipo" existir são tratadas como TIPO_ENVIADO, já que só
    envios eram registrados na época.
    """
    if not path.exists():
        return []
    eventos = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                registro = json.loads(line)
                eventos.append((registro["ts"], registro.get("tipo", TIPO_ENVIADO)))
            except (json.JSONDecodeError, KeyError):
                continue
    return eventos


def _contar_periodo(timestamps: Iterable[str], agora: datetime) -> dict:
    """
    Conta timestamps ("%Y-%m-%d %H:%M:%S") por dia/semana/mês corrente e o
    total geral (todo o período do log), relativos a 'agora'. Semana =
    segunda a domingo (ISO) contendo 'agora'.
    """
    hoje = agora.date()
    inicio_semana = hoje - timedelta(days=hoje.weekday())

    hoje_count = semana_count = mes_count = total_count = 0
    for ts in timestamps:
        try:
            d = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S").date()
        except ValueError:
            continue
        total_count += 1
        if d == hoje:
            hoje_count += 1
        if inicio_semana <= d <= hoje:
            semana_count += 1
        if d.year == hoje.year and d.month == hoje.month:
            mes_count += 1

    return {"hoje": hoje_count, "semana": semana_count, "mes": mes_count, "total": total_count}


def contar_eventos(eventos: Iterable[tuple[str, str]], agora: datetime) -> dict:
    """Separa os eventos por tipo e conta cada um por período (ver _contar_periodo)."""
    enviados = [ts for ts, tipo in eventos if tipo == TIPO_ENVIADO]
    rejeitados = [ts for ts, tipo in eventos if tipo == TIPO_REJEITADO]
    return {
        "enviados": _contar_periodo(enviados, agora),
        "rejeitados": _contar_periodo(rejeitados, agora),
    }


def obter_estatisticas(agora: datetime = None, path: Path = STATS_LOG_PATH) -> dict:
    """Lê o log persistente e retorna as contagens de enviados/rejeitados por período."""
    agora = agora or datetime.now()
    return contar_eventos(_ler_eventos(path), agora)
