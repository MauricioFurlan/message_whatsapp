# Sessão de 08/09/2026 — Verificação de respostas

Registro do que foi feito, por quê, e o que ficou em aberto.

Ponto de partida: a feature de varredura (`varredura.py`, `linha_conversa.py`,
`seletores.py`) já existia na working tree, **sem commit e sem nunca ter rodado
contra o WhatsApp real**. Esta sessão foi o primeiro teste de campo. Sete bugs
apareceram, e três deles só foram identificáveis porque o cliente capturou o DOM
real com sondas no navegador.

---

## 1. Bugs encontrados e corrigidos

### 1.1 O histórico de respostas era apagado a cada envio

**Sintoma:** "quando eu dou F5 ou reinicio o servidor o histórico da resposta é
apagado".

**Causa:** `POST /contacts` reconstruía a planilha inteira do zero com uma lista
de colunas escrita à mão, que não incluía `Respondeu`, `DataResposta`, `Entrega`
nem `UltimaVerificacao`.

O gatilho não era o F5: **`startSending()` salva os contatos antes de chamar
`/start`**. Todo novo envio apagava a varredura anterior.

**Correção:** as quatro colunas passaram a fazer a mesma ida e volta que
`Enviado`/`DataEnvio` já faziam — `collectContacts()` → `ContactModel` →
`to_excel`. O botão ↺ (reenviar) limpa esses campos, porque a leitura antiga
descrevia a mensagem anterior.

> **Invariante:** o editor reescreve a planilha INTEIRA a partir da tela. Toda
> coluna que não subir no payload é apagada. Qualquer coluna nova precisa dos
> três lados: dataset na linha, `collectContacts`, e a lista de colunas do
> `to_excel`.

### 1.2 Contato que respondeu aparecia como "Lido"

**Causa (a mais séria da sessão):** com mensagem não lida, o WhatsApp Web injeta
o anúncio de acessibilidade **dentro do mesmo elemento do título**:

```
"1 mensagem não lida+55 19 99422-9146"
```

`numero_do_titulo()` pegava *todos os dígitos* → `15519994229146` (14 dígitos).
Não começa com `55`, então nem o corte de DDI corrigia. A linha **não casava com
a planilha**, e quem não casa **não grava nada** — o contato ficava com a leitura
anterior ("Lido").

O estrago era dirigido ao pior alvo possível: **só quem tem não-lida tem o
prefixo, e só quem respondeu tem não-lida**. O bug acertava exatamente, e apenas,
os leads quentes. Era isso que o log reportava como "1 não localizados na lista".

**Correção:** a extração procura o **trecho com forma de telefone**
(`_RE_TELEFONE`), não dígitos soltos. Independente de idioma — o texto do anúncio
muda com a língua, mas nunca tem forma de telefone.

### 1.3 Os nomes dos ícones do WhatsApp estão deslocados

**Descoberto pela sonda, confirmado pelo cliente.** Medição ao vivo no mesmo
contato:

| t | ícone | cor | significado real |
|---|---|---|---|
| 0.5s | `wds-ic-read` | `rgba(0, 0, 0, 0.6)` | ✓✓ chegou, **não** lido |
| 11.6s | `wds-ic-read` | `rgb(0, 123, 252)` | ✓✓ **lido** (abriu a conversa) |
| 23.2s | *(nenhum)*, 1 não-lida | — | ele respondeu |
| 34.9s | *(nenhum)*, 0 não-lidas | — | resposta dele ainda é a última |
| 72.3s | `wds-ic-delivered` | `rgba(0, 0, 0, 0.6)` | **✓ solitário: saiu, NÃO chegou** |

Ou seja:

- **`wds-ic-delivered` é o ✓ solitário** — o estado de NÃO-entrega, apesar do
  nome. É o "✓ solitário nunca capturado em campo" que o `CLAUDE.md` mencionava.
  Estava ali o tempo todo, com um nome que prometia o contrário.
- **`wds-ic-read` é o ✓✓ duplo**, e cobre entregue **e** lido. O que separa os
  dois é a **cor**, não o nome.

**Por que isso era grave:** tratar `wds-ic-delivered` como entrega **calava o
alarme de entrega**. Esse alarme existe para detectar mensagens que saem e não
chegam — a assinatura do número sendo limitado pelo WhatsApp — e o popup dele
manda **parar**, porque continuar arrisca a conta do cliente. Uma campanha
inteira travada no ✓ seria lida como "tudo entregue" e o alarme nunca dispararia.

**Correção estrutural:** as chaves de seletor passaram a ser nomeadas pelo
**desenho**, não pelo estado:

```python
ICONES_PADRAO = {
    "icone_tique_duplo": "wds-ic-read",
    "icone_falha": "message-fail",
}
```

`icone_entregue` foi removida. O ✓ solitário não precisa de chave: cai na regra
por ausência ("qualquer outro ícone = não entregue"), que é o lado seguro — um
ícone novo **arma** o alarme em vez de silenciá-lo.

> Nomear pelo estado foi a causa raiz de dois bugs desta sessão. Nomear pelo
> desenho impede a repetição.

### 1.4 "Leu" era afirmado sem prova

Consequência de 1.3: o app dizia "Leu" para tique cinza. A regra agora é
**assimétrica de propósito**:

- **azul prova leitura** → `LIDO`
- **qualquer outra cor, ou cor ilegível** → `ENTREGUE` (verdade nos dois casos)

Quem desliga a confirmação de leitura nunca fica azul mesmo tendo lido. Por isso
o tooltip de "Entregue" **não** afirma "não leu" — diz *"sem confirmação de
leitura: ele pode ter lido sem o WhatsApp avisar"*.

O limiar (`b >= 150 && b - r >= 60`) é "o canal azul domina", e não "azul alto":
no tema escuro o cinza vira **branco translúcido**, com canal azul em 255. Um
teste ingênuo diria "Leu" em toda mensagem entregue de quem usa tema escuro.

### 1.5 Sinal independente: o badge de não-lidas

Adicionado antes de 1.3 ser diagnosticado, mantido como segunda evidência:
`nao_lidas > 0` decide "respondeu", vencendo qualquer ícone.

Não-lida só existe para mensagem **recebida**, e o envio abre a conversa (o que
zera o contador). Então, num contato com `Enviado=X`, qualquer não-lida é
mensagem nova dele.

### 1.6 `nan` na coluna Resposta

`GET /contacts` fazia `fillna("")` só nas colunas antigas. As quatro da varredura
ficavam de fora, e célula vazia virava a string `"nan"` do pandas — que é
*truthy*, então passava no teste de "tem entrega?".

### 1.7 CSS do Tailwind defasado

Duas queixas visuais tiveram a mesma causa: **`static/tailwind.css` estava
desatualizado em relação ao `index.html`**.

- `text-blue-500` não existia no CSS → tique de "lido" saía **preto**.
- `gap-x-*` / `gap-y-*` não existiam → o espaçamento do painel novo **nunca foi
  aplicado**.

Auditei as 218 classes do markup contra o CSS (com o escape que o Tailwind aplica
em `:`, `.`, `[`): três estavam realmente ausentes — `flex-wrap`,
`border-red-200`, `text-red-800`. `npm run build:css` resolveu.

**Não afetava o `.exe`** (o `build.bat` roda o build antes de empacotar) — só o
ambiente de desenvolvimento. As cores dos tiques foram para `style` inline, que
não depende de build nenhum.

---

## 2. Mudanças de UX

| Mudança | Motivo |
|---|---|
| Botão "Verificar respostas" movido para **Controles**, sem a lupa | É irmã de Iniciar Envio: abre o mesmo Chrome, disputa o mesmo `chrome_profile/`, reescreve a mesma planilha. Junto da tabela parecia um filtro de tela. |
| Durante a varredura, **tudo trava menos Parar** | Ela reescreve a planilha e segura o Chrome. Sem o Parar ativo, o usuário fica preso numa operação de minutos. |
| Backend reserva a varredura **antes** de subir a thread + push do `/status` | Sem isso a tela ficava editável até o heartbeat seguinte (5s). |
| Botões de ordenar do `<thead>` agora travam junto | Viviam fora do `#contacts-tbody` que o CSS neutraliza — e ordenar **salva** a nova ordem na planilha. Era furo também no envio. |
| Tooltips em Iniciar / Parar / Verificar | Linguagem de leigo, sem citar navegador, planilha ou mecanismo. |
| Coluna Resposta usa **os tiques do WhatsApp** | Vocabulário que o cliente já lê todo dia; ele pode conferir contra a conversa real. |
| Resposta continua em **texto** (`10 min`) | Não existe tique para "ele respondeu" — os tiques falam da NOSSA mensagem. E o tempo é a chave de ordenação. |
| Data encurtada para `08/09/26 22:27`; colunas com largura fixa e `whitespace-nowrap` | 18 caracteres não cabem em nenhuma largura razoável. |
| Resumo com símbolos no painel Status | `1 ↩  2 ✓✓(azul)  3 ✓✓(cinza)  2 ✓`. Lê a **tabela**, não um contador próprio: dois contadores independentes divergem e o usuário não sabe em qual acreditar. |
| Linha inválida mostra `—`, não o estado de entrega | Um inválido nunca teve entrega; qualquer `Entrega` remanescente descreve outra mensagem. |
| Contador do log distingue conversas de linhas | Dizia "1 contato" e depois "25 responderam" (planilha de teste com o mesmo número repetido). |

### Estado final da coluna Resposta

| Estado | Símbolo | Cor |
|---|---|---|
| Respondeu | `10 min` (texto) | verde |
| Lido | ✓✓ | azul `rgb(0,123,252)` |
| Entregue | ✓✓ | cinza |
| Não entregue | ✓ | cinza |
| Falhou | ⓘ | vermelho |
| Inválido / pendente / não verificado | — | cinza claro |

---

## 3. Diagnóstico permanente

Cada linha lida grava no `log.txt`:

```
[varredura] linha=0 numero=19994229146 estado=entregue icones=['wds-ic-read']
            cor_status='rgba(0, 0, 0, 0.45)' horario='22:31' titulo_tem_numero=True
```

Os ícones crus **e a cor** são literalmente a evidência da decisão. Sem isso, um
"Lido" errado e uma extração quebrada são indistinguíveis depois do fato — foi o
que travou o diagnóstico no começo da sessão.

### Sondas criadas

| Arquivo | Para quê |
|---|---|
| `sonda_resposta.js` | Por que uma linha foi classificada como foi. Mostra ícones, badge e o veredito do app lado a lado com o DOM. |
| `sonda_cor_tique.js` | A cor do tique. `__cores()` para foto; `__vigiar("99422")` grava as transições ao vivo por 120s. |

Ambas mascaram dígitos e trocam texto por `<len:N>` — a saída pode ser colada em
qualquer lugar.

---

## 4. Testes

**191 Python + 10 arquivos JS** (83 asserções só em `test_varredura_ui.js`).

Regressões novas que vale conhecer:

- o título com prefixo de não-lidas casa com a planilha
- `wds-ic-delivered` **não** conta como entrega, e não entra em `ESTADOS_ENTREGUES`
- ✓✓ cinza é `ENTREGUE`, ✓✓ azul é `LIDO`, sem cor cai para `ENTREGUE`
- branco translúcido (tema escuro) não é confundido com azul
- rebaixar `LIDO`→`ENTREGUE` não mexe no alarme de entrega
- durante a varredura só o Parar fica ativo
- nenhum rótulo da coluna passa de 13 caracteres (senão quebra a linha)
- cor de tique nunca vem de classe do Tailwind (a regressão do preto)
- tooltips existem, são acentuados e não têm jargão técnico

---

## 5. Pontos para discutir

### 5.1 Nada disso está commitado

Vinte e seis arquivos entre modificados e novos, incluindo a feature inteira.
**É o item mais urgente.** Sugestão: dois ou três commits — a feature de
varredura, as correções de campo, e os ajustes de UI.

Há um arquivo vazio chamado `s` (de 06/09) que parece um `>s` que escapou; e o
`log.txt` e o `uploads/contatos.xlsx` estão modificados — o xlsx tem dados de
teste, vale conferir antes de commitar.

### 5.2 A regra da cor está hardcoded

`cor_de_leitura()` em `linha_conversa.py` é a única coisa **load-bearing** fora
do `seletores.py`. Se o WhatsApp mudar o tom do azul, a distinção Leu/Entregue
quebra e **não dá para consertar publicando uma linha no Supabase** — exige
rebuild e novo `.exe` para todo cliente.

Quebra de forma segura (tudo vira "Entregue", nunca mente), mas perde informação.

Dá para publicar o azul esperado como string e comparar por distância, respeitando
a invariante de que o payload só carrega strings. **É uma mudança no contrato
publicado — decisão em aberto.**

### 5.3 O alarme de entrega nunca foi validado em campo

Ele estava **efetivamente desligado** por causa de 1.3. Agora funciona pela
primeira vez. Como o popup dele manda **parar o envio**, um falso positivo é
caro. Vale um teste dirigido: mandar para um número com o celular desligado e ver
se ele arma quando deve — e, mais importante, se **não** arma numa campanha
saudável.

### 5.4 Contato salvo na agenda não é encontrado

A varredura casa **por número**, e contato salvo aparece pelo **nome** na lista.
Esses viram "não localizados" e não recebem leitura nenhuma.

O silêncio é intencional (melhor que um "não respondeu" que não foi lido), mas é
um buraco real de cobertura. Casar por nome é possível — a planilha tem a coluna
`Nome` — mas é matching frouxo, com risco de atribuir a resposta de um contato a
outro. **Vale a pena? Qual a fração da base do cliente que está salva na agenda?**

### 5.5 A varredura é manual

Hoje é um botão. Poderia rodar sozinha depois do envio, ou uma vez por dia. Mas
ela abre o Chrome e segura o `chrome_profile/` — automatizar significa decidir o
que acontece se o usuário quiser enviar naquele momento.

### 5.6 Ícone desconhecido é desenhado como ✓

Discutido e **decidido não mexer**: o ✓ solitário e um ícone desconhecido caem no
mesmo balde, então a coluna desenha um tique único para ambos. Para o alarme está
certo (o conservador é tratar desconhecido como "não chegou"), mas a tela afirma
um pouco além da evidência.

O cenário exige o WhatsApp inventar um quinto estado de entrega, que não existe.
O log já grava os nomes crus — se aparecer um desconhecido, a gente saberá.
**Revisitar só com um caso real.**

### 5.7 Detalhes de UI ainda não comentados

- Para quem respondeu, o valor visível é a **latência** (`10 min`), não a palavra
  "Respondeu". Foi escolha minha para caber em uma linha; funciona sob o
  cabeçalho "Resposta", mas você não comentou.
- "Falhou" é o único símbolo vermelho, agora que os tiques voltaram ao cinza.
  Fica coerente ou destoa?

### 5.8 A feature #5 (morno, por teor)

Não existe "morno" hoje, deliberadamente: separar morno de quente exige ler o
**teor** da resposta. *"Sim"* é a resposta mais quente possível e tem uma palavra;
*"não tenho interesse"* tem quatro. Nenhuma regra sobre metadado acerta isso.

O texto completo da última mensagem **já é capturado** (`ultima_mensagem` em
`linha_conversa.py`) justamente para alimentar isso quando chegar a hora. É o que
transforma a aba "Respondeu" em quente/morno e captura opt-out.

### 5.9 A planilha de teste perdeu o histórico

`uploads/contatos.xlsx` foi zerado pelo bug 1.1 antes da correção. O histórico
volta na próxima varredura, mas os horários de resposta das mensagens antigas se
perderam.

---

## 6. Arquivos tocados

**Modificados:** `app.py`, `whatsapp_sender.py`, `static/index.html`,
`static/tailwind.css`, `seletores.py`, `linha_conversa.py`, `varredura.py`,
`supabase_seletores.sql`, `../CLAUDE.md`, `tests/test_linha_conversa.py`,
`tests/test_varredura_ui.js`

**Novos:** `sonda_resposta.js`, `sonda_cor_tique.js`, este arquivo

> A linha do Supabase, se já publicada, tem as chaves antigas
> (`icone_entregue`/`icone_lido`). Elas serão ignoradas com aviso no log e os
> embutidos (corretos) valem — não quebra nada, mas vale atualizar.

---

## 7. Antes de testar amanhã

1. **Reiniciar o servidor** (mudanças em `app.py`, `whatsapp_sender.py`,
   `linha_conversa.py`, `varredura.py`, `seletores.py`).
2. **Ctrl+F5** no navegador — o CSS foi regenerado e o antigo pode estar em cache.
