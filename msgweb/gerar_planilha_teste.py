# -*- coding: utf-8 -*-
"""
Gera `uploads/test_contatos.xlsx` do zero, a partir do seed `test_contatos.csv`.

## Por que existe

A planilha de teste é a bancada: 46 linhas desenhadas uma a uma para cobrir
placeholder vazio, número em cinco formatos, anexo inexistente, emoji, quebra
de linha, duplicado, contato já enviado. Testar contra ela custa um envio real
— e um envio real ESCREVE nela: `Enviado`, `DataEnvio`, `Invalido`, `Motivo`,
`Tentativas`, e desde a varredura também `Respondeu`, `Entrega`,
`RespostaTexto`.

Depois da primeira rodada a bancada não serve mais: quase toda linha está com
`Enviado=X` e é PULADA no envio seguinte. Limpar na mão, no Excel, com 46
linhas e 14 colunas, é o tipo de trabalho que a gente acaba não fazendo — e aí
o teste seguinte roda contra meia dúzia de linhas em vez da bateria inteira.

## Por que o seed é um CSV, e não um .xlsx modelo

`uploads/` está no `.gitignore` (é onde mora a planilha do cliente, com
contatos reais), então nada lá dentro pode ser o original. O seed fica na raiz
do `msgweb/`, versionado, e em texto: dá para revisar num diff, dá para
adicionar um caso de teste sem abrir o Excel, e não há binário para conflitar.

O `.xlsx` é derivado — apague quando quiser, este script refaz.

## O que nasce marcado, e por quê

Só duas linhas, e elas são fixtures e não resultado: "Ja Enviado" (tem de ser
PULADA no envio) e "Ja Invalido" (idem). Se o seed trouxesse mais alguma coluna
de controle preenchida, seria estado de execução vazando para dentro do
original — exatamente o problema que este script existe para resolver.

Uso:
    python gerar_planilha_teste.py            # uploads/test_contatos.xlsx
    python gerar_planilha_teste.py caminho.xlsx
"""

import csv
import io
import sys
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parent
SEED = RAIZ / "test_contatos.csv"
DESTINO_PADRAO = RAIZ / "uploads" / "test_contatos.xlsx"

# Colunas de conteúdo (vêm do seed) e colunas de controle (nascem vazias, fora
# das duas fixtures). A ordem é a que o app espera ver na planilha.
COLUNAS_DE_CONTEUDO = ["Nome", "Número", "Mensagem", "Arquivo"]
COLUNAS_DE_CONTROLE = [
    "Enviado", "DataEnvio", "Invalido", "Motivo", "Tentativas",
    "Respondeu", "DataResposta", "Entrega", "UltimaVerificacao", "RespostaTexto",
]
# As únicas de controle que o seed tem permissão de preencher — ver o docstring.
CONTROLE_NO_SEED = ["Enviado", "Invalido", "Motivo"]


def ler_seed(caminho: Path) -> list:
    with io.open(caminho, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def montar(linhas: list) -> pd.DataFrame:
    registros = []
    for linha in linhas:
        # Nada de strip: os espaços em volta de "  Pedro  " SÃO o caso de teste
        # daquela linha (o app é que tem de removê-los).
        reg = {c: linha.get(c, "") or "" for c in COLUNAS_DE_CONTEUDO}
        for c in COLUNAS_DE_CONTROLE:
            reg[c] = linha.get(c, "") or "" if c in CONTROLE_NO_SEED else ""
        reg["Tentativas"] = "0"
        registros.append(reg)

    df = pd.DataFrame(registros, columns=COLUNAS_DE_CONTEUDO + COLUNAS_DE_CONTROLE)
    # Telefone como texto, sempre: gravado como número, o Excel devolve
    # notação científica e o pandas devolve float com `.0`.
    df["Número"] = df["Número"].astype(str)
    return df


def gerar(destino: Path) -> int:
    if not SEED.exists():
        raise SystemExit(f"Seed nao encontrado: {SEED}")
    df = montar(ler_seed(SEED))
    destino.parent.mkdir(parents=True, exist_ok=True)
    df.to_excel(destino, index=False)
    return len(df)


if __name__ == "__main__":
    destino = Path(sys.argv[1]) if len(sys.argv) > 1 else DESTINO_PADRAO
    total = gerar(destino)
    print(f"Planilha de teste zerada: {destino} ({total} contatos)")
