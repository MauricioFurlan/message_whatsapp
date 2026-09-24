"""
Leitura de uma linha da lista de conversas do WhatsApp Web (`#pane-side`).

É a fundação das features de classificação de contatos (ver BRAINSTORM_IA.md,
#7 / #7b / #7c): descobrir, SEM abrir a conversa, se o contato respondeu e em
que estado ficou a nossa última mensagem.

Por que não abrir a conversa: abrir custa 41-58s por contato (o item mais caro
do app) e marca a mensagem dele como lida. A linha da lista já traz tudo o que
interessa.

## Como o estado é decidido

O ícone de status fica dentro de `[data-testid="last-msg-status"]`, como o
`<title>` de um `<svg>` — parte permanente do DOM, não texto renderizado:

    <span data-testid="last-msg-status" title="teste">
      <span aria-hidden="true">
        <svg fill="currentColor">
          <title>wds-ic-delivered</title>
          <path .../>
        </svg>
      </span>
      ...texto da mensagem...
    </span>

**Cuidado obrigatório:** ícone de TIPO DE MÍDIA (figurinha, áudio) mora no
mesmo lugar, aninhado em `[data-testid="chat-msg-symbol"]`. Sem excluir esse,
uma figurinha que ELE mandou seria lida como tique nosso. O ícone de status é
o que está no `last-msg-status` e **fora** do `chat-msg-symbol`.

A decisão é por AUSÊNCIA, não por presença de um ícone específico:

| O que há                  | Estado          | Inferência                   |
|---------------------------|-----------------|------------------------------|
| sem `last-msg-status`     | `INDETERMINADO` | rascunho — não é evidência   |
| nenhum ícone              | `ULTIMA_DELES`  | a última mensagem é dele     |
| badge de não-lidas > 0    | `ULTIMA_DELES`  | chegou mensagem dele         |
| `message-fail`            | `FALHOU`        | não saiu                     |
| `wds-ic-read` + azul      | `LIDO`          | nossa, lida, sem resposta    |
| `wds-ic-read` + cinza     | `ENTREGUE`      | nossa, chegou, não lida      |
| qualquer outro ícone      | `NAO_ENTREGUE`  | nossa, saiu e não chegou     |

**Os nomes do WhatsApp estão deslocados do que exibem** (medido em campo em
08/09/2026, `sonda_cor_tique.js`, e confirmado pelo cliente):

- `wds-ic-delivered` é o **✓ solitário**: saiu, mas NÃO chegou. Apesar do
  nome. Ele cai no `NAO_ENTREGUE` pela regra por ausência — é justamente o
  ✓ solitário que este módulo dizia nunca ter capturado.
- `wds-ic-read` é o **✓✓ duplo**, e cobre entregue E lido. O que separa os
  dois é a COR, não o nome: cinza `rgba(0,0,0,.6)` contra azul
  `rgb(0,123,252)`, medidos no mesmo contato com 11s de diferença.

Confiar no nome fazia o app dizer "Leu" sobre mensagem não lida e "Entregue"
sobre mensagem que não chegou — esta última calando o alarme de entrega, que
existe exatamente para detectar mensagens que saem e não chegam.

## Divisão de responsabilidade

O DOM é extraído por UM `execute_script` que devolve dicts simples — uma ida
ao browser para a lista inteira, em vez de N `find_element`. A interpretação
é Python puro, sem Selenium, e por isso testável sem browser (mesmo motivo do
`contact_logic.py`).
"""

import json
import re
import unicodedata
from datetime import datetime, timedelta
from typing import Optional

import seletores
from contact_logic import clean_number

# ---- Estados possíveis da última mensagem de uma conversa ----
ULTIMA_DELES = "ultima_deles"
LIDO = "lido"
ENTREGUE = "entregue"
NAO_ENTREGUE = "nao_entregue"
FALHOU = "falhou"
INDETERMINADO = "indeterminado"

# Estados em que a nossa mensagem chegou ao aparelho dele.
ESTADOS_ENTREGUES = (ENTREGUE, LIDO)

# Caracteres de controle bidirecional que o WhatsApp põe em volta do texto da
# última mensagem (LRE/RLE/PDF/LRI/.../PDI e as marcas LRM/RLM). Invisíveis, e
# quebram qualquer comparação de string se não forem removidos.
_BIDI = dict.fromkeys(
    [0x200E, 0x200F, 0x061C]
    + list(range(0x202A, 0x202F))
    + list(range(0x2066, 0x206A))
)

# Um número precisa de DDD + telefone. Abaixo disso o título é um nome que por
# acaso tem dígitos, não um contato fora da agenda.
MIN_DIGITOS_NUMERO = 10


def limpar_bidi(texto) -> str:
    """Remove marcas bidi invisíveis e espaços das pontas."""
    if not texto:
        return ""
    return str(texto).translate(_BIDI).strip()


# Um telefone dentro do título: começa em dígito (com "+" opcional) e daí em
# diante só aceita dígitos, espaço e pontuação de telefone. É o que separa o
# número do resto do texto do título — ver `numero_do_titulo`.
_RE_TELEFONE = re.compile(r"\+?\d[\d\s \-().]{8,}\d")


def numero_do_titulo(titulo) -> str:
    """
    Extrai o número de um título de linha, quando ele for um número.

    Contato FORA da agenda — o caso normal numa campanha de prospecção —
    aparece como "+55 19 99594-7333", e casa com a planilha via
    `clean_number()`. Contato salvo aparece pelo nome: devolve "".

    **Não dá para pegar "todos os dígitos do título".** Quando a conversa tem
    mensagem não lida, o WhatsApp Web injeta um anúncio de acessibilidade no
    mesmo elemento, e o texto vira:

        "1 mensagem não lida+55 19 99422-9146"

    Todos os dígitos daí é "15519994229146" — 14 dígitos que não começam com
    55, então nem o corte de DDI salva. O número saía errado, a linha não
    casava com a planilha e a varredura não gravava nada; a linha ficava com
    a leitura ANTERIOR ("Lido"). Ou seja: o bug atingia exatamente os
    contatos que tinham respondido, que são os únicos com badge de não-lida.

    Por isso a busca é pelo TRECHO com forma de telefone, e não pelos dígitos
    soltos. É independente de idioma — o anúncio muda de texto conforme a
    língua do WhatsApp, mas nunca tem forma de telefone.
    """
    limpo = limpar_bidi(titulo)
    candidatos = [re.sub(r"\D", "", c) for c in _RE_TELEFONE.findall(limpo)]
    if not candidatos:
        return ""
    # O mais longo: o anúncio de não-lidas pode contribuir com um número
    # curto ("12 mensagens não lidas") antes do telefone de verdade.
    melhor = max(candidatos, key=len)
    if len(melhor) < MIN_DIGITOS_NUMERO:
        return ""
    return clean_number(melhor)


# Um nome precisa de alguma substância para servir de chave de casamento:
# iniciais ("Ed", "Jô") casariam com meio mundo numa lista de conversas.
MIN_CARACTERES_NOME = 3

_RE_ESPACOS = re.compile(r"\s+")


def chave_de_nome(texto) -> str:
    """
    Normaliza um nome para comparar planilha contra lista: minúsculas, sem
    acento, espaços colapsados.

    Existe porque o mesmo contato é escrito de dois jeitos por duas pessoas
    diferentes — "José  Silva" na planilha, "Jose Silva" na agenda — e nenhum
    dos dois está errado.
    """
    limpo = limpar_bidi(texto)
    sem_acento = "".join(
        c for c in unicodedata.normalize("NFD", limpo) if not unicodedata.combining(c)
    )
    return _RE_ESPACOS.sub(" ", sem_acento.lower()).strip()


def titulo_casa_com_nome(titulo, nome) -> bool:
    """
    O título desta linha é o contato `nome` da planilha?

    **Por que isso é necessário.** Contato SALVO na agenda não mostra número
    nenhum na lista de conversas: o título é o nome. `numero_do_titulo`
    devolve "" e, como todo o casamento planilha-contra-lista era por número,
    esses contatos caíam em "conversa não encontrada" — que é o único desfecho
    que não escreve nada. Na prática o cliente via "-" e concluía que o app não
    sabia dizer se a mensagem tinha sido vista, justamente nos contatos dele
    que já eram conhecidos.

    **O anúncio de não-lidas mora no mesmo elemento**, prefixado ao nome, do
    mesmo jeito que já envenenava a extração de número (ver `numero_do_titulo`):
    o título vira `"1 mensagem não lidaIsis Campos"` — sem nem um espaço no
    meio. Então a comparação aceita o nome no FIM do título, desde que o que
    sobra na frente comece com dígito: anúncio começa com contador, nome de
    gente não. É independente de idioma, ao contrário de casar o texto
    "mensagem não lida" / "unread message".

    Não é casamento aproximado de propósito. Um "parecido" aqui gravaria o
    estado da conversa de OUTRA pessoa na linha deste contato, e um erro desses
    não deixa rastro nenhum na tela — o mesmo motivo pelo qual nomes curtos
    demais (< `MIN_CARACTERES_NOME`) não servem de chave.
    """
    alvo = chave_de_nome(nome)
    if len(alvo) < MIN_CARACTERES_NOME:
        return False
    titulo_limpo = chave_de_nome(titulo)
    if not titulo_limpo:
        return False
    if titulo_limpo == alvo:
        return True
    if titulo_limpo.endswith(alvo):
        prefixo = titulo_limpo[: -len(alvo)]
        return bool(re.match(r"\d", prefixo))
    return False


def _normalizar_icone(nome) -> str:
    """Minúsculas e sem acento, para comparar nome de ícone sem sustos."""
    limpo = limpar_bidi(nome).lower()
    return "".join(c for c in unicodedata.normalize("NFD", limpo) if not unicodedata.combining(c))


_RE_COR = re.compile(r"rgba?\(\s*(\d+)[,\s]+(\d+)[,\s]+(\d+)")


def cor_de_leitura(cor) -> bool:
    """
    A cor do tique prova que ele LEU? Só o azul prova.

    O nome do ícone não distingue: em campo apareceu `wds-ic-read` num tique
    ainda CINZA (entregue, não lido), e o app dizia "Leu" sobre uma mensagem
    que o contato não tinha aberto. O que separa os dois estados na tela é a
    cor, não o nome.

    Medido em campo (08/09/2026, sonda `sonda_cor_tique.js`, capturando a
    transição ao vivo no mesmo contato):

        entregue, não lido  ->  rgba(0, 0, 0, 0.6)     (cinza)
        lido                ->  rgb(0, 123, 252)       (azul)

    A regra é "o canal azul domina": azul alto **e** bem acima do vermelho.
    Isso separa os dois com folga enorme (252 contra 0) e sobrevive ao tema
    escuro, onde o cinza vira branco translúcido — `rgba(255,255,255,.6)`
    tem azul alto mas azul-menos-vermelho zero, então não passa. Um tom de
    azul diferente (o WhatsApp já usou rgb(83,189,235)) continua passando.

    Sem cor legível, devolve False: "não consegui provar" tem de virar
    "Entregue", nunca "Leu". Há quem desligue a confirmação de leitura, e aí o
    azul nunca aparece — dizer "Leu" nesse caso seria inventar.
    """
    m = _RE_COR.search(str(cor or ""))
    if not m:
        return False
    r, g, b = (int(x) for x in m.groups())
    return b >= 150 and (b - r) >= 60


def classificar_status(icones, cor=None) -> str:
    """
    Traduz os ícones de status de uma linha no estado da última mensagem.

    `icones` são os nomes já filtrados (fora do `chat-msg-symbol`). Lista
    vazia significa que a última mensagem é DELE — não há tique em mensagem
    recebida.

    **`None` é diferente de lista vazia, e a diferença é o guard do rascunho.**
    `None` significa que a linha não tem elemento `last-msg-status` NENHUM, e
    isso não é evidência de resposta — é ausência de evidência. A sonda de
    12/09/2026 (`sonda_texto_resposta.js`, 19 linhas com mensagem dele) achou
    exatamente um caso assim, e era uma conversa com **rascunho**: texto
    digitado e não enviado, que substitui a prévia e leva o status junto.

    Tratar isso como lista vazia gravava `Respondeu=Sim` num contato que nunca
    respondeu — e o caminho é alcançável numa campanha real: um envio
    interrompido entre `_human_type` e `_confirm_message_sent` deixa o texto
    digitado como rascunho naquela conversa. `INDETERMINADO` não é gravado por
    `aplicar_leitura`, então a linha simplesmente fica como estava.

    A ordem importa: falha vence tudo (a mensagem não saiu), depois o ✓✓
    (cuja cor decide entre lido e entregue). Qualquer ícone restante é uma
    mensagem nossa que ainda não chegou — é o que arma o alarme de entrega,
    e é onde cai o ✓ solitário.
    """
    if icones is None:
        return INDETERMINADO

    nomes = [_normalizar_icone(i) for i in icones if limpar_bidi(i)]
    if not nomes:
        return ULTIMA_DELES

    falha = _normalizar_icone(seletores.get("icone_falha"))
    duplo = _normalizar_icone(seletores.get("icone_tique_duplo"))

    if any(falha in n for n in nomes):
        return FALHOU
    if any(duplo in n for n in nomes):
        # O ✓✓ tem o mesmo nome de ícone entregue ou lido; só a cor separa os
        # dois. Sem o azul não há prova, e sem prova cai para ENTREGUE — que é
        # verdade nos dois casos.
        return LIDO if cor_de_leitura(cor) else ENTREGUE
    # Tudo o mais é "saiu e não chegou" — inclusive `wds-ic-delivered`, que é
    # o ✓ solitário apesar do nome prometer entrega. É esta linha que faz o
    # alarme de entrega enxergar o bloqueio do número.
    return NAO_ENTREGUE


def interpretar_horario(texto, agora: Optional[datetime] = None) -> Optional[datetime]:
    """
    Converte o horário da linha em datetime, quando dá.

    A lista só mostra "14:32" para hoje, "Ontem" para ontem, e o nome do dia
    ou a data para o resto. Só o caso de hoje tem precisão de minuto — é por
    isso que a régua de "quente" degrada para granularidade de dia depois de
    24h, e por isso a classificação ordena por latência em vez de rotular.

    Devolve None quando não dá para saber (nome de dia da semana, formato
    desconhecido). None é resposta legítima, não erro.
    """
    limpo = limpar_bidi(texto)
    if not limpo:
        return None
    agora = agora or datetime.now()

    m = re.fullmatch(r"(\d{1,2}):(\d{2})", limpo)
    if m:
        hora, minuto = int(m.group(1)), int(m.group(2))
        if hora > 23 or minuto > 59:
            return None
        return agora.replace(hour=hora, minute=minuto, second=0, microsecond=0)

    if _normalizar_icone(limpo) == "ontem":
        # Sem hora: o WhatsApp não a mostra. Meia-noite é a única âncora
        # honesta — a latência sai como "mais de X horas", não como um número
        # preciso que seria invenção.
        ontem = agora - timedelta(days=1)
        return ontem.replace(hour=0, minute=0, second=0, microsecond=0)

    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{2,4})", limpo)
    if m:
        dia, mes, ano = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if ano < 100:
            ano += 2000
        try:
            return datetime(ano, mes, dia)
        except ValueError:
            return None

    return None


def decidir_estado(icones, nao_lidas, cor=None) -> str:
    """
    Estado final da linha, combinando o ícone de status com o contador de
    não-lidas. É esta função que manda, não `classificar_status` sozinha.

    **Por que o ícone não basta.** Em campo apareceu a combinação que a regra
    por ausência não prevê: a linha traz o badge verde de não-lidas — chegou
    mensagem dele — E um `wds-ic-read` da nossa mensagem, e a leitura saía
    "Lido / não respondeu" para um contato que tinha respondido. Seja lá qual
    for a causa no DOM (badge e tique convivendo, ou nó de status remanescente
    numa lista virtualizada), o contador é evidência independente e mais forte.

    **Por que o contador é conclusivo aqui.** Não-lida só existe para mensagem
    RECEBIDA — ninguém tem não-lidas das próprias mensagens. E o envio abre a
    conversa para digitar, o que zera o contador daquele chat; então qualquer
    não-lida posterior ao envio é mensagem nova dele. Como a varredura só olha
    contatos com `Enviado=X`, essa condição vale sempre.

    Vence inclusive `FALHOU`: uma falha de entrega descreve uma mensagem
    nossa, e uma resposta dele é o fato mais recente e o único acionável.
    E vence também o guard do rascunho (`icones=None`): uma conversa pode ter
    rascunho E mensagem nova dele ao mesmo tempo, e o contador é prova
    independente do elemento de status.
    """
    if nao_lidas and nao_lidas > 0:
        return ULTIMA_DELES
    return classificar_status(icones, cor)


def _contar_nao_lidas(texto) -> int:
    """
    Lê o badge de não-lidas. Só dígitos: o WhatsApp escreve "3" mas também
    "3 mensagens não lidas" dependendo do idioma e do aria-label.
    """
    digitos = re.sub(r"\D", "", limpar_bidi(texto))
    return int(digitos) if digitos else 0


def interpretar(bruto: dict, agora: Optional[datetime] = None) -> dict:
    """
    Normaliza uma linha crua vinda do JS num registro utilizável.

    Não decide nada sobre a campanha (isso é do chamador, que sabe quem foi
    enviado): apenas relata o que a linha mostra.
    """
    bruto = bruto or {}
    titulo = limpar_bidi(bruto.get("titulo"))
    numero = numero_do_titulo(titulo)
    nao_lidas = _contar_nao_lidas(bruto.get("nao_lidas"))
    cor = bruto.get("cor_status")
    estado = decidir_estado(bruto.get("icones_status"), nao_lidas, cor)

    return {
        "indice": bruto.get("indice"),
        "titulo": titulo,
        "numero": numero,
        # Contato salvo na agenda aparece pelo nome: o casamento com a
        # planilha tem de cair no Nome, que é mais frouxo.
        "casa_por_numero": bool(numero),
        "estado": estado,
        # Os nomes crus dos ícones, do jeito que saíram do DOM. Não alimentam
        # decisão nenhuma — existem para o log de diagnóstico poder dizer POR
        # QUE uma linha foi lida como foi. Sem isso, "Lido" num contato que
        # respondeu é indistinguível de uma extração quebrada.
        "icones": [limpar_bidi(i) for i in (bruto.get("icones_status") or [])],
        # A cor computada do tique, do jeito que veio do browser. Entra no log
        # de diagnóstico junto dos ícones: é ela que decide entre "Leu" e
        # "Entregue", então sem ela o log não explicaria a decisão.
        "cor_status": limpar_bidi(cor),
        "respondeu": estado == ULTIMA_DELES,
        "entregue": estado in ESTADOS_ENTREGUES,
        "horario_texto": limpar_bidi(bruto.get("horario")),
        "horario": interpretar_horario(bruto.get("horario"), agora),
        "nao_lidas": nao_lidas,
        # Texto completo da última mensagem. Vem do `title` do
        # `last-msg-status`, e a sonda de 12/09/2026 mediu por que essa é a
        # fonte certa e não a prévia (`linha_previa`):
        #
        #   - o `title` vem INTEIRO, não truncado (393 e 385 caracteres
        #     capturados, sem reticências de corte);
        #   - a prévia é `textContent`, então ABSORVE o `<title>` do svg do
        #     ícone e o prefixo de remetente de grupo — sai
        #     `"wds-ic-readEu vim treinar"` e `"~Malu Matos: Combinado..."`.
        #     Alimentar a triagem com isso seria ruim na heurística e pior no
        #     LLM. Por isso `linha_previa` continua sem uso.
        #
        # Dois cuidados para quem consumir: quando a última mensagem é NOSSA,
        # este campo traz o NOSSO texto (só vale como resposta se
        # `respondeu`), e mídia vira rótulo localizado do WhatsApp ("Foto",
        # "Figurinha", "Mensagem apagada"), não conteúdo.
        "ultima_mensagem": limpar_bidi(bruto.get("ultima_mensagem")),
    }


# ============================================================
# Extração do DOM — uma única ida ao browser
# ============================================================
_JS_EXTRAIR = """
const S = __SELETORES__;

const nomesDeIcone = (raiz) => {
  if (!raiz) return [];
  const nomes = [];
  // Ícone de status = o que está no last-msg-status e FORA do símbolo de
  // mídia. Sem esse filtro, uma figurinha que ELE mandou viraria tique nosso.
  raiz.querySelectorAll('svg > title').forEach((t) => {
    if (S.linha_simbolo_midia && t.closest(S.linha_simbolo_midia)) return;
    const nome = (t.textContent || '').trim();
    if (nome) nomes.push(nome);
  });
  // Esquema antigo, que ainda convive com o novo (ex.: message-fail).
  raiz.querySelectorAll('[data-icon]').forEach((el) => {
    if (S.linha_simbolo_midia && el.closest(S.linha_simbolo_midia)) return;
    const nome = (el.getAttribute('data-icon') || '').trim();
    if (nome) nomes.push(nome);
  });
  return nomes;
};

// O <svg> do tique de STATUS (nao o de tipo de midia). E dele que sai a cor
// que separa "entregue" (cinza) de "lido" (azul) — os dois usam o mesmo nome
// de icone, entao sem a cor nao da para distinguir.
const svgDeStatus = (raiz) => {
  if (!raiz) return null;
  for (const t of raiz.querySelectorAll('svg > title')) {
    if (S.linha_simbolo_midia && t.closest(S.linha_simbolo_midia)) continue;
    return t.parentElement;
  }
  for (const el of raiz.querySelectorAll('[data-icon]')) {
    if (S.linha_simbolo_midia && el.closest(S.linha_simbolo_midia)) continue;
    return el;
  }
  return null;
};

const corDoStatus = (raiz) => {
  const svg = svgDeStatus(raiz);
  if (!svg) return '';
  try {
    // `currentColor` no fill do svg: a cor efetiva vem do computed style.
    return getComputedStyle(svg).color || '';
  } catch (e) {
    return '';
  }
};

const texto = (linha, sel) => {
  const el = sel ? linha.querySelector(sel) : null;
  return el ? (el.textContent || '') : '';
};

return [...document.querySelectorAll(S.linha_conversa)].map((linha, i) => {
  const status = linha.querySelector(S.linha_status_ultima_msg);
  return {
    indice: i,
    titulo: texto(linha, S.linha_titulo),
    horario: texto(linha, S.linha_horario),
    nao_lidas: texto(linha, S.linha_nao_lidas),
    // `null` quando NAO EXISTE elemento de status na linha — diferente de
    // `[]`, que e' "existe e nao tem icone" (= mensagem dele). Ver o guard
    // do rascunho em `classificar_status`.
    icones_status: status ? nomesDeIcone(status) : null,
    cor_status: corDoStatus(status),
    ultima_mensagem: status ? (status.getAttribute('title') || '') : '',
  };
});
"""


def js_extrair(sels: Optional[dict] = None) -> str:
    """Monta o JS de extração com os seletores vigentes."""
    sels = sels if sels is not None else seletores.todos()
    return _JS_EXTRAIR.replace("__SELETORES__", json.dumps(sels, ensure_ascii=False))


def ler_linhas(driver, agora: Optional[datetime] = None) -> list:
    """
    Lê a lista de conversas visível e devolve os registros interpretados.

    Uma única chamada de `execute_script` para a lista inteira: o custo é
    sub-segundo, o que é o que permite rodar isto na pausa entre rajadas sem
    atrasar a próxima (ver BRAINSTORM_IA.md #7c).

    `#pane-side` é virtualizado — só vem o que está renderizado. Para a
    varredura no meio do envio isso basta e sobra: mandar mensagem joga a
    conversa para o topo da lista, então os contatos da rajada que acabou de
    rodar são as primeiras linhas.
    """
    brutos = driver.execute_script(js_extrair()) or []
    return [interpretar(b, agora) for b in brutos]
