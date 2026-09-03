"""
Módulo de validação de licença via Supabase.

Responsável por:
- Gerar machine_id único por máquina
- Ativar licença (vincular chave à máquina)
- Validar licença (verificar expiração, status, máquina)
- Cache offline (funciona até 3 dias sem internet)
"""

import hashlib
import json
import logging
import os
import platform
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests

# Mesmo logger de arquivo usado pelo resto do app (configurado em app.py).
# Obtido por nome para não importar app.py aqui — evita import circular.
logger = logging.getLogger("whatsapp_sender_file")

# ============================================================
# CONFIGURAÇÃO — Preencha com seus dados do Supabase
# ============================================================
SUPABASE_URL = "https://jropavqnpsjeqwefilcs.supabase.co"
SUPABASE_ANON_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Impyb3BhdnFucHNqZXF3ZWZpbGNzIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODUwNDY5NzYsImV4cCI6MjEwMDYyMjk3Nn0.qoRiNoFvYKLYaT8p66ewZ7K1dVNvtnWpz8lgq2_67D0"
# ============================================================

# Tabela no Supabase
TABLE = "licencas"

# Cache offline: máximo de dias sem validar online
OFFLINE_GRACE_DAYS = 3

# Arquivo local onde a licença ativada é salva
LICENSE_CACHE_FILE = Path(os.path.expanduser("~")) / ".whatsapp_automacao_license.json"

# De onde saiu o machine_id na última chamada: "wmic", "fallback-hostname"
# ou "erro:<detalhe>". Puramente diagnóstico. O relato "às vezes pede a
# licença de novo" é compatível com essa fonte oscilar entre execuções
# (o machine_id muda junto e a licença local cai), e hoje não há como
# saber se foi isso sem registrar no log.
_MACHINE_ID_SOURCE = "?"
_MACHINE_ID_SOURCE_ANTERIOR = None


def get_machine_id() -> str:
    """
    Gera um ID único para esta máquina baseado no hardware.
    Não muda se reinstalar o app ou o Windows.
    """
    global _MACHINE_ID_SOURCE, _MACHINE_ID_SOURCE_ANTERIOR
    raw = ""
    _MACHINE_ID_SOURCE = "?"

    system = platform.system()

    if system == "Windows":
        # Usa o UUID da BIOS/motherboard (não muda com formatação)
        try:
            result = subprocess.run(
                ["wmic", "csproduct", "get", "UUID"],
                capture_output=True, text=True, timeout=5
            )
            lines = [l.strip() for l in result.stdout.strip().split("\n") if l.strip() and l.strip() != "UUID"]
            if lines:
                raw = lines[0]
                _MACHINE_ID_SOURCE = "wmic"
            else:
                _MACHINE_ID_SOURCE = "erro:wmic-sem-saida"
        except Exception as e:
            _MACHINE_ID_SOURCE = f"erro:wmic-{type(e).__name__}"

    elif system == "Linux":
        # machine-id é único por instalação
        try:
            raw = Path("/etc/machine-id").read_text().strip()
        except Exception:
            pass

    elif system == "Darwin":
        # macOS: serial number do hardware
        try:
            result = subprocess.run(
                ["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
                capture_output=True, text=True, timeout=5
            )
            for line in result.stdout.split("\n"):
                if "IOPlatformSerialNumber" in line:
                    raw = line.split('"')[-2]
                    break
        except Exception:
            pass

    # Fallback: hostname + username (menos seguro, mas funciona)
    if not raw:
        try:
            raw = f"{platform.node()}-{os.getlogin()}-{platform.machine()}"
            _MACHINE_ID_SOURCE = "fallback-hostname"
        except Exception as e:
            # os.getlogin() falha sem console associado. Registra e deixa
            # estourar como antes — aqui a intenção é só instrumentar.
            _MACHINE_ID_SOURCE = f"erro:fallback-{type(e).__name__}"
            logger.error(f"[licenca] get_machine_id falhou no fallback: {e!r}")
            raise

    # A fonte mudar entre execuções muda o machine_id e, com ele, derruba a
    # licença salva. Se acontecer, tem que ficar registrado.
    if _MACHINE_ID_SOURCE_ANTERIOR and _MACHINE_ID_SOURCE_ANTERIOR != _MACHINE_ID_SOURCE:
        logger.warning(
            f"[licenca] ATENCAO: a fonte do machine_id mudou durante a execução: "
            f"{_MACHINE_ID_SOURCE_ANTERIOR} -> {_MACHINE_ID_SOURCE}. "
            f"Isso muda o machine_id e invalida a licença desta máquina."
        )
    _MACHINE_ID_SOURCE_ANTERIOR = _MACHINE_ID_SOURCE

    # Hash para não expor dados de hardware
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def _supabase_request(method: str, endpoint: str, data: dict = None, params: dict = None) -> requests.Response:
    """Faz uma requisição à API REST do Supabase."""
    url = f"{SUPABASE_URL}/rest/v1/{endpoint}"
    headers = {
        "apikey": SUPABASE_ANON_KEY,
        "Authorization": f"Bearer {SUPABASE_ANON_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }

    response = requests.request(
        method=method,
        url=url,
        headers=headers,
        json=data,
        params=params,
        timeout=10,
    )
    return response


def _save_cache(chave: str, data_expiracao: str):
    """Salva licença validada no cache local."""
    cache = {
        "chave": chave,
        "machine_id": get_machine_id(),
        "data_expiracao": data_expiracao,
        "ultimo_check": datetime.now(timezone.utc).isoformat(),
    }
    try:
        LICENSE_CACHE_FILE.write_text(json.dumps(cache), encoding="utf-8")
        logger.info(
            f"[licenca] cache gravado em {LICENSE_CACHE_FILE} "
            f"(machine_id={cache['machine_id'][:12]}..., fonte={_MACHINE_ID_SOURCE}, "
            f"expira={data_expiracao})"
        )
    except OSError as e:
        # Sem cache gravado, a próxima abertura offline pede a chave de novo.
        logger.error(f"[licenca] FALHA ao gravar o cache em {LICENSE_CACHE_FILE}: {e!r}")
        raise


def _load_cache() -> Optional[dict]:
    """Carrega cache local da licença."""
    if not LICENSE_CACHE_FILE.exists():
        logger.warning(
            f"[licenca] arquivo de licença NÃO existe: {LICENSE_CACHE_FILE} "
            f"— a tela vai pedir a chave."
        )
        return None
    try:
        return json.loads(LICENSE_CACHE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        logger.error(
            f"[licenca] arquivo de licença ilegível ({LICENSE_CACHE_FILE}): {e!r} "
            f"— a tela vai pedir a chave."
        )
        return None


def _clear_cache(motivo: str = "não informado"):
    """
    Remove cache local.

    É este apagamento que obriga o usuário a digitar a chave de novo, então
    toda chamada fica registrada no log com o motivo.
    """
    existia = LICENSE_CACHE_FILE.exists()
    if existia:
        LICENSE_CACHE_FILE.unlink()
    logger.warning(
        f"[licenca] CACHE APAGADO (existia={existia}) — motivo: {motivo}. "
        f"A tela vai pedir a chave de licença na próxima abertura."
    )


def ativar_licenca(chave: str) -> dict:
    """
    Ativa uma licença vinculando à máquina atual.

    Retorna:
        {"ok": True, "mensagem": "..."} em caso de sucesso
        {"ok": False, "erro": "..."} em caso de falha
    """
    chave = chave.strip().upper()
    machine_id = get_machine_id()
    logger.info(
        f"[licenca] tentativa de ativação manual: chave={chave[:8]}..., "
        f"machine_id={machine_id[:12]}... (fonte={_MACHINE_ID_SOURCE})"
    )

    try:
        # Busca a licença pela chave
        response = _supabase_request(
            "GET", TABLE,
            params={"chave": f"eq.{chave}", "select": "*"}
        )

        if response.status_code != 200:
            return {"ok": False, "erro": "Erro ao conectar com servidor de licenças."}

        licencas = response.json()

        if not licencas:
            return {"ok": False, "erro": "Chave de licença não encontrada."}

        licenca = licencas[0]

        # Verifica se está ativa
        if not licenca.get("ativa", False):
            return {"ok": False, "erro": "Esta licença foi desativada. Entre em contato com o suporte."}

        # Verifica se expirou
        data_exp = datetime.fromisoformat(licenca["data_expiracao"].replace("Z", "+00:00"))
        if datetime.now(timezone.utc) > data_exp:
            return {"ok": False, "erro": "Esta licença está expirada."}

        # Verifica se já está vinculada a outra máquina
        if licenca.get("machine_id") and licenca["machine_id"] != machine_id:
            return {"ok": False, "erro": "Esta licença já está ativada em outra máquina. Entre em contato com o suporte para transferir."}

        # Ativa: vincula machine_id
        update_response = _supabase_request(
            "PATCH", TABLE,
            data={"machine_id": machine_id, "ultimo_check": datetime.now(timezone.utc).isoformat()},
            params={"chave": f"eq.{chave}"}
        )

        if update_response.status_code not in (200, 204):
            return {"ok": False, "erro": "Erro ao ativar licença. Tente novamente."}

        # Salva no cache local
        _save_cache(chave, licenca["data_expiracao"])

        logger.info(
            f"[licenca] ATIVADA manualmente pelo usuário: chave={chave[:8]}..., "
            f"machine_id={machine_id[:12]}... (fonte={_MACHINE_ID_SOURCE}), "
            f"expira={licenca['data_expiracao']}"
        )
        return {"ok": True, "mensagem": "Licença ativada com sucesso!"}

    except requests.exceptions.ConnectionError:
        return {"ok": False, "erro": "Sem conexão com a internet. Verifique sua rede."}
    except requests.exceptions.Timeout:
        return {"ok": False, "erro": "Servidor demorou para responder. Tente novamente."}
    except Exception as e:
        return {"ok": False, "erro": f"Erro inesperado: {str(e)}"}


def validar_licenca() -> dict:
    """
    Valida se a licença atual é válida.

    Tenta validar online. Se sem internet, usa cache offline (até 3 dias).

    Cada caminho que resulta em "inválida" é registrado no log.txt com o
    motivo exato. Sem isso, o relato do cliente ("às vezes ele pede a chave de
    novo") não tinha como ser diagnosticado depois do fato: a tela mostra o
    mesmo formulário para machine_id divergente, cache ausente, licença
    expirada e erro de rede.

    Retorna:
        {"valida": True, "mensagem": "...", "dias_restantes": N}
        {"valida": False, "erro": "..."}
    """
    cache = _load_cache()

    if not cache:
        logger.warning("[licenca] RESULTADO: inválida — nenhuma licença ativada nesta máquina.")
        return {"valida": False, "erro": "Nenhuma licença ativada nesta máquina."}

    chave = cache.get("chave")
    machine_id = get_machine_id()
    machine_id_cache = cache.get("machine_id")

    logger.info(
        f"[licenca] verificando: chave={str(chave)[:8]}..., "
        f"machine_id_atual={str(machine_id)[:12]}... (fonte={_MACHINE_ID_SOURCE}), "
        f"machine_id_cache={str(machine_id_cache)[:12]}..., "
        f"ultimo_check={cache.get('ultimo_check')}, expira={cache.get('data_expiracao')}"
    )

    # Verifica se o machine_id do cache bate com a máquina atual
    if machine_id_cache != machine_id:
        _clear_cache(
            motivo=(
                f"machine_id divergente — cache={machine_id_cache} vs "
                f"atual={machine_id} (fonte atual={_MACHINE_ID_SOURCE})"
            )
        )
        logger.warning("[licenca] RESULTADO: inválida — machine_id divergente.")
        return {"valida": False, "erro": "Licença ativada em outra máquina."}

    # Tenta validar online
    try:
        response = _supabase_request(
            "GET", TABLE,
            params={"chave": f"eq.{chave}", "select": "*"}
        )
        logger.info(f"[licenca] Supabase respondeu HTTP {response.status_code}")

        if response.status_code == 200:
            licencas = response.json()

            if not licencas:
                _clear_cache(motivo="chave não existe mais no Supabase")
                logger.warning("[licenca] RESULTADO: inválida — chave não encontrada no servidor.")
                return {"valida": False, "erro": "Licença não encontrada no servidor."}

            licenca = licencas[0]

            # Verifica ativa
            if not licenca.get("ativa", False):
                _clear_cache(motivo="licença marcada como inativa no Supabase")
                logger.warning("[licenca] RESULTADO: inválida — desativada pelo administrador.")
                return {"valida": False, "erro": "Licença desativada pelo administrador."}

            # Verifica machine_id
            if licenca.get("machine_id") and licenca["machine_id"] != machine_id:
                _clear_cache(
                    motivo=(
                        f"machine_id do servidor difere — servidor="
                        f"{licenca['machine_id']} vs atual={machine_id} "
                        f"(fonte atual={_MACHINE_ID_SOURCE})"
                    )
                )
                logger.warning("[licenca] RESULTADO: inválida — licença vinculada a outra máquina no servidor.")
                return {"valida": False, "erro": "Licença transferida para outra máquina."}

            # Verifica expiração
            data_exp = datetime.fromisoformat(licenca["data_expiracao"].replace("Z", "+00:00"))
            agora = datetime.now(timezone.utc)

            if agora > data_exp:
                _clear_cache(motivo=f"licença expirou em {data_exp.isoformat()}")
                logger.warning("[licenca] RESULTADO: inválida — expirada.")
                return {"valida": False, "erro": "Licença expirada."}

            dias_restantes = (data_exp - agora).days

            # Atualiza ultimo_check no servidor
            _supabase_request(
                "PATCH", TABLE,
                data={"ultimo_check": agora.isoformat()},
                params={"chave": f"eq.{chave}"}
            )

            # Atualiza cache local
            _save_cache(chave, licenca["data_expiracao"])

            logger.info(f"[licenca] RESULTADO: válida (online), {dias_restantes} dia(s) restante(s).")
            return {"valida": True, "mensagem": "Licença válida.", "dias_restantes": dias_restantes}

        # Status != 200: cai para a validação offline logo abaixo, como antes.
        logger.warning(
            f"[licenca] Supabase devolveu HTTP {response.status_code} "
            f"(corpo: {response.text[:200]!r}) — caindo para validação offline pelo cache."
        )

    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
        # Sem internet — tenta validar offline via cache
        logger.warning(
            f"[licenca] sem resposta do Supabase ({type(e).__name__}: {e}) "
            f"— caindo para validação offline pelo cache."
        )
    except Exception as e:
        # Não engole: o comportamento continua sendo o de antes (a exceção sobe
        # e /license/status devolve 500, que a tela trata abrindo o formulário).
        # A diferença é que agora o motivo fica no log. Candidato conhecido:
        # response.json() com uma resposta HTML (portal de rede / DNS
        # sequestrado) levanta JSONDecodeError, que não é erro de conexão.
        logger.exception(
            f"[licenca] ERRO INESPERADO ao validar online ({type(e).__name__}: {e}) "
            f"— a tela vai pedir a chave."
        )
        raise

    # Validação offline pelo cache
    ultimo_check_str = cache.get("ultimo_check")
    data_exp_str = cache.get("data_expiracao")

    if not ultimo_check_str or not data_exp_str:
        logger.warning(
            f"[licenca] RESULTADO: inválida — cache incompleto "
            f"(ultimo_check={ultimo_check_str!r}, data_expiracao={data_exp_str!r})."
        )
        return {"valida": False, "erro": "Cache de licença corrompido. Conecte à internet para revalidar."}

    ultimo_check = datetime.fromisoformat(ultimo_check_str)
    data_exp = datetime.fromisoformat(data_exp_str.replace("Z", "+00:00"))
    agora = datetime.now(timezone.utc)

    # Verifica se expirou
    if agora > data_exp:
        _clear_cache(motivo=f"licença expirou em {data_exp.isoformat()} (verificação offline)")
        logger.warning("[licenca] RESULTADO: inválida — expirada (offline).")
        return {"valida": False, "erro": "Licença expirada."}

    # Verifica grace period offline
    dias_offline = (agora - ultimo_check).days
    if dias_offline > OFFLINE_GRACE_DAYS:
        logger.warning(
            f"[licenca] RESULTADO: inválida — {dias_offline} dias sem validação online "
            f"(limite: {OFFLINE_GRACE_DAYS})."
        )
        return {"valida": False, "erro": f"Sem validação online há {dias_offline} dias. Conecte à internet para revalidar."}

    dias_restantes = (data_exp - agora).days
    logger.info(
        f"[licenca] RESULTADO: válida (offline, último check há {dias_offline} dia(s)), "
        f"{dias_restantes} dia(s) restante(s)."
    )
    return {
        "valida": True,
        "mensagem": f"Licença válida (offline, última verificação há {dias_offline} dia(s)).",
        "dias_restantes": dias_restantes,
        "offline": True,
    }


def desativar_licenca() -> dict:
    """
    Remove a ativação local (não desativa no servidor).
    Útil para o cliente trocar de máquina.
    """
    _clear_cache(motivo="desativação pedida pelo usuário na tela")
    return {"ok": True, "mensagem": "Licença removida desta máquina."}


def get_cached_key() -> Optional[str]:
    """Retorna a chave salva no cache, se existir."""
    cache = _load_cache()
    return cache.get("chave") if cache else None
