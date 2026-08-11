# -*- coding: utf-8 -*-
"""
Regressão do lado do backend: o evento SSE contact_update precisa carregar
row_index (índice da linha na planilha) como identificador do contato.

Antes, o contato era identificado só pelo número — e número vazio ou repetido
não identifica uma linha, o que fazia o frontend marcar linhas erradas.

Uso:  venv\\Scripts\\python.exe tests\\test_contact_update_backend.py
"""
import json
import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
os.chdir(RAIZ)              # app.py monta static/ a partir do diretório atual
sys.path.insert(0, str(RAIZ))

import app as appmod                       # noqa: E402
from whatsapp_sender import WhatsAppSender  # noqa: E402

capturados = []


class FakeQueue:
    def put_nowait(self, item):
        capturados.append(item)


class FakeLoop:
    def call_soon_threadsafe(self, fn, *args):
        fn(*args)


appmod.state._loop = FakeLoop()
appmod.state.sse_queues = [FakeQueue()]

sender = WhatsAppSender(
    excel_path="uploads/contatos.xlsx",
    config={},
    log_callback=lambda m: None,
    contact_update_callback=appmod.broadcast_contact_update,
)

falhas = []


def checar(titulo, condicao):
    print(f"{'PASSOU' if condicao else 'FALHOU'}  {titulo}")
    if not condicao:
        falhas.append(titulo)


# Linha 8 da planilha (índice 7) com célula de número vazia -> inválida
sender._notify_contact_update(7, "", "invalido")
# Linha 3 da planilha (índice 2) enviada com sucesso
sender._notify_contact_update(2, "19994229146", "enviado", "2026-08-05 22:30:00")

checar("emitiu um evento por chamada", len(capturados) == 2)

if len(capturados) == 2:
    d0 = json.loads(capturados[0]["data"])
    d1 = json.loads(capturados[1]["data"])

    checar("evento é contact_update", all(e["event"] == "contact_update" for e in capturados))
    checar("payload traz row_index", "row_index" in d0 and "row_index" in d1)
    checar("row_index preservado (7)", d0["row_index"] == 7)
    checar("número vazio não é mais o identificador", d0["numero"] == "" and d0["status"] == "invalido")
    checar("row_index preservado (2)", d1["row_index"] == 2)
    checar("data de envio preservada", d1["data_envio"] == "2026-08-05 22:30:00")

# _clean_number deve zerar valores que não são telefone (viram row_index-only)
checar("célula vazia -> número vazio", sender._clean_number("") == "")
checar("NaN do pandas -> número vazio", sender._clean_number(float("nan")) == "")
checar("texto -> número vazio", sender._clean_number("sem numero") == "")
checar("float do Excel sem zero extra", sender._clean_number(19994229146.0) == "19994229146")

print("\nOK: backend consistente." if not falhas else f"\nFALHA: {len(falhas)} verificação(ões).")
sys.exit(0 if not falhas else 1)
