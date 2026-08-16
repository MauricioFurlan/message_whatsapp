# -*- coding: utf-8 -*-
"""
Gera a planilha modelo para distribuição (build).
Sempre cria um único contato de teste com status pendente.
"""
import sys
from pathlib import Path

import pandas as pd

destino = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("dist/WhatsAppAutomacao/uploads/contatos.xlsx")
destino.parent.mkdir(parents=True, exist_ok=True)

df = pd.DataFrame([{
    "Nome": "Mauricio",
    "N\u00famero": "19994229146",
    "Mensagem": "Ol\u00e1 {nome}, tudo bem?",
    "Arquivo": "",
    "Enviado": "",
    "Invalido": "",
    "Motivo": "",
}])

# Garante que Número é salvo como texto (evita notação científica no Excel)
df["N\u00famero"] = df["N\u00famero"].astype(str)

df.to_excel(destino, index=False)
print(f"  Planilha modelo gerada: {destino}")
