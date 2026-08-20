"""
FastAPI backend para automação de envio de mensagens WhatsApp Web.
"""

import asyncio
import json
import logging
import os
import platform
import sys
from dataclasses import dataclass, field
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from threading import Thread
from typing import Optional

import pandas as pd
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import requests as http_requests

from whatsapp_sender import WhatsAppSender
from contact_logic import get_pending_contacts
from license import validar_licenca, ativar_licenca, desativar_licenca, get_cached_key
from version import APP_VERSION
import stats_log
GITHUB_REPO = "MauricioFurlan/message_whatsapp"

# --- File Logger Setup ---
LOG_FILE = Path("log.txt")

file_logger = logging.getLogger("whatsapp_sender_file")
file_logger.setLevel(logging.DEBUG)

# Rotação: max 5MB por arquivo, mantém 2 backups (log.txt, log.txt.1, log.txt.2)
_handler = RotatingFileHandler(
    LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=2, encoding="utf-8"
)
_handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
file_logger.addHandler(_handler)

# Marca início de sessão com informações de diagnóstico
file_logger.info("=" * 70)
file_logger.info("NOVA SESSÃO INICIADA")
file_logger.info(f"Versão: {APP_VERSION}")
file_logger.info(f"Horário: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
file_logger.info(f"Python: {sys.version}")
file_logger.info(f"SO: {platform.system()} {platform.release()} ({platform.machine()})")
file_logger.info(f"Diretório: {os.getcwd()}")
file_logger.info("=" * 70)

app = FastAPI(title="WhatsApp Automação Web")

# Serve static files
app.mount("/static", StaticFiles(directory="static"), name="static")


# --- Models ---

class ConfigModel(BaseModel):
    total_msgs: int = 10
    tempo_minutos: int = 60
    hora_inicio: str = "08:00"
    hora_fim: str = "18:00"
    skip_weekends: bool = True
    human_behavior: bool = True
    allow_duplicates: bool = False


# --- Global State ---

@dataclass
class AppState:
    config: dict = field(default_factory=lambda: {
        "total_msgs": 10,
        "tempo_minutos": 60,
        "hora_inicio": "08:00",
        "hora_fim": "18:00",
        "skip_weekends": True,
        "human_behavior": True,
        "allow_duplicates": False,
    })
    excel_path: Optional[str] = None
    # Procedência da planilha em uso: "upload" (enviada agora), "editor"
    # (salva pela tabela da tela) ou "restaurada" (cópia da sessão anterior).
    # Existe porque o sistema trabalha SEMPRE sobre a cópia uploads/contatos.xlsx:
    # editar o .xlsx original no disco não tem efeito nenhum sem novo upload, e
    # isso já gerou relato de "enviou o nome antigo do contato".
    excel_source: str = ""
    excel_saved_at: str = ""
    sender: Optional[WhatsAppSender] = None
    sender_thread: Optional[Thread] = None
    logs: list = field(default_factory=list)
    sse_queues: list = field(default_factory=list)
    _loop: Optional[asyncio.AbstractEventLoop] = None
    global_message: str = ""
    global_message_active: bool = False


state = AppState()


def _file_timestamp(path) -> str:
    """Data/hora da última gravação do arquivo, formatada, ou '' se não existir."""
    try:
        return datetime.fromtimestamp(Path(path).stat().st_mtime).strftime("%d/%m/%Y %H:%M")
    except Exception:
        return ""


def _set_excel_source(origem: str, path) -> None:
    """Registra de onde veio a planilha em uso e quando ela foi gravada."""
    state.excel_source = origem
    state.excel_saved_at = _file_timestamp(path)


def _count_contacts(df: pd.DataFrame) -> tuple[int, int, int, int]:
    """
    Retorna (total, pendentes, enviados, invalidos, duplicados) a partir do DataFrame.
    Duplicados (Invalido=X com Motivo contendo 'duplicado') são contados separadamente
    e NÃO entram na contagem de inválidos.
    """
    total = len(df)
    enviados = int((df.get("Enviado", pd.Series(dtype=str)).str.strip().str.upper() == "X").sum())
    invalidos_mask = df.get("Invalido", pd.Series(dtype=str)).str.strip().str.upper() == "X"
    duplicados_mask = invalidos_mask & df.get("Motivo", pd.Series(dtype=str)).str.lower().str.contains("duplicado", na=False)
    invalidos = int((invalidos_mask & ~duplicados_mask).sum())
    duplicados = int(duplicados_mask.sum())
    pendentes = total - enviados - invalidos - duplicados
    return total, pendentes, enviados, invalidos, duplicados


def get_excel_info() -> dict:
    """Procedência da planilha em uso, para a tela avisar o usuário."""
    return {
        "origem": state.excel_source,
        "atualizado_em": state.excel_saved_at,
        "arquivo": state.excel_path or "",
    }


@app.on_event("startup")
async def startup_event():
    """Captura o event loop principal do asyncio e restaura estado."""
    state._loop = asyncio.get_event_loop()
    # Se o path já foi definido via CLI (--planilha), respeita essa escolha
    if state.excel_path and state.excel_source == "cli":
        p = Path(state.excel_path)
        if p.exists():
            add_log(f"Planilha carregada via CLI: {state.excel_path}")
        else:
            add_log(f"AVISO: planilha informada via CLI não encontrada: {state.excel_path}")
        return
    # Restaura planilha se já existia (sobrevive a reloads)
    upload_path = Path("uploads/contatos.xlsx")
    if upload_path.exists():
        state.excel_path = str(upload_path)
        _set_excel_source("restaurada", upload_path)
        add_log(
            f"Planilha restaurada da sessão anterior (gravada em {state.excel_saved_at}). "
            "Atenção: o sistema usa esta cópia — alterações feitas no arquivo .xlsx "
            "original só valem depois de um novo upload."
        )


@app.on_event("shutdown")
async def shutdown_event():
    """Para o sender e fecha o Chrome ao encerrar o servidor."""
    file_logger.info("Servidor encerrando...")
    if state.sender and state.sender.is_running():
        state.sender.stop()
        # Espera no máximo 5s para a thread encerrar
        if state.sender_thread and state.sender_thread.is_alive():
            state.sender_thread.join(timeout=5)
    # Força cleanup do driver se ainda existir
    if state.sender and state.sender._driver:
        try:
            state.sender._driver.quit()
        except Exception:
            pass
    file_logger.info("Sessão encerrada.")
    file_logger.info("=" * 70)


def add_log(message: str):
    """Adiciona mensagem ao log em memória, SSE, e arquivo de diagnóstico."""
    timestamp = datetime.now().strftime("%H:%M:%S")
    entry = f"[{timestamp}] {message}"
    state.logs.append(entry)
    # Mantém apenas os últimos 500 logs
    if len(state.logs) > 500:
        state.logs = state.logs[-500:]
    # Grava no arquivo de log para diagnóstico remoto
    file_logger.info(message)
    # Notifica clientes SSE
    _broadcast_event("log", entry)


def _broadcast_event(event_type: str, data: str):
    """Envia evento para todos os clientes SSE conectados (thread-safe)."""
    loop = state._loop
    if loop is None:
        return
    for q in state.sse_queues[:]:
        try:
            loop.call_soon_threadsafe(q.put_nowait, {"event": event_type, "data": data})
        except Exception:
            pass


def broadcast_contact_update(row_index: int, numero: str, status: str, data_envio: str = "", motivo: str = ""):
    """
    Emite um evento SSE para atualizar o status de um contato na tabela do frontend.

    O contato é identificado por row_index (índice da linha na planilha, 0 = primeira
    linha de dados). O número segue no payload apenas para conferência no frontend —
    identificar por número marcava todas as linhas com o mesmo telefone, e marcava
    a tabela inteira quando o número era vazio.

    motivo: texto explicando por que foi marcado como inválido (tooltip no badge).
    """
    import json as _json
    payload = _json.dumps(
        {"row_index": int(row_index), "numero": numero, "status": status, "data_envio": data_envio, "motivo": motivo},
        ensure_ascii=False,
    )
    _broadcast_event("contact_update", payload)


def get_status_dict() -> dict:
    """Retorna o status atual como dicionário."""
    if state.sender:
        sender_status = state.sender.get_status()
    else:
        sender_status = {
            "state": "aguardando",
            "current_round": 0,
            "messages_sent": 0,
            "total_pending": 0,
            "total_contacts": 0,
            "total_invalids": 0,
            "invalid_motivos": {},
            "session_target": 0,
            "pause_until": None,
            "next_leva_size": None,
            "elapsed_seconds": None,
        }

    return {
        "state": sender_status["state"],
        "current_round": sender_status["current_round"],
        "messages_sent": sender_status["messages_sent"],
        "total_pending": sender_status["total_pending"],
        "total_contacts": sender_status["total_contacts"],
        "total_invalids": sender_status.get("total_invalids", 0),
        # Detalhamento dos inválidos DESTA sessão ({motivo: quantidade}).
        # O frontend agrupa esses motivos em categorias para o tooltip.
        "invalid_motivos": sender_status.get("invalid_motivos", {}),
        # Quantas mensagens este envio pretende mandar (o "5" que o usuário pediu).
        "session_target": sender_status.get("session_target", 0),
        # Timestamp (epoch) de quando a leva atual retoma — só setado durante
        # "pausado", usado pelo painel para a contagem regressiva precisa.
        "pause_until": sender_status.get("pause_until"),
        # Tamanho planejado da próxima leva — evita o usuário achar que todo
        # o "restante" sai de uma vez na próxima leva.
        "next_leva_size": sender_status.get("next_leva_size"),
        # Duração real do envio (do primeiro ao último contato), apurada só
        # ao concluir com sucesso — o painel mostra em "Finalizado".
        "elapsed_seconds": sender_status.get("elapsed_seconds"),
        "config": state.config,
        "excel_loaded": state.excel_path is not None,
        "excel_info": get_excel_info(),
        "logs": state.logs[-200:],
    }


# --- Endpoints ---

@app.get("/", response_class=HTMLResponse)
async def serve_frontend():
    """Serve a página HTML principal."""
    html_path = Path("static/index.html")
    return FileResponse(html_path)


# --- Licença ---

class LicenseActivateModel(BaseModel):
    chave: str


@app.get("/license/status")
async def license_status():
    """Verifica o status da licença atual."""
    result = validar_licenca()
    return result


@app.post("/license/activate")
async def license_activate(payload: LicenseActivateModel):
    """Ativa uma licença com a chave fornecida."""
    result = ativar_licenca(payload.chave)
    return result


@app.post("/license/deactivate")
async def license_deactivate():
    """Remove a licença desta máquina."""
    result = desativar_licenca()
    return result


# --- Atualização ---

def _parse_version(v: str) -> tuple:
    """
    Converte "1.10.2" em (1, 10, 2) para comparação numérica.

    Comparar versões como texto está errado: "1.10.0" > "1.9.0" é False porque
    "1" vem antes de "9" na ordem alfabética. Isso faria o aviso de atualização
    parar de funcionar a partir da 1.10.

    Tolerante a formatos comuns: "1.4" -> (1, 4, 0), "1.4.0-beta" -> (1, 4, 0),
    espaços e prefixo "v" já removidos pelo chamador. Segmentos não numéricos
    são ignorados. Retorna () se nada puder ser lido, o que faz o chamador
    tratar como "sem atualização" em vez de comparar lixo.
    """
    numeros = []
    for parte in str(v).strip().split("."):
        # Corta sufixos como "-beta", "rc1": mantém só os dígitos iniciais
        digitos = ""
        for ch in parte:
            if ch.isdigit():
                digitos += ch
            else:
                break
        if not digitos:
            break
        numeros.append(int(digitos))

    if not numeros:
        return ()

    # Normaliza para 3 posições: (1, 4) e (1, 4, 0) devem ser equivalentes
    while len(numeros) < 3:
        numeros.append(0)
    return tuple(numeros[:3])


def _fetch_latest_release():
    """Busca última release do GitHub (roda em thread para não bloquear o event loop)."""
    resp = http_requests.get(
        f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest",
        timeout=10,
        headers={"Accept": "application/vnd.github.v3+json"},
    )
    return resp


@app.get("/check-update")
async def check_update():
    """Verifica se há nova versão disponível no GitHub Releases."""
    try:
        loop = asyncio.get_event_loop()
        resp = await loop.run_in_executor(None, _fetch_latest_release)
        if resp.status_code == 404:
            return {"update_available": False, "current_version": APP_VERSION}
        resp.raise_for_status()
        data = resp.json()
        latest_tag = data.get("tag_name", "").lstrip("v")
        download_url = ""
        for asset in data.get("assets", []):
            if asset["name"].endswith(".zip"):
                download_url = asset["browser_download_url"]
                break
        update_available = False
        if latest_tag:
            v_latest = _parse_version(latest_tag)
            v_atual = _parse_version(APP_VERSION)
            # Só compara se as duas versões foram lidas com sucesso; formato
            # inesperado no tag do GitHub não deve gerar aviso falso.
            if v_latest and v_atual:
                update_available = v_latest > v_atual
        return {
            "update_available": update_available,
            "current_version": APP_VERSION,
            "latest_version": latest_tag,
            "download_url": download_url,
            "changelog": data.get("body", ""),
        }
    except Exception:
        return {"update_available": False, "current_version": APP_VERSION}


@app.get("/version")
async def get_version():
    """Retorna a versão atual do app."""
    return {"version": APP_VERSION}


@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    """Upload da planilha Excel com contatos."""
    if not file.filename.endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="Arquivo deve ser .xlsx ou .xls")

    # Salva em arquivo temporário para validar antes de sobrescrever o anterior
    upload_dir = Path("uploads")
    upload_dir.mkdir(exist_ok=True)
    file_path = upload_dir / "contatos.xlsx"
    temp_path = upload_dir / "contatos_temp.xlsx"

    with open(temp_path, "wb") as f:
        content = await file.read()
        f.write(content)

    # Valida colunas
    try:
        df = pd.read_excel(temp_path)
        required_cols = ["Nome", "Número", "Mensagem"]
        missing = [col for col in required_cols if col not in df.columns]
        if missing:
            os.remove(temp_path)
            raise HTTPException(
                status_code=400,
                detail=f"Colunas obrigatórias faltando: {', '.join(missing)}"
            )

        # Adiciona colunas de controle se não existirem
        for col in ["Enviado", "DataEnvio", "Invalido", "Arquivo", "Motivo"]:
            if col not in df.columns:
                df[col] = ""
            else:
                if col == "Arquivo":
                    df[col] = df[col].fillna("").astype(str).str.strip()
                elif col == "Motivo":
                    df[col] = df[col].fillna("").astype(str).str.strip()
                else:
                    df[col] = df[col].fillna("").astype(str).str.strip().str.upper()

        # --- Deduplicação automática ---
        # Normaliza números (mesma lógica de _clean_number em whatsapp_sender.py)
        def _normalize_numero(numero) -> str:
            numero_str = str(numero).strip()
            if numero_str.lower() in ("", "nan", "none"):
                return ""
            try:
                f = float(numero_str)
                if f.is_integer():
                    numero_str = str(int(f))
            except (ValueError, OverflowError):
                pass
            digits = "".join(c for c in numero_str if c.isdigit())
            # Remove código de país 55 se o usuário incluiu na planilha
            # Número brasileiro válido tem 10-11 dígitos (DDD + telefone)
            if len(digits) > 11 and digits.startswith("55"):
                digits = digits[2:]
            return digits

        df["_numero_normalizado"] = df["Número"].apply(_normalize_numero)

        # Contatos já enviados não devem ser removidos como duplicatas
        duplicatas_removidas = 0
        numeros_vistos = set()
        indices_para_remover = []

        for idx, row in df.iterrows():
            num_norm = row["_numero_normalizado"]
            if not num_norm:
                continue
            # Contatos já marcados como Enviado='X' são preservados sempre
            if row["Enviado"] == "X":
                numeros_vistos.add(num_norm)
                continue
            if num_norm in numeros_vistos:
                indices_para_remover.append(idx)
                duplicatas_removidas += 1
            else:
                numeros_vistos.add(num_norm)

        if duplicatas_removidas > 0:
            df = df.drop(indices_para_remover).reset_index(drop=True)
            add_log(f"Deduplicação: {duplicatas_removidas} número(s) duplicado(s) removido(s)")

        df = df.drop(columns=["_numero_normalizado"])
        # --- Fim deduplicação ---

        # Validação OK — salva no destino definitivo (sobrescreve o anterior)
        df.to_excel(file_path, index=False)
        # Remove o temporário se ainda existir
        if temp_path.exists():
            os.remove(temp_path)
        state.excel_path = str(file_path)
        _set_excel_source("upload", file_path)

        total = len(df)
        enviados = len(df[df["Enviado"] == "X"])
        invalidos = len(df[df["Invalido"] == "X"])
        pendentes = total - enviados - invalidos

        add_log(f"Planilha carregada: {total} contatos ({pendentes} pendentes, {enviados} enviados, {invalidos} inválidos)")

        return {
            "status": "ok",
            "total": total,
            "pendentes": pendentes,
            "enviados": enviados,
            "invalidos": invalidos,
            "duplicatas_removidas": duplicatas_removidas,
        }
    except HTTPException:
        # Limpa temporário em caso de erro de validação
        if temp_path.exists():
            os.remove(temp_path)
        raise
    except Exception as e:
        # Limpa temporário em caso de erro inesperado
        if temp_path.exists():
            os.remove(temp_path)
        raise HTTPException(status_code=400, detail=f"Erro ao ler planilha: {str(e)}")


@app.post("/config")
async def set_config(config: ConfigModel):
    """Atualiza configuração de envio. Recebe parâmetros simplificados do usuário."""
    state.config = {
        # Parâmetros do usuário (para restaurar na tela e para o sender)
        "total_msgs": config.total_msgs,
        "tempo_minutos": config.tempo_minutos,
        "hora_inicio": config.hora_inicio,
        "hora_fim": config.hora_fim,
        "skip_weekends": config.skip_weekends,
        "human_behavior": config.human_behavior,
        "allow_duplicates": config.allow_duplicates,
    }

    add_log(
        f"Configuração atualizada: {config.total_msgs} msgs em {config.tempo_minutos}min, "
        f"horário {config.hora_inicio}h-{config.hora_fim}h"
    )
    return {"status": "ok", "config": state.config}


# --- Mensagem Global ---

class GlobalMessageModel(BaseModel):
    mensagem: str = ""
    ativa: bool = False


@app.get("/global-message")
async def get_global_message():
    """Retorna a mensagem global atual."""
    return {"status": "ok", "mensagem": state.global_message, "ativa": state.global_message_active}


@app.post("/global-message")
async def set_global_message(payload: GlobalMessageModel):
    """Salva a mensagem global."""
    state.global_message = payload.mensagem
    state.global_message_active = payload.ativa
    if payload.ativa and payload.mensagem.strip():
        add_log(f"Mensagem global ativada ({len(payload.mensagem)} caracteres)")
    elif not payload.ativa:
        add_log("Mensagem global desativada")
    else:
        add_log("Mensagem global salva (vazia)")
    return {"status": "ok"}


@app.get("/estimate")
async def estimate_time(total_msgs: int = 0, tempo_minutos: int = 0):
    """
    Prévia do tempo real de envio para o painel, ANTES de clicar em "Iniciar
    Envio". Reaproveita a mesma conta que o sender faz de verdade em
    start() (_calcular_orcamento_de_pausas) — inclui o tempo real de
    digitação/anexos, não só o piso de 15s entre mensagens — para que o
    aviso na tela bata com o que o log mostraria depois de iniciado.

    Só lê a planilha (via _load_contacts, que não grava nada); não abre
    navegador, não deduplica/marca nada e não altera o arquivo.
    """
    if not state.excel_path or not os.path.exists(state.excel_path):
        return {"status": "sem_planilha"}
    if total_msgs <= 0 or tempo_minutos <= 0:
        return {"status": "ok", "session_target": 0, "inviavel": False}

    sender = WhatsAppSender(excel_path=state.excel_path, config=state.config)
    df = sender._load_contacts()
    pending = get_pending_contacts(df)
    session_target = min(total_msgs, len(pending))

    if session_target <= 1:
        return {"status": "ok", "session_target": session_target, "pendentes": len(pending), "inviavel": False}

    orcamento = sender._calcular_orcamento_de_pausas(pending, session_target, tempo_minutos)
    # Espelha o que _generate_burst_plan faz na prática: quando não sobra
    # orçamento pra pausa real, o ritmo cai pro piso de segurança em vez de
    # zerar — então o tempo real nunca fica abaixo disso.
    piso_pausas_seg = (session_target - 1) * WhatsAppSender.DELAY_INTRA_MIN
    tempo_total_estimado_seg = orcamento["tempo_de_envio_seg"] + max(orcamento["tempo_pausas_seg"], piso_pausas_seg)

    return {
        "status": "ok",
        "session_target": session_target,
        "pendentes": len(pending),
        "inviavel": orcamento["inviavel"],
        "tempo_configurado_seg": tempo_minutos * 60,
        "tempo_de_envio_seg": round(orcamento["tempo_de_envio_seg"]),
        "tempo_total_estimado_seg": round(tempo_total_estimado_seg),
        "tempo_total_estimado_fmt": WhatsAppSender._fmt_duracao(tempo_total_estimado_seg),
    }


@app.post("/start")
async def start_sending():
    """Inicia o envio de mensagens."""
    # Verifica licença antes de iniciar
    license_check = validar_licenca()
    if not license_check.get("valida"):
        raise HTTPException(status_code=403, detail="Licença inválida ou expirada. Ative uma licença para usar o sistema.")

    if not state.excel_path:
        raise HTTPException(status_code=400, detail="Nenhuma planilha carregada. Faça upload primeiro.")

    if state.sender and state.sender.is_running():
        raise HTTPException(status_code=400, detail="Envio já está em andamento.")

    # Log de diagnóstico: configurações usadas neste envio
    file_logger.info("-" * 40)
    file_logger.info("INÍCIO DE ENVIO — Configurações:")
    for key, value in state.config.items():
        file_logger.info(f"  {key}: {value}")
    file_logger.info(f"  Planilha: {state.excel_path}")
    file_logger.info(
        f"  Procedência da planilha: {state.excel_source or 'desconhecida'} "
        f"(gravada em {state.excel_saved_at or 'n/d'})"
    )
    file_logger.info(
        f"  Mensagem global: {'ATIVA' if state.global_message_active and state.global_message.strip() else 'inativa'}"
    )

    # Mesmas informações no log da tela: são as três perguntas que sempre
    # aparecem quando o cliente relata comportamento inesperado.
    add_log(
        f"Comportamento humano: {'ON (digitação simulada)' if state.config.get('human_behavior') else 'OFF (mensagem enviada de uma vez)'}"
        f" | Mensagem global: {'ATIVA' if state.global_message_active and state.global_message.strip() else 'inativa'}"
        f" | Planilha: {state.excel_source or 'desconhecida'} de {state.excel_saved_at or 'n/d'}"
    )

    # Log contagem da planilha
    try:
        df = pd.read_excel(state.excel_path)
        total = len(df)
        for col in ["Enviado", "Invalido"]:
            if col not in df.columns:
                df[col] = ""
            else:
                df[col] = df[col].fillna("").astype(str).str.strip().str.upper()
        enviados = len(df[df["Enviado"] == "X"])
        invalidos = len(df[df["Invalido"] == "X"])
        pendentes = total - enviados - invalidos
        file_logger.info(f"  Contatos: {total} total, {pendentes} pendentes, {enviados} enviados, {invalidos} inválidos")
    except Exception as e:
        file_logger.warning(f"  Não foi possível ler planilha para log: {e}")

    file_logger.info("-" * 40)

    # Cria o sender
    state.sender = WhatsAppSender(
        excel_path=state.excel_path,
        config=state.config,
        log_callback=add_log,
        contact_update_callback=broadcast_contact_update,
        global_message=state.global_message if state.global_message_active else "",
    )

    # Seta estado como "iniciando" imediatamente para que o frontend saiba que está rodando
    state.sender._set_state("iniciando")

    # Inicia em thread separada
    state.sender_thread = Thread(target=state.sender.start, daemon=True)
    state.sender_thread.start()

    add_log("Envio iniciado. Abrindo navegador...")
    return {"status": "ok", "message": "Envio iniciado"}


@app.post("/stop")
async def stop_sending():
    """Para o envio de mensagens."""
    if not state.sender or not state.sender.is_running():
        raise HTTPException(status_code=400, detail="Nenhum envio em andamento.")

    state.sender.stop()
    add_log("Solicitação de parada enviada. Aguardando finalização...")
    return {"status": "ok", "message": "Parada solicitada"}


@app.get("/status")
async def get_status():
    """Retorna o status atual do sistema."""
    return get_status_dict()


@app.get("/stats")
async def get_stats():
    """Retorna o total de mensagens enviadas/rejeitadas por período (histórico persistente)."""
    return stats_log.obter_estatisticas()


def _fmt_stats_bloco(titulo: str, periodo: dict) -> str:
    return (
        f"{titulo}\n"
        f"  Hoje:                    {periodo['hoje']}\n"
        f"  Semana:                  {periodo['semana']}\n"
        f"  Mês:                     {periodo['mes']}\n"
        f"  Total (todo o período):  {periodo['total']}\n"
    )


def _fmt_stats_por_mes(por_mes: list) -> str:
    if not por_mes:
        return ""
    linhas = "\n".join(
        f"  {m['mes_extenso']:<16} enviadas {m['enviados']:>5}   rejeitadas {m['rejeitados']:>5}"
        for m in por_mes
    )
    return f"Histórico por mês (todo o período, mais recente primeiro)\n{linhas}\n"


@app.get("/stats/download")
async def download_stats():
    """Baixa um .txt com o total de mensagens enviadas e rejeitadas por período."""
    stats = stats_log.obter_estatisticas()
    conteudo = (
        "Histórico de envios — WhatsApp Automação\n"
        f"Gerado em: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}\n\n"
        f"{_fmt_stats_bloco('Mensagens enviadas', stats['enviados'])}\n"
        f"{_fmt_stats_bloco('Mensagens rejeitadas', stats['rejeitados'])}\n"
        f"{_fmt_stats_por_mes(stats['por_mes'])}"
    )
    return Response(
        content=conteudo,
        media_type="text/plain; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="historico_envios_{datetime.now().strftime("%Y%m%d_%H%M%S")}.txt"'
        },
    )


@app.get("/contacts")
async def get_contacts():
    """Retorna os contatos da planilha para visualização/edição."""
    if not state.excel_path or not Path(state.excel_path).exists():
        raise HTTPException(status_code=404, detail="Nenhuma planilha carregada.")

    try:
        df = pd.read_excel(state.excel_path)
        # Garante colunas de controle
        for col in ["Enviado", "DataEnvio", "Invalido", "Arquivo", "Motivo"]:
            if col not in df.columns:
                df[col] = ""
            else:
                df[col] = df[col].fillna("").astype(str).str.strip()

        # Normaliza campos principais como string
        for col in ["Nome", "Número", "Mensagem"]:
            if col in df.columns:
                df[col] = df[col].fillna("").astype(str)

        def _safe_numero_str(val) -> str:
            """Remove .0 de floats para evitar zero fantasma no final."""
            s = str(val).strip()
            if s.lower() in ("", "nan", "none"):
                return ""
            try:
                f = float(s)
                if f.is_integer():
                    return str(int(f))
            except (ValueError, OverflowError):
                pass
            return s

        contacts = []
        for _, row in df.iterrows():
            contacts.append({
                "pessoa": str(row.get("Nome", "")),
                "numero": _safe_numero_str(row.get("Número", "")),
                "mensagem": str(row.get("Mensagem", "")),
                "arquivo": str(row.get("Arquivo", "")),
                "enviado": str(row.get("Enviado", "")).strip().upper() == "X",
                "invalido": str(row.get("Invalido", "")).strip().upper() == "X",
                "data_envio": str(row.get("DataEnvio", "")),
                "motivo": str(row.get("Motivo", "")),
            })

        # --- Detecção de duplicados ---
        # Só marca duplicados visualmente se allow_duplicates está desativado
        allow_duplicates = state.config.get("allow_duplicates", False)
        if not allow_duplicates:
            # Normaliza números para detectar duplicatas (mesma lógica de _clean_number)
            def _normalize_for_dup(numero_str: str) -> str:
                s = numero_str.strip()
                if s.lower() in ("", "nan", "none"):
                    return ""
                try:
                    f = float(s)
                    if f.is_integer():
                        s = str(int(f))
                except (ValueError, OverflowError):
                    pass
                digits = "".join(c for c in s if c.isdigit())
                if len(digits) > 11 and digits.startswith("55"):
                    digits = digits[2:]
                return digits

            # Mapeia número normalizado -> índice da primeira ocorrência
            numeros_vistos: dict[str, int] = {}
            for i, contact in enumerate(contacts):
                num_norm = _normalize_for_dup(contact["numero"])
                if not num_norm:
                    contact["duplicado"] = False
                    continue
                if num_norm in numeros_vistos:
                    first_idx = numeros_vistos[num_norm]
                    first_nome = contacts[first_idx]["pessoa"] or f"linha {first_idx + 1}"
                    contact["duplicado"] = True
                    contact["motivo_duplicado"] = f"Número duplicado (mesmo que {first_nome}, linha {first_idx + 1})"
                    # Se o sender gravou Invalido=X por duplicata, limpa visualmente:
                    # o frontend trata duplicados como categoria própria, não como inválido
                    if contact["invalido"] and "duplicado" in contact["motivo"].lower():
                        contact["invalido"] = False
                        contact["motivo"] = ""
                else:
                    numeros_vistos[num_norm] = i
                    contact["duplicado"] = False
        else:
            # Modo teste: não marca duplicados
            for contact in contacts:
                contact["duplicado"] = False

        return {"status": "ok", "contacts": contacts}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Erro ao ler planilha: {str(e)}")


class ContactModel(BaseModel):
    pessoa: str = ""
    numero: str = ""
    mensagem: str = ""
    arquivo: str = ""
    enviado: bool = False
    invalido: bool = False
    data_envio: str = ""
    motivo: str = ""


class ContactsPayload(BaseModel):
    contacts: list[ContactModel]


@app.post("/contacts")
async def save_contacts(payload: ContactsPayload):
    """Salva os contatos editados na planilha."""
    if state.sender and state.sender.is_running():
        raise HTTPException(
            status_code=400,
            detail="Não é possível editar contatos durante o envio."
        )

    # Filtra linhas totalmente vazias (sem nome e sem número)
    valid_contacts = [
        c for c in payload.contacts
        if c.pessoa.strip() or c.numero.strip()
    ]

    if not valid_contacts:
        raise HTTPException(status_code=400, detail="Nenhum contato válido para salvar.")

    # Monta o DataFrame preservando as colunas de controle
    rows = []
    for c in valid_contacts:
        rows.append({
            "Nome": c.pessoa.strip(),
            "Número": c.numero.strip(),
            "Mensagem": c.mensagem.strip(),
            "Arquivo": c.arquivo.strip(),
            "Enviado": "X" if c.enviado else "",
            "DataEnvio": c.data_envio.strip(),
            "Invalido": "X" if c.invalido else "",
            "Motivo": c.motivo.strip(),
        })

    df = pd.DataFrame(rows, columns=["Nome", "Número", "Mensagem", "Arquivo", "Enviado", "DataEnvio", "Invalido", "Motivo"])

    upload_dir = Path("uploads")
    upload_dir.mkdir(exist_ok=True)
    file_path = upload_dir / "contatos.xlsx"
    df.to_excel(file_path, index=False)
    state.excel_path = str(file_path)
    _set_excel_source("editor", file_path)

    total = len(df)
    enviados = len(df[df["Enviado"] == "X"])
    invalidos = len(df[df["Invalido"] == "X"])
    pendentes = total - enviados - invalidos

    add_log(f"Contatos atualizados via editor: {total} contatos ({pendentes} pendentes, {enviados} enviados, {invalidos} inválidos)")

    return {
        "status": "ok",
        "total": total,
        "pendentes": pendentes,
        "enviados": enviados,
        "invalidos": invalidos,
    }


@app.get("/download-contacts")
async def download_contacts():
    """Baixa a planilha de contatos atualizada."""
    if not state.excel_path or not Path(state.excel_path).exists():
        raise HTTPException(status_code=404, detail="Nenhuma planilha carregada.")
    return FileResponse(
        state.excel_path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=f"contatos_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
    )


@app.get("/download-log")
async def download_log():
    """Baixa o arquivo de log para diagnóstico."""
    if not LOG_FILE.exists():
        raise HTTPException(status_code=404, detail="Arquivo de log não encontrado.")
    return FileResponse(
        LOG_FILE,
        media_type="text/plain",
        filename=f"log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
    )


# --- Media Endpoints ---

@app.post("/upload-media")
async def upload_media(file: UploadFile = File(...)):
    """Upload de arquivo de mídia (imagem ou PDF) para envio junto com mensagens."""
    allowed_extensions = (".jpg", ".jpeg", ".png", ".pdf", ".mp3", ".ogg", ".opus")
    filename_lower = file.filename.lower() if file.filename else ""
    if not filename_lower.endswith(allowed_extensions):
        raise HTTPException(
            status_code=400,
            detail="Arquivo deve ser .jpg, .jpeg, .png, .pdf, .mp3, .ogg ou .opus"
        )

    # Usa SOMENTE o nome final do arquivo. Antes o nome vindo do cliente era
    # concatenado direto no caminho, então algo como "../../qualquer.png"
    # gravava fora de uploads/media (a checagem de extensão não impedia isso).
    nome_seguro = Path(file.filename).name
    if not nome_seguro or nome_seguro in (".", ".."):
        raise HTTPException(status_code=400, detail="Nome de arquivo inválido.")

    media_dir = Path("uploads/media")
    media_dir.mkdir(parents=True, exist_ok=True)
    file_path = media_dir / nome_seguro

    # Confirma que o destino ficou dentro de uploads/media
    if media_dir.resolve() not in file_path.resolve().parents:
        raise HTTPException(status_code=400, detail="Nome de arquivo inválido.")

    with open(file_path, "wb") as f:
        content = await file.read()
        f.write(content)

    add_log(f"Mídia carregada: {nome_seguro}")
    return {
        "status": "ok",
        "filename": nome_seguro,
        "path": str(file_path.resolve()),
    }


@app.get("/media-files")
async def list_media_files():
    """Lista arquivos de mídia disponíveis em uploads/media/."""
    media_dir = Path("uploads/media")
    if not media_dir.exists():
        return {"status": "ok", "files": []}

    allowed_extensions = (".jpg", ".jpeg", ".png", ".pdf", ".mp3", ".ogg", ".opus")
    files = []
    for f in media_dir.iterdir():
        if f.is_file() and f.name.lower().endswith(allowed_extensions):
            files.append({
                "filename": f.name,
                "path": str(f.resolve()),
                "size": f.stat().st_size,
            })

    return {"status": "ok", "files": files}


@app.delete("/media/{filename}")
async def delete_media(filename: str):
    """Remove um arquivo de mídia."""
    media_dir = Path("uploads/media")
    file_path = media_dir / filename

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Arquivo não encontrado.")

    # Segurança: garante que o path está dentro de uploads/media
    try:
        file_path.resolve().relative_to(media_dir.resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail="Caminho inválido.")

    os.remove(file_path)
    add_log(f"Mídia removida: {filename}")

    return {"status": "ok", "message": f"Arquivo {filename} removido."}


@app.get("/session-status")
async def session_status():
    """Verifica se existe sessão salva do WhatsApp (sem abrir o Chrome)."""
    profile_dir = Path("chrome_profile")
    if profile_dir.exists() and any(profile_dir.iterdir()):
        # Encontra o timestamp do arquivo mais recente no perfil
        latest_mtime = max(
            f.stat().st_mtime
            for f in profile_dir.rglob("*")
            if f.is_file()
        )
        last_used = datetime.fromtimestamp(latest_mtime).strftime("%Y-%m-%d %H:%M:%S")
        return {"logged_in": True, "last_used": last_used}
    return {"logged_in": False, "last_used": None}


@app.get("/events")
async def sse_events():
    """Server-Sent Events para atualizações em tempo real."""

    async def event_generator():
        queue = asyncio.Queue()
        state.sse_queues.append(queue)
        try:
            # Envia status inicial
            status = get_status_dict()
            yield f"event: status\ndata: {json.dumps(status, ensure_ascii=False)}\n\n"

            while True:
                try:
                    # Espera por novos eventos com timeout para manter conexão viva
                    event = await asyncio.wait_for(queue.get(), timeout=5.0)
                    yield f"event: {event['event']}\ndata: {event['data']}\n\n"
                except asyncio.TimeoutError:
                    # Envia heartbeat e status atualizado
                    status = get_status_dict()
                    yield f"event: status\ndata: {json.dumps(status, ensure_ascii=False)}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            if queue in state.sse_queues:
                state.sse_queues.remove(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


if __name__ == "__main__":
    import argparse
    import signal
    import sys
    import asyncio
    from hypercorn.config import Config
    from hypercorn.asyncio import serve

    parser = argparse.ArgumentParser(description="WhatsApp Automação Web")
    parser.add_argument(
        "--planilha",
        default="uploads/contatos.xlsx",
        help="Caminho para a planilha de contatos (default: uploads/contatos.xlsx)",
    )
    args = parser.parse_args()

    # Aplica o caminho da planilha informado via CLI
    path = args.planilha
    if path == 'test':
        path = 'uploads/test_contatos.xlsx'
    _cli_planilha = Path(path)
    if _cli_planilha.exists():
        state.excel_path = str(_cli_planilha)
        _set_excel_source("cli", _cli_planilha)
    else:
        print(f"AVISO: planilha '{args.planilha}' não encontrada. Será usada quando disponível.")
        state.excel_path = str(_cli_planilha)

    print(f"Planilha: {args.planilha}")
    print('Acesse: http://localhost:8000')

    # Evento que sinaliza shutdown para o Hypercorn
    _shutdown_event = asyncio.Event()

    def _signal_handler(sig, frame):
        """Primeiro CTRL+C: sinaliza shutdown gracioso. Segundo: força saída."""
        if _shutdown_event.is_set():
            # Segundo CTRL+C — força encerramento imediato
            print("\nForçando encerramento...")
            if state.sender and hasattr(state.sender, '_driver') and state.sender._driver:
                try:
                    state.sender._driver.quit()
                except Exception:
                    pass
            os._exit(0)
        else:
            print("\nEncerrando servidor... (CTRL+C novamente para forçar)")
            _shutdown_event.set()

    signal.signal(signal.SIGINT, _signal_handler)
    if hasattr(signal, 'SIGBREAK'):
        signal.signal(signal.SIGBREAK, _signal_handler)

    async def _main():
        config = Config()
        # Escuta SÓ no localhost. Com 0.0.0.0 qualquer máquina da mesma rede
        # (ou de uma rede Wi-Fi compartilhada) abria a interface sem nenhuma
        # autenticação: dava para ler a lista de contatos com nomes e telefones,
        # subir arquivos e disparar envios em nome do usuário.
        config.bind = ["127.0.0.1:8000"]
        config.graceful_timeout = 3  # Espera no máximo 3s para fechar conexões
        await serve(app, config, shutdown_trigger=_shutdown_event.wait)

    asyncio.run(_main())
