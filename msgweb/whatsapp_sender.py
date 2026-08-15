"""
Módulo de envio de mensagens via WhatsApp Web usando Selenium.
Adaptado do main.py original para funcionar como classe reutilizável.
"""

import logging
import math
import os
import random
import time
import threading
import traceback
from datetime import datetime
from typing import Callable, Optional
from urllib.parse import quote

import pandas as pd
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.webdriver import WebDriver as ChromeWebDriver  # noqa: F401 - força inclusão no PyInstaller
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import (
    TimeoutException,
    WebDriverException,
    InvalidSessionIdException,
    NoSuchWindowException,
    StaleElementReferenceException,
)

import win_dialog

# Logger de arquivo para diagnóstico (compartilhado com app.py)
file_logger = logging.getLogger("whatsapp_sender_file")


class BrowserClosedError(RuntimeError):
    """
    Levantada quando a sessão do Chrome morreu (janela fechada pelo usuário,
    Chrome travou ou perdeu conexão com o DevTools).

    Diferente de uma falha de envio pontual: não faz sentido continuar
    tentando os próximos contatos, porque nenhum vai funcionar.
    """


class AttachmentError(RuntimeError):
    """
    Levantada quando o envio de um anexo falha (arquivo não encontrado no disco,
    ou falha ao anexar no WhatsApp Web).

    Quando o anexo falha, a mensagem inteira é considerada inválida — o texto
    NÃO deve ser enviado. O contato é marcado como inválido imediatamente,
    sem retentativas.
    """


class InvalidNumberError(RuntimeError):
    """
    Levantada quando o WhatsApp Web exibe o popup de 'número inválido' ao
    tentar abrir uma conversa. Isso acontece quando:
      - O número não existe no WhatsApp
      - O número está bloqueado no aparelho do remetente
      - O formato do número é inválido

    Diferente de um TimeoutException genérico: aqui temos certeza de que o
    WhatsApp rejeitou o número (o popup apareceu explicitamente).
    """


# Textos que o WhatsApp Web exibe no popup quando o número é inválido/bloqueado.
# Incluímos variações em PT-BR, EN e ES para cobrir diferentes idiomas do navegador.
_INVALID_NUMBER_MARKERS = (
    "número de telefone compartilhado por meio de url é inválido",
    "phone number shared via url is invalid",
    "número de teléfono compartido a través de url no es válido",
    "o número de telefone compartilhado",
    "phone number shared via",
    "número inválido",
    "invalid phone number",
    "não tem uma conta",
    "doesn't have an account",
    "doesn't have a whatsapp account",
    "não tem whatsapp",
)


# Trechos de mensagem que indicam que o navegador/sessão morreu
_DEAD_SESSION_MARKERS = (
    "invalid session id",
    "no such window",
    "target window already closed",
    "not connected to devtools",
    "chrome not reachable",
    "disconnected",
    "web view not found",
    "session deleted",
)


class WhatsAppSender:
    """
    Classe para envio automatizado de mensagens via WhatsApp Web.
    
    Usa Selenium para controlar o Chrome e enviar mensagens
    conforme planilha Excel carregada.
    """

    def __init__(
        self,
        excel_path: str,
        config: dict,
        log_callback: Optional[Callable[[str], None]] = None,
        contact_update_callback: Optional[Callable[[int, str, str, str], None]] = None,
        global_message: str = "",
    ):
        self.excel_path = excel_path
        self.config = config
        self.log_callback = log_callback or print
        self.contact_update_callback = contact_update_callback
        self.global_message = global_message

        # Estado interno (thread-safe)
        self._lock = threading.Lock()
        self._state = "aguardando"  # aguardando, iniciando, waiting_qr, enviando, pausado, finalizado, erro, parado
        self._current_round = 0
        self._messages_sent = 0
        self._total_pending = 0
        self._total_contacts = 0
        self._total_invalids = 0
        self._running = False
        self._stop_event = threading.Event()

        # Selenium
        self._driver: Optional[webdriver.Chrome] = None

    def _log(self, message: str):
        """Envia mensagem para o callback de log."""
        if self.log_callback:
            self.log_callback(message)

    def _notify_contact_update(self, row_index: int, numero: str, status: str, data_envio: str = "", motivo: str = ""):
        """
        Notifica o frontend sobre mudança de status de um contato.

        row_index é o índice da linha na planilha (0 = primeira linha de dados),
        e é o que identifica o contato. O número vai apenas como conferência,
        porque números repetidos ou vazios não identificam uma linha.

        motivo: texto explicando a razão da invalidação (exibido como tooltip
        no badge "Inválido" da tabela de contatos).
        """
        if self.contact_update_callback:
            try:
                self.contact_update_callback(int(row_index), numero, status, data_envio, motivo)
            except Exception:
                pass

    def _set_state(self, new_state: str):
        """Atualiza o estado de forma thread-safe."""
        with self._lock:
            self._state = new_state

    def get_status(self) -> dict:
        """Retorna o status atual (thread-safe)."""
        with self._lock:
            return {
                "state": self._state,
                "current_round": self._current_round,
                "messages_sent": self._messages_sent,
                "total_pending": self._total_pending,
                "total_contacts": self._total_contacts,
                "total_invalids": self._total_invalids,
            }

    def is_running(self) -> bool:
        """Verifica se o sender está rodando."""
        with self._lock:
            return self._running

    def stop(self):
        """Solicita parada imediata do envio."""
        self._stop_event.set()
        self._log("Parada solicitada. Interrompendo...")

    def _should_stop(self) -> bool:
        """Verifica se deve parar."""
        return self._stop_event.is_set()

    def _interruptible_sleep(self, seconds: float) -> bool:
        """
        Sleep interruptível. Retorna True se a parada foi solicitada
        (ou seja, a operação corrente deve ser abortada imediatamente).
        Usa Event.wait() que acorda instantaneamente quando stop() é chamado.
        """
        return self._stop_event.wait(timeout=seconds)

    def _dismiss_on_stop(self):
        """
        Pressiona ESC para fechar modais/overlays abertos quando a parada
        é detectada no meio de uma operação. Garante que não fica nenhum
        modal travado na tela após interromper.
        """
        if not self._driver:
            return
        try:
            ActionChains(self._driver).send_keys(Keys.ESCAPE).perform()
            time.sleep(0.3)
            ActionChains(self._driver).send_keys(Keys.ESCAPE).perform()
        except Exception:
            pass

    def _init_driver(self) -> webdriver.Chrome:
        """Inicializa o Chrome WebDriver."""
        chrome_options = Options()
        chrome_options.add_argument("--start-maximized")
        chrome_options.add_argument("--disable-notifications")
        chrome_options.add_argument("--disable-infobars")

        # Anti-detecção: remove flags que denunciam automação
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option("useAutomationExtension", False)

        # Manter sessão do WhatsApp
        user_data_dir = os.path.join(os.getcwd(), "chrome_profile")
        chrome_options.add_argument(f"--user-data-dir={user_data_dir}")

        # Mata chromedriver anterior que possa ter ficado travado (não afeta Chrome pessoal)
        try:
            import subprocess
            subprocess.run(
                ["taskkill", "/F", "/IM", "chromedriver.exe"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            time.sleep(1)
        except Exception:
            pass

        # Remove arquivos de lock órfãos do perfil
        for lock_file in ("SingletonLock", "SingletonSocket", "SingletonCookie"):
            lock_path = os.path.join(user_data_dir, lock_file)
            if os.path.exists(lock_path):
                try:
                    os.remove(lock_path)
                except OSError:
                    pass

        file_logger.info(f"Selenium versão: {webdriver.__version__ if hasattr(webdriver, '__version__') else 'desconhecida'}")
        file_logger.info(f"Chrome profile: {user_data_dir}")

        # Tenta usar webdriver_manager primeiro, fallback para local
        try:
            from webdriver_manager.chrome import ChromeDriverManager
            service = Service(ChromeDriverManager().install())
            driver = webdriver.Chrome(service=service, options=chrome_options)
            self._log("ChromeDriver instalado via webdriver-manager")
        except Exception as e:
            file_logger.warning(f"webdriver-manager falhou: {e}")
            self._log(f"webdriver-manager falhou ({e}), tentando chromedriver local...")
            try:
                # Tenta chromedriver.exe local
                local_path = os.path.join(os.getcwd(), "chromedriver.exe")
                if os.path.exists(local_path):
                    service = Service(local_path)
                    driver = webdriver.Chrome(service=service, options=chrome_options)
                    self._log("Usando chromedriver.exe local")
                else:
                    # Tenta sem especificar caminho (precisa estar no PATH)
                    driver = webdriver.Chrome(options=chrome_options)
                    self._log("Usando chromedriver do PATH")
            except Exception as e2:
                file_logger.error(f"Falha total ao iniciar Chrome: {e2}\n{traceback.format_exc()}")
                raise RuntimeError(f"Não foi possível iniciar o Chrome: {e2}")

        # Anti-detecção: remove navigator.webdriver via CDP
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            "source": """
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
                Object.defineProperty(navigator, 'languages', {get: () => ['pt-BR', 'pt', 'en-US', 'en']});
                window.chrome = { runtime: {} };
            """
        })

        # Log das capabilities (versão do Chrome)
        try:
            caps = driver.capabilities
            browser_version = caps.get("browserVersion", caps.get("version", "desconhecida"))
            driver_version = caps.get("chrome", {}).get("chromedriverVersion", "desconhecida")
            file_logger.info(f"Chrome versão: {browser_version}")
            file_logger.info(f"ChromeDriver versão: {driver_version}")
        except Exception:
            pass

        return driver

    def _parse_time(self, time_str) -> tuple:
        """Converte 'HH:MM' ou int (legado) para tupla (hora, minuto)."""
        if isinstance(time_str, int):
            return (time_str, 0)
        parts = str(time_str).split(":")
        return (int(parts[0]), int(parts[1]) if len(parts) > 1 else 0)

    def _is_business_hours(self) -> bool:
        """Verifica se está no horário comercial configurado."""
        now = datetime.now()
        # Verifica fim de semana se configurado (0=segunda, 6=domingo)
        skip_weekends = self.config.get("skip_weekends", True)
        if skip_weekends and now.weekday() >= 5:
            return False
        hora_inicio_h, hora_inicio_m = self._parse_time(self.config.get("hora_inicio", "08:00"))
        hora_fim_h, hora_fim_m = self._parse_time(self.config.get("hora_fim", "18:00"))
        # Converte tudo para minutos do dia para comparar
        agora_min = now.hour * 60 + now.minute
        inicio_min = hora_inicio_h * 60 + hora_inicio_m
        fim_min = hora_fim_h * 60 + hora_fim_m
        return inicio_min <= agora_min < fim_min

    def _get_business_hours_reason(self) -> str:
        """Retorna o motivo pelo qual está fora do horário comercial."""
        now = datetime.now()
        skip_weekends = self.config.get("skip_weekends", True)
        dias_semana = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]
        if skip_weekends and now.weekday() >= 5:
            return f"Hoje é {dias_semana[now.weekday()]} e a opção 'Não enviar nos finais de semana' está ativa"
        hora_inicio = self.config.get("hora_inicio", "08:00")
        hora_fim = self.config.get("hora_fim", "18:00")
        return f"Horário atual ({now.strftime('%H:%M')}) está fora da janela configurada ({hora_inicio}–{hora_fim})"

    def _wait_for_business_hours(self):
        """Aguarda até o próximo horário comercial."""
        if self._is_business_hours():
            return

        self._set_state("pausado")
        motivo = self._get_business_hours_reason()
        self._log(f"Fora do horário comercial. {motivo}. Aguardando próximo horário...")

        while not self._is_business_hours() and not self._should_stop():
            self._interruptible_sleep(2)

        if not self._should_stop():
            self._set_state("enviando")
            self._log("Horário comercial iniciado. Retomando envio...")

    def _load_contacts(self) -> pd.DataFrame:
        """Carrega a planilha de contatos."""
        df = pd.read_excel(self.excel_path)
        # Garante colunas de controle existem e são string normalizadas
        for col in ["Enviado", "DataEnvio", "Invalido"]:
            if col not in df.columns:
                df[col] = ""
            else:
                df[col] = df[col].fillna("").astype(str).str.strip().str.upper()
        # Coluna Arquivo (caminho de mídia por contato)
        if "Arquivo" not in df.columns:
            df["Arquivo"] = ""
        else:
            df["Arquivo"] = df["Arquivo"].fillna("").astype(str).str.strip()
        # Coluna Tentativas (falhas de envio acumuladas — limita as retentativas)
        if "Tentativas" not in df.columns:
            df["Tentativas"] = 0
        else:
            df["Tentativas"] = (
                pd.to_numeric(df["Tentativas"], errors="coerce").fillna(0).astype(int)
            )
        # Coluna Motivo (razão da invalidação — persiste o tooltip entre sessões)
        if "Motivo" not in df.columns:
            df["Motivo"] = ""
        else:
            df["Motivo"] = df["Motivo"].fillna("").astype(str).str.strip()
        return df

    def _max_tentativas_contato(self) -> int:
        """Quantas falhas um contato pode ter antes de ser abandonado."""
        try:
            return max(1, int(self.config.get("max_tentativas_contato", 3)))
        except (TypeError, ValueError):
            return 3

    def _registrar_falha(self, df: pd.DataFrame, idx, pessoa: str, numero: str, motivo: str):
        """
        Contabiliza uma falha de envio do contato.

        Enquanto estiver abaixo do limite, o contato continua pendente e é
        retentado na próxima rodada. Ao atingir o limite ele é marcado como
        inválido, para não ficar consumindo rodada após rodada indefinidamente.
        """
        if "Tentativas" not in df.columns:
            df["Tentativas"] = 0
        try:
            falhas = int(df.at[idx, "Tentativas"] or 0) + 1
        except (TypeError, ValueError):
            falhas = 1
        df.at[idx, "Tentativas"] = falhas
        limite = self._max_tentativas_contato()

        if falhas >= limite:
            df.at[idx, "Invalido"] = "X"
            df.at[idx, "Motivo"] = f"Falhou {falhas} vezes seguidas ({motivo}). Limite de tentativas atingido."
            self._save_contacts(df)
            with self._lock:
                self._total_pending -= 1
                self._total_invalids += 1
            file_logger.error(
                f"Contato abandonado após {falhas} falhas: {pessoa} ({numero}) — {motivo}"
            )
            self._log(
                f"❌ {pessoa} — falhou {falhas}x ({motivo}). Desistindo deste contato "
                f"para não travar as próximas rodadas."
            )
            self._notify_contact_update(
                idx, numero, "invalido", "",
                f"Falhou {falhas} vezes seguidas ({motivo}). Limite de tentativas atingido.",
            )
        else:
            self._save_contacts(df)
            self._log(
                f"⚠️ {pessoa} — falha ao enviar ({motivo}). Tentativa {falhas}/{limite}, "
                f"será tentado novamente na próxima rodada."
            )

    def _save_contacts(self, df: pd.DataFrame):
        """Salva a planilha com progresso atualizado."""
        df.to_excel(self.excel_path, index=False)

    def _get_pending_contacts(self, df: pd.DataFrame) -> pd.DataFrame:
        """Retorna contatos pendentes (não enviados, não inválidos, dentro do limite de tentativas)."""
        mask = (df["Enviado"] != "X") & (df["Invalido"] != "X")
        if "Tentativas" in df.columns:
            tentativas = pd.to_numeric(df["Tentativas"], errors="coerce").fillna(0)
            mask = mask & (tentativas < self._max_tentativas_contato())
        return df[mask]

    def _clean_number(self, numero) -> str:
        """
        Normaliza um número de telefone vindo da planilha, retornando
        apenas os dígitos (DDD + telefone, sem código de país).

        Trata o caso comum em que o pandas lê a coluna como float
        (ex: 19994229146 -> "19994229146.0"), o que adicionaria um "0"
        extra indevido ao final se apenas filtrássemos os dígitos.

        Remove código de país 55 se o usuário incluiu na planilha,
        já que o _send_message adiciona o 55 automaticamente.
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

    def _validate_contact(self, numero: str, mensagem: str) -> tuple:
        """
        Valida um contato antes de acionar o Selenium.

        Retorna (True, "") se o contato for válido, ou (False, motivo)
        caso não tenha número, número inválido ou mensagem vazia.
        Regras:
          - Número ausente/vazio ("", "nan", "none") => inválido
          - Número com menos de 10 dígitos (DDD + telefone) => inválido
          - Mensagem ausente/vazia => inválido
        """
        # Normaliza valores vindos do Excel (podem ser NaN convertido para string)
        numero_str = str(numero).strip().lower()
        mensagem_str = str(mensagem).strip()

        # Mensagem vazia
        if mensagem_str == "" or mensagem_str.lower() in ("nan", "none"):
            return False, "mensagem vazia"

        # Número ausente
        if numero_str == "" or numero_str in ("nan", "none"):
            return False, "número ausente"

        # Número inválido (poucos dígitos)
        numero_limpo = self._clean_number(numero)
        if len(numero_limpo) < 10:
            return False, "número inválido"

        return True, ""

    def _human_behavior_enabled(self) -> bool:
        """Verifica se o modo comportamento humano está ativo."""
        return self.config.get("human_behavior", False)

    def _type_budget(self, length: int) -> float:
        """
        Orçamento de tempo da digitação humanizada, proporcional ao tamanho
        do texto.

        Antes o orçamento era fixo (25s). Mensagem longa — o caso típico da
        mensagem global — estourava o limite no meio da digitação e o restante
        ia numa única chamada: na tela a mensagem "aparecia inteira de uma vez",
        e o cliente concluía (com razão) que o comportamento humano não estava
        valendo para a mensagem global. Agora o orçamento cresce com o texto:

            orçamento = base + segundos_por_caractere * len(texto)   (com teto)

        Base <= 0 continua significando "sem orçamento": manda tudo de uma vez.
        É o escape para navegador degradado e o modo usado nos testes.
        """
        base = float(self.config.get("human_type_max_seconds", 25))
        if base <= 0:
            return 0.0
        por_char = float(self.config.get("human_type_seconds_per_char", 0.05))
        teto = float(self.config.get("human_type_budget_cap", 180))
        # Teto nunca pode ficar abaixo da base, senão a config se contradiz
        teto = max(teto, base)
        return min(base + por_char * max(0, length), teto)

    def _gaussian_delay(self, d_min: float, d_max: float) -> float:
        """
        Gera um delay com distribuição gaussiana (mais natural que uniforme).
        A média fica no centro do intervalo, com 95% dos valores dentro do range.
        """
        mean = (d_min + d_max) / 2
        std_dev = (d_max - d_min) / 4  # 95% dentro do intervalo (2 desvios)
        delay = random.gauss(mean, std_dev)
        # Clamp para não sair dos limites
        return max(d_min * 0.8, min(d_max * 1.2, delay))

    @staticmethod
    def _has_non_bmp(text: str) -> bool:
        """Verifica se o texto contém caracteres fora do BMP (emojis, bandeiras etc.)."""
        return any(ord(c) > 0xFFFF for c in text)

    def _clear_input_field(self, element):
        """
        Limpa qualquer texto residual do campo de input antes de digitar.

        Usa Ctrl+A (seleciona tudo) seguido de Delete para garantir que o campo
        esteja vazio. Isso evita que texto pré-existente (de uma navegação
        anterior, rascunho não enviado, etc.) se misture com a mensagem nova.
        """
        try:
            element.click()
            time.sleep(0.1)
            # Ctrl+A seleciona tudo, depois Delete apaga
            ActionChains(self._driver).key_down(Keys.CONTROL).send_keys("a").key_up(Keys.CONTROL).perform()
            time.sleep(0.05)
            element.send_keys(Keys.DELETE)
            time.sleep(0.1)
        except Exception as e:
            file_logger.debug(f"_clear_input_field: não conseguiu limpar campo: {e}")

    def _paste_text(self, element, text: str):
        """
        Insere texto no campo usando clipboard (Ctrl+V) via JavaScript.

        Necessário para caracteres fora do BMP (emojis compostos, bandeiras,
        família etc.) que o ChromeDriver não suporta via send_keys.
        Preserva quebras de linha usando insertText que respeita o contenteditable.
        """
        # Foca no elemento
        element.click()
        time.sleep(0.2)

        # Usa execCommand insertText via JS — preserva quebras de linha
        # e funciona em contenteditable do WhatsApp Web
        js_script = """
        var element = arguments[0];
        var text = arguments[1];
        element.focus();

        // Usa a Clipboard API para colar texto com emojis
        var dt = new DataTransfer();
        dt.setData('text/plain', text);
        var pasteEvent = new ClipboardEvent('paste', {
            clipboardData: dt,
            bubbles: true,
            cancelable: true
        });
        element.dispatchEvent(pasteEvent);

        // Fallback: se o paste event não inseriu, usa insertText
        if (element.textContent.length === 0 || !element.textContent.includes(text.substring(0, 10))) {
            document.execCommand('insertText', false, text);
        }
        """
        self._driver.execute_script(js_script, element, text)
        time.sleep(0.3)

    def _type_with_newlines(self, element, text: str):
        """
        Digita texto de forma rápida (não-human) mas tratando quebras de linha
        como Shift+Enter para o WhatsApp Web não enviar a mensagem prematuramente.

        Se o texto contém caracteres fora do BMP (emojis compostos, bandeiras etc.),
        usa clipboard (Ctrl+V) pois send_keys do ChromeDriver não suporta.
        """
        if self._has_non_bmp(text):
            self._paste_text(element, text)
            return

        lines = text.split('\n')
        for i, line in enumerate(lines):
            if line:
                element.send_keys(line)
            if i < len(lines) - 1:
                # Shift+Enter para quebra de linha
                ActionChains(self._driver).key_down(Keys.SHIFT).send_keys(Keys.ENTER).key_up(Keys.SHIFT).perform()

    def _human_type(self, element, text: str) -> bool:
        """
        Digita texto simulando digitação humana.
        
        Retorna True se completou a digitação, False se foi interrompido pelo stop.
        Quando interrompido, o texto parcial NÃO deve ser enviado (ENTER não é pressionado).

        Mensagens normais (até `human_type_char_limit`, padrão 200 caracteres)
        são digitadas CARACTERE POR CARACTERE, com micro-pausas variáveis —
        exatamente o comportamento humanizado original, que é o ponto de manter
        essa opção ligada.

        Só textos longos são digitados por PALAVRA. Motivo: cada send_keys() é
        um round-trip HTTP ao ChromeDriver, e o WhatsApp Web fica
        progressivamente mais lento conforme a sessão envelhece. Uma mensagem
        de 400 caracteres gerava 400 chamadas e levava minutos — o bot parecia
        travado e nunca enviava (bug real em produção).

        Em ambos os modos existe um orçamento de tempo (ver `_type_budget`,
        padrão 25s + 0,05s por caractere, com teto de 180s): se estourar, o
        restante vai de uma vez. É a rede de segurança para o caso de o
        navegador estar muito degradado.

        Nota sobre detecção: agrupar não é colar. O send_keys("abc") faz o
        ChromeDriver disparar os eventos de tecla de cada caractere; o que muda
        é apenas o intervalo entre eles.

        Se o texto contém caracteres fora do BMP (emojis), usa clipboard (Ctrl+V)
        pois send_keys do ChromeDriver não suporta esses caracteres.
        """
        # Fallback para emojis e caracteres não-BMP
        if self._has_non_bmp(text):
            file_logger.info(
                f"_human_type: texto contém caracteres fora do BMP (emojis), "
                f"usando clipboard para {len(text)} caracteres"
            )
            # Simula uma pausa "humana" antes de colar
            if self._interruptible_sleep(random.uniform(0.5, 1.5)):
                return False
            self._paste_text(element, text)
            return True

        budget = self._type_budget(len(text))
        limite_char = int(self.config.get("human_type_char_limit", 200))

        # Textos curtos: caractere por caractere (fidelidade máxima)
        por_caractere = len(text) <= limite_char

        started = time.monotonic()
        modo = "caractere" if por_caractere else "palavra"

        file_logger.info(
            f"_human_type: iniciando digitação de {len(text)} caracteres "
            f"por {modo} (limite {limite_char}, orçamento {budget:.0f}s)"
        )

        lines = text.split("\n")
        char_count = 0

        for line_idx, line in enumerate(lines):
            if line:
                tokens = list(line) if por_caractere else self._split_palavras(line)
                pendente = ""

                for token in tokens:
                    if not token:
                        continue

                    # Checkpoint de parada a cada 5 caracteres (ou cada palavra)
                    char_count += len(token)
                    if char_count >= 5 or not por_caractere:
                        if self._should_stop():
                            file_logger.info("_human_type: interrompido pelo stop")
                            return False
                        char_count = 0

                    # Estourou o orçamento: acumula e manda o resto de uma vez
                    if time.monotonic() - started > budget:
                        pendente += token
                        continue

                    element.send_keys(token)

                    # Ritmo humano: pausa maior após espaço e pontuação
                    if token[-1] in (" ", ".", ",", "!", "?"):
                        if self._interruptible_sleep(random.uniform(0.08, 0.25)):
                            return False
                    else:
                        if self._interruptible_sleep(random.uniform(0.03, 0.12)):
                            return False
                    # Ocasionalmente uma pausa maior, como se pensasse
                    if random.random() < 0.02:
                        if self._interruptible_sleep(random.uniform(0.3, 0.8)):
                            return False

                if pendente:
                    if self._should_stop():
                        return False
                    element.send_keys(pendente)
                    file_logger.warning(
                        f"_human_type: orçamento de {budget:.0f}s estourado, "
                        f"{len(pendente)} caracteres restantes enviados de uma vez"
                    )

            if line_idx < len(lines) - 1:
                if self._should_stop():
                    return False
                # Shift+Enter para quebra de linha no WhatsApp Web
                ActionChains(self._driver).key_down(Keys.SHIFT).send_keys(
                    Keys.ENTER
                ).key_up(Keys.SHIFT).perform()
                if self._interruptible_sleep(random.uniform(0.1, 0.3)):
                    return False

        elapsed = time.monotonic() - started
        file_logger.info(
            f"_human_type: {len(text)} caracteres digitados em {elapsed:.1f}s "
            f"(modo {modo})"
        )
        return True

    @staticmethod
    def _split_palavras(line: str) -> list:
        """
        Divide a linha em palavras mantendo o espaço junto da palavra
        ("ola mundo" -> ["ola ", "mundo"]), para o texto digitado ficar
        idêntico ao original.
        """
        partes = line.split(" ")
        return [
            p if i == len(partes) - 1 else p + " "
            for i, p in enumerate(partes)
        ]

    def _is_session_dead(self, exc: Exception) -> bool:
        """
        Detecta se a exceção indica que o navegador/sessão morreu.

        Quando isso acontece, continuar o loop é inútil: todos os contatos
        seguintes falham instantaneamente (foi o que ocorreu no log do cliente,
        onde após a janela fechar o bot seguiu "tentando" contato após contato).
        """
        if isinstance(exc, (InvalidSessionIdException, NoSuchWindowException)):
            return True
        msg = str(exc).lower()
        return any(marker in msg for marker in _DEAD_SESSION_MARKERS)

    def _confirm_message_sent(self, texto_enviado: str, timeout: float = 6.0) -> bool:
        """
        Confirma que a mensagem realmente saiu do campo de texto.

        O WhatsApp Web limpa o campo ao enviar. Se o texto continuar lá, o ENTER
        não surtiu efeito (foco perdido, seletor de emoji aberto, etc.) e a
        mensagem NÃO foi enviada — antes o código assumia sucesso cegamente.

        A verificação compara com um trecho do texto que tentamos enviar em vez
        de exigir campo vazio, porque o WhatsApp renderiza um placeholder
        ("Digite uma mensagem") quando o campo está vazio, o que geraria falso
        negativo e marcaria envios bem-sucedidos como falha.

        Retorna True se o texto saiu do campo, False se continuou lá.
        Levanta BrowserClosedError se a sessão morreu durante a verificação.
        """
        # Trecho de referência: usa o início do texto ANTES de qualquer URL,
        # porque o WhatsApp pode redesenhar o campo ao gerar o preview de link
        # (o texto do link pode aparecer diferente no DOM).
        texto_limpo = texto_enviado.strip()
        # Pega texto antes do primeiro link como referência
        for marker in ("http://", "https://", "www."):
            pos = texto_limpo.find(marker)
            if pos > 0:
                texto_limpo = texto_limpo[:pos].strip()
                break

        alvo = texto_limpo[:40].strip()
        if not alvo:
            return True

        deadline = time.monotonic() + timeout
        ultimo_conteudo = ""

        while time.monotonic() < deadline:
            try:
                field = self._driver.find_element(
                    By.CSS_SELECTOR, "footer div[contenteditable='true']"
                )
                ultimo_conteudo = field.text
                if alvo not in ultimo_conteudo:
                    return True
            except StaleElementReferenceException:
                # Rerender do WhatsApp após o envio — sinal positivo, tenta de novo
                pass
            except Exception as e:
                if self._is_session_dead(e):
                    raise BrowserClosedError(str(e))
                # Não conseguimos verificar: não bloqueia o fluxo
                file_logger.warning(f"Falha ao confirmar envio: {e}")
                return True
            # Sleep interruptível — se stop foi pedido, considera enviado
            # (ENTER já foi pressionado neste ponto)
            if self._interruptible_sleep(0.5):
                return True

        file_logger.warning(
            f"Campo de texto ainda contém a mensagem após {timeout:.0f}s "
            f"(conteúdo: {ultimo_conteudo[:80]!r})"
        )
        return False

    def _random_scroll(self):
        """
        Faz scroll aleatório no painel de conversas antes de enviar,
        simulando navegação humana.
        """
        try:
            pane = self._driver.find_element(By.CSS_SELECTOR, "#pane-side")
            # Scroll para cima ou para baixo aleatoriamente
            direction = random.choice([-1, 1])
            amount = random.randint(100, 400) * direction
            self._driver.execute_script(
                "arguments[0].scrollTop += arguments[1];", pane, amount
            )
            if self._interruptible_sleep(random.uniform(0.5, 1.5)):
                return
            # Volta ao topo
            self._driver.execute_script("arguments[0].scrollTop = 0;", pane)
            self._interruptible_sleep(random.uniform(0.3, 0.8))
        except Exception:
            pass  # Se falhar o scroll, segue normalmente

    def _get_batch_size(self, msgs_por_rodada: int, compensacao: int = 0) -> int:
        """
        Retorna o tamanho do batch para esta rodada.
        
        Quando comportamento humano está ativo, aplica variação de ±1-2 mas
        leva em conta a compensação (débito/crédito de rodadas anteriores)
        para garantir que o total final bata exatamente.
        
        compensacao: positivo = deve mandar a mais, negativo = deve mandar a menos
        """
        base = msgs_por_rodada + compensacao
        if not self._human_behavior_enabled():
            return max(1, base)
        variacao = random.choice([-2, -1, 0, 1, 2])
        return max(1, base + variacao)

    def _generate_burst_plan(self, total_msgs: int, tempo_minutos: int) -> list:
        """
        Gera um plano de envio em rajadas (bursts) com distribuição irregular.

        Em vez de enviar 1 msg a cada X segundos (metrônomo), simula o
        comportamento real de uma pessoa: manda umas 4-5 seguidas, para,
        manda mais 2-3, etc.

        Retorna uma lista de dicts:
        [
            {"burst_size": 5, "intra_delay": 18, "pause_after": 300},
            {"burst_size": 3, "intra_delay": 15, "pause_after": 180},
            ...
        ]

        - burst_size: quantas msgs mandar seguidas nessa rajada
        - intra_delay: delay entre msgs dentro da rajada (curto, 15-25s)
        - pause_after: pausa após essa rajada antes da próxima (mais longa)
          O último burst tem pause_after = 0 (não precisa esperar depois)
        """
        DELAY_INTRA_MIN = 15   # delay mínimo entre msgs dentro de um burst
        DELAY_INTRA_MAX = 25   # delay máximo entre msgs dentro de um burst
        BURST_MIN = 2          # tamanho mínimo de uma rajada
        BURST_MAX = 8          # tamanho máximo de uma rajada

        if total_msgs <= 0:
            return []

        # Caso trivial: poucas mensagens — um único burst
        if total_msgs <= BURST_MAX:
            intra_delay = random.uniform(DELAY_INTRA_MIN, DELAY_INTRA_MAX)
            return [{"burst_size": total_msgs, "intra_delay": intra_delay, "pause_after": 0}]

        # Gera bursts com tamanhos aleatórios até somar total_msgs
        bursts = []
        restante = total_msgs
        while restante > 0:
            if restante <= BURST_MAX:
                bursts.append(restante)
                restante = 0
            else:
                size = random.randint(BURST_MIN, min(BURST_MAX, restante - 1))
                bursts.append(size)
                restante -= size

        # Calcula o tempo total disponível e distribui as pausas
        tempo_segundos = tempo_minutos * 60

        # Tempo gasto dentro dos bursts (intra-delays)
        intra_delays = []
        tempo_intra_total = 0
        for size in bursts:
            d = random.uniform(DELAY_INTRA_MIN, DELAY_INTRA_MAX)
            intra_delays.append(d)
            # Dentro de cada burst há (size - 1) intervalos
            tempo_intra_total += (size - 1) * d

        # Tempo restante para distribuir entre as pausas dos bursts
        tempo_para_pausas = max(0, tempo_segundos - tempo_intra_total)

        # Distribui pausas com pesos aleatórios (distribuição Dirichlet-like)
        num_pausas = len(bursts) - 1  # última rajada não tem pausa depois
        if num_pausas > 0 and tempo_para_pausas > 0:
            # Gera pesos aleatórios
            pesos = [random.uniform(0.5, 2.0) for _ in range(num_pausas)]
            soma_pesos = sum(pesos)
            pausas = [(p / soma_pesos) * tempo_para_pausas for p in pesos]
        else:
            pausas = []

        # Monta o plano final
        plan = []
        for i, size in enumerate(bursts):
            pause = pausas[i] if i < len(pausas) else 0
            plan.append({
                "burst_size": size,
                "intra_delay": intra_delays[i],
                "pause_after": pause,
            })

        return plan

    @staticmethod
    def _preview_texto(texto: str, limite: int = 300) -> str:
        """
        Versão do texto segura para o arquivo de log: uma linha só e truncada.

        Existe para diagnóstico remoto — quando o cliente diz "enviou o nome
        errado", o log precisa mostrar exatamente o texto que o sistema montou.
        """
        t = (texto or "").replace("\r", "").replace("\n", "\\n")
        if len(t) <= limite:
            return t
        return f"{t[:limite]}... (+{len(t) - limite} caracteres)"

    @staticmethod
    def _format_texto(pessoa: str, mensagem: str) -> tuple:
        """
        Monta o texto final da mensagem e devolve (texto, regra_aplicada).

        O nome vem SEMPRE da coluna `Nome` da planilha — o sistema nunca lê o
        nome do contato salvo no WhatsApp. A `regra` é só descrição para o log,
        para diagnosticar relatos de "enviou o nome errado".

        Regras, em ordem:
          1. mensagem com {nome}  -> substitui o placeholder pelo nome
          2. nenhuma das duas -> mensagem exatamente como está
        """
        pessoa_limpo = pessoa.strip() if pessoa else ""
        nome_vazio = pessoa_limpo.lower() in ("nan", "none", "")

        if "{nome}" in mensagem:
            # Placeholder: substitui {nome} pelo nome do contato (ou remove se vazio)
            nome_subst = "" if nome_vazio else pessoa_limpo
            texto = mensagem.replace("{nome}", nome_subst)
            regra = f"placeholder {{nome}} -> '{nome_subst}' (coluna Nome da planilha)"
        else:
            texto = mensagem
            regra = "texto puro (sem substituição de nome)"

        return texto, regra

    def _send_message(self, pessoa: str, numero: str, mensagem: str, arquivo: str = "") -> bool:
        """
        Envia uma mensagem para um contato.
        Se há arquivo associado, envia primeiro o(s) anexo(s) e depois o texto.
        Se o anexo falhar (arquivo não encontrado ou erro ao enviar), a mensagem
        de texto NÃO é enviada e o contato é marcado como inválido (AttachmentError).
        Se não há arquivo, envia apenas texto.
        Retorna True se enviou com sucesso, False se falhou.
        Levanta TimeoutException se número é inválido.
        Levanta AttachmentError se o anexo falhar (contato deve ser marcado inválido).
        """
        # Formata mensagem com placeholder {nome} se presente
        texto, regra = self._format_texto(pessoa, mensagem)

        # Formata número (remove caracteres não numéricos e notação float)
        numero_limpo = self._clean_number(numero)
        if not numero_limpo.startswith("55"):
            numero_limpo = "55" + numero_limpo

        human = self._human_behavior_enabled()

        # Diagnóstico: registra o texto EXATO que será enviado, o nome usado e o
        # modo de digitação. É o que permite responder objetivamente a relatos do
        # tipo "enviou outro nome" ou "não digitou como humano".
        file_logger.info(
            f"Texto final para '{pessoa}' ({numero_limpo}) — {len(texto)} caracteres, "
            f"regra: {regra}, modo: {'humanizado' if human else 'rápido (texto pré-preenchido na URL)'} "
            f"| {self._preview_texto(texto)}"
        )
        
        # Suporta múltiplos arquivos separados por vírgula
        media_files = []
        if arquivo:
            for f in arquivo.split(","):
                f = f.strip()
                if not f:
                    continue
                if os.path.isfile(f):
                    media_files.append(f)
                else:
                    # Arquivo especificado mas não existe no disco: aborta o envio
                    # inteiro (texto + anexo). Contato será marcado como inválido.
                    raise AttachmentError(
                        f"Anexo não encontrado: {os.path.basename(f)} "
                        f"(caminho: {f})"
                    )
        has_media = len(media_files) > 0

        # O anexo é enviado ANTES do texto. Se o anexo falhar, o texto não é
        # enviado e o contato é marcado como inválido. Imagens/vídeos vão pelo
        # input de mídia do WhatsApp (foto grande inline); os demais vão como documento.
        all_images = False

        # Navega para o chat (sempre sem texto pré-preenchido quando human ou mídia)
        if human or has_media:
            url = f"https://web.whatsapp.com/send?phone={numero_limpo}"
        else:
            texto_encoded = quote(texto)
            url = f"https://web.whatsapp.com/send?phone={numero_limpo}&text={texto_encoded}"

        try:
            # Scroll aleatório antes de navegar (simula olhar conversas)
            if human:
                self._random_scroll()

            self._driver.get(url)

            # Espera a página carregar (pane-side indica que o WhatsApp carregou)
            # Usa espera interruptível em vez de WebDriverWait monolítico
            pane_found = False
            pane_deadline = time.monotonic() + 30
            while time.monotonic() < pane_deadline:
                if self._should_stop():
                    self._dismiss_on_stop()
                    return False
                try:
                    self._driver.find_element(By.CSS_SELECTOR, "#pane-side")
                    pane_found = True
                    break
                except Exception:
                    pass
                if self._interruptible_sleep(0.5):
                    self._dismiss_on_stop()
                    return False
            if not pane_found:
                raise TimeoutException("Timeout esperando WhatsApp carregar (pane-side)")

            # Espera o chat carregar OU detecta popup de número inválido/bloqueado.
            # O WhatsApp Web mostra um popup imediatamente quando o número é
            # inválido ou bloqueado — detectá-lo evita esperar o timeout inteiro
            # de 20s e permite dar feedback preciso ao usuário.
            self._wait_chat_or_invalid_popup(numero_limpo, pessoa, timeout=20)

            # Pequena pausa antes de interagir
            if human:
                if self._interruptible_sleep(random.uniform(1.5, 4.0)):
                    self._dismiss_on_stop()
                    return False
            else:
                if self._interruptible_sleep(random.uniform(1.5, 3.0)):
                    self._dismiss_on_stop()
                    return False

            # Passo 1: Se tem mídia, envia os anexos PRIMEIRO.
            # Se o anexo falhar, a mensagem de texto NÃO será enviada e o
            # contato será marcado como inválido. Isso garante que não se
            # entrega uma mensagem "solta" (sem o anexo prometido).
            if has_media:
                for media_file in media_files:
                    if self._should_stop():
                        self._dismiss_on_stop()
                        return False
                    if self._interruptible_sleep(random.uniform(1.0, 2.0)):
                        self._dismiss_on_stop()
                        return False
                    try:
                        self._send_media(media_file, pessoa, human)
                    except BrowserClosedError:
                        raise
                    except Exception as e:
                        if self._is_session_dead(e):
                            raise BrowserClosedError(str(e))
                        raise AttachmentError(
                            f"Falha ao enviar anexo {os.path.basename(media_file)}: {e}"
                        )

            if self._should_stop():
                self._dismiss_on_stop()
                return False

            if human:
                if self._interruptible_sleep(random.uniform(2.0, 5.0)):
                    self._dismiss_on_stop()
                    return False
            else:
                if self._interruptible_sleep(random.uniform(2.0, 4.0)):
                    self._dismiss_on_stop()
                    return False

            # Passo 2: Envia a mensagem de texto (SOMENTE se NÃO for enviar como legenda de imagem)
            if not all_images:
                input_field = self._driver.find_element(
                    By.CSS_SELECTOR, "footer div[contenteditable='true']"
                )

                # Garante que o campo está vazio antes de digitar (evita sobrescrever
                # rascunhos ou texto residual de navegação anterior)
                if human or has_media:
                    self._clear_input_field(input_field)

                if human:
                    typing_ok = self._human_type(input_field, texto)
                    if not typing_ok:
                        # Stop requested during typing — do NOT send
                        self._dismiss_on_stop()
                        return False
                    if self._interruptible_sleep(random.uniform(0.8, 2.0)):
                        self._dismiss_on_stop()
                        return False
                else:
                    # Se não usou human, o texto já está no campo via URL (exceto com mídia)
                    if has_media:
                        # Envia texto com suporte a quebras de linha (Shift+Enter)
                        self._type_with_newlines(input_field, texto)
                        if self._interruptible_sleep(random.uniform(0.5, 1.0)):
                            self._dismiss_on_stop()
                            return False

                # Verifica stop antes de pressionar ENTER (ponto sem retorno)
                if self._should_stop():
                    self._dismiss_on_stop()
                    return False

                # Se a mensagem contém um link, o WhatsApp gera um preview card.
                has_link = "http://" in texto or "https://" in texto or "www." in texto
                if has_link:
                    if self._interruptible_sleep(random.uniform(2.0, 4.0)):
                        self._dismiss_on_stop()
                        return False

                input_field.send_keys(Keys.ENTER)

                # Confirma que a mensagem saiu de fato.
                confirm_timeout = 8.0 if has_link else 6.0
                if not self._confirm_message_sent(texto, timeout=confirm_timeout):
                    self._log(f"⚠️ {pessoa} — campo não esvaziou, tentando ENTER novamente...")
                    file_logger.warning(f"ENTER não enviou a mensagem de {pessoa}, tentando novamente")
                    try:
                        input_field = self._driver.find_element(
                            By.CSS_SELECTOR, "footer div[contenteditable='true']"
                        )
                        input_field.send_keys(Keys.ENTER)
                    except StaleElementReferenceException:
                        pass

                    if not self._confirm_message_sent(texto, timeout=confirm_timeout):
                        file_logger.error(
                            f"NÃO CONFIRMADO: mensagem de {pessoa} ({numero_limpo}) pode "
                            f"não ter sido enviada — campo de texto ainda continha o "
                            f"texto após 2 tentativas de ENTER. Seguindo adiante."
                        )
                        self._log(
                            f"⚠️ {pessoa} — não foi possível confirmar o envio. "
                            f"Verifique manualmente esta conversa."
                        )

            return True

        except BrowserClosedError:
            raise  # Sessão morta: aborta o envio inteiro
        except AttachmentError:
            raise  # Falha no anexo: contato será marcado inválido sem retentativa
        except InvalidNumberError:
            raise  # Número rejeitado pelo WhatsApp (popup detectado)
        except TimeoutException:
            raise  # Re-raise para marcar como inválido
        except Exception as e:
            if self._is_session_dead(e):
                file_logger.error(
                    f"Sessão do Chrome morreu durante o envio para {pessoa} "
                    f"({numero_limpo}): {e}"
                )
                raise BrowserClosedError(str(e))
            file_logger.error(f"Erro no envio Selenium para {pessoa} ({numero_limpo}): {e}\n{traceback.format_exc()}")
            self._log(f"Erro ao enviar para {pessoa}: {e}")
            return False

    # Extensões que devem ser enviadas como "Fotos e Vídeos" (aparecem inline no chat)
    _IMAGE_VIDEO_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".mp4", ".3gp", ".mov"}

    def _is_image_or_video(self, file_path: str) -> bool:
        """Verifica se o arquivo é imagem/vídeo (deve ser enviado inline, não como documento)."""
        ext = os.path.splitext(file_path)[1].lower()
        return ext in self._IMAGE_VIDEO_EXTENSIONS

    def _find_all_file_inputs(self) -> list:
        """Retorna todos os input[type=file] presentes no DOM."""
        try:
            return self._driver.find_elements(By.CSS_SELECTOR, 'input[type="file"]')
        except Exception:
            return []

    @staticmethod
    def _classify_file_input(accept: str) -> str:
        """
        Classifica um input[type=file] do WhatsApp Web pelo atributo accept.

        O WhatsApp mantém vários inputs escondidos no DOM ao mesmo tempo, e é o
        input escolhido — não o item do menu — que decide o formato do envio:

          - "midia"      accept="image/*,video/mp4,video/3gpp,video/quicktime"
                         → abre o preview de FOTO/VÍDEO (imagem grande, inline)
          - "figurinha"  accept="image/webp,image/png,image/jpeg" (lista fixa de
                         mime types de imagem, sem vídeo)
                         → abre o editor de FIGURINHA (era a causa do bug)
          - "documento"  accept="*" ou "*/*"
                         → envia como arquivo anexado
          - "imagem"     accept="image/*" puro (foto de perfil e afins)
        """
        a = (accept or "").lower().replace(" ", "")
        if a in ("", "*", "*/*"):
            return "documento"
        tem_video = "video" in a
        tem_imagem = "image" in a
        if tem_video:
            return "midia"
        if tem_imagem:
            return "imagem" if "image/*" in a else "figurinha"
        return "outro"

    def _pick_file_input(self, is_image_video: bool, ja_tentados: set):
        """
        Escolhe o melhor input[type=file] para o tipo de arquivo, relendo o DOM
        (os inputs somem/reaparecem conforme o WhatsApp abre e fecha modais).

        Retorna (classe, accept, elemento) ou None se não houver candidato novo.
        Para imagens/vídeos o input de figurinha é sempre ignorado — é ele que
        fazia a foto virar sticker.
        """
        classificados = []
        for inp in self._find_all_file_inputs():
            try:
                accept = inp.get_attribute("accept") or ""
            except Exception:
                continue
            classificados.append((self._classify_file_input(accept), accept, inp))

        file_logger.info(
            "Inputs de arquivo no DOM: "
            + (", ".join(f"[{k}] accept='{a}'" for k, a, _ in classificados) or "nenhum")
        )

        if is_image_video:
            # Nunca usa o input de figurinha para foto/vídeo
            ordem = ["midia", "imagem", "outro"]
        else:
            # "imagem" entra como último recurso: em algumas versões o WhatsApp
            # mantém um único input no DOM e valida o tipo no próprio JS.
            ordem = ["documento", "outro", "midia", "imagem"]

        for classe in ordem:
            for k, a, el in classificados:
                if k == classe and a not in ja_tentados:
                    return k, a, el
        return None

    def _reveal_file_input(self, element):
        """
        Torna o input[type=file] interagível. O WhatsApp o mantém escondido
        (display:none), o que faz o Selenium recusar o send_keys em algumas
        versões do Chrome.
        """
        try:
            self._driver.execute_script(
                "const el = arguments[0];"
                "el.style.display = 'block';"
                "el.style.visibility = 'visible';"
                "el.style.opacity = '1';"
                "el.style.width = '1px';"
                "el.style.height = '1px';"
                "el.removeAttribute('disabled');",
                element,
            )
        except Exception as e:
            file_logger.warning(f"Não foi possível revelar o input de arquivo: {e}")

    # Textos que denunciam o editor de figurinha (envio no formato errado)
    _STICKER_MARKERS = ("figurinha", "sticker")
    # Marcadores inequívocos do editor de figurinha
    _STICKER_STRONG_MARKERS = (
        "criar figurinha",
        "nova figurinha",
        "create sticker",
        "new sticker",
    )

    def _modal_text(self) -> str:
        """Texto visível dos modais/overlays abertos (minúsculo)."""
        try:
            containers = self._driver.find_elements(
                By.CSS_SELECTOR,
                'div[role="dialog"], div[data-animate-modal-body="true"], '
                'div[data-animate-modal-popup="true"], .overlay',
            )
            return " ".join((c.text or "") for c in containers).lower()
        except Exception:
            return ""

    def _detect_invalid_number_popup(self) -> str:
        """
        Verifica se o WhatsApp Web está exibindo o popup de 'número inválido'.

        Retorna o texto do popup (minúsculo) se detectado, ou string vazia se
        não há popup de erro visível. Isso permite diferenciar entre:
          - Número inexistente no WhatsApp
          - Número bloqueado (o WhatsApp mostra o mesmo popup)
          - Timeout genérico (problema de rede, lentidão, etc.)
        """
        texto = self._modal_text()
        if not texto:
            return ""
        for marker in _INVALID_NUMBER_MARKERS:
            if marker in texto:
                return texto
        return ""

    def _wait_chat_or_invalid_popup(self, numero: str, pessoa: str, timeout: float = 20.0):
        """
        Espera o chat abrir (campo de texto no rodapé) OU detecta:
          1. Popup de número inválido (modal com texto "número inválido")
          2. Contato bloqueado (conversa abre mas mostra botões "Desbloquear"/
             "Apagar conversa" em vez do campo de digitação)

        Levanta InvalidNumberError com mensagem descritiva se detectar
        qualquer um dos cenários acima, evitando esperar o timeout inteiro.
        """
        fim = time.time() + timeout
        while time.time() < fim:
            # Verifica se o chat abriu (campo de digitação apareceu)
            try:
                elements = self._driver.find_elements(
                    By.CSS_SELECTOR, "footer div[contenteditable='true']"
                )
                if elements:
                    return  # Chat abriu com sucesso
            except Exception:
                pass

            # Verifica se apareceu popup de número inválido
            popup_text = self._detect_invalid_number_popup()
            if popup_text:
                # Fecha o popup (clica em OK ou ESC)
                self._dismiss_invalid_number_popup()
                file_logger.warning(
                    f"Popup de número inválido detectado para {pessoa} ({numero}): "
                    f"{popup_text[:120]}"
                )
                raise InvalidNumberError(
                    f"WhatsApp rejeitou o número {numero}: {popup_text[:100]}"
                )

            # Verifica se é um contato bloqueado (aparece botão Desbloquear
            # ou "Apagar conversa" no lugar do campo de texto)
            blocked_reason = self._detect_blocked_contact()
            if blocked_reason:
                file_logger.warning(
                    f"Contato bloqueado detectado para {pessoa} ({numero}): "
                    f"{blocked_reason}"
                )
                raise InvalidNumberError(
                    f"Contato bloqueado no WhatsApp: {pessoa} ({numero})"
                )

            if self._interruptible_sleep(0.5):
                return  # Stop requested — caller will check _should_stop()

        # Se chegou aqui, deu timeout sem chat nem popup — comportamento antigo
        raise TimeoutException(
            f"Timeout aguardando chat de {pessoa} ({numero}) — "
            f"nem chat nem popup de erro apareceram em {timeout}s"
        )

    def _detect_blocked_contact(self) -> str:
        """
        Detecta se a conversa aberta é de um contato bloqueado.

        Quando um contato está bloqueado no WhatsApp, a conversa abre mas o
        footer mostra botões como "Desbloquear" e "Apagar conversa" em vez do
        campo de digitação. Detectamos isso procurando por textos/botões
        característicos na área do chat.

        Retorna o motivo (string) se detectou bloqueio, ou "" se não.
        """
        try:
            # Procura botões ou textos indicativos de bloqueio na página
            # O WhatsApp Web mostra esses botões no rodapé ou corpo do chat
            page_text = ""
            # Verifica no footer (onde normalmente ficaria o campo de digitação)
            footer_elements = self._driver.find_elements(By.CSS_SELECTOR, "footer")
            for el in footer_elements:
                try:
                    page_text += " " + (el.text or "").lower()
                except Exception:
                    continue

            # Verifica também na área principal do chat (span/button com texto)
            chat_area = self._driver.find_elements(
                By.CSS_SELECTOR,
                'div[data-tab] button, div[data-tab] span, '
                'div.copyable-area button, div.copyable-area span'
            )
            for el in chat_area:
                try:
                    page_text += " " + (el.text or "").lower()
                except Exception:
                    continue

            # Marcadores de contato bloqueado (PT-BR, EN, ES)
            blocked_markers = (
                "desbloquear",
                "unblock",
                "desbloquear",  # ES é igual PT
                "apagar conversa",
                "delete chat",
                "eliminar chat",
                "you blocked this contact",
                "você bloqueou este contato",
                "bloqueaste este contacto",
            )
            for marker in blocked_markers:
                if marker in page_text:
                    return f"Texto '{marker}' encontrado na conversa"

        except Exception:
            pass
        return ""

    def _dismiss_invalid_number_popup(self):
        """
        Fecha o popup de número inválido clicando no botão OK ou enviando ESC.
        O WhatsApp Web mostra um botão "OK" no popup de erro.
        """
        try:
            # Tenta clicar no botão OK do popup
            buttons = self._driver.find_elements(
                By.CSS_SELECTOR,
                'div[role="dialog"] button, div[role="dialog"] div[role="button"]'
            )
            for btn in buttons:
                try:
                    text = (btn.text or "").strip().lower()
                    if text in ("ok", "fechar", "close"):
                        btn.click()
                        time.sleep(0.5)
                        return
                except Exception:
                    continue
            # Fallback: ESC
            ActionChains(self._driver).send_keys(Keys.ESCAPE).perform()
            time.sleep(0.5)
        except Exception:
            pass

    def _has_caption_field(self) -> bool:
        """
        Detecta o campo de legenda, que só existe no preview de foto/vídeo/
        documento — o editor de figurinha não tem legenda.
        """
        selectors = [
            'div[contenteditable="true"][aria-label*="legenda"]',
            'div[contenteditable="true"][aria-label*="caption"]',
            'div[data-testid="media-caption-input-container"]',
            'div[role="dialog"] div[contenteditable="true"]',
        ]
        for selector in selectors:
            try:
                for el in self._driver.find_elements(By.CSS_SELECTOR, selector):
                    if el.is_displayed():
                        return True
            except Exception:
                continue
        return False

    def _looks_like_sticker_editor(self, texto: str) -> bool:
        """
        Decide se o modal aberto é o editor de figurinha.

        Cuidado: o editor de foto tem uma ferramenta de figurinha/emoji, então a
        simples presença da palavra não basta — só conta como figurinha se o
        texto for inequívoco ou se não houver campo de legenda no modal.
        """
        if not texto:
            return False
        if any(m in texto for m in self._STICKER_STRONG_MARKERS):
            return True
        if any(m in texto for m in self._STICKER_MARKERS):
            return not self._has_caption_field()
        return False

    # Tempo que o preview de uma imagem pode ficar aberto sem campo de legenda
    # antes de ser considerado editor de figurinha
    _STICKER_GRACE_SECONDS = 4.0

    def _detect_attach_preview(self, is_image_video: bool, timeout: float = 20.0) -> str:
        """
        Aguarda o preview do anexo abrir e diz qual preview é.

        O discriminador confiável é o CAMPO DE LEGENDA: o preview de foto/vídeo
        tem legenda, o editor de figurinha não (foi o que o diagnóstico mostrou —
        modal sem legenda, botão enviar presente, imagem chegando pequena).

        Retorna:
          "midia"     → preview correto (foto grande com legenda / documento)
          "figurinha" → editor de figurinha; o arquivo foi pelo caminho errado
          ""          → nada abriu
        """
        fim = time.time() + timeout
        botao_visto_em = None

        while time.time() < fim:
            if self._looks_like_sticker_editor(self._modal_text()):
                return "figurinha"

            if self._has_caption_field():
                return "midia"

            if self._find_send_button_modal(timeout=0.3):
                if botao_visto_em is None:
                    botao_visto_em = time.time()
                elif not is_image_video:
                    # Documento: preview sem legenda é normal
                    return "midia"
                elif time.time() - botao_visto_em >= self._STICKER_GRACE_SECONDS:
                    # Imagem com preview aberto e sem legenda = editor de figurinha
                    return "figurinha"

            if self._interruptible_sleep(0.4):
                return ""  # Stop requested, abort

        return ""

    def _close_modal(self):
        """Fecha o modal aberto (ESC) e dá tempo do DOM se reorganizar."""
        try:
            ActionChains(self._driver).send_keys(Keys.ESCAPE).perform()
            time.sleep(0.8)
            # Alguns modais pedem confirmação de descarte
            ActionChains(self._driver).send_keys(Keys.ESCAPE).perform()
            time.sleep(0.5)
        except Exception:
            pass

    # Botão de anexo (o "+" ao lado do campo de mensagem)
    _ATTACH_BUTTON_SELECTORS = [
        'button[aria-label="Anexar"]',
        'button[aria-label="Attach"]',
        'span[data-icon="plus-rounded"]',
        'span[data-icon="plus"]',
        'span[data-icon="clip"]',
        'span[data-icon="attach-menu-plus"]',
        '[data-testid="clip"]',
    ]

    # Rótulos dos itens do menu de anexo, por tipo de arquivo
    _MENU_LABELS_MIDIA = ("fotos e vídeos", "fotos e videos", "photos & videos")
    _MENU_LABELS_DOCUMENTO = ("documento", "document")

    def _open_attach_menu(self, pessoa: str) -> bool:
        """Abre o menu de anexo. Só abrir o menu não dispara janela nativa."""
        for seletor in self._ATTACH_BUTTON_SELECTORS:
            try:
                elementos = self._driver.find_elements(By.CSS_SELECTOR, seletor)
            except Exception as e:
                if self._is_session_dead(e):
                    raise BrowserClosedError(str(e))
                continue

            for el in elementos:
                try:
                    if not el.is_displayed():
                        continue
                    el.click()
                    time.sleep(random.uniform(0.8, 1.5))
                    file_logger.info(f"Menu de anexo aberto via: {seletor}")
                    return True
                except Exception as e:
                    if self._is_session_dead(e):
                        raise BrowserClosedError(str(e))
                    continue

        file_logger.error(f"Não encontrou o botão de anexo para {pessoa}")
        return False

    def _find_menu_item(self, is_image_video: bool):
        """
        Encontra o item do menu de anexo ("Fotos e vídeos" ou "Documento").

        O casamento é exato contra a lista de rótulos — importante para não
        clicar em "Nova figurinha" por engano.
        """
        alvos = (
            self._MENU_LABELS_MIDIA if is_image_video else self._MENU_LABELS_DOCUMENTO
        )
        for seletor in ("button", 'div[role="button"]', "li"):
            try:
                elementos = self._driver.find_elements(By.CSS_SELECTOR, seletor)
            except Exception:
                continue
            for el in elementos:
                try:
                    if not el.is_displayed():
                        continue
                    rotulo = (el.get_attribute("aria-label") or el.text or "").strip().lower()
                    if rotulo in alvos:
                        file_logger.info(f"Item de menu '{rotulo}' encontrado em <{seletor}>")
                        return el
                except Exception:
                    continue
        return None

    def _abrir_menu_e_achar_item(self, is_image_video: bool, pessoa: str):
        """
        Deixa o menu de anexo aberto e devolve o item desejado.

        O botão "+" é um toggle: se o menu já estiver aberto, clicar nele fecha.
        Por isso o item é procurado antes de qualquer clique, e uma segunda
        tentativa é feita caso o clique tenha fechado o menu.
        """
        item = self._find_menu_item(is_image_video)
        if item is not None:
            return item

        for _ in range(2):
            if not self._open_attach_menu(pessoa):
                return None
            item = self._find_menu_item(is_image_video)
            if item is not None:
                return item
            file_logger.warning(
                "Item não apareceu após abrir o menu de anexo — o clique pode ter "
                "fechado um menu que já estava aberto; tentando de novo"
            )
            time.sleep(0.8)

        return None

    def _send_media_via_dialog(self, abs_path: str, is_image_video: bool, pessoa: str) -> str:
        """
        Anexa o arquivo pelo caminho oficial: menu de anexo → "Fotos e vídeos"
        (ou "Documento") → janela nativa do Windows preenchida via mensagens
        Win32. É o que garante FOTO GRANDE em vez de figurinha.

        O clique no item do menu roda em outra thread porque ele só retorna
        quando a janela nativa fecha.

        Retorna "" em caso de sucesso, ou o motivo da falha.
        """
        if not win_dialog.IS_WINDOWS:
            return "sistema não é Windows"

        item = self._abrir_menu_e_achar_item(is_image_video, pessoa)
        if item is None:
            esperado = "Fotos e vídeos" if is_image_video else "Documento"
            self._close_modal()
            return f"não encontrou '{esperado}' no menu de anexo"

        dialogs_antes = win_dialog.list_dialogs()
        falha_clique = {}

        def clicar():
            try:
                item.click()
            except Exception as e:  # noqa: BLE001 - reportado na thread principal
                falha_clique["erro"] = e

        thread = threading.Thread(target=clicar, daemon=True)
        thread.start()

        dialog = win_dialog.wait_for_new_dialog(dialogs_antes, timeout=20.0)
        if dialog is None:
            thread.join(timeout=5)
            if "erro" in falha_clique:
                return f"clique no item do menu falhou ({falha_clique['erro']})"
            return "a janela de arquivos do Windows não abriu"

        file_logger.info(f"Janela de arquivos aberta (hwnd={dialog}); escolhendo {abs_path}")

        if not win_dialog.choose_file(dialog, abs_path):
            win_dialog.cancel_dialog(dialog)
            thread.join(timeout=5)
            return "não foi possível preencher a janela de arquivos do Windows"

        thread.join(timeout=15)
        return ""

    def _send_media(self, media_path: str, pessoa: str, human: bool = False):
        """
        Envia um arquivo no chat atual.

        Caminho principal (Windows): menu de anexo → "Fotos e vídeos" /
        "Documento" → janela nativa preenchida por mensagens Win32. É o fluxo
        oficial do WhatsApp, o único que entrega FOTO GRANDE.

        Por que não os outros caminhos (todos testados no WhatsApp Web atual):
          - o único input[type=file] do DOM tem accept="image/*" e abre o editor
            de FIGURINHA (a imagem chega pequena);
          - evento de drop sintético (DataTransfer via JS) é ignorado.

        Fallback: input[type=file]. Para imagem/vídeo, um preview sem campo de
        legenda é tratado como figurinha e descartado — nunca enviado.
        """
        is_image_video = self._is_image_or_video(media_path)
        tipo = "foto/vídeo" if is_image_video else "documento"
        abs_path = os.path.abspath(media_path)
        file_logger.info(f"Enviando {abs_path} como {tipo} para {pessoa}")

        ultimo_erro = "não foi possível abrir o preview do anexo"

        # --- Caminho principal: menu + janela nativa do Windows ---
        if win_dialog.IS_WINDOWS:
            erro = self._send_media_via_dialog(abs_path, is_image_video, pessoa)
            if erro:
                ultimo_erro = erro
                file_logger.warning(f"Caminho do menu de anexo falhou: {erro}")
            else:
                resultado = self._detect_attach_preview(is_image_video, timeout=25.0)
                file_logger.info(f"Preview após a janela nativa: '{resultado or 'nenhum'}'")

                if resultado == "midia":
                    self._finalizar_envio_de_anexo(pessoa, media_path, tipo)
                    return

                if resultado == "figurinha":
                    ultimo_erro = "o menu de anexo abriu o editor de figurinha"
                    file_logger.warning(ultimo_erro)
                    self._close_modal()
                else:
                    ultimo_erro = "o preview não abriu depois de escolher o arquivo"
                    file_logger.warning(ultimo_erro)
                    self._close_modal()

        # --- Fallback: input[type=file] ---
        file_logger.warning(
            f"Tentando os input[type=file] como fallback para {pessoa} ({ultimo_erro})"
        )
        ja_tentados = set()

        for _ in range(4):
            candidato = self._pick_file_input(is_image_video, ja_tentados)
            if not candidato:
                break

            classe, accept, file_input = candidato
            ja_tentados.add(accept)
            file_logger.info(f"Tentando input [{classe}] accept='{accept}' para {pessoa}")

            self._reveal_file_input(file_input)
            try:
                file_input.send_keys(abs_path)
            except Exception as e:
                if self._is_session_dead(e):
                    raise BrowserClosedError(str(e))
                ultimo_erro = f"input [{classe}] recusou o arquivo ({e})"
                file_logger.warning(ultimo_erro)
                continue

            resultado = self._detect_attach_preview(is_image_video, timeout=20.0)

            if resultado == "figurinha":
                ultimo_erro = f"input [{classe}] abriu o editor de figurinha"
                file_logger.warning(f"{ultimo_erro} — descartando e tentando outro input")
                self._close_modal()
                continue

            if not resultado:
                ultimo_erro = f"preview do anexo não abriu pelo input [{classe}]"
                file_logger.warning(ultimo_erro)
                self._close_modal()
                continue

            self._finalizar_envio_de_anexo(pessoa, media_path, tipo)
            return

        raise RuntimeError(
            f"Não foi possível anexar {os.path.basename(media_path)} para {pessoa}: {ultimo_erro}"
        )

    def _finalizar_envio_de_anexo(self, pessoa: str, media_path: str, tipo: str):
        """Com o preview correto aberto, clica em enviar e confirma o envio."""
        self._interruptible_sleep(random.uniform(1.0, 2.0))
        if self._should_stop():
            self._close_modal()
            raise RuntimeError("Parada solicitada durante envio de anexo")
        send_btn = self._click_send_button_modal(pessoa)

        if not self._wait_attachment_sent(send_btn, timeout=30.0):
            file_logger.warning(
                f"Modal de anexo não fechou para {pessoa} após clicar em enviar — "
                f"verifique a conversa manualmente"
            )

        self._interruptible_sleep(random.uniform(2.0, 4.0))
        self._log(f"📎 Anexo enviado para {pessoa} como {tipo}: {os.path.basename(media_path)}")
        file_logger.info(
            f"Mídia enviada como {tipo} para {pessoa}: {os.path.abspath(media_path)}"
        )

    def _type_caption_in_modal(self, caption: str, pessoa: str, human: bool = False):
        """
        Digita a legenda (caption) no campo de texto do modal de preview de imagem.
        O modal de foto/vídeo tem um campo editável para adicionar legenda.
        """
        caption_selectors = [
            'div[contenteditable="true"][data-testid="media-caption-input-container"]',
            'div.copyable-text[contenteditable="true"][data-tab]',
            # O modal tem um contenteditable que NÃO é o footer
            'div[role="dialog"] div[contenteditable="true"]',
            'div.overlay div[contenteditable="true"]',
            # Genérico: segundo contenteditable na página (o primeiro é o chat principal)
        ]

        caption_field = None
        for selector in caption_selectors:
            try:
                caption_field = WebDriverWait(self._driver, 5).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                )
                if caption_field:
                    file_logger.info(f"Campo de legenda encontrado via: {selector}")
                    break
            except (TimeoutException, Exception):
                continue

        # Fallback: procura contenteditable que NÃO seja o footer
        if not caption_field:
            try:
                fields = self._driver.find_elements(
                    By.CSS_SELECTOR, 'div[contenteditable="true"]'
                )
                for f in fields:
                    # Pula o campo de texto do chat (que está no footer)
                    try:
                        parent = f.find_element(By.XPATH, "./ancestor::footer")
                        continue  # É o campo do footer, pula
                    except Exception:
                        pass
                    caption_field = f
                    file_logger.info("Campo de legenda encontrado via fallback (non-footer contenteditable)")
                    break
            except Exception:
                pass

        if not caption_field:
            file_logger.warning(f"Não encontrou campo de legenda para {pessoa} — enviando sem caption")
            return

        # Clica no campo para focar
        caption_field.click()
        time.sleep(random.uniform(0.3, 0.6))

        # Limpa qualquer texto residual no campo de legenda
        self._clear_input_field(caption_field)

        # Digita a legenda
        if human:
            self._human_type(caption_field, caption)
        else:
            self._type_with_newlines(caption_field, caption)

        time.sleep(random.uniform(0.5, 1.0))

    # Seletores do botão "enviar" do preview de anexo
    _SEND_BUTTON_SELECTORS = [
        '[data-testid="send"]',
        'span[data-icon="wds-ic-send-filled"]',
        'span[data-icon="send"]',
        'span[data-icon="send-light"]',
        'div[role="button"][aria-label*="Enviar"]',
        'div[role="button"][aria-label*="Send"]',
        'button[aria-label="Enviar"]',
        'button[aria-label="Send"]',
    ]

    def _find_send_button_modal(self, timeout: float = 10.0):
        """
        Procura o botão de enviar do modal de preview de anexo.
        Retorna o elemento visível ou None. Não levanta exceção.
        """
        fim = time.time() + max(0.1, timeout)
        while True:
            for selector in self._SEND_BUTTON_SELECTORS:
                try:
                    for btn in self._driver.find_elements(By.CSS_SELECTOR, selector):
                        if btn.is_displayed():
                            return btn
                except Exception:
                    continue
            if time.time() >= fim:
                return None
            time.sleep(0.3)

    def _click_send_button_modal(self, pessoa: str):
        """
        Clica no botão enviar do modal de preview de anexo.
        Retorna o elemento clicado (usado para detectar o fechamento do modal).
        """
        btn = self._find_send_button_modal(timeout=10.0)
        if btn is None:
            self._close_modal()
            raise RuntimeError(f"Não encontrou botão enviar no modal para {pessoa}")

        try:
            btn.click()
        except Exception as e:
            if self._is_session_dead(e):
                raise BrowserClosedError(str(e))
            # Ícone pode estar coberto pelo <button> pai: clica via JS
            file_logger.warning(f"Clique direto no enviar falhou ({e}), tentando via JS")
            try:
                self._driver.execute_script("arguments[0].click();", btn)
            except Exception as e2:
                self._close_modal()
                raise RuntimeError(f"Não conseguiu clicar em enviar para {pessoa}: {e2}")

        return btn

    def _wait_attachment_sent(self, send_btn, timeout: float = 30.0) -> bool:
        """
        Espera o modal de anexo fechar (o botão enviar fica stale ou invisível),
        o que confirma que o WhatsApp aceitou o envio.
        """
        fim = time.time() + timeout
        while time.time() < fim:
            try:
                if not send_btn.is_displayed():
                    return True
            except StaleElementReferenceException:
                return True
            except Exception:
                return True
            if self._interruptible_sleep(0.5):
                return True  # Stop requested — attachment already sent
        return False

    def start(self):
        """
        Método principal de envio. Deve ser executado em uma thread separada.
        Abre o Chrome, aguarda QR, e inicia o envio por rodadas.
        """
        with self._lock:
            self._running = True
        self._stop_event.clear()

        try:
            # Inicializa o driver
            self._set_state("iniciando")
            self._log("Iniciando navegador Chrome...")

            try:
                self._driver = self._init_driver()
            except Exception as e:
                self._set_state("erro")
                self._log(f"ERRO: Não foi possível iniciar o Chrome: {e}")
                return

            # Abre WhatsApp Web
            self._driver.get("https://web.whatsapp.com")
            self._log("WhatsApp Web aberto. Verificando sessão...")

            # Verifica se a sessão já está ativa (login instantâneo via perfil salvo)
            try:
                WebDriverWait(self._driver, 8).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "#pane-side"))
                )
                self._log("✅ Sessão ativa detectada! Login automático via perfil salvo.")
            except TimeoutException:
                # Sessão não estava ativa — precisa escanear QR Code
                self._set_state("waiting_qr")
                self._log("⏳ Sessão não encontrada. Escaneie o QR Code no navegador...")

                try:
                    WebDriverWait(self._driver, 120).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, "#pane-side"))
                    )
                    self._log("✅ Login realizado com sucesso!")
                except TimeoutException:
                    self._set_state("erro")
                    self._log("ERRO: Tempo esgotado aguardando QR Code. Tente novamente.")
                    self._cleanup()
                    return

            if self._should_stop():
                self._set_state("parado")
                self._log("🛑 Envio interrompido pelo usuário.")
                self._cleanup()
                return

            # Carrega contatos
            df = self._load_contacts()
            with self._lock:
                self._total_contacts = len(df)

            # Configurações
            total_msgs = self.config.get("total_msgs", 10)
            tempo_minutos = self.config.get("tempo_minutos", 60)

            # Gera plano de envio em bursts (rajadas irregulares)
            burst_plan = self._generate_burst_plan(total_msgs, tempo_minutos)
            total_bursts = len(burst_plan)

            # Inicia envio por bursts
            self._set_state("enviando")
            browser_died = False

            # Carrega contatos pendentes
            df = self._load_contacts()
            pending = self._get_pending_contacts(df)

            # --- Detecção de duplicados ---
            # Se allow_duplicates está desativado, marca duplicados como inválidos
            allow_duplicates = self.config.get("allow_duplicates", False)
            if not allow_duplicates:
                numeros_vistos: dict[str, int] = {}
                duplicados_indices = []
                for idx, row in pending.iterrows():
                    num_norm = self._clean_number(row["Número"])
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
                        self._notify_contact_update(idx, num_norm, "invalido", "", motivo)
                        self._log(f"[SKIP] {pessoa} ({num_norm}) — número duplicado, pulando.")
                    else:
                        numeros_vistos[num_norm] = idx

                if duplicados_indices:
                    self._save_contacts(df)
                    # Recarrega pendentes sem os duplicados
                    pending = self._get_pending_contacts(df)
                    self._log(f"⚠️ {len(duplicados_indices)} contato(s) com número duplicado marcado(s) como inválido(s).")
            else:
                # Modo teste: reabilita contatos que foram invalidados por duplicata em execução anterior
                reabilitados = 0
                for idx, row in df.iterrows():
                    if str(row.get("Invalido", "")).strip().upper() == "X":
                        motivo = str(row.get("Motivo", "")).lower()
                        if "duplicado" in motivo:
                            df.at[idx, "Invalido"] = ""
                            df.at[idx, "Motivo"] = ""
                            reabilitados += 1
                if reabilitados > 0:
                    self._save_contacts(df)
                    pending = self._get_pending_contacts(df)
                    self._log(f"🔄 {reabilitados} contato(s) duplicado(s) reabilitado(s) (modo teste ativo).")

            # Log de contatos já processados
            enviados_df = df[df["Enviado"] == "X"]
            invalidos_df = df[df["Invalido"] == "X"]
            if len(enviados_df) > 0:
                for _, row in enviados_df.iterrows():
                    self._log(f"[SKIP] {row['Nome']} — já enviado, pulando.")
            if len(invalidos_df) > 0:
                for _, row in invalidos_df.iterrows():
                    self._log(f"[SKIP] {row['Nome']} — número inválido, pulando.")

            with self._lock:
                self._total_pending = len(pending)
                self._total_invalids = len(invalidos_df)

            if len(pending) == 0:
                self._log("✅ Todos os contatos já foram processados!")
            else:
                self._log(
                    f"📤 Iniciando envio: {len(pending)} pendentes, "
                    f"{total_bursts} rajadas planejadas em {tempo_minutos}min"
                )

                # Iterador dos contatos pendentes
                pending_iter = pending.iterrows()
                total_enviados_sessao = 0

                for burst_idx, burst in enumerate(burst_plan):
                    if self._should_stop() or browser_died:
                        break

                    # Verifica horário comercial antes de cada burst
                    self._wait_for_business_hours()
                    if self._should_stop():
                        break

                    burst_size = burst["burst_size"]
                    intra_delay = burst["intra_delay"]
                    pause_after = burst["pause_after"]

                    with self._lock:
                        self._current_round = burst_idx + 1

                    self._log(
                        f"📨 Rajada {burst_idx + 1}/{total_bursts} "
                        f"({burst_size} msgs, ~{intra_delay:.0f}s entre)"
                    )

                    enviados_burst = 0

                    for msg_in_burst in range(burst_size):
                        if self._should_stop() or browser_died:
                            break

                        # Pega próximo contato pendente
                        try:
                            idx, row = next(pending_iter)
                        except StopIteration:
                            # Não há mais contatos pendentes
                            self._log("✅ Todos os contatos foram processados!")
                            break

                        # Verifica horário comercial antes de cada mensagem
                        self._wait_for_business_hours()
                        if self._should_stop():
                            break

                        pessoa = str(row["Nome"])
                        numero = self._clean_number(row["Número"])
                        mensagem = str(row["Mensagem"])
                        arquivo = str(row.get("Arquivo", "")).strip()
                        if arquivo.lower() in ("", "nan", "none"):
                            arquivo = ""
                        usou_global = False
                        if mensagem.strip().lower() in ("", "nan", "none") and self.global_message.strip():
                            mensagem = self.global_message
                            usou_global = True

                        # Validação prévia
                        valido, motivo = self._validate_contact(numero, mensagem)
                        if not valido:
                            df.at[idx, "Invalido"] = "X"
                            if motivo == "mensagem vazia":
                                tooltip_motivo = "Coluna Mensagem vazia e sem mensagem global ativa."
                            elif motivo == "número ausente":
                                tooltip_motivo = "Coluna Número vazia. Preencha com DDD + telefone."
                            elif motivo == "número inválido":
                                tooltip_motivo = "Número com menos de 10 dígitos. Confira DDD + telefone."
                            else:
                                tooltip_motivo = motivo
                            df.at[idx, "Motivo"] = tooltip_motivo
                            self._save_contacts(df)

                            with self._lock:
                                self._total_pending -= 1
                                self._total_invalids += 1

                            file_logger.warning(f"Contato inválido ({motivo}): {pessoa} ({numero})")
                            self._log(f"❌ {pessoa} ({numero}) — {motivo}, marcado como inválido.")
                            self._notify_contact_update(idx, numero, "invalido", "", tooltip_motivo)
                            # Contato inválido não conta como msg do burst — tenta o próximo
                            # mas precisa compensar no burst_size
                            burst_size += 1
                            continue

                        self._log(
                            f"Enviando para {pessoa} ({numero})"
                            f"{' [mensagem global]' if usou_global else ''}..."
                        )

                        try:
                            success = self._send_message(pessoa, numero, mensagem, arquivo)

                            if success:
                                df.at[idx, "Enviado"] = "X"
                                data_envio = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                df.at[idx, "DataEnvio"] = data_envio
                                self._save_contacts(df)

                                with self._lock:
                                    self._messages_sent += 1
                                    self._total_pending -= 1

                                enviados_burst += 1
                                total_enviados_sessao += 1
                                self._log(f"✅ {pessoa} — mensagem enviada com sucesso.")
                                self._notify_contact_update(idx, numero, "enviado", data_envio)
                            else:
                                # Falha no envio: marca como inválido imediatamente
                                tooltip_motivo = "Falha ao enviar mensagem (veja o log para detalhes)."
                                df.at[idx, "Invalido"] = "X"
                                df.at[idx, "Motivo"] = tooltip_motivo
                                self._save_contacts(df)
                                with self._lock:
                                    self._total_pending -= 1
                                    self._total_invalids += 1
                                self._notify_contact_update(idx, numero, "invalido", "", tooltip_motivo)
                                # Compensa no burst para tentar o próximo contato
                                burst_size += 1

                        except BrowserClosedError as e:
                            file_logger.error(
                                f"Navegador fechado durante o envio para {pessoa} ({numero}): {e}"
                            )
                            self._log(
                                "🛑 O navegador foi fechado ou perdeu a conexão. "
                                "Envio abortado — os pendentes continuam para a próxima execução."
                            )
                            browser_died = True
                            break

                        except AttachmentError as e:
                            # Falha no anexo: marca como inválido IMEDIATAMENTE, sem
                            # retentativas. A mensagem de texto NÃO foi enviada.
                            tooltip_motivo = f"Falha no anexo: {e}"
                            df.at[idx, "Invalido"] = "X"
                            df.at[idx, "Motivo"] = tooltip_motivo
                            self._save_contacts(df)
                            with self._lock:
                                self._total_pending -= 1
                                self._total_invalids += 1
                            file_logger.error(
                                f"Anexo falhou para {pessoa} ({numero}): {e} — "
                                f"contato marcado como inválido (texto NÃO enviado)"
                            )
                            self._log(
                                f"❌ {pessoa} ({numero}) — falha no anexo: {e}. "
                                f"Mensagem NÃO enviada, contato marcado como inválido."
                            )
                            self._notify_contact_update(idx, numero, "invalido", "", tooltip_motivo)
                            # Compensa no burst para tentar o próximo contato
                            burst_size += 1

                        except InvalidNumberError as e:
                            # O WhatsApp Web indicou que o número é inválido ou
                            # o contato está bloqueado. A mensagem da exceção
                            # contém o detalhe (popup vs. botão Desbloquear).
                            erro_str = str(e)
                            if "bloqueado" in erro_str.lower() or "blocked" in erro_str.lower():
                                tooltip_motivo = (
                                    "Contato bloqueado no seu WhatsApp. "
                                    "Desbloqueie para enviar."
                                )
                                log_msg = (
                                    f"🚫 {pessoa} ({numero}) — contato bloqueado no "
                                    f"seu WhatsApp. Desbloqueie para enviar."
                                )
                            else:
                                tooltip_motivo = (
                                    "Número rejeitado pelo WhatsApp "
                                    "(inexistente ou inválido)."
                                )
                                log_msg = (
                                    f"❌ {pessoa} ({numero}) — número rejeitado pelo "
                                    f"WhatsApp (inexistente ou inválido)."
                                )
                            df.at[idx, "Invalido"] = "X"
                            df.at[idx, "Motivo"] = tooltip_motivo
                            self._save_contacts(df)

                            with self._lock:
                                self._total_pending -= 1
                                self._total_invalids += 1

                            file_logger.warning(
                                f"Número rejeitado: {pessoa} ({numero}) — {e}"
                            )
                            self._log(log_msg)
                            self._notify_contact_update(
                                idx, numero, "invalido", "", tooltip_motivo,
                            )
                            # Compensa no burst para tentar o próximo contato
                            burst_size += 1

                        except TimeoutException:
                            df.at[idx, "Invalido"] = "X"
                            df.at[idx, "Motivo"] = "Número não encontrado no WhatsApp (timeout ao abrir conversa)."
                            self._save_contacts(df)

                            with self._lock:
                                self._total_pending -= 1
                                self._total_invalids += 1

                            file_logger.warning(f"Número inválido (timeout): {pessoa} ({numero})")
                            self._log(f"❌ {pessoa} ({numero}) — número inválido ou não encontrado no WhatsApp.")
                            self._notify_contact_update(
                                idx, numero, "invalido", "",
                                "Número não encontrado no WhatsApp (timeout ao abrir conversa).",
                            )

                        except Exception as e:
                            if self._is_session_dead(e):
                                file_logger.error(f"Sessão morta em {pessoa} ({numero}): {e}")
                                self._log("🛑 O navegador foi fechado ou perdeu a conexão. Envio abortado.")
                                browser_died = True
                                break
                            file_logger.error(f"Erro ao enviar para {pessoa} ({numero}): {e}\n{traceback.format_exc()}")
                            self._log(f"❌ {pessoa} ({numero}) — erro inesperado: {e}")
                            # Marca como inválido imediatamente com o erro no tooltip
                            tooltip_motivo = f"Erro inesperado: {e}"
                            df.at[idx, "Invalido"] = "X"
                            df.at[idx, "Motivo"] = tooltip_motivo
                            self._save_contacts(df)
                            with self._lock:
                                self._total_pending -= 1
                                self._total_invalids += 1
                            self._notify_contact_update(idx, numero, "invalido", "", tooltip_motivo)
                            # Compensa no burst para tentar o próximo contato
                            burst_size += 1

                        # Delay intra-burst (entre msgs dentro da rajada)
                        # Pulado na última msg do burst e quando vai parar
                        if (
                            not self._should_stop()
                            and not browser_died
                            and msg_in_burst < burst_size - 1
                        ):
                            # Variação gaussiana no intra_delay para ser mais natural
                            if self._human_behavior_enabled():
                                delay = self._gaussian_delay(
                                    intra_delay * 0.7, intra_delay * 1.3
                                )
                            else:
                                delay = random.uniform(intra_delay * 0.8, intra_delay * 1.2)
                            self._log(f"Aguardando {delay:.0f}s...")
                            time.sleep(delay)

                    # Fim do burst — log e pausa entre bursts
                    self._log(f"📊 Rajada {burst_idx + 1} finalizada: {enviados_burst} msgs enviadas")

                    if browser_died:
                        break

                    # Verifica se ainda há pendentes
                    df = self._load_contacts()
                    remaining = self._get_pending_contacts(df)
                    with self._lock:
                        self._total_pending = len(remaining)

                    if len(remaining) == 0:
                        self._log("✅ Todos os contatos foram processados!")
                        break

                    # Pausa entre bursts (a última rajada não tem pausa)
                    if (
                        pause_after > 0
                        and burst_idx < total_bursts - 1
                        and not self._should_stop()
                    ):
                        pause_min = pause_after / 60
                        self._log(f"⏸️ Pausa de ~{pause_min:.1f} min antes da próxima rajada...")

                        # Espera em intervalos curtos para poder parar
                        elapsed = 0
                        while elapsed < pause_after and not self._should_stop():
                            time.sleep(min(2, pause_after - elapsed))
                            elapsed += 2

            # Finalização
            if browser_died:
                self._set_state("erro")
                status = self.get_status()
                self._log(
                    f"⚠️ Envio interrompido: o navegador foi fechado. "
                    f"Enviadas {status['messages_sent']} mensagens antes da interrupção. "
                    f"Clique em Iniciar Envio para retomar de onde parou."
                )
            elif self._should_stop():
                self._set_state("parado")
                self._log("🛑 Envio interrompido pelo usuário.")
            else:
                self._set_state("finalizado")
                status = self.get_status()
                self._log(
                    f"🎉 Envio finalizado! Total enviado: {status['messages_sent']} mensagens"
                )

        except Exception as e:
            self._set_state("erro")
            file_logger.error(f"ERRO FATAL: {e}\n{traceback.format_exc()}")
            self._log(f"ERRO FATAL: {e}")
        finally:
            self._cleanup()

    def _cleanup(self):
        """Fecha o navegador e limpa recursos."""
        with self._lock:
            self._running = False

        if self._driver:
            try:
                self._log("Fechando navegador...")
                # Fecha em thread separada com timeout para não travar
                import threading
                def quit_driver():
                    try:
                        self._driver.quit()
                    except Exception:
                        pass

                t = threading.Thread(target=quit_driver, daemon=True)
                t.start()
                t.join(timeout=5)
                self._log("Navegador fechado.")
            except Exception:
                self._log("Navegador encerrado (forçado).")
            self._driver = None
