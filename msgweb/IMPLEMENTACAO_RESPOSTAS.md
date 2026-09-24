# Verificação de respostas e alarme de entrega — o que foi feito

> Data: 06/09/2026
> Escopo: features **#7** (classificação de contatos) e **#7c** (alarme de
> entrega) do `BRAINSTORM_IA.md`, mais a fundação de seletores remotos (**#6**)
> Estado: **implementado e testado**, sem teste de ponta a ponta contra o
> WhatsApp real

---

## 📌 O que o produto ganhou

Antes, o app era fire-and-forget: disparava as mensagens e acabava. O cliente
não tinha ideia de quem valia follow-up, e só descobria que o número tinha sido
limitado pelo WhatsApp ao abrir a planilha no dia seguinte com tudo não
entregue.

Agora existem duas coisas novas:

**1. Alarme de entrega (automático, durante o envio).** Se as mensagens saem e
não chegam, um popup vermelho avisa ainda no meio da execução e oferece parar.
Mensagem não entregue em bloco é a assinatura do número sendo limitado pelo
WhatsApp — o risco existencial do produto, e até aqui nada o detectava.

**2. Verificação de respostas (sob demanda, depois do envio).** Um botão
"Verificar respostas" lê a lista de conversas, descobre quem respondeu e em
quanto tempo, e preenche uma coluna na tabela com abas de filtro.

---

## 🔍 A investigação que veio antes do código

Nada disso era possível sem responder uma pergunta: **dá para ler o estado de
uma conversa sem abri-la?** Abrir custa 41-58s por contato (o item mais caro do
app) e marca a mensagem como lida, o que faz o cliente perder o badge de
não-lidas que ele usa para trabalhar.

Foram escritas duas sondas de DevTools, rodadas contra o WhatsApp Web real.
Ambas mascaram números e texto de mensagem: o que sai delas é estrutura
(`data-testid`, `data-icon`, `aria-label`, cor computada), nunca conteúdo.

### `sonda_pane_side.js` — o levantamento inicial

O achado que derrubou o risco do projeto: **o `#pane-side` mantém âncoras
`data-testid` semânticas**, não só classes ofuscadas (`x1n2onr6`).

| `data-testid` | Serve para |
|---|---|
| `list-item-N` | a linha, com o índice de posição |
| `cell-frame-title` | nome ou número do contato |
| `cell-frame-primary-detail` | horário (`14:32`, `Ontem`) |
| `cell-frame-secondary` | a prévia da última mensagem |
| `last-msg-status` | span cujo `title` traz o texto **completo** da última mensagem |
| `icon-unread-count` | badge, com `aria-label="N mensagens não lidas"` |
| `chat-msg-symbol` | ícone de tipo de mídia |

Mais: a busca é `input[role="textbox"][aria-label^="Pesquisar"]` — um `<input>`
de verdade (não `contenteditable`), fora do `#pane-side`, trivial de dirigir com
Selenium. E 71 linhas vinham renderizadas sem rolar.

**Contato fora da agenda** — o caso normal numa campanha de prospecção —
aparece no `cell-frame-title` como `+55 19 99594-7333`. Só os dígitos já passam
pelo `clean_number()` e casam com a planilha. O casamento frouxo por nome só
ameaça contatos salvos, que em prospecção são a exceção.

### `sonda_tiques.js` — o hook do ícone

A primeira sonda não capturou tique nenhum: nas linhas amostradas a última
mensagem era sempre do outro lado. E os nomes dos ícones apareciam como *texto*
(`wds-ic-read`, `wds-ic-sticker`), o que levantou a suspeita de sprite não
renderizado — algo em que não se pode construir.

A sonda v2, com modo vigia, respondeu: o nome vem do `<title>` de dentro do
próprio `<svg>`, que é parte permanente do DOM (é o nome acessível do gráfico),
não texto renderizado.

```html
<span data-testid="last-msg-status" title="teste">
  <span aria-hidden="true">
    <svg fill="currentColor">
      <title>wds-ic-delivered</title>   <!-- o nome está AQUI -->
      <path .../>
    </svg>
  </span>
  ...texto da mensagem...
</span>
```

**Ícones confirmados em campo:** `wds-ic-read` (✓✓ azul), `wds-ic-delivered`
(✓✓), `message-fail` (falha de envio, esquema antigo com `data-icon`).

O ✓ solitário (enviado, não entregue) nunca foi capturado — o teste com modo
avião entregou mesmo assim, quase certamente por multi-dispositivo. **E não
precisou:** a decisão de estado é por *ausência*, não por presença de um ícone
específico (ver abaixo).

**Detalhe de parsing que quebra tudo se ignorado:** o `title` do
`last-msg-status` vem cercado de marcas bidi invisíveis (U+202A/U+202C).

---

## 🧠 Decisões de desenho, e por quê

### "Quente/morno/frio" mistura dois eixos

O enunciado original junta duas medidas com custo de obtenção radicalmente
diferente:

- **Latência** — respondeu rápido / devagar / nunca. Metadado puro, zero LLM.
- **Teor** — interessado / evasivo / mandou parar. Precisa de julgamento sobre
  texto.

E falta um terceiro eixo que o WhatsApp dá de graça: **entrega/leitura**. "Não
respondeu" esconde três coisas incompatíveis — não entregou (número morto),
entregou mas não leu (cedo demais), leu e não respondeu (o frio de verdade).
Chamar as três de "frio" faz o cliente descartar contato bom e continuar
batendo em número inválido.

### A v1 não tem "morno" — e isso é deliberado

Separar morno de quente exige ler o **teor**, e nenhuma regra sobre metadado faz
isso. A heurística óbvia ("resposta de uma palavra") reprova de forma decisiva:
**"sim" é a resposta mais quente possível e tem uma palavra**, enquanto "não
tenho interesse" tem quatro.

Consequência prática: **em vez de rotular, ordenar.** Quem respondeu sai numa
lista ordenada por latência, mais rápido primeiro. Entrega o mesmo valor sem
inventar régua, e o cliente vê sozinho onde está o corte dele.

Uma aba "morno" que existe e nunca retorna nada é pior que não existir — o
usuário clica, vê vazio e conclui que o sistema está quebrado.

### O tique azul é opcional, e isso rebaixou um eixo

Confirmação de leitura pode ser desligada de **duas** formas, e a segunda é a
perigosa: no WhatsApp a opção é **recíproca**, então quem desliga a própria
também para de ver a dos outros. Nesse caso o azul some da base inteira.

E "tem leitura desligada" é indistinguível de "ainda não abriu" — os dois param
no ✓✓.

| Sinal | Afetado? |
|---|---|
| Respondeu / não respondeu | ✅ imune — resposta é resposta |
| ✓ vs ✓✓ (entrega) | ✅ imune — confirmação de entrega não pode ser desligada |
| ✓✓ azul (leitura) | ❌ opcional, some sem aviso |

Por isso "leu e não respondeu" **deixou de ser classe** e virou refinamento
opcional dentro de "entregue, sem resposta". E o alarme de entrega segue 100% de
pé, porque só olha ✓ vs ✓✓.

*(A conta da campanha atual está com confirmação de leitura **ligada**.)*

### Grava fato, deriva rótulo

**Não existe coluna `Classe`.** O app já tinha esse padrão resolvido: `duplicado`
é derivado no `GET /contacts` na hora de exibir, e não fica gravado.

Motivos: o corte ("quente é < 2h ou < 6h?") é decisão de negócio do cliente, e
não há dado hoje para defender um número; e rótulo gravado congela a régua —
derivado, mudar o corte é mudar uma função pura, **sem varrer nada de novo**.

### Escopo da varredura: a planilha, sem recorte por data

A pergunta "quantos dias?" se dissolve. O app opera sempre em
`uploads/contatos.xlsx` e todo `/upload` sobrescreve, então a planilha *já é* o
recorte da campanha. O escopo é simplesmente `Enviado=X`. Nada de configuração:
seria um número arbitrário para um usuário leigo errar.

**Contatos inválidos ficam de fora por construção**, e isso importa por dois
motivos. Um inválido nunca teve entrega — `AttachmentError` diz explicitamente
que *"o texto NÃO deve ser enviado"* e `WhatsAppNotLoadedError` é *"sempre ANTES
de qualquer entrega"*. E se o cliente já tinha conversa anterior com aquele
número, ler a linha atribuiria a esta campanha o estado de uma mensagem antiga.

O duplicado também se resolve sozinho: a linha duplicada fica inválida, mas a
original tem `Enviado=X` — o número é coberto pela original.

### Varredura sob demanda, não vigilância contínua

Três modelos foram considerados:

| Modelo | Veredito |
|---|---|
| Chrome aberto vigiando | ❌ só vale com o app aberto (as respostas chegam à noite); daria um quarto significado a `is_running()`; um driver parado segurando o `chrome_profile/` faria o próximo `/start` cair em `ChromeProfileInUseError` |
| **Botão "Verificar respostas"** | ✅ execução curta e independente, idempotente |
| Varredura agendada | 🔸 timer em cima da anterior; soma depois, não substitui |

O ponto de fundo: **a informação não é perecível.** A resposta fica na conversa
esperando. Não é preciso assistir na hora em que ela chega — é preciso passar lá
depois.

---

## 🧱 O que foi construído

### `seletores.py` (394 linhas) — seletores como dado

Tira os seletores do código-fonte e os põe numa cadeia de três camadas:

```
EMBUTIDO  ->  CACHE EM DISCO  ->  SUPABASE
```

Quando o WhatsApp mudar o DOM, o conserto vira um `insert` numa tabela, não um
build do `.exe` e uma release para todos os clientes.

Espelha o padrão que o `license.py` já usava (busca remota + cache local +
degradação silenciosa), porque é o mesmo problema.

**Quatro invariantes, cada uma com teste:**

1. **Cache em arquivo, nunca `localStorage`.** Quem consome os seletores é o
   Selenium, em Python. O `localStorage` vive no navegador da UI
   (localhost:8000) e o sender nunca o enxerga.
2. **Nunca dependência dura.** Supabase fora do ar, tabela inexistente, JSON
   corrompido, cache de outro schema — em todos os casos cai para a camada
   anterior. Nada aqui pode impedir um envio de rodar.
3. **Só seletores, nunca código.** `_validar_payload()` aceita apenas chave já
   conhecida, valor string não vazia, dentro de 500 caracteres. É conteúdo
   remoto entrando num app que dirige a conta de WhatsApp do cliente; a
   fronteira é estreita de propósito.
4. **Refetch só em falha ESTRUTURAL, com trava.** `registrar_falha_estrutural()`
   busca atualização quando o `#pane-side` não aparece ou a lista volta zero
   linhas — nunca por falha de um contato, que não diz nada sobre seletor. Trava
   de 15 minutos, senão um WhatsApp quebrado martelaria o Supabase a cada
   contato.

A busca remota roda em thread no startup: o app abre na hora mesmo com a rede
ruim, porque o embutido já basta para operar.

**Mensagens ao usuário nunca são técnicas** (ele é leigo; nome de seletor vai só
para o `log.txt`):

> **Atualizando…** O WhatsApp mudou alguma coisa e o programa está buscando o
> ajuste automaticamente. Isso leva alguns segundos.

### `supabase_seletores.sql` (93 linhas) — a tabela

Criada e verificada em 06/09/2026. Colunas: `versao_schema`, `versao`, `ativo`,
`criado_em`, `seletores` (jsonb), com índice para a query exata do app.

**A parte central é a RLS: `anon` lê, `anon` nunca escreve.**

Isso não é arrumação. A chave anon vai **dentro do `.exe`** distribuído ao
cliente — ou seja, é pública. Se `anon` pudesse escrever, qualquer pessoa com o
executável poderia publicar seletores para **todos os clientes de uma vez**. O
`_validar_payload()` limita o estrago, mas é a segunda linha de defesa; a policy
é a primeira. Escrita só pela `service_role`.

**Verificado em campo:**

| Verificação | Resultado |
|---|---|
| App lê a tabela | ✅ 13 chaves, versão `2026-09-06.1` |
| Query do app (schema + ativo + ordem + limit) | ✅ funciona |
| Valores batem com os embutidos | ✅ todas as 13 idênticas |
| `anon` tentando escrever | ✅ bloqueado — `42501 new row violates row-level security policy` |

**Como consertar um seletor no futuro:** não editar a linha existente, inserir
uma nova. O payload pode conter só as chaves que mudaram (o resto cai no
embutido). Se der errado, `update ... set ativo = false` na linha ruim e todos
voltam para a anterior no próximo ciclo.

### `linha_conversa.py` (291 linhas) — o leitor

Lê uma linha do `#pane-side` sem abrir a conversa. Um `execute_script` extrai a
lista inteira para dicts simples (uma ida ao browser, não N `find_element`); a
interpretação é Python puro, testável sem browser — mesmo motivo do
`contact_logic.py`.

**O filtro obrigatório:** o ícone de status fica dentro de `last-msg-status` e
**fora** de `chat-msg-symbol`. Sem essa exclusão, uma figurinha que *ele* mandou
seria lida como tique nosso — o erro mais caro que esta leitura pode cometer,
porque transforma "respondeu" em "entregue".

**A decisão de estado é por ausência:**

| O que há no `cell-frame-secondary` | Estado | Inferência |
|---|---|---|
| nenhum ícone de status | `ULTIMA_DELES` | a última mensagem é dele → respondeu |
| `wds-ic-read` | `LIDO` | nossa, lida, sem resposta |
| `wds-ic-delivered` | `ENTREGUE` | nossa, entregue, sem resposta |
| `message-fail` | `FALHOU` | não saiu |
| **qualquer outro** ícone | `NAO_ENTREGUE` | nossa, ainda não entregue |

É isso que faz o ✓ solitário funcionar sem que se saiba o nome dele.

**Um comportamento que os testes forçaram a corrigir:** extração quebrada (dict
sem `icones_status`) devolve `INDETERMINADO`, **não** "respondeu". Confundir os
dois marcaria o contato como respondido sem nenhuma evidência, tirando-o da fila
de follow-up para sempre. Lista vazia continua sendo evidência de verdade.

`interpretar_horario()` converte o horário da linha quando dá: `14:32` vira hoje
naquela hora, "Ontem" é ancorado na meia-noite (o WhatsApp não mostra a hora — a
latência sai como "mais de X horas", não como um número inventado), data
explícita é parseada, e nome de dia da semana devolve `None`. **None é resposta
legítima, não erro.**

### Alarme de entrega — `whatsapp_sender.py` (+326 linhas)

Roda na **pausa entre rajadas**, que é ociosa por construção. Simulando o
`_generate_burst_plan` com o caso de referência (118 msgs / 240 min → orçamento
de pausas ≈ 6730s): 24 a 32 rajadas, pausas de 90 a 275s (mediana ~150-200s).
São ~25 janelas de 2 a 4 minutos com o navegador de pé sem fazer nada.

**O mecanismo é trivial ali:** mandar mensagem joga a conversa para o **topo** do
`#pane-side`, então os contatos da rajada que acabou de rodar são as primeiras
linhas, já renderizadas, ao lado da conversa aberta. Um `execute_script`,
sub-segundo, **zero interação** — nada de digitar na busca, o que
descaracterizaria a pausa justamente no que ela existe para simular.

**Métodos:**

- `_registrar_envio_para_entrega()` — anota um envio concluído
- `_verificar_entregas_na_pausa()` — lê durante a pausa
- `_absorver_leitura_de_entrega()` — casa as linhas com os envios desta execução
- `_avaliar_alarme_de_entrega()` — arma o alarme

**Regras de disparo:**

| Constante | Valor | Por quê |
|---|---|---|
| `_ENTREGA_AMOSTRA_MINIMA` | 8 | duas não entregues no começo não dizem nada |
| `_ENTREGA_TAXA_NAO_ENTREGUE` | 0.70 | é a taxa que importa, não a existência de um caso ruim |
| `_ENTREGA_IDADE_MINIMA_SEG` | 120 | **sem isso todo envio daria alarme falso** — logo depois de mandar, "ainda não entregue" é o estado normal |
| `_ENTREGA_REARME_A_CADA` | 5 | o popup informa, não atrapalha |
| `_VERIFICACAO_PAUSA_MINIMA_SEG` | 45 | a leitura é oportunista: com a janela apertada não há pausa folgada |
| `_VERIFICACAO_FRACAO_DA_PAUSA` | 0.25 | teto de tempo da leitura |

**Uma resposta prova a entrega** pelo caminho mais curto possível: ele não teria
como responder sem receber.

**Quatro travas que não podem regredir:**

1. **Não pode derrubar um envio.** Qualquer exceção é engolida. Um
   `StaleElementReference` cascateando para o laço marcaria contato como
   inválido ou mataria a rajada.
2. **Não pode estourar a pausa.** Estourar atrasa a próxima rajada e faz a
   execução passar do tempo prometido — o orçamento do plano é um total, não uma
   sugestão.
3. **Não pode segurar o botão Parar.** Checa `_should_stop()`.
4. **Não polui a métrica de lentidão.** O tempo gasto ali é nosso, não do
   WhatsApp; contá-lo faria o `alerta_lentidao` disparar por causa do próprio
   código.

### `varredura.py` (315 linhas) — a verificação sob demanda

**Duas passadas, e a primeira é de graça:**

1. **Livre:** um `execute_script` lê tudo que já está renderizado (~71 linhas).
   Sub-segundo, e resolve a maioria quando a campanha foi a última coisa que
   aconteceu na conta.
2. **Busca:** só para quem sobrou. Digita o número, lê a linha, limpa. ~2-3s
   cada.

**Filtrar pela busca não abre a conversa nem marca como lida** — o cliente não
perde o badge de não-lidas, e o destinatário não vê tique azul de uma leitura
que não houve.

**Colunas gravadas** (fatos, não rótulos): `Respondeu`, `DataResposta`,
`Entrega`, `UltimaVerificacao`. Valores de `Entrega` em português legível,
porque o cliente abre a planilha no Excel.

**Silêncio é melhor que invenção**, em três pontos:

- conversa não encontrada **não** vira "não respondeu" (pode ser contato salvo
  na agenda, cuja linha aparece pelo nome, ou conversa apagada)
- horário desconhecido deixa `DataResposta` em branco
- `INDETERMINADO` não sobrescreve leitura boa anterior

**Não reconsulta quem já respondeu** — ninguém des-responde, e a varredura custa
~5 min para 118 contatos.

A planilha é salva **uma vez, no fim**: reescrevê-la a cada contato
multiplicaria por N o risco de deixá-la corrompida se algo morresse no meio.

`WhatsAppSender.verificar_respostas()` cuida do ciclo de vida do Chrome (reusa
`_init_driver`, detecção de QR, `_aguardar_sincronizacao`) e **nunca levanta** —
devolve o resumo com `erro` preenchido.

### Backend — `app.py` (+102 linhas)

- `POST /verificar-respostas` — dispara a varredura em thread
- `GET /contacts` devolve `entrega`, `respondeu`, `data_resposta`,
  `verificado_em` e `latencia_seg` (este último **derivado na hora**)
- `GET /status` ganhou `alerta_entrega` e `varredura` (progresso)
- `POST /stop` agora para também a varredura

**Trava de concorrência nos dois sentidos.** Varredura e envio disputam o mesmo
`chrome_profile/` e escrevem a mesma planilha:

- `/start` recusa se a varredura estiver rodando
- `_recusar_se_enviando()` recusa edições durante a varredura

O estado é **próprio** (`is_varrendo()`), não reaproveitado de `is_running()` —
que significa "está enviando" e é o que congela config e mensagem global.

### Frontend — `static/index.html` (+302 linhas)

**Botão "Verificar respostas"** com progresso (*"Verificando 34 de 118..."*).
Progresso e término vêm pelo heartbeat de status de 5s, o mesmo caminho de tudo
o mais — um canal a menos para manter em sincronia, e sobrevive a F5.

**Abas com contadores:** `Todos 118` · `Respondeu 12` · `Sem resposta 94` ·
`Não entregou 12`. Só aparecem depois da primeira varredura. O contador já
responde "quantos responderam?" sem clicar em nada, que é a pergunta real do
cliente.

**Coluna "Resposta" ordenável**, mostrando a latência (*"Respondeu · 12 min"*).
Vermelha para não entregue, neutra para entregue-sem-resposta. Quem não tem
latência conhecida vai para o fim nas duas direções: "não sei" não é nem mais
rápido nem mais lento.

**Popup do alarme de entrega — vermelho, com "Parar o envio" como ação
primária.** O tom é deliberadamente **oposto** ao do aviso de lentidão, e isso
está travado por teste:

| Aviso | Diz |
|---|---|
| lentidão | "o envio continua normalmente — não precisa parar" |
| entrega | "pare agora; continuar pode bloquear a conta" |

Uma refatoração que unifique os dois é exatamente a falha que a feature existe
para evitar.

---

## 🧪 Testes

**106 testes novos**, todos passando.

| Arquivo | Testes | Cobre |
|---|---|---|
| `tests/test_seletores.py` | 29 | filtro do payload, cadeia de fallback, trava do refetch |
| `tests/test_linha_conversa.py` | 31 | exclusão do símbolo de mídia, estados, casamento por número, bidi |
| `tests/test_alerta_entrega.py` | 24 | alarme falso, resposta prova entrega, popup uma vez, as 4 travas |
| `tests/test_varredura.py` | 23 | escopo, gravação, latência, execução |
| `tests/test_alerta_entrega_ui.js` | 13 | popup, `seq`, botão de parar, **o tom do texto** |
| `tests/test_varredura_ui.js` | 28 | agrupamento, abas, filtro, ordenação, badges |

**Suite completo em verde:** 201 no `tests/`, 35 no dedup, 6 no nav_retry, 7
suites JS, backend de contact_update.

### Três correções que os testes forçaram

1. **`test_leitura_lenta_nao_estoura_a_pausa` passava pelo motivo errado.** A
   pausa de 1s era barrada pelo piso de 45s antes de chegar ao orçamento — o
   teste nunca exercitava o que se propunha. Corrigido baixando o piso no
   próprio teste, com a contraparte "dentro do prazo, aproveita".
2. **A ordenação abria invertida.** `ordenarPorResposta()` alterna antes de
   ordenar, então o primeiro clique dava o mais lento no topo — o oposto de "em
   quem eu ligo agora?".
3. **`INDETERMINADO` era tratado como "respondeu".** Ver acima.

### Falhas pré-existentes (não são regressão)

`test_app_estado.py` tem 4 falhas que **já existiam antes** deste trabalho —
confirmado com `git stash` da alteração. São testes desatualizados: esperam
chaves de config `msgs_por_rodada` / `total_rodadas` e um default de
`human_behavior` que o schema atual não usa mais.

---

## 📁 Arquivos

**Novos:**

```
seletores.py                     394   seletores remotos (embutido -> cache -> Supabase)
linha_conversa.py                291   leitor de uma linha do #pane-side
varredura.py                     315   verificação de respostas sob demanda
supabase_seletores.sql            93   DDL + RLS da tabela
sonda_pane_side.js               123   sonda de DevTools (levantamento)
sonda_tiques.js                  193   sonda v2, com modo vigia
tests/test_seletores.py          290
tests/test_linha_conversa.py     259
tests/test_alerta_entrega.py     322
tests/test_varredura.py          299
tests/test_alerta_entrega_ui.js  150
tests/test_varredura_ui.js       183
```

**Alterados:**

```
whatsapp_sender.py               +326   alarme de entrega, verificar_respostas(), colunas novas
static/index.html                +302   botão, abas, coluna, popup
app.py                           +102   endpoint, status, trava de concorrência
tests/test_trava_durante_envio.py +31   fake ganhou is_varrendo() + teste do caso novo
CLAUDE.md                               documentação das invariantes novas
BRAINSTORM_IA.md                        seções #7, #7b, #7c e o levantamento das sondas
```

---

## ⏭️ O que ficou pendente

**Teste de ponta a ponta contra o WhatsApp real.** Nada disso passou por um
Selenium de verdade — os testes usam driver falso. É o próximo passo natural:
rodar com a planilha de teste e ler o log.

**O ✓ solitário.** O nome do ícone de "enviado, não entregue" nunca foi
capturado. Não bloqueia nada (a regra por ausência cobre), mas permitiria um
`Motivo` mais preciso. Para capturá-lo, mandar para um número **sem nenhum
dispositivo companheiro online** — celular desligado de verdade, não só em modo
avião.

**Migração dos demais seletores.** Só os da leitura de linha e o `#pane-side`
foram para o `seletores.json`. Anexo, QR e detecção de popup continuam
hardcoded. Migrar incrementalmente: fazer tudo de uma vez é refatoração grande
em cima do caminho de envio.

**A feature #5 (triagem por teor).** É o que acrescenta o "morno": uma chamada
de LLM sobre o texto da última mensagem, só para quem respondeu — que são
poucos, em vez das 118. O dado já está capturado: o leitor guarda o texto
**completo** (o `title` do `last-msg-status`), não a prévia truncada. Quando ela
entrar, a aba "Respondeu" se divide em quente/morno; o conceito não muda de
lugar, ganha subdivisão.

**Varredura agendada (#7c estendida).** A varredura rodando sozinha a cada X
horas enquanto o app está aberto. É só um timer em cima do que existe.
