"""
Sonda executável — le os icones das bolhas e das linhas da lista.

Por que em Python e nao no console: o `chrome_profile/` so aceita UM Chrome.
Nao da' para o app enviar enquanto uma aba de DevTools observa; a sonda tem
que ser a dona da janela. Reusa `WhatsAppSender._init_driver()` de proposito —
herda a deteccao de perfil em uso e a cadeia de fallback do chromedriver, que
sao justamente as partes chatas de reescrever.

Uso:
    python sonda_bolha.py                      # so' le a LISTA (nao abre nada,
                                               # nao marca nada como lido)
    python sonda_bolha.py --conversa 19995947333 --segundos 180
                                               # abre a conversa e vigia as
                                               # bolhas (ATENCAO: abrir marca
                                               # as mensagens dela como lidas)

Privacidade: nenhum texto de mensagem e' impresso. Digitos viram "#".
"""

import argparse
import json
import sys
import time
from datetime import datetime

from selenium.webdriver.common.by import By

import seletores
from whatsapp_sender import ChromeProfileInUseError, WhatsAppSender

# Uma ida ao browser por volta, devolvendo dicts simples — mesmo padrao do
# `linha_conversa.ler_linhas`. Interpretar no Python e' o que torna isso
# legivel e testavel; fazer N find_element seria lento e frágil.
JS_LEITURA = r"""
// Medido em 19/09/2026: `message-out`/`message-in` NAO EXISTEM MAIS (0
// ocorrencias). As bolhas sao `[role="row"]` com `[data-id]`, dentro do #main.
const BOLHAS = ['#main [role="row"][data-id]', "#main [data-id]"];
const mascarar = (s) => String(s || "").replace(/\d/g, "#").trim().slice(0, 60);

const icones = (el) => {
  const titulos = [...el.querySelectorAll("svg title")].map(t => (t.textContent || "").trim());
  const datas = [...el.querySelectorAll("[data-icon]")].map(s => s.getAttribute("data-icon"));
  return [...new Set([...titulos, ...datas])].filter(Boolean);
};

let usado = "(nenhum)", bolhas = [];
for (const sel of BOLHAS) {
  const achadas = [...document.querySelectorAll(sel)];
  if (achadas.length) { usado = sel; bolhas = achadas; break; }
}

const saida_bolhas = bolhas.slice(-8).map((el) => ({
  // `data-id` e' estavel por bolha (ao contrario do indice, que desloca
  // quando chega mensagem nova) — e' a chave para casar leituras seguidas.
  id: mascarar(el.getAttribute("data-id") || ""),
  icones: icones(el),
  // A prova de que a mensagem nao saiu. A bolha falhada tem `msg-meta`
  // VAZIO, entao nao ha' icone de status para ler — o sinal e' o container.
  falhou: !!el.querySelector('[data-testid="fail-container"]'),
}));

const LINHAS = arguments[0];
const saida_linhas = [...document.querySelectorAll(LINHAS)].slice(0, 20).map((l) => {
  const status = l.querySelector('[data-testid="last-msg-status"]');
  const midia = l.querySelector('[data-testid="chat-msg-symbol"]');
  const nomes = status
    ? [...status.querySelectorAll("svg title")]
        .filter(t => !midia || !midia.contains(t))
        .map(t => t.textContent)
    : null;
  return {
    titulo: mascarar((l.querySelector('[data-testid="cell-frame-title"]') || {}).innerText),
    icones: nomes,   // null = sem last-msg-status (rascunho), [] = sem icone
  };
});

return {seletor_bolha: usado, total_bolhas: bolhas.length,
        bolhas: saida_bolhas, linhas: saida_linhas};
"""


def agora() -> str:
    return datetime.now().strftime("%H:%M:%S")


def abrir():
    sender = WhatsAppSender(excel_path="uploads/contatos.xlsx", config={})
    driver = sender._init_driver()
    driver.get("https://web.whatsapp.com")
    print(f"[{agora()}] Chrome aberto. Aguardando a lista de conversas...")
    limite = time.time() + 90
    while time.time() < limite:
        if driver.find_elements(By.CSS_SELECTOR, seletores.get("pane_side")):
            print(f"[{agora()}] Lista carregada.")
            return sender, driver
        time.sleep(1)
    raise TimeoutError("#pane-side nao apareceu em 90s (QR pendente? sem rede?)")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--conversa", default="", help="numero a abrir (marca como lido!)")
    p.add_argument("--segundos", type=int, default=120)
    args = p.parse_args()

    try:
        sender, driver = abrir()
    except ChromeProfileInUseError as e:
        print(f"ERRO: {e}", file=sys.stderr)
        print("Feche o programa (e qualquer Chrome do perfil) e rode de novo.", file=sys.stderr)
        return 2

    eventos = []
    try:
        dados = driver.execute_script(JS_LEITURA, seletores.get("linha_conversa"))
        print("\n=== LINHAS DA LISTA (sem abrir nada) ===")
        for i, ln in enumerate(dados["linhas"]):
            marca = "(sem last-msg-status)" if ln["icones"] is None else (ln["icones"] or "(sem icone)")
            print(f"  [{i:2}] {ln['titulo']!r:30} {marca}")

        if not args.conversa:
            print("\nSem --conversa: nao abro nada, nao marco nada como lido.")
            return 0

        print(f"\n[{agora()}] Abrindo a conversa (isso MARCA COMO LIDO)...")
        driver.get(f"https://web.whatsapp.com/send?phone=55{args.conversa}")
        time.sleep(8)

        print(f"[{agora()}] Vigiando as bolhas por {args.segundos}s. "
              f"Pode digitar e enviar nesta janela — eu registro cada mudanca.\n")
        anterior = {}
        fim = time.time() + args.segundos
        while time.time() < fim:
            dados = driver.execute_script(JS_LEITURA, seletores.get("linha_conversa"))
            for b in dados["bolhas"]:
                chave = b["id"]
                atual = ",".join(b["icones"]) or "(sem icone)"
                if anterior.get(chave) != atual:
                    de = anterior.get(chave, "(bolha nova)")
                    anterior[chave] = atual
                    ev = {"hora": agora(), "id": chave, "de": de, "para": atual,
                          "falhou": b["falhou"]}
                    eventos.append(ev)
                    print(f"  [{ev['hora']}] {de}  ->  {atual}"
                          f"{'   <<< FALHOU (nao saiu da maquina)' if b['falhou'] else ''}")
            time.sleep(0.5)
    finally:
        if eventos:
            with open("sonda_bolha_resultado.json", "w", encoding="utf-8") as f:
                json.dump(eventos, f, ensure_ascii=False, indent=2)
            print(f"\n{len(eventos)} evento(s) gravado(s) em sonda_bolha_resultado.json")
        print("Fechando o navegador...")
        try:
            driver.quit()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
