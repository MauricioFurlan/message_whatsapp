"""
Diagnóstico dos inputs de arquivo do WhatsApp Web.

Descobre, na versão do WhatsApp Web instalada:
  1. quais input[type=file] existem com o chat aberto (em repouso);
  2. se abrir o menu de anexo (+) faz o WhatsApp criar os inputs
     especializados (mídia com video/*, documento com accept="*");
  3. quais itens o menu de anexo oferece (texto e aria-label);
  4. qual preview abre ao mandar uma imagem para o input escolhido
     (foto normal x editor de figurinha) — SEM enviar nada, dá ESC no final.

Uso:
    python diag_inputs.py                          # só lista os inputs
    python diag_inputs.py 19994229146              # abre a conversa e lista
    python diag_inputs.py 19994229146 C:\\fotos\\a.png   # + testa o preview
"""

import os
import sys
import time

from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from whatsapp_sender import WhatsAppSender

ATTACH_SELECTORS = [
    'span[data-icon="plus-rounded"]',
    'span[data-icon="plus"]',
    'span[data-icon="clip"]',
    'span[data-icon="attach-menu-plus"]',
    '[data-testid="clip"]',
    'button[aria-label="Anexar"]',
    'button[aria-label="Attach"]',
    'div[title="Anexar"]',
]


def dump_inputs(sender, driver, titulo):
    print(f"\n--- {titulo} ---")
    inputs = driver.find_elements(By.CSS_SELECTOR, 'input[type="file"]')
    print(f"{len(inputs)} input[type=file]:")
    for i, inp in enumerate(inputs):
        accept = inp.get_attribute("accept") or ""
        print(f"  [{i}] classe={sender._classify_file_input(accept):<10} accept='{accept}'")
    return inputs


def dump_menu_items(driver):
    print("\n--- Itens do menu de anexo ---")
    seletores = ['li', 'div[role="button"]', 'div[role="menuitem"]', 'button']
    vistos = set()
    for sel in seletores:
        for el in driver.find_elements(By.CSS_SELECTOR, sel):
            try:
                if not el.is_displayed():
                    continue
                texto = (el.text or "").strip().replace("\n", " | ")
                aria = el.get_attribute("aria-label") or ""
                if not texto and not aria:
                    continue
                chave = (texto, aria)
                if chave in vistos or len(texto) > 60:
                    continue
                vistos.add(chave)
                print(f"  <{sel}> texto='{texto}' aria-label='{aria}'")
            except Exception:
                continue


def main():
    numero = sys.argv[1] if len(sys.argv) > 1 else ""
    imagem = sys.argv[2] if len(sys.argv) > 2 else ""

    if imagem and not os.path.isfile(imagem):
        print(f"Arquivo não encontrado: {imagem}")
        return

    sender = WhatsAppSender(
        excel_path="fake.xlsx", config={}, log_callback=lambda m: print(m)
    )
    driver = sender._init_driver()
    sender._driver = driver

    try:
        driver.get("https://web.whatsapp.com")
        print("Aguardando login (escaneie o QR se necessário)...")
        WebDriverWait(driver, 120).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "#pane-side"))
        )
        print("Login OK.")

        if numero:
            digits = sender._clean_number(numero)
            if not digits.startswith("55"):
                digits = "55" + digits
            driver.get(f"https://web.whatsapp.com/send?phone={digits}")
            WebDriverWait(driver, 30).until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, "footer div[contenteditable='true']")
                )
            )
            print(f"Conversa de {digits} aberta.")
            time.sleep(2)

        dump_inputs(sender, driver, "INPUTS EM REPOUSO")

        # --- Abre o menu de anexo (só o "+", nunca um item do menu) ---
        botao = None
        for sel in ATTACH_SELECTORS:
            try:
                el = driver.find_element(By.CSS_SELECTOR, sel)
                if el.is_displayed():
                    botao = el
                    print(f"\nBotão de anexo encontrado via: {sel}")
                    break
            except Exception:
                continue

        if botao is None:
            print("\n⚠️ Não encontrou o botão de anexo (+).")
        else:
            botao.click()
            time.sleep(2)
            dump_inputs(sender, driver, "INPUTS COM O MENU DE ANEXO ABERTO")
            dump_menu_items(driver)
            # Fecha o menu: o "+" é toggle e deixá-lo aberto atrapalha o teste
            ActionChains(driver).send_keys(Keys.ESCAPE).perform()
            time.sleep(1)

        print("\nEscolha para imagem/vídeo:", sender._pick_file_input(True, set()))
        print("Escolha para documento:   ", sender._pick_file_input(False, set()))

        # --- Teste dos caminhos de anexo (não envia: dá ESC no final) ---
        if imagem:
            print("\n=== TESTE: MENU DE ANEXO + JANELA NATIVA DO WINDOWS ===")
            erro = sender._send_media_via_dialog(
                os.path.abspath(imagem), True, "diagnóstico"
            )
            if erro:
                print(f"  ❌ falhou: {erro}")
            else:
                print("  ✅ arquivo escolhido na janela nativa")
                time.sleep(5)
                print(f"    texto do modal: {sender._modal_text()[:200]!r}")
                print(f"    tem campo de legenda? {sender._has_caption_field()}")
                print(f"    botão enviar visível? {sender._find_send_button_modal(timeout=2) is not None}")
                print(f"    classificação: {sender._detect_attach_preview(True, timeout=8) or 'nada detectado'}")
                print("\n  >>> OLHE A TELA: preview de FOTO (imagem grande + campo de")
                print("      legenda) ou editor de FIGURINHA (recorte/desenho)?")
                input("  Enter para descartar o anexo (nada será enviado)...")
                ActionChains(driver).send_keys(Keys.ESCAPE).perform()
                time.sleep(1)
                ActionChains(driver).send_keys(Keys.ESCAPE).perform()

        input("\nEnter para fechar o navegador...")
    finally:
        try:
            driver.quit()
        except Exception:
            pass


if __name__ == "__main__":
    main()
