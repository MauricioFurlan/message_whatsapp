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
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from whatsapp_sender import WhatsAppSender

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
    msgs_por_rodada: int = 5
    total_rodadas: int = 3
    intervalo_rodadas_min: int = 30
    hora_inicio: int = 8
    hora_fim: int = 18
    skip_weekends: bool = True
    delay_min: int = 15
    delay_max: int = 30


# --- Global State ---

@dataclass
class AppState:
    config: dict = field(default_factory=lambda: {
        "msgs_por_rodada": 5,
        "total_rodadas": 3,
        "intervalo_rodadas_min": 30,
        "hora_inicio": 8,
        "hora_fim": 18,
        "skip_weekends": True,
        "delay_min": 15,
        "delay_max": 30,
    })
    excel_path: Optional[str] = None
    sender: Optional[WhatsAppSender] = None
    sender_thread: Optional[Thread] = None
    logs: list = field(default_factory=list)
    sse_queues: list = field(default_factory=list)
    _loop: Optional[asyncio.AbstractEventLoop] = None


state = AppState()


@app.on_event("startup")
async def startup_event():
    """Captura o event loop principal do asyncio e restaura estado."""
    state._loop = asyncio.get_event_loop()
    # Restaura planilha se já existia (sobrevive a reloads)
    upload_path = Path("uploads/contatos.xlsx")
    if upload_path.exists():
        state.excel_path = str(upload_path)
        add_log("Planilha restaurada do upload anterior.")


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


def broadcast_contact_update(numero: str, status: str, data_envio: str = ""):
    """Emite um evento SSE para atualizar o status de um contato na tabela do frontend."""
    import json as _json
    payload = _json.dumps({"numero": numero, "status": status, "data_envio": data_envio}, ensure_ascii=False)
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
        }

    return {
        "state": sender_status["state"],
        "current_round": sender_status["current_round"],
        "messages_sent": sender_status["messages_sent"],
        "total_pending": sender_status["total_pending"],
        "total_contacts": sender_status["total_contacts"],
        "config": state.config,
        "excel_loaded": state.excel_path is not None,
        "logs": state.logs[-50:],
    }


# --- Endpoints ---

@app.get("/", response_class=HTMLResponse)
async def serve_frontend():
    """Serve a página HTML principal."""
    html_path = Path("static/index.html")
    return FileResponse(html_path)


@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    """Upload da planilha Excel com contatos."""
    if not file.filename.endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="Arquivo deve ser .xlsx ou .xls")

    # Salva o arquivo
    upload_dir = Path("uploads")
    upload_dir.mkdir(exist_ok=True)
    file_path = upload_dir / "contatos.xlsx"

    with open(file_path, "wb") as f:
        content = await file.read()
        f.write(content)

    # Valida colunas
    try:
        df = pd.read_excel(file_path)
        required_cols = ["Pessoa", "Número", "Mensagem"]
        missing = [col for col in required_cols if col not in df.columns]
        if missing:
            os.remove(file_path)
            raise HTTPException(
                status_code=400,
                detail=f"Colunas obrigatórias faltando: {', '.join(missing)}"
            )

        # Adiciona colunas de controle se não existirem
        for col in ["Enviado", "DataEnvio", "Invalido"]:
            if col not in df.columns:
                df[col] = ""
            else:
                df[col] = df[col].fillna("").astype(str).str.strip().str.upper()

        df.to_excel(file_path, index=False)
        state.excel_path = str(file_path)

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
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Erro ao ler planilha: {str(e)}")


@app.post("/config")
async def set_config(config: ConfigModel):
    """Atualiza configuração de envio."""
    state.config = config.model_dump()
    add_log(
        f"Configuração atualizada: {config.msgs_por_rodada} msgs/rodada, "
        f"{config.total_rodadas} rodadas, intervalo {config.intervalo_rodadas_min}min, "
        f"horário {config.hora_inicio}h-{config.hora_fim}h"
    )
    return {"status": "ok", "config": state.config}


@app.post("/start")
async def start_sending():
    """Inicia o envio de mensagens."""
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
    )

    # Inicia em thread separada
    state.sender_thread = Thread(target=state.sender.start, daemon=True)
    state.sender_thread.start()

    add_log("Envio iniciado. Aguardando escaneio do QR Code...")
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


@app.get("/contacts")
async def get_contacts():
    """Retorna os contatos da planilha para visualização/edição."""
    if not state.excel_path or not Path(state.excel_path).exists():
        raise HTTPException(status_code=404, detail="Nenhuma planilha carregada.")

    try:
        df = pd.read_excel(state.excel_path)
        # Garante colunas de controle
        for col in ["Enviado", "DataEnvio", "Invalido"]:
            if col not in df.columns:
                df[col] = ""
            else:
                df[col] = df[col].fillna("").astype(str).str.strip()

        # Normaliza campos principais como string
        for col in ["Pessoa", "Número", "Mensagem"]:
            if col in df.columns:
                df[col] = df[col].fillna("").astype(str)

        contacts = []
        for _, row in df.iterrows():
            contacts.append({
                "pessoa": str(row.get("Pessoa", "")),
                "numero": str(row.get("Número", "")),
                "mensagem": str(row.get("Mensagem", "")),
                "enviado": str(row.get("Enviado", "")).strip().upper() == "X",
                "invalido": str(row.get("Invalido", "")).strip().upper() == "X",
                "data_envio": str(row.get("DataEnvio", "")),
            })

        return {"status": "ok", "contacts": contacts}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Erro ao ler planilha: {str(e)}")


class ContactModel(BaseModel):
    pessoa: str = ""
    numero: str = ""
    mensagem: str = ""
    enviado: bool = False
    invalido: bool = False
    data_envio: str = ""


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
            "Pessoa": c.pessoa.strip(),
            "Número": c.numero.strip(),
            "Mensagem": c.mensagem.strip(),
            "Enviado": "X" if c.enviado else "",
            "DataEnvio": c.data_envio.strip(),
            "Invalido": "X" if c.invalido else "",
        })

    df = pd.DataFrame(rows, columns=["Pessoa", "Número", "Mensagem", "Enviado", "DataEnvio", "Invalido"])

    upload_dir = Path("uploads")
    upload_dir.mkdir(exist_ok=True)
    file_path = upload_dir / "contatos.xlsx"
    df.to_excel(file_path, index=False)
    state.excel_path = str(file_path)

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
    import signal
    import sys
    import uvicorn
    print('Acesse: http://localhost:8000')

    def force_exit(sig, frame):
        """Força encerramento no segundo CTRL+C."""
        print("\nForçando encerramento...")
        if state.sender and state.sender._driver:
            try:
                state.sender._driver.quit()
            except Exception:
                pass
        sys.exit(0)

    signal.signal(signal.SIGINT, force_exit)
    uvicorn.run(app, host="0.0.0.0", port=8000)
