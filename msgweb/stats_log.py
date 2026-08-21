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

Fica na home do usuário (mesmo padrão de license.py / LICENSE_CACHE_FILE),
não dentro da pasta do app: o cliente baixa um .exe/zip novo a cada
atualização, numa pasta diferente da anterior (relato de 21/08/2026 — "todo
lançamento de versão nova perde o histórico"). Se o arquivo morasse dentro
da pasta do app (como uploads/ mora), cada atualização começaria um
histórico do zero.
"""

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable

STATS_LOG_PATH = Path(os.path.expanduser("~")) / ".whatsapp_automacao_stats.jsonl"

# Caminho antigo (dentro da pasta do app, versão <= 1.4.4) — migrado
# automaticamente uma única vez por _migrar_local_legado(), para quem já
# tinha histórico acumulado não perder nada na primeira execução com o
# caminho novo.
STATS_LOG_PATH_LEGADO = Path("uploads/envios_stats.jsonl")

TIPO_ENVIADO = "enviado"
TIPO_REJEITADO = "rejeitado"


def _migrar_local_legado(path: Path = STATS_LOG_PATH, legado: Path = STATS_LOG_PATH_LEGADO) -> None:
    """
    Copia o histórico do caminho antigo (dentro da pasta do app) pro novo
    (na home do usuário), uma única vez: só age se o caminho novo ainda não
    existe e o antigo existe. Rodar de novo depois da primeira vez é sempre
    um no-op — não sobrescreve nada que o usuário já acumulou no caminho
    novo. Falha silenciosa (ex.: sem permissão de leitura) não deve impedir
    o app de iniciar; o pior caso é só recomeçar o histórico do zero.
    """
    if path.exists() or not legado.exists():
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(legado.read_bytes())
    except OSError:
        pass


_migrar_local_legado()


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


_MESES_PT = [
    "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
    "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro",
]


def _agrupar_por_mes(eventos: Iterable[tuple[str, str]]) -> list[dict]:
    """
    Agrupa TODO o histórico do log por mês civil (não só o mês corrente —
    esse é o "mes" de _contar_periodo). É o que permite responder "quantas
    mandei em agosto?" depois que setembro já começou: os dados de agosto
    nunca são apagados do log, só saem da contagem "Mês" corrente.

    Retorna do mês mais recente para o mais antigo, um item por mês que
    teve pelo menos um evento (enviado ou rejeitado).
    """
    contagem: dict[tuple[int, int], dict[str, int]] = {}
    for ts, tipo in eventos:
        try:
            d = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S").date()
        except ValueError:
            continue
        chave = (d.year, d.month)
        bucket = contagem.setdefault(chave, {"enviados": 0, "rejeitados": 0})
        if tipo == TIPO_ENVIADO:
            bucket["enviados"] += 1
        elif tipo == TIPO_REJEITADO:
            bucket["rejeitados"] += 1

    resultado = []
    for ano, mes in sorted(contagem.keys(), reverse=True):
        resultado.append({
            "mes": f"{ano:04d}-{mes:02d}",
            "mes_extenso": f"{_MESES_PT[mes - 1]}/{ano}",
            **contagem[(ano, mes)],
        })
    return resultado


def obter_estatisticas(agora: datetime = None, path: Path = STATS_LOG_PATH) -> dict:
    """
    Lê o log persistente e retorna as contagens de enviados/rejeitados por
    período (hoje/semana/mês corrente/total) e o detalhamento mês a mês de
    todo o histórico em "por_mes".
    """
    agora = agora or datetime.now()
    eventos = _ler_eventos(path)
    resultado = contar_eventos(eventos, agora)
    resultado["por_mes"] = _agrupar_por_mes(eventos)
    return resultado
