"""
Seletores do WhatsApp Web como DADO, não como código.

Quando o WhatsApp muda o DOM, hoje todos os clientes param até sair um
`.exe` novo. Este módulo tira os seletores do código-fonte e os põe numa
cadeia de três camadas:

    EMBUTIDO  ->  CACHE EM DISCO  ->  SUPABASE

O embutido (`PADRAO`) vai dentro do `.exe` e garante que o app funcione mesmo
no primeiro uso sem internet. O cache guarda a última versão baixada. O
Supabase é a fonte de atualização — publicar um seletor novo vira um UPDATE
numa tabela, não um build.

Espelha deliberadamente o padrão do `license.py` (busca remota + cache local +
degradação silenciosa), porque é o mesmo problema.

Quatro invariantes que não podem regredir:

1. **Cache em disco, nunca `localStorage`.** Quem consome estes seletores é o
   Selenium, em Python. O `localStorage` vive no navegador da UI
   (localhost:8000) e o sender nunca o enxerga.

2. **Nunca dependência dura.** Supabase fora do ar, tabela inexistente, JSON
   corrompido — em todos os casos o app cai para a camada anterior e segue
   funcionando. Nada aqui pode impedir um envio de rodar.

3. **Só seletores, nunca código.** O payload remoto carrega STRINGS de seletor
   CSS (ou listas delas) e nada mais. `_validar_payload()` rejeita chave
   desconhecida, string longa demais, lista longa demais e — importante — todo
   valor cujo TIPO não bate com o do embutido: uma chave que o código lê com
   `get()` não pode virar lista pelo payload, nem vice-versa. É conteúdo remoto
   entrando num app que dirige a conta de WhatsApp do cliente: a fronteira é
   estreita de propósito.

4. **Refetch só em falha ESTRUTURAL.** Um contato que falhou não diz nada
   sobre os seletores. Só "o `#pane-side` não apareceu", "a lista voltou zero
   linhas" ou "o campo de digitação não apareceu em N contatos seguidos"
   justificam buscar de novo — e com trava de tempo, ou um WhatsApp quebrado
   martela o Supabase a cada contato. Repare que o terceiro caso é contado, e
   não reportado no primeiro timeout: um contato sozinho que não abre é o caso
   comum de número inválido, e cairia direto na regra que esta invariante
   proíbe.
"""

import json
import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests

# Mesmo logger de arquivo do resto do app (configurado em app.py). Obtido por
# nome para não importar app.py aqui — evita import circular.
logger = logging.getLogger("whatsapp_sender_file")

# Reaproveita as credenciais já existentes: é o mesmo projeto Supabase.
from license import SUPABASE_URL, SUPABASE_ANON_KEY  # noqa: E402

import caminhos  # noqa: E402

TABELA = "seletores"

# Versão do formato. Um `.exe` só aceita payload com este mesmo número —
# assim um JSON novo publicado para uma versão futura do app não quebra um
# cliente antigo, ele simplesmente ignora e usa o que já tem.
VERSAO_SCHEMA = 1

CACHE_FILE = caminhos.uploads_dir() / "seletores_cache.json"

# Intervalo mínimo entre duas buscas remotas disparadas por falha estrutural.
# Sem isso, um WhatsApp quebrado geraria uma requisição por contato.
INTERVALO_MINIMO_REFETCH_SEG = 15 * 60

# Um seletor CSS legítimo é curto. O teto é uma defesa barata contra payload
# absurdo, não uma validação de sintaxe.
TAMANHO_MAXIMO_SELETOR = 500

# Algumas chaves são LISTAS de seletores tentados em ordem (o botão de anexar,
# o de enviar, o campo de legenda). O WhatsApp mudou esses elementos várias
# vezes, e manter os antigos na lista é o que fez o app sobreviver às mudanças
# anteriores sem release. O teto existe pelo mesmo motivo que o de string.
TAMANHO_MAXIMO_LISTA = 30


# ============================================================
# Camada 1: o embutido. Vai dentro do .exe.
# ============================================================
# Levantado em 06/09/2026 com as sondas `sonda_pane_side.js` e
# `sonda_tiques.js` contra o WhatsApp Web real. Ver BRAINSTORM_IA.md #7.
PADRAO = {
    # --- estrutura da lista de conversas ---
    "pane_side": "#pane-side",
    "linha_conversa": '#pane-side [role="listitem"], #pane-side [role="row"]',
    # --- campos de uma linha ---
    # Contato NÃO salvo na agenda aparece aqui como "+55 19 99594-7333":
    # só os dígitos já casam com clean_number().
    "linha_titulo": '[data-testid="cell-frame-title"]',
    "linha_horario": '[data-testid="cell-frame-primary-detail"]',
    "linha_previa": '[data-testid="cell-frame-secondary"]',
    # O `title` deste span traz o texto COMPLETO da última mensagem, e é
    # dentro dele que mora o ícone de status.
    "linha_status_ultima_msg": '[data-testid="last-msg-status"]',
    # Ícone de TIPO DE MÍDIA (figurinha, áudio...). Mora aninhado dentro do
    # status, e precisa ser excluído para não ser confundido com o tique.
    "linha_simbolo_midia": '[data-testid="chat-msg-symbol"]',
    "linha_nao_lidas": '[data-testid="icon-unread-count"]',
    # --- busca (usada pela varredura pós-envio) ---
    # É um <input> de verdade, não contenteditable, e fica FORA do #pane-side.
    "busca_input": 'input[role="textbox"][aria-label^="Pesquisar"]',
    "busca_container": '[data-testid="chat-list-search-container"]',

    # --- caminho de ENVIO ---
    # Até 12/09/2026 tudo abaixo vivia escrito à mão no whatsapp_sender.py, o
    # que deixava justamente o lado crítico de fora da correção publicável: se
    # a lista de conversas quebra, a varredura para; se o campo de mensagem
    # quebra, ninguém envia mais nada. Agora os dois se consertam pelo mesmo
    # caminho.
    #
    # O campo de digitação do rodapé é o seletor mais crítico do app inteiro —
    # é por ele que a mensagem é escrita, é ele que prova que a conversa abriu
    # (_wait_chat_or_invalid_popup) e é ele que prova que a mensagem saiu
    # (_confirm_message_sent, por ficar vazio).
    "campo_mensagem": "footer div[contenteditable='true']",
    "input_arquivo": 'input[type="file"]',

    # A prova de que a mensagem NAO saiu da maquina. Medido em campo em
    # 19/09/2026 (`sonda_bolha.py`): a bolha que falhou carrega
    # `[data-testid="fail-container"]`, com um `ic-error` clicavel dentro que
    # reenvia. Ela persistiu 12 MINUTOS sem se resolver sozinha — por isso a
    # presenca do container e' veredito, nao suspeita.
    #
    # Por que nao um nome de icone, como os tiques: a bolha que falhou tem o
    # `msg-meta` VAZIO (`meta=[]` na medicao). A falha nao e' um icone de
    # status ali dentro, e' este container irmao. Ler por ausencia de icone,
    # como a lista faz, daria "mensagem deles" — exatamente ao contrario.
    "bolha_falha": '[data-testid="fail-container"]',
    # Escopo da conversa aberta. `message-out`/`message-in` estao MORTAS (0
    # ocorrencias na mesma medicao); hoje as bolhas sao `[role="row"]` com
    # `[data-id]` dentro do `#main`.
    "area_mensagens": "#main",

    # Containers onde se PROCURA texto — o que decide o desfecho é o texto
    # (marcadores em pt/en/es no sender), não o seletor. São vírgula-separados
    # de propósito: é um querySelectorAll só, e a ordem não importa.
    "modais": (
        'div[role="dialog"], div[data-animate-modal-body="true"], '
        'div[data-animate-modal-popup="true"], .overlay'
    ),
    "modal_botoes": 'div[role="dialog"] button, div[role="dialog"] div[role="button"]',
    "alertas_conexao": (
        'div[role="alert"], [data-testid="alert-computer"], '
        '[data-testid="alert-phone"]'
    ),
    "area_conversa": (
        'div[data-tab] button, div[data-tab] span, '
        'div.copyable-area button, div.copyable-area span'
    ),

    # --- listas tentadas EM ORDEM ---
    # Aqui a ordem importa (a primeira que casar e estiver visível vence), por
    # isso são listas e não uma string vírgula-separada.
    "qr_canvas": [
        'canvas[aria-label*="QR"]',
        'canvas[aria-label*="qr"]',
        'div[data-ref] canvas',
        '[data-testid="qrcode"]',
    ],
    "botao_anexar": [
        'button[aria-label="Anexar"]',
        'button[aria-label="Attach"]',
        'span[data-icon="plus-rounded"]',
        'span[data-icon="plus"]',
        'span[data-icon="clip"]',
        'span[data-icon="attach-menu-plus"]',
        '[data-testid="clip"]',
    ],
    "botao_enviar_modal": [
        '[data-testid="send"]',
        'span[data-icon="wds-ic-send-filled"]',
        'span[data-icon="send"]',
        'span[data-icon="send-light"]',
        'div[role="button"][aria-label*="Enviar"]',
        'div[role="button"][aria-label*="Send"]',
        'button[aria-label="Enviar"]',
        'button[aria-label="Send"]',
    ],
    # Duas listas de legenda, de propósito: uma responde "existe legenda nesta
    # tela?" (para distinguir o preview de foto do editor de figurinha, que não
    # tem legenda) e a outra acha o campo para digitar dentro. São perguntas
    # diferentes e já tinham seletores diferentes.
    "campo_legenda_presenca": [
        'div[contenteditable="true"][aria-label*="legenda"]',
        'div[contenteditable="true"][aria-label*="caption"]',
        'div[data-testid="media-caption-input-container"]',
        'div[role="dialog"] div[contenteditable="true"]',
    ],
    "campo_legenda_edicao": [
        'div[contenteditable="true"][data-testid="media-caption-input-container"]',
        'div.copyable-text[contenteditable="true"][data-tab]',
        # O modal tem um contenteditable que NÃO é o footer
        'div[role="dialog"] div[contenteditable="true"]',
        'div.overlay div[contenteditable="true"]',
    ],
}

# Nomes dos ícones de status, lidos do <title> de dentro do <svg>. Ficam aqui
# junto dos seletores porque mudam pelo mesmo motivo e devem ser publicáveis
# do mesmo jeito.
#
# ATENÇÃO: os nomes do WhatsApp estão DESLOCADOS em relação ao que exibem —
# medido em campo em 08/09/2026 e confirmado pelo cliente:
#
#   wds-ic-delivered  ->  ✓  solitário: SAIU, mas NÃO chegou
#   wds-ic-read       ->  ✓✓ duplo: chegou. A COR diz se foi lido
#                          (cinza = entregue, azul = lido)
#
# Ou seja, "delivered" é justamente o estado de não-entrega, e "read" cobre
# entregue E lido. Confiar no nome fazia o app dizer "Entregue" para mensagem
# que não chegou — e, pior, calava o alarme de entrega, que existe para
# detectar exatamente isso.
#
# Por isso só há DUAS chaves aqui, nomeadas pelo DESENHO e não pelo estado: o
# tique duplo e a falha. O ✓ solitário não precisa de chave — ele cai na regra
# por ausência ("qualquer outro ícone = não entregue"), que continua sendo o
# que faz um ícone novo e desconhecido ser tratado com segurança.
ICONES_PADRAO = {
    "icone_tique_duplo": "wds-ic-read",
    "icone_falha": "message-fail",
}


PADRAO.update(ICONES_PADRAO)


# ============================================================
# Estado em memória
# ============================================================
_lock = threading.Lock()
_atual: dict = dict(PADRAO)
_origem = "embutido"          # embutido | cache | supabase
_versao_remota: Optional[str] = None
_ultimo_refetch = 0.0
_falhas_estruturais: dict = {}


def _validar_payload(bruto) -> dict:
    """
    Filtra um payload remoto para o que é seguro consumir.

    Aceita SOMENTE chaves já conhecidas do embutido, com valor string não
    vazia e dentro do teto de tamanho. Tudo o mais é descartado com log.

    É esta função que materializa a invariante "só seletores, nunca código":
    nada que não seja uma string curta e de chave conhecida atravessa.
    """
    if not isinstance(bruto, dict):
        logger.warning(f"[seletores] payload não é objeto ({type(bruto).__name__}) — ignorado.")
        return {}

    limpo = {}
    for chave, valor in bruto.items():
        if chave not in PADRAO:
            logger.warning(f"[seletores] chave desconhecida '{chave}' — ignorada.")
            continue

        # O tipo é definido pelo embutido, nunca pelo payload: o código chama
        # `get()` ou `lista()` conforme a chave, e deixar o remoto trocar o
        # tipo seria deixá-lo escolher por qual caminho o app passa.
        espera_lista = isinstance(PADRAO[chave], list)
        if espera_lista != isinstance(valor, list):
            logger.warning(
                f"[seletores] '{chave}' veio como {type(valor).__name__}, "
                f"mas é {'lista' if espera_lista else 'string'} — ignorada."
            )
            continue

        if espera_lista:
            itens = _validar_lista(chave, valor)
            if itens:
                limpo[chave] = itens
            continue

        item = _validar_string(chave, valor)
        if item:
            limpo[chave] = item
    return limpo


def _validar_string(chave: str, valor) -> Optional[str]:
    """Um seletor: string não vazia, dentro do teto. Devolve None se reprovar."""
    if not isinstance(valor, str):
        logger.warning(f"[seletores] '{chave}' não é string ({type(valor).__name__}) — ignorada.")
        return None
    valor = valor.strip()
    if not valor:
        logger.warning(f"[seletores] '{chave}' veio vazia — ignorada.")
        return None
    if len(valor) > TAMANHO_MAXIMO_SELETOR:
        logger.warning(f"[seletores] '{chave}' tem {len(valor)} chars (teto {TAMANHO_MAXIMO_SELETOR}) — ignorada.")
        return None
    return valor


def _validar_lista(chave: str, valor: list) -> list:
    """
    Uma lista de seletores tentados em ordem.

    Item ruim é descartado individualmente, e não invalida a lista: uma lista
    de fallbacks com 7 entradas não deve ser perdida inteira porque a oitava
    veio torta. Lista que sobra vazia é descartada (o chamador cai no embutido).
    """
    if len(valor) > TAMANHO_MAXIMO_LISTA:
        logger.warning(
            f"[seletores] '{chave}' tem {len(valor)} itens "
            f"(teto {TAMANHO_MAXIMO_LISTA}) — ignorada."
        )
        return []
    itens = []
    for bruto_item in valor:
        item = _validar_string(chave, bruto_item)
        if item:
            itens.append(item)
    if not itens:
        logger.warning(f"[seletores] '{chave}' não sobrou nenhum item válido — ignorada.")
    return itens


def _aplicar(payload: dict, origem: str, versao: Optional[str] = None) -> int:
    """
    Sobrepõe o embutido com o que veio validado. Retorna quantas chaves mudaram.

    Sempre parte de PADRAO, nunca do estado anterior: assim uma chave removida
    do payload volta ao embutido em vez de ficar presa num valor velho.
    """
    global _atual, _origem, _versao_remota
    novo = dict(PADRAO)
    novo.update(payload)
    with _lock:
        mudou = sum(1 for k, v in novo.items() if _atual.get(k) != v)
        _atual = novo
        _origem = origem
        _versao_remota = versao
    return mudou


def get(chave: str) -> str:
    """
    Devolve um seletor. Chave desconhecida é erro de programação, não de dado.

    Nunca levanta por causa de payload remoto ruim: o `_validar_payload` já
    garantiu que só chaves do embutido chegam aqui, e com o tipo certo, então o
    `PADRAO` é sempre um fallback válido.
    """
    valor = _bruto(chave)
    if isinstance(valor, list):
        raise TypeError(f"seletor {chave!r} é lista — use lista() em vez de get()")
    return valor


def lista(chave: str) -> list:
    """
    Devolve uma lista de seletores para tentar EM ORDEM (o primeiro visível
    vence). Sempre uma cópia: o chamador itera, e ninguém deve conseguir
    mutar o embutido por acidente.

    Tolera uma chave de string por conveniência do chamador — mas o embutido é
    quem define o tipo, então na prática isso não acontece.
    """
    valor = _bruto(chave)
    if isinstance(valor, list):
        return list(valor)
    return [valor]


def _bruto(chave: str):
    with _lock:
        if chave in _atual:
            return _atual[chave]
    if chave in PADRAO:
        return PADRAO[chave]
    raise KeyError(f"seletor desconhecido: {chave!r}")


def todos() -> dict:
    """
    Cópia do conjunto atual — para injetar no JS de extração de uma vez só.

    As listas são copiadas também: `dict()` é raso, e devolver a lista viva do
    `PADRAO` deixaria um chamador mutar o embutido do processo inteiro.
    """
    with _lock:
        return {
            k: (list(v) if isinstance(v, list) else v)
            for k, v in _atual.items()
        }


def status() -> dict:
    """Diagnóstico para o log e para a UI (que só mostra a versão amigável)."""
    with _lock:
        return {
            "origem": _origem,
            "versao_remota": _versao_remota,
            "versao_schema": VERSAO_SCHEMA,
            "total": len(_atual),
            "falhas_estruturais": dict(_falhas_estruturais),
        }


# ============================================================
# Camada 2: cache em disco
# ============================================================
def _gravar_cache(payload: dict, versao: Optional[str]):
    try:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        CACHE_FILE.write_text(
            json.dumps(
                {
                    "versao_schema": VERSAO_SCHEMA,
                    "versao": versao,
                    "baixado_em": datetime.now(timezone.utc).isoformat(),
                    "seletores": payload,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        logger.info(f"[seletores] cache gravado ({len(payload)} chaves, versão={versao}).")
    except OSError as e:
        # Não é fatal: o app segue com o que está em memória.
        logger.warning(f"[seletores] falha ao gravar cache em {CACHE_FILE}: {e!r}")


def _ler_cache() -> tuple[dict, Optional[str]]:
    if not CACHE_FILE.exists():
        return {}, None
    try:
        dados = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"[seletores] cache ilegível ({CACHE_FILE}): {e!r} — usando o embutido.")
        return {}, None

    if dados.get("versao_schema") != VERSAO_SCHEMA:
        logger.info(
            f"[seletores] cache é de outro schema "
            f"({dados.get('versao_schema')} != {VERSAO_SCHEMA}) — usando o embutido."
        )
        return {}, None

    return _validar_payload(dados.get("seletores")), dados.get("versao")


# ============================================================
# Camada 3: Supabase
# ============================================================
def _buscar_remoto() -> tuple[dict, Optional[str]]:
    """
    Busca a linha de seletores mais recente para este schema.

    A tabela pode simplesmente não existir ainda — nesse caso isto devolve
    vazio e o app segue no embutido/cache, sem barulho para o usuário.
    """
    try:
        resp = requests.get(
            f"{SUPABASE_URL}/rest/v1/{TABELA}",
            headers={
                "apikey": SUPABASE_ANON_KEY,
                "Authorization": f"Bearer {SUPABASE_ANON_KEY}",
            },
            params={
                "select": "versao,seletores",
                "versao_schema": f"eq.{VERSAO_SCHEMA}",
                "ativo": "is.true",
                "order": "criado_em.desc",
                "limit": "1",
            },
            timeout=10,
        )
    except requests.RequestException as e:
        logger.info(f"[seletores] sem rede para atualizar ({e.__class__.__name__}) — seguindo com o local.")
        return {}, None

    if resp.status_code != 200:
        logger.info(
            f"[seletores] Supabase respondeu {resp.status_code} "
            f"(tabela '{TABELA}' existe?) — seguindo com o local."
        )
        return {}, None

    try:
        linhas = resp.json()
    except ValueError:
        logger.warning("[seletores] resposta do Supabase não é JSON — seguindo com o local.")
        return {}, None

    if not linhas:
        return {}, None

    linha = linhas[0]
    return _validar_payload(linha.get("seletores")), linha.get("versao")


def atualizar_do_servidor(motivo: str = "rotina") -> bool:
    """
    Busca no Supabase e, se vier algo válido, aplica e persiste no cache.

    Retorna True se algum seletor de fato mudou — é o que diz ao chamador se
    vale a pena tentar a operação de novo.
    """
    global _ultimo_refetch
    payload, versao = _buscar_remoto()
    with _lock:
        _ultimo_refetch = time.monotonic()
    if not payload:
        return False

    mudou = _aplicar(payload, "supabase", versao)
    _gravar_cache(payload, versao)
    logger.info(f"[seletores] atualizados do servidor ({motivo}): versão={versao}, {mudou} mudança(s).")
    return mudou > 0


def carregar(buscar_remoto: bool = True):
    """
    Chamada no startup. Embutido -> cache (síncrono) -> Supabase (em thread).

    A busca remota vai para uma thread de propósito: o app tem que abrir
    instantaneamente mesmo com a rede ruim, e o embutido/cache já é suficiente
    para operar.
    """
    payload, versao = _ler_cache()
    if payload:
        _aplicar(payload, "cache", versao)
        logger.info(f"[seletores] carregados do cache ({len(payload)} chaves, versão={versao}).")
    else:
        _aplicar({}, "embutido")
        logger.info("[seletores] usando os embutidos.")

    if buscar_remoto:
        threading.Thread(
            target=lambda: atualizar_do_servidor("startup"),
            daemon=True,
        ).start()


# ============================================================
# Refetch por falha estrutural
# ============================================================
def registrar_falha_estrutural(qual: str) -> bool:
    """
    Sinaliza que um seletor ESTRUTURAL não encontrou nada, e talvez busca uma
    atualização.

    Chamar APENAS quando a falha diz algo sobre o DOM: `#pane-side` que não
    aparece, lista de conversas que volta zero linhas. NUNCA por falha de um
    contato — número inválido, chat que não abriu, rede caída. Esses não dizem
    nada sobre seletor e só gerariam requisições inúteis.

    Retorna True se buscou E algo mudou (ou seja: vale tentar de novo).
    """
    with _lock:
        _falhas_estruturais[qual] = _falhas_estruturais.get(qual, 0) + 1
        desde_ultimo = time.monotonic() - _ultimo_refetch
        cedo_demais = _ultimo_refetch > 0 and desde_ultimo < INTERVALO_MINIMO_REFETCH_SEG

    if cedo_demais:
        logger.debug(
            f"[seletores] falha estrutural em '{qual}', mas a última busca foi há "
            f"{desde_ultimo:.0f}s (mínimo {INTERVALO_MINIMO_REFETCH_SEG}s) — não busca."
        )
        return False

    logger.warning(f"[seletores] falha estrutural em '{qual}' — buscando atualização.")
    return atualizar_do_servidor(f"falha estrutural: {qual}")


# ============================================================
# Mensagens para o usuário — nunca técnicas
# ============================================================
MSG_ATUALIZANDO = (
    "O WhatsApp mudou alguma coisa e o programa está buscando o ajuste "
    "automaticamente. Isso leva alguns segundos."
)

MSG_FALHOU = (
    "Não consegui buscar a atualização agora. Verifique sua conexão e tente de "
    "novo — se o problema continuar, entre em contato com o suporte."
)
