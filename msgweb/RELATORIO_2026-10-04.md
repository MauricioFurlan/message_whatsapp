# Relatório técnico — ritmo das rajadas e modo "envio direto"

Sessões de 03/10/2026 e 04/10/2026. Este documento cobre:

1. [Correção do tempo das rajadas](#1-correção-do-tempo-das-rajadas) — **no commit `dfe96f1`**
2. [Piso da pausa reajustada (decisão de 04/10)](#2-piso-da-pausa-reajustada) — **no commit `dfe96f1`**
3. [Modo "envio direto"](#3-modo-envio-direto) — **ainda sem commit**
4. [Textos para o cliente leigo](#4-textos-para-o-cliente-leigo) — **ainda sem commit**
5. [Testes](#5-testes)
6. [Decisões de regra (do usuário)](#6-decisões-de-regra-do-usuário)
7. [Pendências e riscos](#7-pendências-e-riscos)
8. [Os testes somavam no histórico de envios](#8-os-testes-somavam-no-histórico-de-envios)

---

## 1. Correção do tempo das rajadas

### Sintoma

O cliente relatou que o envio "não está fiel ao tempo estipulado". No teste
com o WhatsApp simulado, uma janela de **60min** terminava em **74min**, quando
a conversa demorava a abrir, ou em **45min**, quando abria rápido.

### Causa

`_generate_burst_plan` sorteava o plano (tamanho de cada rajada e a pausa
depois dela) **uma vez, no início**, em cima de uma **estimativa fixa** do custo
de cada envio:

- 40s para abrir a conversa (`TEMPO_ESTIMADO_ABERTURA_CHAT`);
- 18s por anexo (`TEMPO_ESTIMADO_POR_ANEXO`);
- o orçamento de digitação (`_type_budget`).

Depois as pausas eram executadas **do tamanho planejado, sem olhar o relógio**.
Todo erro da estimativa caía inteiro no total. Nos logs reais, abrir a conversa
variou de 31s a 58s. Cada falha de abertura custa ~3,7min e não gasta vaga da
rajada (invariante antiga), então o atraso se acumulava.

### Correção: o plano dá a forma, o prazo dá a escala

O plano continua sendo sorteado no início, mas passa a definir só a **forma**:
o tamanho das rajadas e a **proporção** entre as pausas. Antes de cada pausa,
`WhatsAppSender._replanejar_pausa` recalcula o tamanho real dela:

```
orçamento = segundos até o prazo
          - msgs que faltam × custo médio REAL por mensagem
          - delays curtos (intra-rajada) que ainda vão acontecer

pausa     = orçamento × (pausa_planejada / soma das pausas planejadas restantes)
```

- **Prazo:** `prazo_mono = inicio_mono + tempo_minutos * 60`, com
  `time.monotonic()`.
- **Custo médio real:** `(tempo decorrido - tempo ocioso) / mensagens enviadas`.
  O `ocioso` soma o tempo em que o app esperou de propósito (delays curtos,
  pausas, espera de horário comercial). O resto é o custo de enviar, **com as
  falhas incluídas**. Sem envio ainda, usa a estimativa.
- **Proporção:** cada pausa leva a mesma fração do orçamento que tinha no
  plano, então o desenho irregular é preservado. Se atrasou, as pausas
  encolhem; se adiantou, crescem.

### Ajustes que vieram junto

| Ajuste | Onde | Por quê |
|---|---|---|
| Espera de horário comercial **empurra o prazo** | `_aguardar_horario_comercial_medindo()` devolve quanto esperou; o laço soma em `prazo_mono` e em `ocioso` | Não é tempo de envio. Sem isso, uma noite de espera faria as pausas seguintes desabarem para o piso. |
| Leitura de entregas **conta dentro da pausa** | `t_pausa` é marcado antes de `_verificar_entregas_na_pausa`, e o laço de espera parte do que já passou | Antes a pausa recomeçava do zero depois da leitura, somando esse tempo por fora. |
| Aviso **único** de atraso irrecuperável | flag `avisou_atraso` no laço | Projeta `falta × custo_médio + delays curtos + pausas no piso`. Passando de 60s além do prazo, avisa uma vez no log da tela e no `log.txt`. Antes acontecia em silêncio. |
| Log final com o configurado | fim de `start()` | `"em 1h 0min (tempo configurado: 60min)"` |
| Rastro de cada reajuste | `file_logger.info` | `[ritmo] leva N: pausa planejada Xs -> reajustada Ys (até o prazo ..., faltam ..., custo médio real ..., delays curtos restantes ...)` |

### Resultado

As mesmas campanhas de teste fecham em **60min ±5%**, com a conversa custando
90s ou 5s para abrir.

---

## 2. Piso da pausa reajustada

**Decisão do usuário em 04/10:** quando o envio atrasa, a pausa entre rajadas
não pode encolher abaixo de **metade da planejada**. Antes o piso era só
`DELAY_INTRA_MIN` (15s), e um envio muito atrasado virava rajadas quase
coladas, justamente o padrão que as pausas existem para evitar. Passar do tempo
configurado é o preço aceito.

### Código (`whatsapp_sender.py`)

```python
PAUSA_PISO_FRACAO = 0.5

@classmethod
def _piso_da_pausa(cls, pausa_planejada: float) -> float:
    """Menor pausa entre rajadas que o reajuste ao prazo pode impor."""
    return max(float(cls.DELAY_INTRA_MIN), pausa_planejada * cls.PAUSA_PISO_FRACAO)
```

`_replanejar_pausa` passou a devolver `max(piso, pausa)` com esse piso.

A **projeção de atraso** do aviso único também mudou. Ela assumia que toda
pausa restante cairia para 15s:

```python
# antes
pausas_no_piso = self.DELAY_INTRA_MIN * (total_bursts - 1 - burst_idx)
# depois
pausas_no_piso = sum(
    self._piso_da_pausa(b["pause_after"])
    for b in burst_plan[burst_idx:total_bursts - 1]
)
```

O intervalo vai até `total_bursts - 1` porque a última rajada tem
`pause_after = 0`, e `_piso_da_pausa(0)` daria 15s de pausa inexistente.

### Decisões que mantiveram o comportamento

- **Aquecimento do WhatsApp Web** (`_aquecer_navegacao`) continua **fora** da
  janela. Ele roda antes de `_envio_iniciado_em`. Quem mede do clique em
  "Iniciar" vê alguns minutos a mais.
- **Intervalo dentro da rajada** continua como estava: `_gaussian_delay` com
  `intra_delay × 0,7` a `× 1,3`, que pode chegar a ~8s.

---

## 3. Modo "envio direto"

Alternativa simples às rajadas. Uma opção na Configuração, **"Envio direto"**,
envia para **todos os contatos com status Pendente**, um depois do outro, com
intervalo sorteado entre **15 e 30s** a cada mensagem.

"Pendente" é exatamente o que `get_pending_contacts` devolve: `Enviado` vazio
**e** `Invalido` vazio. É a mesma palavra da coluna de status da tabela
(`static/index.html`, função que renderiza o status).

### 3.1 Configuração (`app.py`)

```python
class ConfigModel(BaseModel):
    ...
    modo_envio: Literal["rajadas", "direto"] = "rajadas"
```

- **Padrão `"rajadas"`** em `ConfigModel` e em `AppState.config`. Quem nunca
  mexeu continua igual.
- **Valor desconhecido** (ex.: `"turbo"`) é recusado pelo Pydantic com **422**.
- **Persistência:** entra em `uploads/config.json` por `_salvar_config_em_disco`.
  `_restaurar_config_do_disco` só aceita chaves que já existem em
  `state.config`, então um `config.json` antigo, sem a chave, continua no padrão.
- **Trava durante o envio:** já coberta. `POST /config` passa por
  `_recusar_se_enviando`, como o resto da configuração.
- **Logs:** `POST /config` e a restauração escrevem uma linha própria para o
  modo direto (texto na seção 4).

### 3.2 Estimativa (`GET /estimate`)

Novo parâmetro `modo_envio` (query string, padrão `"rajadas"`). No modo direto,
`total_msgs` e `tempo_minutos` não são exigidos e a resposta é:

```json
{
  "status": "ok",
  "modo_envio": "direto",
  "session_target": 100,
  "pendentes": 100,
  "inviavel": false,
  "tempo_total_estimado_seg": 6300,
  "tempo_total_estimado_fmt": "1h 45min"
}
```

O cálculo é o novo `WhatsAppSender._estimar_tempo_modo_direto(pending)`:

```python
intervalo_medio = (DIRETO_INTERVALO_MIN + DIRETO_INTERVALO_MAX) / 2   # 22,5s
estimado = _estimar_tempo_envio_total(pending, n) + (n - 1) * intervalo_medio
```

`_estimar_tempo_envio_total` é a mesma conta das rajadas: abrir a conversa,
digitar e anexar, já com o pacote global resolvido. Não há prazo a cumprir, então
não existe "inviável".

### 3.3 Motor de envio (`whatsapp_sender.py`)

**Constantes e seletor de modo:**

```python
DIRETO_INTERVALO_MIN = 15
DIRETO_INTERVALO_MAX = 30
_VERIFICACAO_DIRETO_A_CADA = 10

def _modo_direto(self) -> bool:
    return self.config.get("modo_envio") == "direto"
```

`_modo_direto()` só é verdadeiro para a string exata `"direto"`, então qualquer
lixo no config cai no modo rajadas.

**Não existe um laço novo.** O modo direto reaproveita o laço de `start()`
com uma "rajada" única:

```python
direto = self._modo_direto()
if direto:
    session_target = len(pending)          # ignora total_msgs
...
if direto:
    burst_plan = [{"burst_size": session_target, "intra_delay": 0.0, "pause_after": 0.0}]
    total_bursts = 1
    # logs de início e de risco
else:
    # orçamento, aviso de inviável, _generate_burst_plan... (bloco antigo, reindentado)
```

Por isso tudo que já funcionava continua igual, sem caminho próprio:
deduplicação (`apply_deduplication`), validação (`_validate_contact`), botão
Parar, retomada, tratamento de falha, mensagem e anexo globais, alarme de
lentidão e registro de queda de conexão.

**Diferenças dentro do laço, todas condicionadas a `direto`:**

| Ponto | Rajadas | Direto |
|---|---|---|
| Quantidade | `min(total_msgs, pendentes)` | todos os pendentes |
| Intervalo após envio | `_gaussian_delay(intra×0,7, intra×1,3)` ou `uniform(intra×0,8, intra×1,2)` | `random.uniform(15, 30)` |
| Pausa longa | sim, reajustada ao prazo | não existe (`pause_after = 0`) |
| Log "▶️ Executando leva N de M" | sim | não |
| Log "📊 Rajada N finalizada" | sim | não |
| Leitura de entregas | na pausa entre rajadas | dentro do intervalo, a cada 10 envios |
| Log final | `(tempo configurado: Nmin)` | `(modo direto)` |
| Horário comercial | antes de cada rajada e de cada mensagem | igual: antes de cada mensagem |

**Falhas:** como nas rajadas, só espera o intervalo quem **enviou de fato**
(`enviados_burst > enviados_antes_da_tentativa`). Contato inválido não espera e
não gasta vaga.

### 3.4 Alarme de entrega no modo direto

O alarme de entrega (`_avaliar_alarme_de_entrega`) detecta mensagens que saem
e não chegam, a assinatura de número limitado pelo WhatsApp. A leitura que o
alimenta rodava **só na pausa entre rajadas** (`_verificar_entregas_na_pausa`,
com mínimo de 45s de pausa). Sem pausas, o alarme ficaria **mudo justamente no
modo mais arriscado**.

Refatoração:

```python
def _verificar_entregas_na_pausa(self, pause_after):
    if pause_after < self._VERIFICACAO_PAUSA_MINIMA_SEG:
        return
    self._ler_entregas(pause_after * self._VERIFICACAO_FRACAO_DA_PAUSA)

def _ler_entregas(self, orcamento_seg):
    # o miolo antigo: nunca levanta exceção, desiste ao passar de
    # orcamento_seg, sai na hora se _should_stop()
```

No laço, dentro do intervalo do modo direto:

```python
t0 = time.monotonic()
if direto and enviados_burst % self._VERIFICACAO_DIRETO_A_CADA == 0:
    self._ler_entregas(delay * self._VERIFICACAO_FRACAO_DA_PAUSA)   # ≤ 25% do intervalo
restante = delay - (time.monotonic() - t0)
if restante > 0:
    self._interruptible_sleep(restante)
ocioso += time.monotonic() - t0
```

- Roda depois do 10º, 20º, 30º... envio.
- O orçamento é no máximo 25% do intervalo (3,75s a 7,5s). A leitura é um
  `execute_script` de menos de 1s.
- O intervalo **absorve** o tempo da leitura, então não fica mais longo.
- Continuam valendo as regras do alarme: só contatos com envio concluído entram
  na amostra, e `_ENTREGA_IDADE_MINIMA_SEG` (120s) evita alarme falso com
  mensagem recém-enviada. Com ~1min por envio, as mensagens de 2 envios atrás
  já contam.

### 3.5 Correção que vale para os dois modos: espera depois do último contato

Achado ao escrever o teste. Com uma falha no meio da lista, o laço esperava
15-30s **depois do último contato**, antes de descobrir que a planilha acabou.

Causa: a condição era `enviados_burst < burst_size`. Com uma falha, os envios
nunca chegam ao tamanho da rajada, então a condição continuava verdadeira
depois do último contato.

Correção: um contador `contatos_tentados`, incrementado a cada `next(pending_iter)`,
e uma condição a mais para esperar:

```python
and contatos_tentados < len(pending)
```

Nas rajadas, o caso aparecia quando a planilha acabava no meio de uma rajada.

### 3.6 Tela (`static/index.html`)

**Elementos novos** (no topo do bloco "Configuração"):

- `#cfg-modo-direto`: checkbox "Envio direto";
- `#cfg-aviso-direto`: aviso de risco em vermelho, escondido quando o modo está
  desligado;
- `#cfg-direto-horario`: frase do horário, em cinza, escondida quando o modo
  está desligado.

**Funções novas:**

| Função | O que faz |
|---|---|
| `isModoDireto()` | lê o checkbox |
| `aplicarModoEnvio()` | desabilita `cfg-total-msgs-input` e `cfg-tempo` com `direto \|\| settingsLocked`; mostra ou esconde o aviso e a frase do horário; preenche a frase |
| `textoHorarioDireto()` | monta a frase com os valores de `cfg-hora-inicio`, `cfg-hora-fim` e `cfg-skip-weekends` |
| `updateEstimativaDireto()` | texto imediato e depois `GET /estimate?modo_envio=direto`, com debounce de 400ms e descarte de respostas fora de ordem (`_estimateRequestSeq`) |

**Integrações:**

- `lockSettingsEditing()` inclui `cfg-modo-direto` na trava e chama
  `aplicarModoEnvio()` no fim. Assim, destravar depois do envio **não
  reabilita** Quantidade e Tempo com o modo direto ligado. É o mesmo cuidado que
  a mensagem global já tinha.
- `saveConfig()` envia `modo_envio: 'direto' | 'rajadas'` e grava no
  `localStorage`. Quantidade e tempo continuam sendo enviados, para a volta às
  rajadas.
- Restauração pelo `/status` (primeira carga) e pelo `localStorage`: marcam o
  checkbox e chamam `aplicarModoEnvio()`.
- `updateEstimativa()` desvia para `updateEstimativaDireto()` no modo direto.
  Não há aviso de "ritmo apertado", porque não há prazo.
- Listeners:
  - `change` do checkbox → `aplicarModoEnvio()` + `updateEstimativa()`, e
    `autoSaveConfig` (incluído na lista de campos sincronizados);
  - `change` de Hora Início, Hora Fim e fim de semana → `aplicarModoEnvio()`,
    para a frase do horário acompanhar.
- `static/tailwind.css` regenerado (`npm run build:css`) para as classes novas
  (`focus:ring-red-500`, `text-red-600` no checkbox).

---

## 4. Textos para o cliente leigo

Pedido do usuário em 04/10: o cliente não sabe o que é "rajada" nem que
existem pausas. O texto tem de ser entendido por alguém com pouca leitura.
Regras usadas:

- frases curtas;
- nenhum termo interno (rajada, pausa, intervalo);
- dizer **quem** recebe com a palavra que o cliente já vê na tela
  ("Pendente", em amarelo como na tabela);
- dizer **o risco** e **a consequência** de forma concreta.

### Textos finais

**Aviso (vermelho):**

> ⚠️ **CUIDADO!** O programa vai mandar a mensagem para **todo mundo da lista que está como Pendente**, um atrás do outro, sem parar para descansar.
> Isso pode fazer o WhatsApp **BLOQUEAR o seu número**. Se bloquear, você não consegue mais mandar mensagem por ele.
> Só use se tiver certeza.

**Horário (cinza, com os valores da tela):**

> 🕗 Ele só manda das 08:00 às 18:00, e não manda no sábado nem no domingo. Fora desse horário, ele espera e continua depois sozinho.

A parte do fim de semana só aparece com "Não enviar nos finais de semana"
marcado.

**Dica ao passar o mouse:** "Manda para todo mundo da lista que está como
Pendente, um atrás do outro, sem parar para descansar."

**Estimativa:**

| Situação | Texto |
|---|---|
| Antes da resposta do servidor | "Vai mandar para todo mundo que está como Pendente" |
| Com pendentes | "100 pessoa(s) como Pendente. Deve levar mais ou menos 1h 45min." |
| Sem pendentes | "Ninguém da lista está como Pendente" |
| Cabeçalho do bloco fechado | "Direto · 100 msgs" |

**Logs que aparecem na tela:**

| Momento | Texto |
|---|---|
| Salvar configuração | "Configuração atualizada: envio direto (todo mundo da lista, um atrás do outro — pode fazer o WhatsApp bloquear o número), horário 08:00h-18:00h" |
| Restaurar ao reiniciar | "Configuração restaurada da sessão anterior: envio direto (todo mundo da lista, um atrás do outro), horário ..." |
| Início do envio | "📤 Começando o envio direto: 100 pessoa(s) como Pendente, uma atrás da outra." |
| Início do envio | "⚠️ Cuidado: mandar muitas mensagens seguidas pode fazer o WhatsApp bloquear o seu número." |
| Fim | "🎉 Envio finalizado! Total enviado: N mensagens em 1h 40min (modo direto)" |

No `log.txt` fica também a linha técnica
`[ritmo] modo direto: N msg(s), intervalo 15-30s`.

O resto da tela (modo rajadas, painel de status) ainda usa "rajada", "leva" e
"pausa". Isso não foi revisado.

---

## 5. Testes

### Novos

**`tests/e2e/test_e2e_ritmo.py`** (commit `dfe96f1`), contra o WhatsApp
simulado com relógio virtual:

| Teste | Garante |
|---|---|
| `test_conversa_mais_lenta_que_a_estimativa_ainda_fecha_no_prazo` | 90s por abertura: fecha em 60min ±5%, em 3 sorteios |
| `test_conversa_mais_rapida_que_a_estimativa_nao_termina_antes` | 5s por abertura: idem |
| `test_janela_impossivel_avisa_que_vai_passar_do_tempo` | 20 conversas de 90s em 10min: passa do tempo e avisa |
| `TestPisoDaPausa` (3 testes) | atrasado: nunca abaixo de 50% da planejada; pausa curta: nunca abaixo de 15s; adiantado: a pausa ainda cresce |

**`tests/e2e/test_e2e_direto.py`** (sem commit), 10 testes:

| Teste | Garante |
|---|---|
| `test_envia_para_todos_os_pendentes_ignorando_a_quantidade` | `total_msgs=3`, 8 contatos: envia 8 |
| `test_intervalo_entre_15_e_30s_e_sem_pausa_longa` | 12 envios: 11 intervalos, todos entre 15 e 30s; sem "Pausa de", sem "Executando leva" |
| `test_falha_nao_espera_o_intervalo` | 4 contatos, o 2º inválido: exatamente 2 intervalos (nem depois da falha, nem depois do último) |
| `test_risco_registrado_no_log_e_fim_sem_tempo_configurado` | logs de configuração, início, risco e "(modo direto)" no fim |
| `test_horario_comercial_conferido_a_cada_mensagem` | `_aguardar_horario_comercial_medindo` chamado pelo menos uma vez por contato |
| `test_alarme_de_entrega_le_a_lista_a_cada_10_envios` | 25 envios: 2 leituras, cada uma com orçamento menor que o intervalo |
| `test_rajadas_continuam_sendo_o_padrao` | sem `modo_envio`: respeita `total_msgs` |
| `test_modo_sobrevive_ao_reinicio` | grava e restaura de `config.json` |
| `test_modo_desconhecido_e_recusado` | `"turbo"` → 422 |
| `test_estimativa_conta_todos_os_pendentes_mais_o_intervalo` | `/estimate?modo_envio=direto` com 10 pendentes |

**`tests/test_modo_direto_ui.js`** (sem commit). Roda o JS da página num
sandbox `vm` com elementos falsos, no mesmo estilo de `test_trava_config_ui.js`.
Confere:

- a opção existe;
- o aviso diz "todo mundo da lista", "Pendente" e "BLOQUEAR o seu número", e
  **não** contém "rajada", "pausa" nem "intervalo";
- ligado: Quantidade e Tempo desabilitados, valores preservados, aviso e frase
  do horário visíveis;
- a frase do horário tem o texto exato e acompanha a mudança de horário e do
  fim de semana;
- a estimativa pede `/estimate?modo_envio=direto` e mostra o texto certo, sem
  aviso de ritmo;
- `saveConfig` grava `modo_envio` e mantém quantidade/tempo;
- a trava do envio desabilita a opção, e destravar **não** reabilita Quantidade
  e Tempo;
- desligado: tudo volta e o aviso some;
- restauração pelo `localStorage`.

### Execuções

- **Suíte completa** (`python rodar_testes.py`): **667 testes, tudo passou**
  (51 arquivos, ~5,5min). Os 4 erros conhecidos de `test_app_estado.py`
  continuam tratados pelo runner.
- **Depois dessa execução**, mudaram só textos (aviso, estimativa, logs) e a
  frase do horário. Depois disso rodaram de novo `test_e2e_direto` (10 OK),
  `test_modo_direto_ui.js`, `test_trava_config_ui.js`,
  `test_aviso_lentidao_ui.js` e `test_load_contacts_falha.js`, todos OK. **A
  suíte completa não foi rodada de novo depois dos textos.** Vale rodar antes do
  commit.

### Contagens no CLAUDE.md

Atualizadas para 667 testes no total e 434 no `--rapido`. O 434 foi
**calculado** (421 + 13 testes Python novos), não medido.

---

## 6. Decisões de regra (do usuário)

| Data | Decisão |
|---|---|
| 03/10 | Modo direto: opção na tela que desliga a rajada e envia para todos os pendentes, ignorando a quantidade |
| 03/10 | Intervalo sorteado entre 15 e 30s, **não configurável** |
| 03/10 | Falha se comporta como na rajada: não espera, não gasta vaga |
| 03/10 | Horário comercial continua respeitado |
| 03/10 | Aviso de risco na tela e registro no log |
| 04/10 | Piso da pausa reajustada = 50% da planejada (mínimo 15s) |
| 04/10 | Aquecimento do WhatsApp Web não é descontado da janela |
| 04/10 | Intervalo dentro da rajada fica como está (pode ~8s) |
| 04/10 | Alarme de entrega no modo direto: leitura a cada ~10 envios, dentro do intervalo |
| 04/10 | Quantidade e Tempo desabilitados no modo direto, com estimativa "N pendentes, ~tempo" |
| 04/10 | Textos do modo direto em linguagem para cliente leigo, dizendo "Pendente" e o horário configurado |

---

## 7. Pendências e riscos

- [x] Commit e push do modo direto e da correção do histórico.
- [x] Suíte completa depois das mudanças de texto: 668 testes, tudo passou.
- [ ] **Envio real curto nos dois modos.** Os testes rodam contra um WhatsApp
      simulado, que garante o contrato do app, não o WhatsApp de verdade.
      Conferir:
      - rajadas: o tempo final no log bate com o configurado;
      - direto: o aviso e a frase do horário na tela, e os intervalos de 15-30s
        no log.
- [ ] **Ver a tela de verdade.** Os textos foram verificados só pelos testes;
      falta conferir como cabem no espaço do painel.
- [ ] Gerar a versão (`build.bat`) depois dos itens acima.

**Riscos conhecidos:**

- **Mensagens seguidas aumentam o risco de bloqueio.** É a razão do aviso, e o
  alarme de entrega continua ativo como rede de proteção. Mesmo assim, ele só
  avisa: quem decide parar é o usuário.
- **A estimativa do modo direto é previsão, não promessa.** Falhas de abertura
  (~3,7min cada) não entram na conta, como nas rajadas.
- **No modo rajadas, o piso de 50% faz o envio passar do tempo** configurado
  quando ele atrasa muito. É o comportamento escolhido, e o log avisa uma vez
  com a projeção.

---

## 8. Os testes somavam no histórico de envios

**Relato:** o "Baixar histórico" mostrou 1035 envios num dia em que só uma
mensagem de verdade tinha saído.

**Causa:** o histórico (`stats_log.py`) grava em
`~/.whatsapp_automacao_stats.jsonl`, na home, para sobreviver às atualizações.
O `AmbienteE2E` isolava só o diretório de trabalho (`uploads/`), então cada
campanha simulada gravava "enviado"/"rejeitado" no histórico real. As duas
rodadas da suíte em 04/10 deram ~1030 linhas. O padrão (centenas de linhas no
mesmo segundo) aparece também em 16/09, 23/09, 30/09 e 03/10.
`tests/test_aviso_lentidao.py` gravava +10 "rejeitados" por execução, via
`_contar_invalido`.

**Correção:**

- `tests/e2e/ambiente.py` troca `stats_log.registrar_envio`,
  `registrar_rejeitado` e `obter_estatisticas` por versões com
  `path=amb.historico`, um arquivo no diretório temporário do cenário. Troca as
  funções e não a constante `STATS_LOG_PATH`, porque o valor padrão do `path`
  é resolvido quando a função é definida.
- `tests/test_aviso_lentidao.py` desliga `registrar_rejeitado` no `setUp`, como
  `test_numeros.py` e `test_mensagem_global.py` já faziam.
- `tests/e2e/test_e2e_historico.py` roda uma campanha (3 envios, 1 inválido),
  confere que `/stats` mostra 3/1 lendo o arquivo do cenário e falha se o
  arquivo real mudar de tamanho ou de data.

**Verificação:** cada arquivo de teste de unidade e o grupo e2e rodados
separados, comparando o arquivo real antes e depois. Nenhum grava mais.

**O cliente não foi afetado:** o histórico é por máquina e os testes não vão
no `.exe`.

**Pendente:** as linhas antigas gravadas pelos testes continuam no histórico
desta máquina. Dá para limpar tirando as linhas gravadas em lote (3 ou mais no
mesmo segundo), com cópia de segurança antes. O risco é que um envio real com
vários números em branco também gera rejeições no mesmo segundo.
