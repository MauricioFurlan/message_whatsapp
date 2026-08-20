# -*- coding: utf-8 -*-
"""
Valida a planilha modelo gerada pelo build (gerar_planilha_modelo.py).

Roda logo apos a geracao, dentro de build.bat, para garantir que o executavel
nunca sai da fabrica com dados de contato reais ou com o placeholder {nome}
quebrado. Sai com codigo != 0 (interrompendo o build) se alguma checagem falhar.
"""
import sys
from pathlib import Path

import pandas as pd

if len(sys.argv) < 2:
    print("Uso: validar_planilha_modelo.py <caminho_do_xlsx>")
    sys.exit(1)

caminho = Path(sys.argv[1])
erros = []

if not caminho.exists():
    print(f"ERRO: planilha modelo nao encontrada em {caminho}")
    sys.exit(1)

df = pd.read_excel(caminho, dtype=str).fillna("")

if len(df) != 1:
    erros.append(f"esperado 1 linha de teste, encontrado {len(df)}")
else:
    row = df.iloc[0]

    nome = str(row.get("Nome", "")).strip()
    if nome != "Mauricio":
        erros.append(f"Nome esperado 'Mauricio', encontrado {nome!r}")

    numero = str(row.get("Número", "")).strip()
    if numero != "19994229146":
        erros.append(f"Número esperado '19994229146', encontrado {numero!r}")

    mensagem = str(row.get("Mensagem", "")).strip()
    if "{nome}" not in mensagem:
        erros.append(f"Mensagem sem o placeholder '{{nome}}': {mensagem!r}")

    for col in ("Enviado", "Invalido", "DataEnvio", "Motivo", "Arquivo"):
        valor = str(row.get(col, "")).strip()
        if valor:
            erros.append(f"coluna {col!r} deveria estar vazia (contato pendente), encontrado {valor!r}")

if erros:
    print("ERRO: planilha modelo do build nao passou na validacao:")
    for erro in erros:
        print(f"  - {erro}")
    sys.exit(1)

print(f"  Planilha modelo validada: 1 contato de teste (Mauricio / 19994229146, placeholder {{nome}} ok)")
