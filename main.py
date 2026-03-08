from selenium import webdriver
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
import pandas as pd
import time
import random
import urllib
from datetime import datetime

from webdriver_manager.chrome import ChromeDriverManager

contatos_df = pd.read_excel("contatos.xlsx")
print('aa', contatos_df)

if "Enviado" not in contatos_df.columns:
    contatos_df["Enviado"] = ""
if "DataEnvio" not in contatos_df.columns:
    contatos_df["DataEnvio"] = ""
if "Invalido" not in contatos_df.columns:
    contatos_df["Invalido"] = ""

def normalize_flag_column(series):
    if series.dtype == "bool":
        return series.map(lambda value: "X" if value else "")
    normalized = series.fillna("").astype(str).str.strip().str.upper()
    return normalized.map(lambda value: "X" if value in {"X", "TRUE", "1"} else "")

contatos_df["Enviado"] = normalize_flag_column(contatos_df["Enviado"])
contatos_df["Invalido"] = normalize_flag_column(contatos_df["Invalido"])
contatos_df["DataEnvio"] = contatos_df["DataEnvio"].fillna("").astype(str)

LIMITE_MENSAGENS_POR_EXECUCAO = 15

# navegador = webdriver.Firefox()
navegador =  webdriver.Chrome(service=Service(ChromeDriverManager().install()))
navegador.get("https://web.whatsapp.com/")

def wait_main_page(type, name_label_tag):
    try:
        navegador.find_element(type, name_label_tag)
        return True
    except:
        return False

while not wait_main_page(By.ID, "pane-side"):
    time.sleep(1)
    print('esperando browser')

wait = WebDriverWait(navegador, 30)

mensagens_enviadas = 0
for i, row in contatos_df.iterrows():
    enviado = str(row.get("Enviado") or "").strip().upper() == "X"
    invalido = str(row.get("Invalido") or "").strip().upper() == "X"
    if enviado or invalido:
        continue
    
    if mensagens_enviadas >= LIMITE_MENSAGENS_POR_EXECUCAO:
        print(f"Limite de {LIMITE_MENSAGENS_POR_EXECUCAO} mensagens atingido. Execute novamente para continuar.")
        break
    pessoa = row["Pessoa"]
    numero = row["Número"]
    mensagem = row["Mensagem"]
    texto = urllib.parse.quote(f"Oi {pessoa}{mensagem}")
    link = f"https://web.whatsapp.com/send?phone={numero}&text={texto}"
    navegador.get(link)
    while not wait_main_page(By.ID, "pane-side"):
        time.sleep(1)
        print('esperando browser')
    try:
        message_box = wait.until(
            EC.presence_of_element_located(
                (By.XPATH, "//footer//div[@contenteditable='true']")
            )
        )
        message_box.send_keys(Keys.ENTER)
        contatos_df.at[i, "Enviado"] = "X"
        contatos_df.at[i, "DataEnvio"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        contatos_df.at[i, "Invalido"] = ""
        mensagens_enviadas += 1
    except TimeoutException:
        contatos_df.at[i, "Enviado"] = ""
        contatos_df.at[i, "Invalido"] = "X"
        contatos_df.at[i, "DataEnvio"] = ""
    contatos_df.to_excel("contatos.xlsx", index=False)
    
    intervalo = random.uniform(15, 30)
    print(f"Aguardando {intervalo:.1f} segundos...")
    time.sleep(intervalo)
    