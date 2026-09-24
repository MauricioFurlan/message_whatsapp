# Brainstorm: IA no WhatsApp Automacao

> Data: 03/09/2026
> Status: Planejamento inicial
> Complementa: `BRAINSTORM_SAAS.md` (infra multi-tenant)

---

## 📌 Contexto

O sistema hoje é FastAPI + Selenium dirigindo um Chrome real contra o
web.whatsapp.com. A pergunta que originou este documento: **"o Claude Code
existe no Chrome e é uma ferramenta de automação — dá pra usar aqui?"**

A resposta curta é: dá, mas não no lugar que parece.

---

## 🔍 Primeiro, a distinção

São duas coisas diferentes, e nenhuma substitui o Selenium:

| O quê | Como funciona | Serve pra quê aqui |
|-------|---------------|--------------------|
| **Claude for Chrome** (extensão) | Claude enxerga a aba e clica/digita. Cada ação é uma chamada de LLM | Não serve como motor de envio — é um agente com usuário presente, não uma API |
| **Claude Code + Chrome DevTools/Playwright MCP** | Claude Code dirigindo um Chrome durante o desenvolvimento | Ferramenta de dev/QA. Não vai no `.exe` do cliente |

### Por que NÃO trocar o Selenium por um agente

- **Não-determinismo onde não pode errar.** O envio roda 2-4h com invariantes
  duros: não reenviar contato marcado, não duplicar anexo no retry, sobreviver a
  restart. Isso é código, não julgamento.
- **Custo por ação.** 118 contatos × N ações cada, com LLM em cada clique.
- **Latência.** Já são 41-58s só pra abrir uma conversa (ver `CLAUDE.md`,
  "The configured time is a total"). Somar inferência a cada passo piora.
- **Mata o plano do SaaS.** O `BRAINSTORM_SAAS.md` prevê worker headless no EC2,
  sem ninguém na frente da tela. Agente de navegador precisa de sessão
  interativa.

**Conclusão: o ganho não é trocar o motor. É colocar inteligência em volta dele
— nos lugares onde hoje o LLM sou eu, lendo log na mão, ou onde não existe nada.**

---

## 🎯 Features propostas

Ordenadas por valor/esforço.

### 1. Diagnóstico visual no fracasso (o híbrido)

**Dor atacada:** o próprio `CLAUDE.md` documenta — *"A network outage looks like
a bad number, and only the log tells them apart."*

Quando o chat não abre, hoje não se sabe se foi número inexistente, rede caída,
contato bloqueado, ou um diálogo novo do WhatsApp que ninguém previu. O código
chuta `Invalido="X"` e o usuário conserta no ↺.

**Proposta:** no timeout, `driver.get_screenshot_as_png()` e uma pergunta fechada
ao Claude (structured outputs, 4 categorias). Selenium continua sendo 99% do
caminho feliz; o LLM só entra quando o código já se declarou perdido.

```python
# whatsapp_sender.py, dentro do except TimeoutException
import base64, anthropic

client = anthropic.Anthropic()
png = self.driver.get_screenshot_as_png()

resp = client.messages.create(
    model="claude-opus-5",
    max_tokens=512,
    messages=[{"role": "user", "content": [
        {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                     "data": base64.standard_b64encode(png).decode()}},
        {"type": "text", "text": PROMPT_CLASSIFICA_FALHA},
    ]}],
)
```

**Custo:** só existe no fracasso. Uma screenshot é ~1.5k tokens de input; 30
falhas num envio dão centavos, ainda mais com Haiku 4.5 ($1/MTok input).

**Ganho:** `Motivo` vira preciso, e dá pra **não queimar o contato** quando for
rede — hoje ele é marcado inválido do mesmo jeito.

---

### 2. Post-mortem automático do log ⭐ começar por aqui

**Dor atacada:** a tabela do `CHANGELOG.md` de 03/09/2026 (execução × enviadas ×
timeouts × falhas de `#pane-side`, e a taxa por faixa 0-20min / 20-60min / 60min+)
foi trabalho manual — e produziu o melhor insight do produto inteiro: o arranque
frio do WhatsApp Web.

**Proposta:** endpoint `/stats/analise`. Manda o `log.txt` (com números
mascarados) + os agregados do `stats_log.py` e devolve um diagnóstico em
português pro cliente:

> "Sua taxa de falha foi 43% nos primeiros 20 minutos e 6% depois. Abra o
> aplicativo ~20 min antes de iniciar o envio."

**Custo:** log de 3h ≈ 50k tokens → ~$0.25 com Opus 5, ~$0.10 com Sonnet 5. Por
envio, é irrelevante.

**Por que é a primeira:** uma chamada de API, usa dado que já existe no disco,
zero risco pro caminho de envio, e automatiza literalmente o trabalho manual que
gerou o maior aprendizado do projeto. Vira argumento de venda direto: o sistema
não só falha — ele explica por quê.

---

### 3. Variação de mensagem (anti-bloqueio de verdade)

**Dor atacada:** o "Modo Comportamento Humano" varia *timing* (gaussiana,
micro-pausas, scroll aleatório). Não varia *texto*. 118 mensagens byte-a-byte
idênticas é exatamente o padrão que o WhatsApp detecta.

**Proposta:** gerar N variações naturais da mensagem global — mesmo sentido,
mesma oferta, redação diferente. O usuário aprova as que quiser na UI, e o sender
sorteia uma por contato dentro de `_montar_mensagem`.

**Custo:** 100 variações ≈ $0.75 com Opus 5; metade disso pela **Batch API**
(50% de desconto, e aqui latência não importa nada — é pré-processamento).

**Extensão natural:** personalização a partir de colunas extras da planilha
(`Empresa`, `Valor`, `Vencimento`). Hoje o cliente escreve as 118 mensagens à mão
no Excel — este é o trabalho chato que o produto ainda não tira dele.

---

### 4. Auditoria pré-envio

Antes do `/start`, Claude lê a planilha (anonimizada) + config + a estimativa do
`/estimate` e devolve avisos:

- mensagem longa demais ou com link que parece spam
- ausência de opt-out
- cadência incompatível com a janela configurada
- contatos com mensagem vazia ou nome quebrado

Uma chamada, barata, e evita o envio ruim **antes** dele acontecer — que é
melhor que explicá-lo depois (feature #2).

---

### 5. Triagem de respostas 🚀 salto de produto

**Dor atacada:** hoje é fire-and-forget. Dispara e acabou.

O Selenium já está logado no WhatsApp Web — ler a caixa de entrada é o mesmo
motor, não um sistema novo. Classificar as respostas com Claude:

| Categoria | O que dispara |
|-----------|---------------|
| `interessado` | destaca na planilha — é o número que o cliente quer ver |
| `nao_interessado` | marca e para de contatar |
| `opt_out` | "pare", "não quero mais", "descadastrar" → bloqueia reenvio |
| `numero_errado` | corrige a base |
| `pergunta` | notifica o usuário pra responder |

Grava de volta em colunas novas da planilha (mesma lógica de `Enviado`/`Motivo`).

**Por que importa:**
- **Opt-out automático é quase obrigatório com LGPD.** Hoje não existe.
- Muda a categoria do produto: de *disparador* para *ferramenta de campanha*.
- É o que justifica **preço recorrente** no lugar de licença única.

Tratar como projeto separado, não como incremento. Conversa direto com o
`BRAINSTORM_SAAS.md`.

---

### 6. Seletores como dado, não como código

Não é IA, mas é a maior fragilidade estrutural do produto.

**Problema:** `#pane-side` e os seletores de `_find_all_file_inputs` estão
hardcoded. Quando o WhatsApp muda o DOM, **todos os clientes param** até haver
rebuild do `.exe` + release nova.

**Proposta:** extrair pra um `seletores.json` versionado, servido pelo mesmo
mecanismo do `/check-update`. WhatsApp quebrado vira um arquivo publicado em 10
minutos, não um build.

**E aqui o Claude Code no Chrome finalmente ganha:** abre o WhatsApp Web
quebrado, pede pra ele localizar o novo seletor, publica o JSON. Este é o único
ponto do projeto onde o agente-de-navegador é a ferramenta certa — porque é
trabalho de investigação pontual, não de produção.

---

### 7. Classificação de contatos: quente / morno / frio

> É a **metade barata e sem IA da #5**. Não depende de chave de API, então não
> fica presa atrás do SaaS — pode sair antes de tudo nesta lista.

**Dor atacada:** o cliente dispara 118 mensagens e não tem ideia de quais valem
follow-up. Hoje o produto entrega "enviei" e nada mais.

#### O enunciado ingênuo mistura dois eixos

"Quente/neutro/frio" junta duas medidas com custo de obtenção radicalmente
diferente:

- **Latência** — respondeu rápido / devagar / nunca. Metadado puro,
  determinístico, zero LLM.
- **Teor** — interessado / evasivo / mandou parar. Precisa de julgamento sobre
  texto (é a #5 propriamente dita).

E falta um terceiro eixo que o WhatsApp dá de graça e que o app hoje ignora:
**entrega/leitura**. "Não respondeu" esconde três coisas incompatíveis:

| Estado real | Sinal | Leitura correta |
|---|---|---|
| Nem entregou (✓) | número morto / bloqueado | não é lead frio, é **base suja** |
| Entregou, não leu (✓✓) | ainda não viu | cedo demais pra classificar |
| Leu e não respondeu (azul) | esse é o **frio de verdade** | descartar ou trocar a abordagem |

Chamar os três de "frio" faz o cliente jogar fora contato bom e continuar
batendo em número inválido. É a mesma armadilha que o `CLAUDE.md` já documenta
do outro lado do funil — *"a network outage looks like a bad number"*.

#### O modelo de controle: varredura sob demanda

O obstáculo não é classificar, é **coletar**. O app é fire-and-forget: uma
passada e `_cleanup()` dá `driver.quit()`. A resposta chega horas ou dias
depois, quando não há navegador nenhum de pé.

Três modelos possíveis, e o do meio é o certo:

| Modelo | Por quê / por que não |
|---|---|
| Chrome aberto vigiando | ❌ só vale com o app aberto (perde a resposta da noite); `is_running()` passa a ter um quarto significado; um driver parado segura o `chrome_profile/` e faz o próximo `/start` cair em `ChromeProfileInUseError` |
| **Botão "Verificar respostas"** | ✅ execução curta e independente: abre o Chrome, espera `#pane-side`, lê, grava, fecha. Dezenas de segundos. Idempotente |
| Varredura agendada | 🔸 é só um timer em cima da anterior; soma depois, não substitui (mesma limitação de precisar do app aberto) |

O ponto de fundo: **a informação não é perecível.** A resposta fica na conversa
esperando. Não é preciso assistir na hora em que ela chega — é preciso passar lá
depois.

#### Como a varredura lê, sem abrir conversa nenhuma

Usar a **busca** do WhatsApp Web, não rolar a lista: `#pane-side` é virtualizado
e o usuário pode ter centenas de conversas. Filtrar pela busca **não abre nem
marca como lida**.

Para cada linha com `Enviado=X`: digita o número na busca → lê a linha da
conversa → limpa a busca. ~2-3s por contato.

| Sinal na linha | Significado |
|---|---|
| Badge verde com contador | ele escreveu e ninguém leu → **respondeu** |
| Prévia sem ícone de tique | a última mensagem é dele → **respondeu** (vale mesmo se o usuário já leu no celular e o badge sumiu) |
| Prévia com ✓ / ✓✓ / ✓✓ azul | a última mensagem ainda é a nossa → **não respondeu**, e o tique dá entregue vs. lido |
| Horário da linha | quando foi a última mensagem — ou seja, a hora da resposta |

A simetria é o que faz fechar: **se respondeu, o tique não faz falta; se não
respondeu, o tique da nossa própria mensagem está bem ali.** Um olhar na linha
resolve os dois casos.

Latência = horário da linha − `DataEnvio` (a planilha já grava).

**Duas limitações honestas:** o horário só é preciso no mesmo dia — depois vira
"ontem"/data, então a régua tem que degradar pra granularidade de dia; e
contato **salvo na agenda** aparece pelo nome, não pelo número, e o casamento
cai pro `Nome`, que é mais frouxo. Em prospecção a maioria não está salva, então
o caso comum é o fácil.

#### Regra de classificação: gravar fato, derivar rótulo

**Não gravar uma coluna `Classe`.** O app já tem exatamente este padrão e ele
funciona: `duplicado` é *derivado* no `GET /contacts`, na hora de exibir,
condicionado à config — não fica gravado na planilha. A classe tem que seguir o
mesmo caminho, por dois motivos:

- o corte ("quente é < 2h ou < 6h?") é decisão de negócio do cliente, e não há
  dado nenhum hoje pra defender um número específico;
- rótulo gravado congela a régua. Derivado, mudar o corte é mudar uma função
  pura — **sem re-varrer nada**.

**Colunas de fato** (mesma lógica de `Enviado`/`DataEnvio`/`Invalido`/`Motivo`):

`Respondeu` · `DataResposta` · `Entrega` (enviado/entregue/lido) ·
`UltimaVerificacao`

Planilha continua sendo fonte única de verdade, `GET /contacts` devolve o rótulo
derivado, a UI colore a linha. Nenhum banco novo.

#### A v1 não tem "morno" — e isso é deliberado

O enunciado original pede três baldes, mas eles não têm o mesmo custo de
verdade:

| Classe | Dá pra determinar sem LLM? |
|---|---|
| Respondeu (e em quanto tempo) | ✅ metadado puro |
| Leu e não respondeu | ✅ tique azul |
| Não leu | ✅ ✓✓ |
| Não entregou | ✅ ✓ |
| **Respondeu sem interesse (morno)** | ❌ **precisa do teor** |

Heurísticas de texto aqui são ruins e é melhor não fingir o contrário:
"resposta de uma palavra" reprova, porque **"sim" é a resposta mais quente
possível e tem uma palavra**, enquanto "não tenho interesse" tem quatro.
Separar morno de quente é exatamente o trabalho da #5, e só ela faz isso bem.

**Consequência prática: em vez de rotular, ordenar.** Quem respondeu sai numa
lista ordenada por latência, mais rápido primeiro. Entrega o mesmo valor sem
inventar régua, e o cliente enxerga sozinho onde está o corte dele.

#### O tique azul é opcional — e isso rebaixa um dos eixos

Confirmação de leitura pode ser desligada, e há **duas** formas disso acontecer
— a segunda é a perigosa:

1. **O destinatário desligou.** Nunca aparece azul para aquele contato.
2. **A conta do cliente desligou.** No WhatsApp a opção é **recíproca**: quem
   desliga a própria confirmação também **para de ver a dos outros**. Nesse caso
   o azul some da base inteira e a leitura do eixo vira ficção.

E o pior: "tem leitura desligada" é **indistinguível** de "ainda não abriu" — os
dois param no ✓✓.

**O que sobrevive intacto:**

| Sinal | Afetado? |
|---|---|
| Respondeu / não respondeu | ✅ imune — resposta é resposta |
| ✓ vs ✓✓ (entrega) | ✅ imune — **confirmação de entrega não pode ser desligada** |
| ✓✓ azul (leitura) | ❌ opcional, some sem aviso |

Ou seja: o **alarme de entrega da #7c continua 100% de pé**, porque ele só olha
✓ vs ✓✓. A peça de maior valor não depende do azul.

**Correção no desenho: "leu e não respondeu" deixa de ser classe.** Os estados
sólidos passam a ser três, com o azul virando um *refinamento oportunista*
dentro do terceiro:

- **Respondeu** → ordenado por latência
- **Não entregou** (✓) → base suja
- **Entregue, sem resposta** (✓✓) → o balde do follow-up
  - *quando* houver azul, anotar "lido" como informação extra — nunca como
    critério de classificação

**Heurística de autodiagnóstico:** se numa varredura de N ≥ 20 entregues não
aparecer **nenhum** azul, é muito mais provável que a conta do cliente esteja
com a confirmação desligada do que ninguém ter lido. Vale um aviso na UI
("verifique Configurações › Privacidade › Confirmações de leitura") em vez de
exibir uma coluna silenciosamente vazia.

Isto reforça a decisão anterior: **ordenar por latência de resposta é o eixo
confiável.** Tudo que depende de leitura é acessório.

#### Levantamento de seletores (sonda de 06/09/2026)

`sonda_pane_side.js` rodada no WhatsApp Web real. **Resultado: o risco de
seletor é muito menor do que se supunha** — o `#pane-side` mantém âncoras
`data-testid` semânticas, não só classes ofuscadas (`x1n2onr6`).

| `data-testid` | Serve para |
|---|---|
| `list-item-N` | a linha, **com índice de posição** |
| `cell-frame-title` | nome ou número do contato |
| `cell-frame-primary-detail` | horário (`14:32`, `Ontem`) |
| `cell-frame-secondary` | a prévia |
| `last-msg-status` | span cujo `title` traz o **texto completo** da última mensagem |
| `icon-unread-count` | badge, com `aria-label="N mensagens não lidas"` |
| `chat-msg-symbol` | ícone de tipo de mídia |

**Busca:** `input[role="textbox"][aria-label^="Pesquisar"]` — é um `<input>` de
verdade (não `contenteditable`) e fica **fora** do `#pane-side`. Simples de
dirigir com `send_keys`.

**Volume:** 71 linhas renderizadas sem rolar — folga de sobra para a #7c, onde
os contatos da rajada estão no topo por construção.

**Número não salvo é o caso fácil — e é o caso da campanha.** Segunda sonda,
com um número fora da agenda: o `cell-frame-title` traz
`"+55 19 99594-7333"`. Só os dígitos (`5519995947333`) já passam pelo
`clean_number()` do `contact_logic.py` e casam com a planilha. O casamento
frouxo por nome só ameaça contatos salvos, que em prospecção são a exceção.

**Detalhe de parsing:** o `title` do `last-msg-status` vem cercado de marcas
bidi invisíveis (U+202A / U+202C). Limpar antes de comparar.

**Os tiques.** Convivem **dois esquemas de ícone**: o antigo com atributo
`data-icon` (`message-fail`, `recalled`, `lock-outline`) e um novo `wds-ic-*`
**sem** `data-icon`. Confirmados em amostras independentes:

- **`wds-ic-read`** = ✓✓ azul (lido)
- **`wds-ic-delivered`** = ✓✓ (entregue)
- o ✓ solitário (enviado, não entregue) ainda não foi capturado: no teste com
  modo avião a mensagem foi entregue mesmo assim, quase certamente por
  **multi-dispositivo** (um aparelho companheiro online recebe por ele).

**E não precisa dele para começar.** O estado se decide por *ausência*, não por
presença de um ícone específico:

| O que há no `cell-frame-secondary` | Estado |
|---|---|
| **nenhum** ícone de status | a última mensagem é dele → **respondeu** |
| `wds-ic-read` | lido, sem resposta |
| `wds-ic-delivered` | entregue, sem resposta |
| `data-icon="message-fail"` | falha de envio |
| **qualquer outro** ícone de status | enviado, **não entregue** → arma o alarme |

**Sutileza obrigatória:** ícone de *tipo de mídia* também mora no
`cell-frame-secondary` (`wds-ic-sticker`, `ic-keyboard-voice-filled`), mas
sempre dentro de `[data-testid="chat-msg-symbol"]`; o tique de status fica
**fora** dele. Logo:

> ícone de status = ícone em `cell-frame-secondary` que **não** está dentro de
> `chat-msg-symbol`

Isso separa os dois casos com precisão, inclusive quando a nossa própria
mensagem é uma mídia (aí existem os dois).

**Consequência: a #7c está destravada.** O alarme de entrega distingue
"entregue/lido" de "qualquer outra coisa", e isso já dá para escrever. O nome
do ✓ vira detalhe de `Motivo`, não critério de decisão.

**O hook do ícone (fechado pela sonda v2).** O nome não vinha de falha de
sprite: é o `<title>` de dentro do próprio `<svg>` — parte permanente do DOM,
o nome acessível do gráfico.

```html
<span data-testid="last-msg-status" title="teste">
  <span aria-hidden="true">
    <svg fill="currentColor">
      <title>wds-ic-delivered</title>   <!-- o nome esta AQUI -->
      <path .../>
    </svg>
  </span>
  ...texto da mensagem...
</span>
```

O ícone de status vive **dentro** do `last-msg-status`, e o `chat-msg-symbol`
(tipo de mídia) também, aninhado. Seletor definitivo:

```
[data-testid="last-msg-status"] svg > title        -> nome do icone
   ignorando os que estao dentro de [data-testid="chat-msg-symbol"]
```

`fill="currentColor"` com cor `rgba(0,0,0,0.6)` no entregue — a cor vem do
container e serve como confirmação secundária do azul.

#### Decisões fechadas (06/09/2026)

**Confirmação de leitura da conta da campanha: LIGADA.** O eixo "leu e não
respondeu" vale. Ressalva mantida: o *destinatário* ainda pode ter desligado a
dele, e aí a linha fica em `wds-ic-delivered` para sempre. O azul é confiável
**quando aparece**; a ausência é ambígua. A heurística de zero-azul-em-20
continua valendo como guarda.

**Escopo da varredura: a planilha atual, sem recorte por data.** A pergunta
"quantos dias?" se dissolve — o app opera sempre em `uploads/contatos.xlsx` e
todo `/upload` sobrescreve, então a planilha *já é* o recorte da campanha. O
escopo é simplesmente **todas as linhas com `Enviado=X`**. Nada de
configuração: seria um número arbitrário para um usuário leigo errar. Otimização
de graça: quem já foi marcado "respondeu" numa varredura anterior não precisa
ser reconsultado — ninguém des-responde. Custo estimado: 118 contatos × ~2-3s
≈ 5 min, aceitável para um botão com barra de progresso.

**UI: abas com contadores + coluna ordenável.** As abas filtram o grupo
(`Todos 118` / `Respondeu 12` / `Sem resposta 94` / `Não entregou 12`), e dentro
da aba a coluna Status ordena por tempo de resposta. O contador da aba já
responde "quantos responderam?" sem clicar em nada — que é a pergunta real do
cliente — e a ordenação faz o mais quente subir ao topo.

Sem aba "morno" na v1: ela exigiria ler o teor, e um filtro que existe e nunca
retorna nada é pior que não existir. Quando a #5 entrar, a aba **Respondeu** se
divide em quente/morno — o conceito não muda de lugar, ganha subdivisão. O dado
já estará lá: o leitor captura o texto **completo** da última mensagem (o
`title` do `last-msg-status`), não a prévia truncada.

Barato de fazer: `static/index.html` já carrega todos os contatos e já guarda
estado por linha em `dataset` (`enviado`, `invalido`), com uma chave de
ordenação em uso. O filtro é client-side, sem endpoint novo — o `GET /contacts`
só passa a devolver o rótulo derivado, como já devolve `duplicado`.

#### Seletores remotos (fecha o #6, com quatro ajustes)

Decidido: os seletores saem do código e passam a vir de fora, para que uma
mudança no WhatsApp vire um arquivo publicado e não um build novo.

**Ajuste 1 — cache em disco, não `localStorage`.** Os seletores são consumidos
pelo **Selenium, em Python**; o `localStorage` vive no navegador da UI
(localhost:8000) e o sender nunca o enxerga. O cache é arquivo, ao lado do
`config.json`. O padrão já existe pronto em `license.py`: busca no Supabase,
grava cache local, degrada com tolerância offline — espelhar aquilo.

**Ajuste 2 — defaults embutidos no `.exe`.** A cadeia é
`embutido → cache em disco → Supabase`. Supabase fora do ar no primeiro uso não
pode impedir o app de funcionar. Nunca dependência dura.

**Ajuste 3 — quando refazer o GET.** "Se der problema" é largo demais: um número
inválido dispararia refetch à toa. Refaz apenas em falha **estrutural** (o
`#pane-side` não aparece, ou `list-item` volta zero linhas em várias
tentativas), nunca em falha de um contato. Com trava de uma vez por sessão / a
cada N minutos, ou um WhatsApp quebrado martela o Supabase a cada contato.

**Ajuste 4 — só seletores, nunca código.** O JSON carrega **strings de seletor**
e nada mais: nada de JS para executar. É conteúdo remoto entrando num app que
dirige a conta de WhatsApp do cliente; a fronteira é estreita de propósito.
Mais um campo `versao_schema`, para um JSON novo não quebrar um `.exe` antigo.

**Migração incremental:** começar pelos seletores novos (leitura da linha) mais
o `#pane-side`, que é o mais crítico. Anexo, QR e detecção de popup vêm depois —
migrar tudo de uma vez é refatoração grande em cima do caminho de envio.

**Mensagem ao usuário: nunca técnica.** Ele não vê nome de seletor.

> **Atualizando…** O WhatsApp mudou alguma coisa e o programa está buscando o
> ajuste automaticamente. Isso leva alguns segundos.

E na falha:

> Não consegui buscar a atualização agora. Verifique sua conexão e tente de
> novo — se persistir, entre em contato com o suporte.

O nome do seletor vai só para o `log.txt`.

#### Restrição de concorrência

Varredura e envio disputam o mesmo Chrome. O endpoint recusa via
`_recusar_se_enviando()` (que já existe), **e o inverso também**: não deixar
iniciar envio com varredura em curso.

#### O que a #5 acrescenta em cima disto

Com as colunas populadas, a #5 vira só a chamada de LLM sobre o texto da prévia
para separar *morno* de *quente* por teor e capturar **opt-out** — e só nas que
responderam, que são poucas, em vez das 118.

---

### 7b. Analisar durante o envio: só o que já está na tela

Pergunta natural: já que o sender abre a conversa de cada contato, dá pra ir
analisando e atualizando a planilha na mesma passada?

**Dá — mas só a parte de graça, e só leitura.**

O que é grátis: o sender **já navegou** e a conversa **já está aberta e já foi
marcada como lida**. O efeito colateral está pago. Ler o DOM que está ali é
alguns ms de JS.

| Fazer no envio | Não fazer no envio |
|---|---|
| Ler resposta de campanha anterior na conversa que já abriu | Voltar em contato já enviado pra ver se respondeu — é **outra navegação**, o item mais caro do app (41-58s) |
| **Checar opt-out antes de mandar** ("pare", "não quero mais") e abortar aquele contato | Qualquer chamada de LLM — viola a restrição "nada de IA no caminho crítico" |
| Registrar o tique da mensagem recém-enviada | Escrever a planilha de outra thread |

**O caso que sozinho justifica a feature é o opt-out.** Se o contato já pediu
pra parar numa campanha anterior, o texto está na tela no exato instante em que
estamos prestes a mandar de novo. Custa uma leitura de DOM e evita o pior erro
possível de LGPD. Isso é bem mais forte que a classificação em si.

**Perigos, e são reais:**

1. **Exceção nova no caminho crítico.** Um `StaleElementReference` no código de
   análise cascateando pra dentro do loop de envio marcaria contato como
   inválido ou abortaria a rajada. Tudo tem que estar embrulhado de forma que
   **nunca** possa derrubar um envio.
2. **A estimativa passa a mentir.** `TEMPO_ESTIMADO_ABERTURA_CHAT` está
   calibrado. Qualquer custo por contato entra nas constantes da estimativa, ou
   o `/estimate` — que existe justamente pra avisar antes de começar — vira
   ficção.
3. **Poluir a métrica de lentidão.** O tempo da análise não pode entrar na
   medição de `_registrar_resultado_de_abertura()`, ou o `alerta_lentidao`
   dispara por causa do nosso próprio código.
4. **Um único escritor.** Quem grava a planilha é a thread do sender, que já
   grava. Nada de um segundo escritor em paralelo.

**Conclusão:** durante o envio, ler o que já está na tela e gravar pela mesma
thread. A classificação propriamente dita fica na varredura pós-envio da #7 —
que é onde a informação existe de verdade, porque quase ninguém responde antes
de a rajada acabar.

---

### 7c. Usar a pausa entre rajadas — e o alarme de entrega

**A ociosidade existe e é considerável.** Simulando `_generate_burst_plan` com
o caso de referência (118 msgs / 240 min → orçamento de pausas ≈ 6730s):

| | |
|---|---|
| Rajadas por execução | 24 a 32 |
| Pausa entre rajadas | 90s a 275s (mediana ~150-200s) |

São ~25 janelas de 2 a 4 minutos com o navegador aberto sem fazer nada.

**Mas não vale supor que a folga sempre existe.** Quando a janela configurada é
apertada, `_generate_burst_plan` cai no ramo de fallback e todo intervalo vira
`DELAY_INTRA_MIN` (15s). A leitura tem que ser **oportunista**: só roda se
`pause_after` passar de um limiar, e limitada pelo que sobrar dele.

#### O mecanismo aqui é mais simples que o da #7

Na varredura pós-envio é preciso usar a busca, porque a execução acabou faz
tempo e outras conversas empurraram as nossas para baixo.

**Durante a pausa, não.** Mandar mensagem joga a conversa para o **topo** do
`#pane-side` — então os contatos da rajada que acabou de rodar são,
por construção, as primeiras linhas da lista. E o painel está visível ao lado da
conversa aberta, sem navegar para lugar nenhum.

Ou seja: **um `find_elements` nas linhas visíveis. Sub-segundo, zero interação.**
Nada de 40 buscas programáticas — o que também elimina a objeção de que
encher a pausa de atividade destrói justamente o comportamento humano que ela
existe para simular.

#### O ganho real não é o quente/frio — é o alarme de entrega

Quase ninguém responde antes de a rajada acabar, então como coletor de
classificação isto rende pouco. O que rende muito é outra coisa:

> Se as últimas N mensagens enviadas continuam todas com **um tique só**
> (não entregue), isso é a assinatura do número sendo limitado ou bloqueado
> pelo WhatsApp.

Esse é o risco existencial do produto, e hoje **nada o detecta**. Descobrir na
mensagem 40, e não ao abrir a planilha no dia seguinte com 118 não entregues,
é a diferença entre perder um envio e perder o número do cliente.

Mesma ideia para o teor: várias respostas do tipo "pare" / "quem é você?" nas
primeiras rajadas dizem que a campanha está indo mal e que talvez valha
interromper.

#### Como expor

Seguir exatamente o padrão de `alerta_lentidao`: um campo dentro de
`get_status()`, com `seq` (a contagem no momento em que armou) para o popup
abrir uma vez só, sobrevivendo a F5 e a queda de SSE numa execução de horas.
Um `alerta_entrega` é o mesmo desenho.

#### Regras

1. **Limitado pela pausa.** Nunca estourar o `pause_after` — estourar atrasa a
   próxima rajada e faz a execução passar do tempo prometido ao usuário.
2. **Checar `_should_stop()`.** Senão o botão Parar durante a pausa passa a
   esperar a leitura terminar.
3. **À prova de exceção**, como na #7b: nada aqui pode derrubar um envio.
4. **Não substitui a #7.** A maioria das respostas chega depois que a execução
   terminou. Isto é a metade "alarme precoce"; a classificação continua sendo
   a varredura sob demanda.

---

## 💰 Referência de custo (preços Anthropic, por 1M tokens)

| Modelo | ID | Input | Output | Uso sugerido aqui |
|--------|----|-------|--------|-------------------|
| Claude Opus 5 | `claude-opus-5` | $5.00 | $25.00 | Post-mortem, variação de mensagem, auditoria |
| Claude Sonnet 5 | `claude-sonnet-5` | $2.00 | $10.00 | Alternativa de alto volume |
| Claude Haiku 4.5 | `claude-haiku-4-5` | $1.00 | $5.00 | Classificação simples (screenshot, triagem) |

- **Batch API:** 50% de desconto, para tudo que não é latência-sensível
  (variação de mensagem, análise de log em lote).
- **Prompt caching:** ~90% mais barato no prefixo repetido — vale se o mesmo
  prompt de sistema for reusado a cada contato.

---

## 🛠️ Do lado do desenvolvimento

O Chrome DevTools MCP no Claude Code faz o que os `tests/*.js` fazem hoje na
unha: exercitar SSE, tooltip, editor de contatos num Chrome de verdade. Vale como
acelerador de dev/QA — não como feature do produto.

---

## 📋 Ordem sugerida

### Fase 1: valor imediato, risco zero
- [ ] **#2** Post-mortem do log (`/stats/analise`)
- [ ] **#4** Auditoria pré-envio (reaproveita o pipeline da #2)
- [x] **#7** Classificação (varredura sob demanda) — **feito** (06/09/2026),
      sem IA e sem chave de API
      - [x] Fundação: `seletores.py` (seletores remotos) e `linha_conversa.py`
            (leitor de linha)
      - [x] `varredura.py` + `WhatsAppSender.verificar_respostas()`,
            `POST /verificar-respostas`, colunas de fato na planilha
      - [x] Botão, abas com contadores e coluna ordenável no `static/index.html`
      - [ ] Pendente para ligar a atualização remota: rodar
            `supabase_seletores.sql` no SQL Editor (sem ele o app usa os
            seletores embutidos e funciona igual)

### Fase 2: toca o caminho de envio
- [ ] **#1** Diagnóstico visual no timeout
- [ ] **#3** Variação de mensagem
- [ ] **#6** `seletores.json` + publicação via `/check-update`
- [ ] **#7b** Leitura oportunista durante o envio (só opt-out, só o que já está
      na tela) — depende da #7 já ter as colunas na planilha
- [x] **#7c** `alerta_entrega` na pausa entre rajadas — detectar o número sendo
      bloqueado/limitado ainda durante a execução. **Feito** (06/09/2026):
      `_verificar_entregas_na_pausa` + `_avaliar_alarme_de_entrega` no sender,
      popup vermelho com ação de parar na UI, 37 testes

### Fase 3: novo produto
- [ ] **#5** Triagem de respostas + opt-out automático (só o teor sobra, em cima
      da #7)

---

## ⚠️ Restrições a respeitar

- **Nada de IA no caminho crítico do envio.** As invariantes de `CLAUDE.md`
  (slot de rajada não consumido por inválido, não duplicar envio no retry,
  "Enviado" superando "duplicado") são código determinístico e continuam sendo.
- **Números não vão pra API.** Mascarar antes de mandar log/planilha — mesmo
  requisito de privacidade do `BRAINSTORM_SAAS.md`.
- **A chave de API não pode ir no `.exe`.** Ou o cliente informa a dele, ou as
  chamadas passam por um backend seu (o que empurra na direção do SaaS).
- **Toda feature de IA precisa degradar bem.** API fora do ar não pode impedir
  um envio de rodar.

---

## 💡 Notas e decisões futuras

- Avaliar se a #5 (triagem) exige o SaaS antes, por causa da chave de API.
- Medir se a #3 (variação de texto) realmente reduz bloqueio — vale instrumentar
  antes de vender como anti-bloqueio.
- A #1 e a #2 juntas dão material pra um "relatório de campanha" em PDF, que é
  entregável de valor pro cliente final.
