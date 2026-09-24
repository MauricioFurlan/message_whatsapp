# -*- coding: utf-8 -*-
"""
Dublê do WhatsApp Web: um DOM falso no lugar do Selenium.

## Por que isto é possível aqui

O app toca o Selenium por **cinco** métodos (`get`, `find_element`,
`find_elements`, `execute_script`, `quit`) e alcança o DOM por **23 seletores**,
todos vindos de `seletores.py`. E `start()` tem uma costura única:
`self._driver = self._init_driver()`. Trocar aquela linha troca o WhatsApp Web
inteiro.

## O ganho escondido da tabela de seletores

Este dublê **não tem CSS escrito nele**. Ele compara a string que o app pediu
contra `seletores.get(...)`/`lista(...)` — a mesma tabela que o app consulta em
produção. Duas consequências que valem a arquitetura:

- o dublê não pode divergir do app: se alguém trocar um seletor no `PADRAO`, os
  dois lados trocam juntos;
- e não pode mascarar: um seletor renomeado no app e esquecido em algum ponto do
  código (o bug que o `tests/test_seletores.py` pega por grep) chega aqui como
  uma consulta que o dublê não reconhece, e uma consulta não reconhecida devolve
  vazio — que é exatamente o que o Chrome de verdade devolveria.

## O que ele NÃO é

Não é um modelo do WhatsApp Web, é um modelo do **contrato** que o app espera
dele. Ele nunca vai pegar o WhatsApp mudando o DOM de verdade — para isso
existem as sondas (`sonda_*.js`) e a tabela publicada. Ele pega regressão nossa:
contato que devia ficar pendente e ficou inválido, mensagem enviada duas vezes,
anexo mandado sem texto, rajada que não respeita o plano.
"""

import re
from urllib.parse import parse_qs, urlparse

from selenium.common.exceptions import NoSuchElementException

import seletores

# ---- Desfechos que um contato pode ter, do ponto de vista do navegador ----
OK = "ok"
# O WhatsApp abre o modal de "número inválido". Contato vira inválido.
NUMERO_INVALIDO = "numero_invalido"
# A conversa abre, mas no lugar do campo de texto há "Desbloquear".
BLOQUEADO = "bloqueado"
# O app do WhatsApp está de pé (#pane-side presente), a conversa é que não
# abre. Contato vira inválido, e o botão ↺ recupera.
CHAT_NAO_ABRE = "chat_nao_abre"
# O #pane-side nunca aparece: problema de ambiente, não do número. O contato
# tem de continuar PENDENTE — é a distinção que o CLAUDE.md chama de
# `tipo="app"` contra `tipo="chat"`.
APP_NAO_SOBE = "app_nao_sobe"
# Rede fora. O #pane-side continua lá (o WhatsApp Web é um PWA), então isto se
# parece com número ruim e só o log separa os dois.
SEM_CONEXAO = "sem_conexao"

_TEXTO_MODAL_INVALIDO = (
    "O número de telefone compartilhado por meio de URL é inválido."
)
_TEXTO_BLOQUEADO = "Desbloquear"


class ElementoFalso:
    """
    Um nó do DOM falso. Só implementa o que o app chama de verdade.

    O campo de mensagem é o único com comportamento: ele acumula o que foi
    digitado e, no ENTER, entrega a mensagem. É de propósito que o texto
    "sai" do campo — `_confirm_message_sent` prova o envio justamente pelo
    campo esvaziar, então um dublê que não esvaziasse deixaria o app achar que
    nada foi enviado (e um que esvaziasse sem entregar esconderia o bug oposto).
    """

    def __init__(self, dom, papel, texto="", visivel=True):
        self._dom = dom
        self.papel = papel
        self._texto = texto
        self._visivel = visivel

    # ---- leitura ----
    @property
    def text(self):
        if self.papel == "campo_mensagem":
            return self._dom.composer
        return self._texto

    def is_displayed(self):
        return self._visivel

    def get_attribute(self, nome):
        if nome in ("value", "textContent", "innerText"):
            return self.text
        return None

    # ---- interação ----
    def click(self):
        self._dom.cliques.append(self.papel)

    def clear(self):
        if self.papel == "campo_mensagem":
            self._dom.composer = ""

    def send_keys(self, *args):
        from selenium.webdriver.common.keys import Keys

        # Ctrl vale só DENTRO desta chamada: `send_keys(Keys.CONTROL, "a")` é
        # "seleciona tudo", mas um "a" numa chamada sem Ctrl é a letra a. Tratar
        # os dois igual comia toda letra "a" do texto digitado — "Ana" chegava
        # como "An" — e o dublê então provaria o oposto do que devia.
        ctrl = False
        for arg in args:
            if arg == Keys.CONTROL:
                ctrl = True
            elif arg == Keys.ENTER:
                self._dom.apertar_enter()
            elif arg in (Keys.DELETE, Keys.BACKSPACE):
                if self.papel == "campo_mensagem":
                    self._dom.composer = ""
                elif self.papel == "busca":
                    self._dom.busca = ""
            elif ctrl:
                ctrl = False  # a tecla combinada com Ctrl não é texto
            elif isinstance(arg, str):
                if self.papel == "campo_mensagem":
                    self._dom.composer += arg
                elif self.papel == "busca":
                    self._dom.busca += arg
                elif self.papel == "input_arquivo":
                    self._dom.anexos_do_contato.append(arg)


class MensagemEnviada:
    def __init__(self, numero, texto, anexos):
        self.numero = numero
        self.texto = texto
        self.anexos = list(anexos)

    def __repr__(self):
        return f"<Enviada {self.numero} {self.texto[:30]!r} anexos={len(self.anexos)}>"


class FakeWhatsAppWeb:
    """
    O driver falso. Recebe um `roteiro` de `numero -> desfecho`.

    O número do roteiro é comparado JÁ LIMPO (só dígitos, sem o 55 que o app
    prefixa antes de montar a URL), para o teste poder escrever o número do
    jeito que ele aparece na planilha.
    """

    def __init__(self, roteiro=None, padrao=OK, linhas_da_lista=None):
        self.roteiro = dict(roteiro or {})
        self.padrao = padrao
        # Linhas cruas da lista de conversas, no formato que o JS de
        # `linha_conversa.js_extrair()` devolveria. Alimenta a varredura e a
        # conferência de entrega na pausa.
        self.linhas_da_lista = list(linhas_da_lista or [])

        self.url = ""
        self.numero_atual = ""
        self.composer = ""
        self.busca = ""
        self.anexos_do_contato = []
        self.enviadas = []
        self.navegacoes = []
        self.cliques = []
        self.encerrado = False

        self._pane_visivel = True
        self._chat_aberto = False
        self._modal = ""
        self._bloqueado = False
        self._offline = False

    # ------------------------------------------------------------------ #
    # Protocolo do WebDriver — só o que o app usa
    # ------------------------------------------------------------------ #
    def get(self, url):
        self.url = url
        self.navegacoes.append(url)
        numero = self._numero_da_url(url)

        if not numero:
            # Navegação "nua" para web.whatsapp.com — é o aquecimento
            # (`_aquecer_navegacao`), que deliberadamente NÃO pode abrir a
            # conversa de ninguém.
            self.numero_atual = ""
            self._pane_visivel = True
            self._chat_aberto = False
            self._modal = ""
            self._bloqueado = False
            return

        self.numero_atual = numero
        self.composer = ""
        self.anexos_do_contato = []
        desfecho = self.roteiro.get(numero, self.padrao)

        self._pane_visivel = desfecho != APP_NAO_SOBE
        self._chat_aberto = desfecho in (OK, SEM_CONEXAO)
        self._modal = _TEXTO_MODAL_INVALIDO if desfecho == NUMERO_INVALIDO else ""
        self._bloqueado = desfecho == BLOQUEADO
        self._offline = desfecho == SEM_CONEXAO

    def find_elements(self, by, css):
        return self._consultar(css)

    def find_element(self, by, css):
        achados = self._consultar(css)
        if not achados:
            raise NoSuchElementException(f"sem elemento para {css!r}")
        return achados[0]

    def execute_script(self, script, *args):
        if "navigator.onLine" in script:
            return self._offline
        # A extração da lista de conversas (`linha_conversa._JS_EXTRAIR`).
        if "S.linha_conversa" in script or "linha_status_ultima_msg" in script:
            return list(self.linhas_da_lista)
        if "scrollTop" in script:
            return None
        # A colagem de texto com emoji (`_paste_text`): o segundo argumento é
        # o texto, e o efeito real é o campo passar a contê-lo.
        if "insertText" in script or "ClipboardEvent" in script:
            if len(args) >= 2 and isinstance(args[1], str):
                self.composer += args[1]
            return None
        return None

    def quit(self):
        self.encerrado = True

    # ------------------------------------------------------------------ #
    # Resolução de seletor — contra a tabela, nunca contra CSS literal
    # ------------------------------------------------------------------ #
    def _consultar(self, css):
        alvo = (css or "").strip()

        if alvo == seletores.get("pane_side"):
            return [ElementoFalso(self, "pane")] if self._pane_visivel else []

        if alvo == seletores.get("campo_mensagem"):
            return [ElementoFalso(self, "campo_mensagem")] if self._chat_aberto else []

        if alvo == seletores.get("modais"):
            return [ElementoFalso(self, "modal", self._modal)] if self._modal else []

        if alvo == seletores.get("modal_botoes"):
            return [ElementoFalso(self, "botao_ok", "OK")] if self._modal else []

        if alvo == seletores.get("area_conversa"):
            return [ElementoFalso(self, "botao", _TEXTO_BLOQUEADO)] if self._bloqueado else []

        if alvo == seletores.get("alertas_conexao"):
            if self._offline:
                return [ElementoFalso(self, "alerta", "Aguardando conexão")]
            return []

        if alvo == seletores.get("input_arquivo"):
            return [ElementoFalso(self, "input_arquivo")] if self._chat_aberto else []

        if alvo == seletores.get("busca_input"):
            return [ElementoFalso(self, "busca")] if self._pane_visivel else []

        if alvo == seletores.get("linha_conversa"):
            return [ElementoFalso(self, "linha") for _ in self.linhas_da_lista]

        # Listas tentadas em ordem: o app pega a primeira visível. Aqui basta
        # responder à primeira alternativa, e só quando faz sentido responder.
        if alvo in seletores.lista("qr_canvas"):
            return []  # sessão salva: QR nunca aparece
        if alvo in seletores.lista("botao_anexar"):
            return [ElementoFalso(self, "botao_anexar")] if self._chat_aberto else []
        if alvo in seletores.lista("botao_enviar_modal"):
            return [ElementoFalso(self, "botao_enviar_modal")] if self._chat_aberto else []
        if alvo in seletores.lista("campo_legenda_presenca"):
            return []
        if alvo in seletores.lista("campo_legenda_edicao"):
            return []

        # Formas de HTML puro, deliberadamente literais no app (ver CLAUDE.md):
        # casadas por texto, não por classe do WhatsApp.
        if alvo in ("footer", "body"):
            texto = _TEXTO_BLOQUEADO if self._bloqueado else ""
            return [ElementoFalso(self, "footer", texto)]

        # Consulta que este dublê não conhece: vazio, que é o que o Chrome
        # devolveria para um seletor que não casa com nada.
        return []

    # ------------------------------------------------------------------ #
    # Ações do DOM falso
    # ------------------------------------------------------------------ #
    def apertar_enter(self):
        """ENTER no campo de mensagem: a mensagem sai e o campo esvazia."""
        if not self._chat_aberto:
            return
        texto = self.composer
        if not texto:
            return
        self.enviadas.append(
            MensagemEnviada(self.numero_atual, texto, self.anexos_do_contato)
        )
        self.composer = ""

    @staticmethod
    def _numero_da_url(url) -> str:
        try:
            q = parse_qs(urlparse(url).query)
        except Exception:
            return ""
        bruto = (q.get("phone") or [""])[0]
        digitos = re.sub(r"\D", "", bruto)
        # O app prefixa 55 ao montar a URL; o roteiro é escrito com o número
        # como ele aparece na planilha.
        if len(digitos) > 11 and digitos.startswith("55"):
            digitos = digitos[2:]
        return digitos

    # ---- conveniências para os testes ----
    def textos_enviados(self) -> list:
        return [m.texto for m in self.enviadas]

    def numeros_enviados(self) -> list:
        return [m.numero for m in self.enviadas]


class AcoesFalsas:
    """
    Substituto de `ActionChains`. O app o usa para Ctrl+A/Delete e para
    Shift+Enter (quebra de linha SEM enviar a mensagem) — e é justamente essa
    segunda que precisa ser fiel: um Shift+Enter tratado como ENTER partiria
    toda mensagem multilinha em várias mensagens.
    """

    def __init__(self, driver):
        self._driver = driver
        self._shift = False
        self._ctrl = False

    def key_down(self, tecla):
        from selenium.webdriver.common.keys import Keys

        if tecla == Keys.SHIFT:
            self._shift = True
        elif tecla == Keys.CONTROL:
            self._ctrl = True
        return self

    def key_up(self, tecla):
        from selenium.webdriver.common.keys import Keys

        if tecla == Keys.SHIFT:
            self._shift = False
        elif tecla == Keys.CONTROL:
            self._ctrl = False
        return self

    def send_keys(self, tecla):
        from selenium.webdriver.common.keys import Keys

        if tecla == Keys.ENTER and self._shift:
            self._driver.composer += "\n"
        elif tecla == "a" and self._ctrl:
            pass  # seleciona tudo; o DELETE seguinte é que apaga
        return self

    def perform(self):
        return None
