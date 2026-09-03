# Como reverter as mudanças de 02-03/09/2026

Guia para desfazer, no todo ou em partes, o trabalho feito a partir das duas
queixas do cliente: o envio de "40 mensagens em 45min" que levou 2h, e o
"manda 2 mensagens e desconecta" do primeiro envio do dia.

---

## O caminho curto

Este trabalho está em **um commit só**, separado de propósito do que já estava
na árvore. Para desfazer tudo:

```bash
git revert $(git log --format=%H --grep="arranque frio do WhatsApp Web" -1)
```

Ou ache o hash na mão com `git log --oneline`: é o commit
`fix: arranque frio do WhatsApp Web, estimativa de tempo e avisos de conexao`.

O commit anterior a ele (`chore: registra o trabalho da 1.4.6/1.4.7...`) é o seu
trabalho de antes, que estava sem commit. Foi separado justamente para o revert
acima não arrastá-lo junto. **Não reverta aquele.**

### Duas ressalvas, e elas importam

**1. Quatro arquivos são mistos.** `whatsapp_sender.py`, `app.py`,
`static/index.html` e `CHANGELOG.md` já vinham com alterações suas não
commitadas de antes de 02/09, e não havia como separá-las por arquivo — elas
foram junto no commit das correções. Então `git revert` nesse commit também
desfaz essas partes anteriores. **Para desfazer só o trabalho de 02-03/09, use
as instruções cirúrgicas das seções abaixo**, que apontam arquivo e linha de
cada trecho.

**2. Dois arquivos levaram pequenas edições minhas no commit anterior**, porque
o corpo deles é predominantemente seu:

- `tests/test_chat_open_timeout.py` — renomeei `test_estimativa_de_envio_nao_mudou`
  para `test_estimativa_conta_digitacao_anexo_e_abertura` e ajustei as
  asserções. A versão antiga afirmava
  `_estimar_tempo_envio_individual("Oi", "") == 5.0`.
- `CLAUDE.md` (raiz do repo) — seções novas de arquitetura e os testes novos nos
  comandos.

Reverter o commit das correções **não** desfaz essas duas edições. Elas estão
listadas nos itens 1 e no rodapé deste arquivo.

### O que ficou fora do git de propósito

`log.txt` e `uploads/contatos.xlsx` **não foram commitados**. Continuam
modificados na sua árvore. O repositório é público no GitHub e esses dois
arquivos carregam dados reais — no diff atual do `log.txt` são 866 números de
telefone, nomes, o texto das mensagens e 109 linhas com `machine_id` e prefixo
de chave de licença.

Se quiser impedir que subam por acidente daqui em diante (sem apagar o que já
está no histórico, o que exigiria reescrever o repositório):

```bash
git rm --cached log.txt uploads/contatos.xlsx
```

Os arquivos continuam no disco; só param de ser rastreados.

---

## Arquivos novos (deletar = reverter)

Estes são 100% meus. Apagar não afeta nada além dos próprios testes.

| Arquivo | O que é |
| --- | --- |
| `tests/test_aviso_lentidao.py` | Estimativa com abertura de conversa + disparo do aviso |
| `tests/test_aviso_lentidao_ui.js` | Popup na tela (título, textos, não reabrir a cada heartbeat) |
| `tests/test_pane_lento.py` | Arranque frio: espera vs. recarga, e o aquecimento |
| `tests/test_execucao_interrompida.py` | Marcador de execução morta + aviso do tipo "app" |
| `REVERTER.md` | Este arquivo |

```bash
rm tests/test_aviso_lentidao.py tests/test_aviso_lentidao_ui.js \
   tests/test_pane_lento.py tests/test_execucao_interrompida.py REVERTER.md
```

Também pode aparecer em disco, em tempo de execução:

```bash
rm -f uploads/envio_em_andamento.json    # gerado pelo item 5; ignorado pelo git
```

---

## As 6 mudanças, e como desfazer cada uma

As linhas são do estado atual do código. Todas as âncoras têm comentário
explicando o porquê — se o comentário citar log do cliente ou data de 2026, é
código meu.

### 1. A estimativa passou a contar a abertura da conversa

**Por quê:** ela somava só digitação e anexos (~25s por contato) quando o envio
real custava ~122s. Previa 45min para algo que levou 2h.

| Onde | O quê |
| --- | --- |
| `whatsapp_sender.py:1450` | constante `TEMPO_ESTIMADO_ABERTURA_CHAT = 40` |
| `whatsapp_sender.py:1457` | constante `TEMPO_ESTIMADO_NAVEGACAO = 15` |
| `whatsapp_sender.py:1614` | `tempo += self.TEMPO_ESTIMADO_ABERTURA_CHAT` em `_estimar_tempo_envio_individual` |

**Para reverter:** apague a linha 1614 e as duas constantes.
**Efeito de reverter:** a tela volta a aceitar calada configurações impossíveis
(era o caso exato do cliente: 40 msgs longas em 45min).
**Cuidado:** `TEMPO_ESTIMADO_NAVEGACAO` também é usada pelo item 3
(`_custo_estimado_de_uma_falha`). Se reverter só este item, mantenha essa
constante ou ajuste a fórmula lá.
**Testes que quebram:** `tests/test_aviso_lentidao.py` (classe
`EstimativaIncluiAberturaTest`) e `test_estimativa_conta_digitacao_anexo_e_abertura`
em `tests/test_chat_open_timeout.py` — este último eu **editei**, não criei; a
versão anterior dele se chamava `test_estimativa_de_envio_nao_mudou` e afirmava
`_estimar_tempo_envio_individual("Oi", "") == 5.0`.

Independente de todo o resto.

---

### 2. Popup de conexão ruim durante o envio

**Por quê:** com 42% de falha, nada na tela dizia o que estava havendo — cada
contato virava só mais um badge "Inválido".

| Onde | O quê |
| --- | --- |
| `whatsapp_sender.py:303-310` | contadores `_aberturas_ok`, `_aberturas_timeout`, `_falhas_app`, `_alerta_lentidao`, `_alerta_lentidao_em` |
| `whatsapp_sender.py:377` | `"alerta_lentidao"` dentro de `get_status()` |
| `whatsapp_sender.py:406-410` | constantes `_ALERTA_AMOSTRA_MINIMA`, `_ALERTA_TAXA_FALHA`, `_ALERTA_REARME_A_CADA` |
| `whatsapp_sender.py:412` | método `_registrar_resultado_de_abertura()` |
| `whatsapp_sender.py:506` | método `_custo_estimado_de_uma_falha()` |
| `whatsapp_sender.py:3157` | reset dos contadores em `start()` |
| `whatsapp_sender.py:3331,3435,3483` | as três chamadas de `_registrar_resultado_de_abertura` |
| `app.py:405` e `app.py:433` | `alerta_lentidao` no `get_status_dict()` |
| `static/index.html:205-240` | o modal `#lentidao-overlay` inteiro |
| `static/index.html:879-927` | `ultimoAlertaLentidaoVisto`, `mostrarAvisoLentidao()`, `fecharAvisoLentidao()` |
| `static/index.html:953` | a chamada `mostrarAvisoLentidao(status.alerta_lentidao)` em `updateDashboard` |

**Para reverter:** remova nessa ordem — a chamada em `updateDashboard`, as
funções, o modal, os dois campos em `app.py`, depois as chamadas e os métodos em
`whatsapp_sender.py`.
**Efeito de reverter:** volta a não haver aviso nenhum durante o envio; o log
continua registrando as falhas contato a contato.
**Testes que quebram:** `tests/test_aviso_lentidao.py`,
`tests/test_aviso_lentidao_ui.js`, e a classe `AvisoDeFalhaDoAppTest` em
`tests/test_execucao_interrompida.py`.

Independente dos itens 4, 5 e 6. O item 3 é uma extensão deste — reverter este
leva o 3 junto.

---

### 3. O popup passou a contar também "o WhatsApp Web não subiu"

**Por quê:** ele contava só falha de *abrir conversa*. No envio de 01/09 foram
4 sucessos, 1 falha de conversa e 3 de app: 1 em 5, abaixo do limite, nenhum
aviso — justo o caso mais grave.

| Onde | O quê |
| --- | --- |
| `whatsapp_sender.py:412` | parâmetro `tipo` em `_registrar_resultado_de_abertura` e os campos `falhas_app`/`tipo` no alerta |
| `whatsapp_sender.py:506` | parâmetro `tipo` em `_custo_estimado_de_uma_falha` |
| `whatsapp_sender.py:3435` | chamada `(False, tipo="app")` dentro do `except WhatsAppNotLoadedError` |
| `static/index.html:881` | bloco `const falhaDoApp = ...` em `mostrarAvisoLentidao` |
| `static/index.html:224` | `id="lentidao-dica-reenvio"` no `<li>` do modal |

**Para reverter isoladamente (mantendo o item 2):** tire o parâmetro `tipo` das
duas assinaturas, apague a chamada da linha 3435 e volte o texto do popup ao
formato único.
**Efeito de reverter:** o popup volta a ficar mudo quando o WhatsApp Web não
carrega — que foi exatamente a falha de 01/09.

---

### 4. Espera em vez de recarga quando a página está lenta

**Por quê:** a retentativa chamava `driver.get` de novo, na hora, sem pausa.
Recarregar joga fora o carregamento em andamento e reinicia o boot do WhatsApp
Web. O log mostra três boots empilhados: 65s, 61s, 61s.

| Onde | O quê |
| --- | --- |
| `whatsapp_sender.py:1842` | `motivo_retentativa = None`, logo antes do `for tentativa in range(...)` |
| logo abaixo | bloco `recarregar = (...)` e o `if recarregar:` que envolve `_random_scroll()` + `driver.get(url)` |
| no `if not pane_found:` | `motivo_retentativa = "pane"`, `vai_recarregar`, e as duas mensagens de log |
| no `except TimeoutException:` do chat | `motivo_retentativa = "chat"` |
| `whatsapp_sender.py:186` | `_PANE_LOAD_TIMEOUT` de `60` para `75` |

**Para reverter:** volte o topo do laço para

```python
for tentativa in range(1, self._NAV_MAX_ATTEMPTS + 1):
    if human:
        self._random_scroll()
    self._driver.get(url)
```

apague as três atribuições de `motivo_retentativa`, volte a mensagem única
"recarregando" no bloco de falha e ponha `_PANE_LOAD_TIMEOUT = 60`.

**Efeito de reverter:** volta o comportamento que produziu o "manda 2 mensagens
e desconecta".
**Testes que quebram:** `tests/test_pane_lento.py` (classe `RetryDoPaneTest`) e
`test_pane_nao_carrega_espera_antes_de_recarregar_sem_digitar_nada` em
`tests/test_nav_retry.py` — que era meu ajuste do teste antigo. Se reverter este
item, o `git checkout -- tests/test_nav_retry.py` do topo deste arquivo já
devolve a versão correta para o comportamento antigo.

O `_PANE_LOAD_TIMEOUT` pode ser revertido sozinho (60s de volta) sem desfazer a
política de espera — são independentes.

---

### 5. Aviso de execução interrompida

**Por quê:** o envio de 31/08 foi encerrado à força às 16:56 (o log termina em
"Aguardando 21s..."), deixando 40 pendentes. No dia seguinte o app reabriu
calado com "118 msgs em 240min" restaurado, aplicado ao punhado que sobrou.

| Onde | O quê |
| --- | --- |
| `app.py:162` | `ENVIO_FLAG_FILE = Path("uploads/envio_em_andamento.json")` |
| `app.py:165` | `_marcar_envio_em_andamento()` |
| `app.py:183` | `_limpar_envio_em_andamento()` |
| `app.py:191` | `_avisar_execucao_interrompida()` |
| `app.py:303` | a chamada em `startup_event()` |
| `app.py:856` | `pendentes = 0` antes do `try` de leitura da planilha |
| `app.py:888` | wrapper `_rodar_envio()` e o `Thread(target=_rodar_envio, ...)` |

**Para reverter:** apague as três funções, a constante, a chamada no startup e o
`pendentes = 0`; e volte a thread para

```python
state.sender_thread = Thread(target=state.sender.start, daemon=True)
```

Depois: `rm -f uploads/envio_em_andamento.json`.

**Efeito de reverter:** volta a reabrir calado depois de um fechamento no meio
do envio. A retomada em si continua funcionando — ela nunca dependeu disto.
**Testes que quebram:** classe `MarcadorDeExecucaoTest` em
`tests/test_execucao_interrompida.py`.

Totalmente independente. Só mexe em `app.py`.

---

### 6. Aquecimento antes de começar o envio

**Por quê:** `_aguardar_sincronizacao` libera quando a lista de conversas para
de crescer por 6s, mas depois de uma noite offline essa lista volta inteira do
cache e nasce estável. Ele deu o mesmo veredito ("67 conversa(s), estável por
6s") em toda sessão do log — na de 6% de falha e na de 67%.

| Onde | O quê |
| --- | --- |
| `whatsapp_sender.py:253-261` | constantes `_AQUECIMENTO_ALVO_SEG`, `_AQUECIMENTO_MAX_TENTATIVAS`, `_AQUECIMENTO_LIMITE_SEG`, `_AQUECIMENTO_PAUSA_SEG` |
| `whatsapp_sender.py:1218` | método `_aquecer_navegacao()` |
| `whatsapp_sender.py:3095` | a chamada, logo após `_aguardar_sincronizacao(...)` |

**Para reverter:** apague a chamada da linha 3095 (isso já basta — o método vira
código morto), e depois o método e as constantes.
**Efeito de reverter:** o envio volta a começar ~5s depois do login, contra um
WhatsApp Web que pode ainda estar subindo. Ganha-se de 1 a 3 minutos no início.
**Testes que quebram:** classe `AquecimentoTest` em `tests/test_pane_lento.py`.

Totalmente independente. **Se você quiser desfazer só uma coisa, comece por
esta** — é a que mais muda a experiência visível (a espera antes de iniciar) e a
que sai com uma linha só.

---

## Reversão parcial: o que é seguro tirar sozinho

| Quero tirar | Dá para tirar sozinho? |
| --- | --- |
| 6 — aquecimento | ✅ apaga 1 linha (a chamada) |
| 5 — aviso de execução interrompida | ✅ só `app.py` |
| 4 — timeout de 75s → 60s | ✅ 1 constante |
| 4 — política de espera sem recarga | ✅ só o laço de navegação |
| 1 — estimativa com abertura | ✅ mas mantenha `TEMPO_ESTIMADO_NAVEGACAO` |
| 3 — tipos de falha no popup | ✅ |
| 2 — popup inteiro | ⚠️ leva o item 3 junto |

Nenhum dos itens muda o que é gravado na planilha. Todos vivem na fase de
navegação, no cálculo da estimativa ou na tela — nada mexe em `Enviado`,
`Invalido`, `DataEnvio` nem na deduplicação. Reverter qualquer combinação não
tem como causar envio duplicado.

---

## Conferir se a reversão ficou consistente

```bash
venv\Scripts\python.exe -m unittest test_numeros test_mensagem_global -v
venv\Scripts\python.exe -m unittest tests.test_chat_open_timeout tests.test_nav_retry \
    tests.test_sync_inicial tests.test_log_queda_conexao tests.test_duplicado_vs_enviado -v
python tests/test_deduplication.py
python tests/test_contact_update_backend.py
node tests/test_contact_update.js
node tests/test_log_tooltip.js
node tests/test_trava_config_ui.js
```

Lembre de apagar do comando os arquivos de teste que você removeu.

**Nota:** `test_app_estado.py` já falhava antes deste trabalho (1 falha + 3
erros, vindos do `uploads/config.json` local vazando para os testes).
Verificado com `git stash`: as falhas são idênticas com e sem as mudanças. Não
use esse arquivo como termômetro da reversão.

---

## Documentação a limpar junto

Se reverter tudo, tire também:

- `CHANGELOG.md` — as duas entradas do topo, `## 2026-09-03` e `## 2026-09-02`.
  ⚠️ Não use `git checkout` neste arquivo: ele já tinha alterações suas antes.
- `../CLAUDE.md` — as seções "A cold WhatsApp Web is the single biggest
  predictor of failure", "The configured time is a total, and most of it is not
  pauses", "An interrupted run is detected by a file, not inferred", as duas
  linhas de teste novas e os nomes dos testes nos comandos.
