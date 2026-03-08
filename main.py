from selenium import webdriver
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from selenium.common.exceptions import SessionNotCreatedException
import pandas as pd
import time
import random
import urllib
import os
from datetime import datetime, timedelta

from webdriver_manager.chrome import ChromeDriverManager

contatos_df = pd.read_excel("contatos.xlsx")
print(contatos_df)

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

def input_int(prompt, default):
    valor = input(prompt)
    return default if not valor.strip() else int(valor)

MSGS_POR_RODADA = input_int("Mensagens por rodada (padrão 5): ", 5)
TOTAL_RODADAS = input_int("Quantidade de rodadas (padrão 4): ", 4)
INTERVALO_RODADAS_MIN = input_int("Intervalo entre rodadas em minutos (padrão 30): ", 30)
HORA_INICIO_COMERCIAL = 8
HORA_FIM_COMERCIAL = 18

if HORA_INICIO_COMERCIAL < 0 or HORA_INICIO_COMERCIAL > 23:
    raise ValueError("Hora início comercial inválida. Use valor entre 0 e 23.")
if HORA_FIM_COMERCIAL < 0 or HORA_FIM_COMERCIAL > 23:
    raise ValueError("Hora fim comercial inválida. Use valor entre 0 e 23.")
if HORA_INICIO_COMERCIAL >= HORA_FIM_COMERCIAL:
    raise ValueError("A hora de início comercial deve ser menor que a hora de fim.")

print(
    f"\n>>> Configuração: {MSGS_POR_RODADA} msgs x {TOTAL_RODADAS} rodadas, "
    f"intervalo de {INTERVALO_RODADAS_MIN} min, horário comercial {HORA_INICIO_COMERCIAL}:00-{HORA_FIM_COMERCIAL}:00 (seg-sex)\n"
)


def em_horario_comercial(agora):
    dia_util = agora.weekday() < 5
    hora_valida = HORA_INICIO_COMERCIAL <= agora.hour < HORA_FIM_COMERCIAL
    return dia_util and hora_valida


def proximo_horario_comercial(agora):
    proximo = agora.replace(hour=HORA_INICIO_COMERCIAL, minute=0, second=0, microsecond=0)

    if agora.weekday() >= 5:
        dias_para_segunda = 7 - agora.weekday()
        proximo = proximo + timedelta(days=dias_para_segunda)
    elif agora.hour >= HORA_FIM_COMERCIAL:
        proximo = proximo + timedelta(days=1)
    elif agora.hour < HORA_INICIO_COMERCIAL:
        pass
    else:
        return agora

    while proximo.weekday() >= 5:
        proximo += timedelta(days=1)

    return proximo


def aguardar_horario_comercial():
    agora = datetime.now()
    if em_horario_comercial(agora):
        return

    proximo = proximo_horario_comercial(agora)
    espera = max(1, int((proximo - agora).total_seconds()))
    print(
        f"Fora do horário comercial. Aguardando até {proximo.strftime('%Y-%m-%d %H:%M:%S')} "
        f"(~{espera/60:.1f} min)..."
    )
    time.sleep(espera)


def create_chrome_driver():
    os.environ.setdefault("WDM_SSL_VERIFY", "0")

    try:
        return webdriver.Chrome(service=Service(ChromeDriverManager().install()))
    except (Exception, KeyboardInterrupt) as error:
        print(f"Falha ao baixar ChromeDriver automaticamente: {error}")

    local_driver = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chromedriver.exe")
    if os.path.exists(local_driver):
        try:
            print(f"Tentando driver local: {local_driver}")
            return webdriver.Chrome(service=Service(local_driver))
        except SessionNotCreatedException as version_error:
            raise RuntimeError(
                "ChromeDriver local incompatível com o Chrome instalado. "
                "Atualize o arquivo chromedriver.exe para a mesma versão principal do Chrome. "
                f"Detalhe: {version_error.msg}"
            )

    return webdriver.Chrome()

navegador = create_chrome_driver()
navegador.get("https://web.whatsapp.com/")

def wait_main_page(type, name_label_tag):
    try:
        navegador.find_element(type, name_label_tag)
        return True
    except:
        return False

while not wait_main_page(By.ID, "pane-side"):
    time.sleep(1)
    print('esperando browser...')

wait = WebDriverWait(navegador, 30)

def enviar_rodada(df, limite):
    """Envia até `limite` mensagens e retorna quantas foram enviadas."""
    enviadas_na_rodada = 0
    for i, row in df.iterrows():
        aguardar_horario_comercial()

        enviado = str(row.get("Enviado") or "").strip().upper() == "X"
        invalido = str(row.get("Invalido") or "").strip().upper() == "X"
        if enviado or invalido:
            continue

        if enviadas_na_rodada >= limite:
            break

        pessoa = row["Pessoa"]
        numero = row["Número"]
        mensagem = row["Mensagem"]
        texto = urllib.parse.quote(f"Oi {pessoa}, {mensagem}")
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
            df.at[i, "Enviado"] = "X"
            df.at[i, "DataEnvio"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            df.at[i, "Invalido"] = ""
            enviadas_na_rodada += 1
        except TimeoutException:
            df.at[i, "Enviado"] = ""
            df.at[i, "Invalido"] = "X"
            df.at[i, "DataEnvio"] = ""
        df.to_excel("contatos.xlsx", index=False)

        intervalo = random.uniform(15, 30)
        print(f"Aguardando {intervalo:.1f} segundos entre mensagens...")
        time.sleep(intervalo)

    return enviadas_na_rodada


total_enviadas = 0
for rodada in range(1, TOTAL_RODADAS + 1):
    aguardar_horario_comercial()

    contatos_df = pd.read_excel("contatos.xlsx")
    for col in ["Enviado", "DataEnvio", "Invalido"]:
        if col not in contatos_df.columns:
            contatos_df[col] = ""
    contatos_df["Enviado"] = normalize_flag_column(contatos_df["Enviado"])
    contatos_df["Invalido"] = normalize_flag_column(contatos_df["Invalido"])
    contatos_df["DataEnvio"] = contatos_df["DataEnvio"].fillna("").astype(str)

    pendentes = contatos_df[
        (contatos_df["Enviado"] != "X") & (contatos_df["Invalido"] != "X")
    ].shape[0]

    if pendentes == 0:
        print("\nTodos os contatos já foram processados. Encerrando.")
        break

    print(f"\n{'='*50}")
    print(f"Rodada {rodada}/{TOTAL_RODADAS} | {pendentes} contato(s) pendente(s)")
    print(f"{'='*50}")

    enviadas = enviar_rodada(contatos_df, MSGS_POR_RODADA)
    total_enviadas += enviadas
    print(f"Rodada {rodada} finalizada: {enviadas} mensagem(ns) enviada(s) (total acumulado: {total_enviadas})")

    if rodada < TOTAL_RODADAS and pendentes - enviadas > 0:
        jitter = random.uniform(-120, 120)
        espera = max(60, INTERVALO_RODADAS_MIN * 60 + jitter)
        proxima = datetime.now().strftime("%H:%M:%S")
        retorno = (datetime.now() + timedelta(seconds=espera)).strftime("%H:%M:%S")
        print(f"Próxima rodada em ~{espera/60:.1f} min (agora: {proxima}, retorno: {retorno})")
        time.sleep(espera)

print(f"\nExecução concluída. Total de mensagens enviadas: {total_enviadas}")
    