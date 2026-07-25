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
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import TimeoutException, WebDriverException

# Logger de arquivo para diagnóstico (compartilhado com app.py)
file_logger = logging.getLogger("whatsapp_sender_file")


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
        contact_update_callback: Optional[Callable[[str, str, str], None]] = None,
    ):
        self.excel_path = excel_path
        self.config = config
        self.log_callback = log_callback or print
        self.contact_update_callback = contact_update_callback

        # Estado interno (thread-safe)
        self._lock = threading.Lock()
        self._state = "aguardando"  # aguardando, waiting_qr, enviando, pausado, finalizado, erro, parado
        self._current_round = 0
        self._messages_sent = 0
        self._total_pending = 0
        self._total_contacts = 0
        self._running = False
        self._stop_requested = False

        # Selenium
        self._driver: Optional[webdriver.Chrome] = None

    def _log(self, message: str):
        """Envia mensagem para o callback de log."""
        if self.log_callback:
            self.log_callback(message)

    def _notify_contact_update(self, numero: str, status: str, data_envio: str = ""):
        """Notifica o frontend sobre mudança de status de um contato."""
        if self.contact_update_callback:
            try:
                self.contact_update_callback(numero, status, data_envio)
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
            }

    def is_running(self) -> bool:
        """Verifica se o sender está rodando."""
        with self._lock:
            return self._running

    def stop(self):
        """Solicita parada graceful do envio."""
        with self._lock:
            self._stop_requested = True
        self._log("Parada solicitada. Finalizando após mensagem atual...")

    def _should_stop(self) -> bool:
        """Verifica se deve parar."""
        with self._lock:
            return self._stop_requested

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

    def _wait_for_business_hours(self):
        """Aguarda até o próximo horário comercial."""
        if self._is_business_hours():
            return

        self._set_state("pausado")
        self._log("Fora do horário comercial. Aguardando próximo horário...")

        while not self._is_business_hours() and not self._should_stop():
            time.sleep(2)  # Verifica a cada 2s para responder rápido ao stop

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
        return df

    def _save_contacts(self, df: pd.DataFrame):
        """Salva a planilha com progresso atualizado."""
        df.to_excel(self.excel_path, index=False)

    def _get_pending_contacts(self, df: pd.DataFrame) -> pd.DataFrame:
        """Retorna contatos pendentes (não enviados e não inválidos)."""
        mask = (df["Enviado"] != "X") & (df["Invalido"] != "X")
        return df[mask]

    def _clean_number(self, numero) -> str:
        """
        Normaliza um número de telefone vindo da planilha, retornando
        apenas os dígitos.

        Trata o caso comum em que o pandas lê a coluna como float
        (ex: 19994229146 -> "19994229146.0"), o que adicionaria um "0"
        extra indevido ao final se apenas filtrássemos os dígitos.
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

        return "".join(c for c in numero_str if c.isdigit())

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

    def _human_type(self, element, text: str):
        """
        Digita texto caractere por caractere com micro-pausas variáveis,
        simulando digitação humana.
        """
        for char in text:
            element.send_keys(char)
            # Pausa entre teclas: mais rápido em sequência, mais lento em espaços/pontuação
            if char in (' ', '.', ',', '!', '?', '\n'):
                time.sleep(random.uniform(0.08, 0.25))
            else:
                time.sleep(random.uniform(0.03, 0.12))
            # Ocasionalmente uma pausa maior (como se pensasse)
            if random.random() < 0.02:
                time.sleep(random.uniform(0.3, 0.8))

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
            time.sleep(random.uniform(0.5, 1.5))
            # Volta ao topo
            self._driver.execute_script("arguments[0].scrollTop = 0;", pane)
            time.sleep(random.uniform(0.3, 0.8))
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

    def _send_message(self, pessoa: str, numero: str, mensagem: str, arquivo: str = "") -> bool:
        """
        Envia uma mensagem para um contato.
        Se há arquivo associado, envia primeiro o texto e depois o anexo separadamente.
        Se não há arquivo, envia apenas texto.
        Retorna True se enviou com sucesso, False se falhou.
        Levanta TimeoutException se número é inválido.
        """
        # Formata mensagem
        pessoa_limpo = pessoa.strip() if pessoa else ""
        if pessoa_limpo and pessoa_limpo.lower() not in ("nan", "none", ""):
            texto = f"Oi {pessoa_limpo}, {mensagem}"
        else:
            texto = mensagem

        # Formata número (remove caracteres não numéricos e notação float)
        numero_limpo = self._clean_number(numero)
        if not numero_limpo.startswith("55"):
            numero_limpo = "55" + numero_limpo

        human = self._human_behavior_enabled()
        
        # Suporta múltiplos arquivos separados por vírgula
        media_files = []
        if arquivo:
            for f in arquivo.split(","):
                f = f.strip()
                if f and os.path.isfile(f):
                    media_files.append(f)
        has_media = len(media_files) > 0

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
            WebDriverWait(self._driver, 30).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "#pane-side"))
            )

            # Espera o chat carregar (campo de texto no rodapé)
            WebDriverWait(self._driver, 20).until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, "footer div[contenteditable='true']")
                )
            )

            # Pequena pausa antes de interagir
            if human:
                time.sleep(random.uniform(1.5, 4.0))
            else:
                time.sleep(random.uniform(1.5, 3.0))

            # Passo 1: Envia a mensagem de texto
            input_field = self._driver.find_element(
                By.CSS_SELECTOR, "footer div[contenteditable='true']"
            )

            if human:
                self._human_type(input_field, texto)
                time.sleep(random.uniform(0.8, 2.0))
            else:
                # Se não usou human, o texto já está no campo via URL (exceto com mídia)
                if has_media:
                    input_field.send_keys(texto)
                    time.sleep(random.uniform(0.5, 1.0))

            input_field.send_keys(Keys.ENTER)

            if human:
                time.sleep(random.uniform(2.0, 5.0))
            else:
                time.sleep(random.uniform(2.0, 4.0))

            # Passo 2: Se tem mídia, envia os anexos separadamente (sem legenda)
            if has_media:
                for media_file in media_files:
                    time.sleep(random.uniform(1.0, 2.0))
                    self._send_media(media_file, pessoa, human)

            return True

        except TimeoutException:
            raise  # Re-raise para marcar como inválido
        except Exception as e:
            file_logger.error(f"Erro no envio Selenium para {pessoa} ({numero_limpo}): {e}\n{traceback.format_exc()}")
            self._log(f"Erro ao enviar para {pessoa}: {e}")
            return False

    def _send_media(self, media_path: str, pessoa: str, human: bool = False):
        """
        Envia um arquivo de mídia no chat atual (sem legenda).
        A mensagem de texto já foi enviada separadamente antes desta chamada.
        Sempre envia como DOCUMENTO para evitar que imagens virem figurinha.
        
        Raises Exception se falhar (para que _send_message retorne False).
        """
        # Passo 1: Clicar no botão de anexo (clip/plus icon)
        attach_btn = None
        attach_selectors = [
            'span[data-icon="plus"]',
            'span[data-icon="clip"]',
            'span[data-icon="attach-menu-plus"]',
            'div[title="Anexar"]',
            'div[title="Attach"]',
            'button[aria-label="Anexar"]',
            'button[aria-label="Attach"]',
        ]

        for selector in attach_selectors:
            try:
                attach_btn = WebDriverWait(self._driver, 5).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, selector))
                )
                if attach_btn:
                    break
            except (TimeoutException, Exception):
                continue

        if not attach_btn:
            raise RuntimeError(f"Não encontrou botão de anexo para {pessoa}")

        attach_btn.click()
        time.sleep(random.uniform(1.0, 2.0))

        # Passo 2: Clicar na opção "Documento" do menu de anexo
        # Isso garante que o arquivo seja enviado como documento, não como imagem/figurinha
        doc_btn = None
        file_input = None
        doc_selectors = [
            'span[data-icon="attach-document"]',
            'button[aria-label="Documento"]',
            'button[aria-label="Document"]',
        ]

        for selector in doc_selectors:
            try:
                el = self._driver.find_element(By.CSS_SELECTOR, selector)
                if el:
                    doc_btn = el
                    break
            except Exception:
                continue

        # Se encontrou o botão de documento, clica nele
        if doc_btn:
            try:
                doc_btn.click()
                time.sleep(random.uniform(0.5, 1.0))
            except Exception:
                pass

        # Passo 3: Encontrar o input[type=file] para documento
        # Procura o input de documento (accept="*" ou sem accept restritivo de imagem)
        input_selectors = [
            'input[accept="*"]',
            'input[accept="*/*"]',
        ]

        for selector in input_selectors:
            try:
                file_input = WebDriverWait(self._driver, 5).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                )
                if file_input:
                    break
            except (TimeoutException, Exception):
                continue

        # Fallback: pega todos os inputs file e escolhe o que NÃO é de imagem
        if not file_input:
            try:
                inputs = self._driver.find_elements(By.CSS_SELECTOR, 'input[type="file"]')
                for inp in inputs:
                    accept = inp.get_attribute("accept") or ""
                    # Pula inputs que aceitam apenas imagem/vídeo
                    if "image/" in accept and "*" not in accept:
                        continue
                    file_input = inp
                    break
                # Se todos são de imagem, pega o último (geralmente é documento)
                if not file_input and inputs:
                    file_input = inputs[-1]
            except Exception:
                pass

        if not file_input:
            # Fecha o menu e levanta erro
            try:
                self._driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
            except Exception:
                pass
            raise RuntimeError(f"Não encontrou input de arquivo para {pessoa}")

        # Envia o caminho do arquivo para o input
        file_input.send_keys(os.path.abspath(media_path))

        # Passo 4: Aguardar o modal de preview carregar
        time.sleep(random.uniform(3.0, 5.0))

        # Passo 5: Clicar no botão de enviar do modal
        send_btn = None
        send_selectors = [
            'span[data-icon="wds-ic-send-filled"]',
            'div[role="button"][aria-label*="Enviar"]',
            'div[role="button"][aria-label*="Send"]',
            'span[data-icon="send"]',
            'span[data-icon="send-light"]',
            'button[aria-label="Enviar"]',
            'button[aria-label="Send"]',
        ]

        for selector in send_selectors:
            try:
                send_btn = WebDriverWait(self._driver, 10).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, selector))
                )
                if send_btn:
                    break
            except (TimeoutException, Exception):
                continue

        if not send_btn:
            # Tenta fechar o modal
            try:
                self._driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
            except Exception:
                pass
            raise RuntimeError(f"Não encontrou botão enviar no modal para {pessoa}")

        send_btn.click()

        # Aguarda envio completar
        time.sleep(random.uniform(3.0, 6.0))

        self._log(f"📎 Anexo enviado para {pessoa}: {os.path.basename(media_path)}")
        file_logger.info(f"Mídia enviada para {pessoa}: {media_path}")

    def start(self):
        """
        Método principal de envio. Deve ser executado em uma thread separada.
        Abre o Chrome, aguarda QR, e inicia o envio por rodadas.
        """
        with self._lock:
            self._running = True
            self._stop_requested = False

        try:
            # Inicializa o driver
            self._set_state("aguardando")
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
            msgs_por_rodada = self.config.get("msgs_por_rodada", 5)
            total_rodadas = self.config.get("total_rodadas", 3)
            intervalo_min = self.config.get("intervalo_rodadas_min", 30)

            # Inicia envio por rodadas
            self._set_state("enviando")
            compensacao = 0  # Rastreia débito/crédito entre rodadas para manter total exato

            for rodada in range(1, total_rodadas + 1):
                if self._should_stop():
                    break

                # Verifica horário comercial
                self._wait_for_business_hours()
                if self._should_stop():
                    break

                with self._lock:
                    self._current_round = rodada

                self._log(f"📤 Rodada {rodada}/{total_rodadas} iniciada")

                # Recarrega planilha para pegar estado atualizado
                df = self._load_contacts()
                pending = self._get_pending_contacts(df)

                # Log de contatos já enviados (pulados)
                enviados_df = df[df["Enviado"] == "X"]
                invalidos_df = df[df["Invalido"] == "X"]
                if len(enviados_df) > 0:
                    for _, row in enviados_df.iterrows():
                        self._log(f"[SKIP] {row['Pessoa']} — já enviado, pulando.")
                if len(invalidos_df) > 0:
                    for _, row in invalidos_df.iterrows():
                        self._log(f"[SKIP] {row['Pessoa']} — número inválido, pulando.")

                with self._lock:
                    self._total_pending = len(pending)

                if len(pending) == 0:
                    self._log("✅ Todos os contatos já foram processados!")
                    break

                # Na última rodada, não aplica variação — manda exatamente o que falta
                # para garantir que o total bata
                if rodada == total_rodadas:
                    batch_size = max(1, msgs_por_rodada + compensacao)
                else:
                    batch_size = self._get_batch_size(msgs_por_rodada, compensacao)
                batch = pending.head(batch_size)
                enviados_rodada = 0

                for idx, row in batch.iterrows():
                    if self._should_stop():
                        break

                    # Verifica horário comercial antes de cada mensagem
                    self._wait_for_business_hours()
                    if self._should_stop():
                        break

                    pessoa = str(row["Pessoa"])
                    numero = self._clean_number(row["Número"])
                    mensagem = str(row["Mensagem"])
                    arquivo = str(row.get("Arquivo", "")).strip()
                    # Limpa valores inválidos do pandas
                    if arquivo.lower() in ("", "nan", "none"):
                        arquivo = ""

                    # Validação prévia: não aciona o Selenium se o contato
                    # não tiver número válido ou mensagem.
                    valido, motivo = self._validate_contact(numero, mensagem)
                    if not valido:
                        df.at[idx, "Invalido"] = "X"
                        self._save_contacts(df)

                        with self._lock:
                            self._total_pending -= 1

                        file_logger.warning(f"Contato inválido ({motivo}): {pessoa} ({numero})")
                        self._log(f"❌ {pessoa} ({numero}) — {motivo}, marcado como inválido (pulado sem abrir o WhatsApp).")
                        self._notify_contact_update(numero, "invalido")
                        continue

                    self._log(f"Enviando para {pessoa} ({numero})...")

                    try:
                        success = self._send_message(pessoa, numero, mensagem, arquivo)

                        if success:
                            # Marca como enviado
                            df.at[idx, "Enviado"] = "X"
                            data_envio = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            df.at[idx, "DataEnvio"] = data_envio
                            self._save_contacts(df)

                            with self._lock:
                                self._messages_sent += 1
                                self._total_pending -= 1

                            enviados_rodada += 1
                            self._log(f"✅ {pessoa} — mensagem enviada com sucesso.")
                            self._notify_contact_update(numero, "enviado", data_envio)
                        else:
                            self._log(f"⚠️ {pessoa} — falha ao enviar, será tentado novamente na próxima rodada.")

                    except TimeoutException:
                        # Número inválido
                        df.at[idx, "Invalido"] = "X"
                        self._save_contacts(df)

                        with self._lock:
                            self._total_pending -= 1

                        file_logger.warning(f"Número inválido (timeout): {pessoa} ({numero})")
                        self._log(f"❌ {pessoa} ({numero}) — número inválido ou não encontrado no WhatsApp, marcado como inválido.")
                        self._notify_contact_update(numero, "invalido")

                    except Exception as e:
                        file_logger.error(f"Erro ao enviar para {pessoa} ({numero}): {e}\n{traceback.format_exc()}")
                        self._log(f"⚠️ {pessoa} ({numero}) — erro inesperado: {e}")

                    # Delay entre mensagens - exceto após a última
                    if not self._should_stop() and idx != batch.index[-1]:
                        d_min = self.config.get("delay_min", 15)
                        d_max = self.config.get("delay_max", 30)
                        if self._human_behavior_enabled():
                            delay = self._gaussian_delay(d_min, d_max)
                        else:
                            delay = random.uniform(d_min, d_max)
                        self._log(f"Aguardando {delay:.0f}s antes da próxima mensagem...")
                        time.sleep(delay)

                self._log(
                    f"📊 Rodada {rodada} finalizada: {enviados_rodada} mensagens enviadas"
                )

                # Atualiza compensação: diferença entre o esperado e o que de fato enviou
                # Se mandou 4 e era pra mandar 5, compensacao fica +1 (próxima manda 1 a mais)
                compensacao = (msgs_por_rodada - enviados_rodada) + compensacao

                # Verifica se ainda há pendentes antes de esperar
                df = self._load_contacts()
                remaining = self._get_pending_contacts(df)
                with self._lock:
                    self._total_pending = len(remaining)

                if len(remaining) == 0:
                    self._log("Todos os contatos foram processados.")
                    break

                # Intervalo entre rodadas (com jitter)
                if rodada < total_rodadas and not self._should_stop():
                    # Jitter: ±20% do intervalo
                    jitter = intervalo_min * 0.2
                    wait_time = random.uniform(
                        (intervalo_min - jitter) * 60,
                        (intervalo_min + jitter) * 60,
                    )
                    wait_minutes = wait_time / 60
                    self._log(
                        f"⏰ Próxima rodada em ~{wait_minutes:.0f} minutos. "
                        f"Aguardando..."
                    )

                    # Espera em intervalos curtos para poder parar
                    elapsed = 0
                    while elapsed < wait_time and not self._should_stop():
                        time.sleep(min(2, wait_time - elapsed))
                        elapsed += 2

            # Finalização
            if self._should_stop():
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
