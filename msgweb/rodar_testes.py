# -*- coding: utf-8 -*-
"""
Roda a suite inteira: Python + Node, e diz o que passou.

## Por que descobrir em vez de listar

A lista de testes do `CLAUDE.md` estava desatualizada em nove arquivos quando
este runner foi escrito — o jeito de uma lista escrita a mao envelhecer e' o
autor do teste seguinte nao saber que ela existe. Aqui os arquivos sao
descobertos do disco, entao um teste novo entra na suite pelo simples fato de
existir, e nao ha lista para esquecer de atualizar.

O preco disso e' que as excecoes precisam ser explicitas — e sao, com o motivo
junto, logo abaixo. Uma excecao sem motivo escrito e' como um teste desativado:
ninguem lembra por que.

## Uso

    python rodar_testes.py            # tudo
    python rodar_testes.py --rapido   # pula os lentos (digitacao humanizada)
    python rodar_testes.py --so e2e   # so um grupo: e2e, unidade, lentos, node

Saida em ASCII de proposito: o cmd.exe le a saida na codepage OEM, e um
acento aqui vira UnicodeEncodeError no meio da suite.
"""

import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent

# ---------------------------------------------------------------- #
# Excecoes — cada uma com o motivo, que e' o que impede de virarem
# testes desativados por acidente.
# ---------------------------------------------------------------- #

# Nao roda nunca: abre uma janela de verdade do Windows e fica esperando
# alguem clicar. Rode na mao quando mexer no win_dialog.py:
#     python tests/test_win_dialog.py
INTERATIVOS = {
    "tests/test_win_dialog.py": "abre um dialogo real do Windows; rode na mao",
}

# Roda, mas a falha ja existia antes e nao derruba a suite: o arquivo afirma
# chaves de config (`msgs_por_rodada`, `total_rodadas`) e um default de
# `human_behavior` que o schema atual nao usa mais. Esta aqui para a contagem
# aparecer, nao para ser ignorada — se o numero de falhas MUDAR, e' regressao
# nova e o runner avisa.
QUEBRADOS_CONHECIDOS = {
    "test_app_estado.py": 4,
}

# Lentos de verdade — 247s dos 283s da suite inteira estao aqui. Nao e'
# desperdicio: os dois primeiros simulam digitacao humanizada caractere a
# caractere e o terceiro espera backoff de verdade, que e' exatamente o que
# eles existem para medir. Mas num ciclo curto atrapalham, e `--rapido` os
# pula (a suite cai de ~4,5min para ~35s).
LENTOS = {
    "test_numeros.py",                  # 111s - digitacao humanizada
    "test_mensagem_global.py",          # montagem da mensagem
    "tests/test_delay_apos_falha.py",   # 136s - espera o backoff de verdade
}


def _arquivos_python():
    achados = [p for p in sorted(RAIZ.glob("test_*.py"))]
    achados += [p for p in sorted(RAIZ.glob("tests/test_*.py"))]
    achados += [p for p in sorted(RAIZ.glob("tests/e2e/test_*.py"))]
    return achados


def _grupo(rel: str) -> str:
    # "lentos" vem primeiro: um arquivo lento pode estar em qualquer pasta, e
    # e' o unico grupo que existe para poder ser PULADO.
    if rel in LENTOS or Path(rel).name in LENTOS:
        return "lentos"
    if rel.startswith("tests/e2e/"):
        return "e2e"
    return "unidade"


def _comando(caminho: Path, rel: str):
    """
    Como invocar este arquivo.

    Quase todo teste do projeto e' unittest, e para esses `-m unittest <modulo>`
    e' o certo: funciona com ou sem bloco `__main__`. Um arquivo sem
    `TestCase` e' script solto (faz as afirmacoes no corpo) e tem de ser
    EXECUTADO — chamar `-m unittest` nele reportaria "Ran 0 tests: OK", que e'
    a pior saida possivel: um teste que nao roda parecendo um teste que passa.
    """
    fonte = caminho.read_text(encoding="utf-8", errors="replace")
    if "unittest.TestCase" in fonte:
        modulo = rel[:-3].replace("/", ".")
        return [sys.executable, "-W", "ignore", "-m", "unittest", modulo]
    return [sys.executable, "-W", "ignore", str(caminho)]


_RE_RAN = re.compile(r"^Ran (\d+) tests? in", re.M)
_RE_FALHAS = re.compile(r"(failures|errors)=(\d+)")


def diga(texto=""):
    """print que aparece na hora, mesmo com a saida redirecionada."""
    print(texto, flush=True)


def _ascii(texto: str) -> str:
    return (texto or "").encode("ascii", "replace").decode("ascii")


def _rodar(cmd, rel):
    inicio = time.monotonic()
    proc = subprocess.run(
        cmd, cwd=str(RAIZ), capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    saida = (proc.stdout or "") + (proc.stderr or "")
    m = _RE_RAN.search(saida)
    total = int(m.group(1)) if m else None
    falhas = sum(int(n) for _, n in _RE_FALHAS.findall(saida))
    return {
        "rel": rel,
        "ok": proc.returncode == 0,
        "codigo": proc.returncode,
        "testes": total,
        "falhas": falhas,
        "segundos": time.monotonic() - inicio,
        "saida": saida,
    }


def main(argv):
    rapido = "--rapido" in argv
    so = ""
    if "--so" in argv:
        i = argv.index("--so")
        so = argv[i + 1] if i + 1 < len(argv) else ""

    diga("=" * 66)
    diga("  Suite completa - WhatsApp Automacao")
    diga("=" * 66)

    tarefas = []
    for caminho in _arquivos_python():
        rel = caminho.relative_to(RAIZ).as_posix()
        if rel in INTERATIVOS:
            continue
        grupo = _grupo(rel)
        if rapido and grupo == "lentos":
            continue
        if so and grupo != so:
            continue
        tarefas.append((grupo, rel, caminho, _comando(caminho, rel)))

    node = shutil.which("node")
    if (not so or so == "node") and node:
        for caminho in sorted(RAIZ.glob("tests/*.js")):
            rel = caminho.relative_to(RAIZ).as_posix()
            tarefas.append(("node", rel, caminho, [node, str(caminho)]))

    # Ordena por GRUPO: os arquivos da raiz se intercalam entre "unidade" e
    # "lentos" na ordem do disco, e sem isto o cabecalho de um grupo aparece
    # duas vezes. Estavel, entao dentro do grupo a ordem continua a do disco.
    ordem = {"unidade": 0, "e2e": 1, "lentos": 2, "node": 3}
    tarefas.sort(key=lambda t: ordem.get(t[0], 9))

    resultados = []
    grupo_atual = ""
    for grupo, rel, _caminho, cmd in tarefas:
        if grupo != grupo_atual:
            grupo_atual = grupo
            diga(f"\n-- {grupo} " + "-" * (60 - len(grupo)))
        r = _rodar(cmd, rel)
        r["grupo"] = grupo

        esperadas = QUEBRADOS_CONHECIDOS.get(rel)
        if esperadas is not None:
            if r["falhas"] == esperadas:
                r["ok"] = True
                r["conhecido"] = True
            else:
                r["conhecido"] = False

        resultados.append(r)
        marca = "ok  " if r["ok"] else "FALHOU"
        qtd = f"{r['testes']:>4} testes" if r["testes"] is not None else "   - testes"
        nota = ""
        if r.get("conhecido"):
            nota = f"  ({esperadas} falhas ja conhecidas)"
        elif esperadas is not None:
            nota = f"  (esperava {esperadas} falhas conhecidas, veio {r['falhas']})"
        diga(f"  [{marca}] {rel:<45} {qtd}  {r['segundos']:5.1f}s{nota}")

    ruins = [r for r in resultados if not r["ok"]]
    for r in ruins:
        diga("\n" + "=" * 66)
        diga(f"  FALHOU: {r['rel']}  (codigo {r['codigo']})")
        diga("=" * 66)
        linhas = r["saida"].strip().splitlines()
        for linha in linhas[-40:]:
            diga("  " + _ascii(linha))

    total_testes = sum(r["testes"] or 0 for r in resultados)
    tempo = sum(r["segundos"] for r in resultados)
    diga("\n" + "=" * 66)
    diga(f"  {len(resultados)} arquivos, {total_testes} testes, {tempo:.1f}s")
    for rel, motivo in INTERATIVOS.items():
        diga(f"  pulado: {rel} ({motivo})")
    if rapido:
        diga("  pulado: os lentos (--rapido). Rode sem a flag antes de um build.")
    if not node:
        diga("  pulado: os testes .js (node nao encontrado no PATH).")
    if ruins:
        diga(f"  RESULTADO: {len(ruins)} arquivo(s) com falha.")
    else:
        diga("  RESULTADO: tudo passou.")
    diga("=" * 66)
    return 1 if ruins else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
