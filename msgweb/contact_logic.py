"""
Lógica pura de contatos — sem dependências de Selenium ou browser.

Extraída do WhatsAppSender para permitir testes unitários isolados.
As funções aqui são chamadas diretamente pelo sender via importação.
"""

import pandas as pd
from typing import Callable


def clean_number(numero) -> str:
    """
    Normaliza um número de telefone vindo da planilha, retornando
    apenas os dígitos (DDD + telefone, sem código de país).

    Trata o caso comum em que o pandas lê a coluna como float
    (ex: 19994229146 -> "19994229146.0"), o que adicionaria um "0"
    extra indevido ao final se apenas filtrássemos os dígitos.

    Remove código de país 55 se o usuário incluiu na planilha,
    já que o envio adiciona o 55 automaticamente.
    """
    numero_str = str(numero).strip()
    if numero_str.lower() in ("", "nan", "none"):
        return ""

    # Remove notação de float ("19994229146.0" -> "19994229146")
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


def validate_contact(numero: str, mensagem: str) -> tuple[bool, str]:
    """
    Valida um contato antes de acionar o browser.

    Retorna (True, "") se válido, ou (False, motivo) caso contrário.
    Regras:
      - Mensagem ausente/vazia => inválido
      - Número ausente/vazio ("", "nan", "none") => inválido
      - Número com menos de 10 dígitos (DDD + telefone) => inválido
    """
    numero_str = str(numero).strip().lower()
    mensagem_str = str(mensagem).strip()

    if mensagem_str == "" or mensagem_str.lower() in ("nan", "none"):
        return False, "mensagem vazia"

    if numero_str == "" or numero_str in ("nan", "none"):
        return False, "número ausente"

    numero_limpo = clean_number(numero)
    if len(numero_limpo) < 10:
        return False, "número inválido"

    return True, ""


def get_pending_contacts(df: pd.DataFrame, max_tentativas: int = 0) -> pd.DataFrame:
    """
    Retorna contatos pendentes (não enviados, não inválidos).
    Se max_tentativas > 0, também exclui contatos que atingiram o limite.
    """
    if df.empty or "Enviado" not in df.columns or "Invalido" not in df.columns:
        return df.iloc[0:0]  # DataFrame vazio com mesmas colunas
    mask = (df["Enviado"] != "X") & (df["Invalido"] != "X")
    if max_tentativas > 0 and "Tentativas" in df.columns:
        tentativas = pd.to_numeric(df["Tentativas"], errors="coerce").fillna(0)
        mask = mask & (tentativas < max_tentativas)
    return df[mask]


def apply_deduplication(
    df: pd.DataFrame,
    allow_duplicates: bool,
    notify_cb: Callable[[int, str, str, str, str], None],
    log_cb: Callable[[str], None],
    save_cb: Callable[[pd.DataFrame], None],
) -> pd.DataFrame:
    """
    Aplica a lógica de deduplicação sobre o DataFrame de contatos.

    - allow_duplicates=False: marca como inválido qualquer contato pendente
      cujo número já apareceu antes (inclusive entre os já enviados).
    - allow_duplicates=True: reabilita contatos que foram invalidados
      exclusivamente por duplicata em execução anterior.

    Chama notify_cb(idx, num, status, data_envio, motivo) para cada duplicado.
    Chama save_cb(df) se alguma linha foi alterada.

    Retorna o df modificado.
    """
    if not allow_duplicates:
        pending = get_pending_contacts(df)
        numeros_vistos: dict[str, int] = {}
        duplicados_indices: list[int] = []

        # 1ª passagem: registra todos os números já enviados como âncoras.
        # Pendentes com o mesmo número de um já-enviado são duplicados.
        for idx, row in df.iterrows():
            if str(row.get("Enviado", "")).strip().upper() != "X":
                continue
            num_norm = clean_number(row["Número"])
            if num_norm and num_norm not in numeros_vistos:
                numeros_vistos[num_norm] = idx

        # 2ª passagem: varre os pendentes e marca duplicatas.
        for idx, row in pending.iterrows():
            num_norm = clean_number(row["Número"])
            if not num_norm:
                continue
            if num_norm in numeros_vistos:
                duplicados_indices.append(idx)
                first_idx = numeros_vistos[num_norm]
                first_nome = str(df.at[first_idx, "Nome"]) if first_idx in df.index else "?"
                pessoa = str(row["Nome"])
                motivo = f"Número duplicado (mesmo que {first_nome})"
                df.at[idx, "Invalido"] = "X"
                df.at[idx, "Motivo"] = motivo
                notify_cb(idx, num_norm, "invalido", "", motivo)
                log_cb(f"[SKIP] {pessoa} ({num_norm}) — número duplicado, pulando.")
            else:
                numeros_vistos[num_norm] = idx

        if duplicados_indices:
            save_cb(df)
            log_cb(f"⚠️ {len(duplicados_indices)} contato(s) com número duplicado marcado(s) como inválido(s).")

    else:
        # Modo teste: reabilita contatos invalidados por duplicata anteriormente.
        reabilitados = 0
        for idx, row in df.iterrows():
            if str(row.get("Invalido", "")).strip().upper() == "X":
                if "duplicado" in str(row.get("Motivo", "")).lower():
                    df.at[idx, "Invalido"] = ""
                    df.at[idx, "Motivo"] = ""
                    reabilitados += 1
        if reabilitados > 0:
            save_cb(df)
            log_cb(f"🔄 {reabilitados} contato(s) duplicado(s) reabilitado(s) (modo teste ativo).")

    return df
