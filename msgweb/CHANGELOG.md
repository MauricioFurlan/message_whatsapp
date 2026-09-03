# Changelog

## 2026-09-03 (arranque frio do WhatsApp Web e execução interrompida)

Duas queixas do cliente, mesma raiz. "No dia seguinte o sistema começou a
desconectar: mandava 2 mensagens e desconectava" — e, antes disso, "sobraram
mensagens pendentes do dia anterior".

### Por que sobraram pendentes

O log de 31/08/2026 termina no meio de um envio, em `16:56:00 | Aguardando
21s...`, sem `Envio finalizado`, sem `Solicitação de parada` e sem `Fechando
navegador`. O programa foi encerrado à força com 48 enviados, 30 inválidos e 40
pendentes de 118. Retomar de onde parou já funcionava; o que faltava era avisar.

No dia seguinte o app reabriu calado, restaurou "118 msgs em 240min" da sessão
anterior e aplicou esse número aos 40 que sobraram — daí um plano com pausas de
24 a 37 minutos entre levas, que não fazia sentido para aquele volume.

Agora `uploads/envio_em_andamento.json` marca que há envio rodando e é apagado
quando a thread termina por qualquer caminho previsto (conclusão, parada manual,
erro). Sobreviveu ao reinício? O processo morreu no meio, e o arranque diz isso
ao usuário, com a data e quantos estavam pendentes, pedindo que confira a
quantidade e o tempo antes de iniciar.

### O bug do "manda 2 e desconecta"

Isolando as quatro execuções dos dois dias:

| execução | enviadas | timeout de conversa | falhas de `#pane-side` |
| ------------------------------ | -------- | ------------------- | ---------------------- |
| 31/08 13:14 (118 em 240min)    | 48       | 27                  | 0                      |
| **01/09 13:01 (40 em 240min)** | **4**    | 1                   | **3**                  |
| 01/09 13:23 (33 em 45min)      | 23       | 9                   | 0                      |
| 01/09 14:41 (111 em 150min)    | 64       | 4                   | 0                      |

E a taxa de falha por fase de cada envio:

| execução | 0-20min | 20-60min | 60min+ |
| ---------------------------------- | ------- | -------- | ------ |
| 31/08 13:14 (arranque frio)        | 50%     | 36%      | 34%    |
| 01/09 13:01 (arranque frio)        | 43%     | —        | —      |
| 01/09 13:23 (reinício, morno)      | 18%     | 33%      | 33%    |
| 01/09 14:41 (3º start, quente 2h)  | 8%      | 5%       | 6%     |
| 02/09 09:22 (arranque frio)        | 67%     | 46%      | 32%    |

A taxa de falha depende de há quanto tempo o WhatsApp Web está de pé, e de mais
nada. O cliente achou que resolveu apagando os enviados e mudando quantidade e
tempo; o que resolveu foi o **reinício**, que pegou o navegador aquecido. A
melhor execução do dia (64 enviadas, 6% de falha) usava 111 mensagens, volume
*maior* que o da que falhou.

#### Correção: o portão de sincronização era cego

`_aguardar_sincronizacao` libera o envio quando a lista de conversas para de
crescer por 6s. Depois de uma noite offline, o WhatsApp Web renderiza a lista
inteira na hora, vinda do IndexedDB — é a lista de ontem, em cache, e ela nasce
estável. O portão dava o mesmo veredito em toda sessão do log:

```
27/08 13:06  67 conversa(s), estável por 6s  ->  envio saudável
31/08 13:14  67 conversa(s), estável por 6s  ->  36% de falha
01/09 13:01  67 conversa(s), estável por 6s  ->  43% + 3 quedas
01/09 14:41  67 conversa(s), estável por 6s  ->  6% de falha
02/09 09:22  67 conversa(s), estável por 6s  ->  67% de falha
```

Sempre 67, sempre em 10-15s. Ele não media o que se supunha que medisse.

Entrou `_aquecer_navegacao()`, que mede o gesto que o envio realmente faz a cada
contato: um `driver.get` e a espera do `#pane-side`. Passou de 25s, o app ainda
está subindo — espera e mede de novo, até três vezes. Nunca bloqueia: numa
máquina cronicamente lenta o envio começa assim mesmo, com aviso, igual ao que
`_aguardar_sincronizacao` já fazia. Vai para `web.whatsapp.com` puro, nunca para
um `send?phone=`, que abriria (e marcaria como lida) a conversa de um contato.

Roda antes de `_envio_iniciado_em`, então o tempo de aquecimento não entra na
duração relatada nem no plano de rajadas.

#### Correção: recarregar era o pior remédio para uma página lenta

Quando o `#pane-side` não aparecia, a retentativa chamava `driver.get` de novo,
na hora, sem pausa. Recarregar joga fora o carregamento em andamento e faz o
WhatsApp Web recomeçar o boot do zero — exatamente o que não se quer numa página
que está apenas lenta. Os tempos do log mostram três boots empilhados: 65s, 61s
e 61s, colados.

Agora as tentativas do meio **seguem esperando sem renavegar**, o que transforma
duas janelas picotadas numa espera contínua pelo mesmo preço. Só a última
recarrega — uma página travada, e não lenta, ainda precisa do reload —, e com um
respiro antes. Note a assimetria que existia: o retry de *abrir conversa* já
tinha backoff de 5s e 15s; o de *carregar a página* não tinha nenhum.

`_PANE_LOAD_TIMEOUT` foi de 60s para 75s. No arranque frio o próprio login levou
~60s e as três falhas foram detectadas em 65s, 61s e 61s: 60s era exatamente a
fronteira, e o resultado virava cara ou coroa.

### E o aviso de lentidão ficava mudo justamente aqui

O popup criado ontem contava só as falhas de abrir CONVERSA. Naquele envio de
01/09 foram 4 sucessos, 1 falha de conversa e 3 do WhatsApp Web inteiro não
subir: 1 em 5, abaixo do limite de 30%, nenhum aviso — no cenário mais grave dos
três dias, em que o envio não avança nem marca nada.

`_registrar_resultado_de_abertura()` agora recebe o tipo da falha e conta as
duas. Os textos são diferentes porque as ações do usuário são diferentes: falha
de conversa marca o contato como inválido (e o botão ↺ o recupera), falha de app
deixa o contato **pendente**, sem nada para reenviar. A dica do ↺ some do popup
no segundo caso.

Testes: `tests/test_pane_lento.py`, `tests/test_execucao_interrompida.py` e os
casos novos em `tests/test_aviso_lentidao_ui.js`. `tests/test_nav_retry.py` teve
o teste de recarga atualizado — ele fixava as 3 navegações do comportamento
antigo; o ponto original dele (nada digitado nem anexado) continua valendo.

## 2026-09-02 (estimativa de tempo do envio e aviso de conexão ruim)

Queixa do cliente: configurou "40 mensagens em 45 minutos" e o envio levou **2h**.

O plano de rajadas não errou — as pausas que ele previu foram cumpridas quase na
mosca. Reconstruindo o `log.txt` do envio (02/09/2026, 09:22 → 11:22):

| Onde o tempo foi                            | Total |
| ------------------------------------------- | ----- |
| 22 envios bem-sucedidos (122s cada, média)  | 45min |
| 16 timeouts de abertura de conversa (224s)  | 60min |
| esperas entre mensagens dentro da leva      | 11min |
| pausas entre as levas (o que o plano prevê) |  9min |

Ou seja: das 2h, o planejador respondia por 9 minutos. Duas causas
independentes, ambas de *estimativa*, não de ritmo.

### Correção: a estimativa ignorava o tempo de abrir a conversa

`_estimar_tempo_envio_individual` somava só o orçamento de digitação e 18s por
anexo — deu "~16min 46s de tempo estimado de envio" para 40 contatos, ~25s cada.
Mas o intervalo entre `Enviando para` e o início da digitação foi de 41-58s
(mediana 46s) nos envios que abriram de primeira: scroll, `driver.get`, esperar
`#pane-side` e a conversa carregar. O envio real custava 122s por contato, quase
5x a previsão.

Entrou `TEMPO_ESTIMADO_ABERTURA_CHAT = 40` (meio-termo entre a mediana de 31s
medida em 24-26/08, numa máquina rápida, e os 46s de 02/09), somado **sempre**,
com ou sem comportamento humano — `driver.get` e `#pane-side` acontecem nos dois
modos. Com isso a configuração do cliente passa a cair no caminho `inviavel` que
já existia em `_calcular_orcamento_de_pausas`, e o aviso aparece na tela **antes**
de iniciar, via `/estimate`, em vez de o usuário descobrir depois de 2h.

Isto não muda o ritmo das rajadas: `_generate_burst_plan` continua recebendo só
o orçamento de pausas. O que muda é o tamanho desse orçamento — que agora
reflete o que sobra de verdade.

### Novo: aviso de conexão instável no meio do envio

O segundo pedaço não dá para prever antes de começar. Um contato cuja conversa
nunca abre custa ~3,7min (3 tentativas de 45s + backoff) e — pela invariante
deliberada de que contato inválido não gasta vaga da rajada — a leva puxa outro
contato no lugar dele. Foi assim que a leva 2, de "7 mensagens seguidas",
sozinha levou 53 minutos.

Com 16 falhas em 38 tentativas (42%), nada na tela dizia o que estava
acontecendo: cada contato virava só mais um badge "Inválido", indistinguível de
um número que não tem WhatsApp.

`_registrar_resultado_de_abertura()` agora acompanha a taxa de falha da sessão e,
a partir de 6 tentativas com 30% ou mais de falha, arma um aviso com o número de
falhas, o percentual e o atraso já acumulado. O painel mostra em popup (o envio
segue rodando — o aviso é informativo) e o mesmo texto vai para o log.

Duas decisões que parecem detalhe e não são:

- **O aviso viaja dentro do `status`**, não como evento SSE próprio. Um envio
  desses dura horas; se o usuário der F5 ou a conexão SSE cair, um evento
  pontual teria se perdido justamente para quem mais precisa dele.
- **O campo `seq` (nº de falhas quando o aviso saiu) é o que abre o popup.** O
  status chega a cada 5s de heartbeat: sem ele, o popup reabriria sozinho a cada
  5 segundos, inclusive depois de fechado. Depois do primeiro aviso, só reaparece
  a cada 5 falhas novas.

Só contam para a taxa as tentativas que chegaram a abrir conversa — número
vazio, mensagem vazia ou duplicado são invalidados antes da navegação e não
dizem nada sobre a rede.

Testes: `tests/test_aviso_lentidao.py` e `tests/test_aviso_lentidao_ui.js`.

## 2026-08-26 (timeouts de envio, estado da planilha e da configuração, abertura do Chrome, diagnóstico da licença)

Investigação do `log.txt` do cliente (24 a 26/08/2026, versão 1.4.5): 172 mensagens
entregues, 52 contatos marcados como inválidos por "timeout ao abrir a conversa" e
duas queixas — o app às vezes pedir a chave de licença já cadastrada, e abrir sem
carregar a planilha.

Os 52 timeouts foram todos na fase de navegação, antes de qualquer entrega: cada um
é precedido no log por `Conversa de X não abriu em 20s`, e nessa fase o código só
executou `driver.get` — o anexo e a digitação vêm depois. Nenhum daqueles contatos
recebeu mensagem, e reenviar não duplica nada.

Os números não eram o problema. 26 das 78 falhas de primeira tentativa foram
resolvidas na segunda tentativa imediata, com o mesmo número; o `19978094539` deu
timeout às 14:40, 14:50 e 14:56 de 26/08 e recebeu a mensagem normalmente às 15:18;
e em três dias o WhatsApp não exibiu **nenhum** popup de número inválido.

### Correção: janela de 20s para a conversa abrir não tinha margem nenhuma

Medindo o intervalo entre disparar o contato e começar a digitar, nas 150
mensagens que abriram de primeira: mínimo 16s, mediana 31s, p90 36s, máximo 41s.
O mínimo de 16s é o custo fixo de scroll + `driver.get` + `#pane-side`, então
metade das aberturas **bem-sucedidas** consumia ~15s dos 20s disponíveis e a mais
lenta raspou o limite. Qualquer lentidão a mais marcava como inválido um número
perfeitamente válido.

`_CHAT_OPEN_TIMEOUT` passou de 20s para 45s. Quem abre rápido continua saindo
rápido — a janela é um teto, não uma espera fixa.

Duas mudanças acompanham:

- **Frequência de verificação.** O laço checava o campo de digitação e, na mesma
  volta, rodava as detecções de popup e de contato bloqueado, que leem `.text` de
  vários elementos (caro em WebDriver). O campo acabava reconsultado poucas vezes
  dentro da janela. Agora o campo é verificado a cada 0,3s e as detecções caras a
  cada 2s — a primeira delas ainda na volta inicial, para número rejeitado
  continuar sendo detectado nos primeiros segundos em vez de gastar a janela.
- **Três tentativas, com pausa entre elas.** As duas tentativas antigas eram
  coladas (~30s de intervalo) e caíam dentro da mesma janela ruim do WhatsApp Web:
  em 26/08 houve 8 contatos seguidos falhando as duas vezes. Agora são 3, com
  pausa de 5s e depois 15s. Continua valendo a invariante da fase de navegação:
  nada foi entregue nela, então repetir não duplica mensagem nem anexo.

O que **não** mudou: o orçamento de pausas das rajadas. `_estimar_tempo_envio_individual`
segue contando apenas digitação e anexos, sem o tempo de abrir a conversa — que
nunca entrou nessa conta. Descontá-lo faria o envio terminar dentro da janela
configurada, mas encurtaria as pausas entre mensagens em ~27% num cenário de 97
mensagens em 240min, deixando o ritmo mais agressivo. Fica como decisão separada.

Coberto por `tests/test_chat_open_timeout.py`.

### Correção: rajada inteira de timeouts logo depois de vincular pelo QR

Em 26/08 o login saiu às 14:37:37 e a primeira mensagem foi disparada às 14:37:39,
2 segundos depois. Os 8 contatos daquela sessão deram timeout e nenhum envio saiu.
Depois de um QR novo o WhatsApp Web ainda está baixando o histórico do celular, e
nesse estado abrir conversa por `send?phone=` trava. O cliente parou e reiniciou
três vezes seguidas (14:44, 14:53), o que só reiniciava a sincronização.

`_aguardar_sincronizacao()` agora segura o início do envio até a lista de conversas
parar de crescer por 6s e sumir qualquer aviso de sincronização — até 180s depois
de um QR novo, 45s quando a sessão já estava ativa. Se não estabilizar, avisa e
segue mesmo assim: o timeout de navegação continua protegendo contato a contato.
Coberto por `tests/test_sync_inicial.py`.

### Correção: "Sessão não encontrada. Escaneie o QR Code" com a sessão salva

A detecção de sessão esperava 8 segundos fixos pelo `#pane-side` e, não achando,
anunciava que era preciso escanear o QR Code. O WhatsApp Web passa disso com folga
num início frio, então o aviso saía com a sessão intacta: em 25/08 13:00:21 a
mensagem foi seguida de "Login realizado com sucesso" às 13:00:24 — 3 segundos
depois. Em 26/08, 6 e 5 segundos. Ninguém escaneia um QR nesse tempo.

Agora a decisão espera até `_SESSION_DETECT_TIMEOUT` (40s) e só fala em QR Code
quando o QR está realmente desenhado na tela (`_qr_na_tela()`). Sem QR e sem lista
de conversas, a mensagem passou a ser "o WhatsApp Web está demorando para
carregar", que descreve o que de fato está acontecendo.

### Queda de internet agora fica registrada no log

Quando a internet cai no meio de um envio, o WhatsApp Web **continua de pé**: é
uma PWA, o shell vem do service worker e as conversas do IndexedDB. O
`#pane-side` segue existindo, então a falha não cai no caminho de "WhatsApp Web
não carregou" (que deixaria o contato pendente) — cai no timeout de abrir a
conversa, que marca o contato como inválido. A premissa desse caminho é "o app
está de pé, logo o problema é o número", e numa queda de rede ela é falsa.

O comportamento foi **mantido de propósito**: o contato continua sendo marcado
como inválido, e quem confere é o usuário pelo botão de reenvio (↺). O que
faltava era conseguir saber, depois, que aquilo foi a rede. Sem isso, uma
internet instável e uma lista de números ruins produzem exatamente o mesmo
registro no log — foi essa a dúvida que abriu a investigação dos 52 timeouts de
24 a 26/08.

`_detect_sem_conexao()` combina dois sinais: `navigator.onLine` (uma chamada,
barata, e um `false` é prova forte) e o aviso que o WhatsApp Web desenha
("Computador não conectado", "Aguardando conexão"), lido apenas dos elementos de
alerta — ler o texto da página inteira a cada volta custaria caro demais. Roda
junto das outras detecções caras, no intervalo de 2s.

O que passa a aparecer:

- uma linha na entrada e uma na saída do estado sem conexão, com quanto tempo
  ficou fora — não uma linha a cada verificação;
- cada timeout durante a queda sai com `ATENÇÃO: sem conexão neste momento` e a
  posição do contato na sequência;
- o motivo gravado na planilha (e no tooltip da linha) diz que foi falta de
  conexão, em vez de sugerir que o número está errado;
- no fim do envio, um resumo com quantos contatos caíram por falta de rede.

Coberto por `tests/test_log_queda_conexao.py`, incluindo uma trava que falha se
alguém trocar o desfecho de "inválido" sem querer.

O que continua fora: não há detecção *global* de queda que pause o envio. Com a
rede fora por muito tempo, o sender segue consumindo a fila a ~2,5 min por
contato em vez de esperar a conexão voltar.

### Correção: planilha não carregava e a tela não dizia nada

`loadContacts()` fazia `if (!response.ok) return;` e o `catch` só chamava
`console.warn`. Quando o `GET /contacts` falhava, a tabela ficava vazia para
sempre — sem retry, sem aviso — exatamente o que o cliente fotografou: tabela sem
nenhuma linha e, logo abaixo, o aviso de que a planilha da sessão anterior tinha
sido restaurada.

O risco não era só cosmético. A tabela da tela é a fonte do `POST /contacts`, que
reescreve a planilha inteira; salvar com a tela vazia apagaria as marcas de
`Enviado` e devolveria à fila quem já recebeu — o mesmo desfecho do bug de
19/08/2026. Agora:

- o `GET` é repetido até 3 vezes com espera crescente (leitura pura, nunca grava);
- uma resposta vazia **nunca** substitui uma tabela já preenchida;
- persistindo a falha, a tela mostra o erro com um botão "Tentar de novo" e
  **bloqueia o salvar** — no botão e no `Ctrl+S`, que não passa pelo `disabled`;
- erro em helper de UI (tooltip, indicadores de ordenação) não é mais confundido
  com falha de carregamento: os dados já estão na tela e o salvar segue liberado.

Coberto por `tests/test_load_contacts_falha.js`.

### Correção: contato "Enviado" aparecendo como "Duplicado" depois de reiniciar o servidor

Reiniciando o servidor com a planilha já carregada, contatos que estavam como
**Enviado** passavam a aparecer como **Duplicado** — mesmo com "permitir números
duplicados" ligado. Um F5 devolvia o status certo.

Duas causas somadas:

1. **`state.config` não sobrevivia ao reinício.** A configuração real morava só
   no `localStorage` do navegador e só chegava ao backend num `POST /config`,
   disparado quando o usuário mexe em algum campo. Até lá o servidor respondia
   com o padrão (`allow_duplicates=False`) e `GET /contacts` marcava duplicados
   que não deveria. O F5 "consertava" porque a essa altura a configuração já
   tinha sido reenviada. Agora a configuração é gravada em `uploads/config.json`
   a cada `POST /config` e restaurada no startup, antes de a tela pedir os
   contatos — o mesmo tratamento que a planilha já tinha.
2. **Uma linha já enviada nunca deveria ser marcada como duplicada.** "Enviado"
   é fato gravado na planilha; "duplicado" é classificação derivada e só diz
   algo sobre quem ainda está na fila. `GET /contacts` agora pula linhas
   enviadas ao marcar — elas continuam servindo de âncora para detectar os
   pendentes que repetem o número.

Não era só cosmético. O status na tela **não** contamina o que é salvo (o
`dataset.enviado` da linha preserva o valor real, e é dele que `collectContacts()`
lê), mas o botão de reenvio (↺) aparece em toda linha já processada: vendo
"Duplicado" onde deveria ler "Enviado", o usuário clica no ↺ para "corrigir" e
`resetContact()` zera o Enviado, devolvendo o contato à fila. Na rodada seguinte
ele recebe a mensagem de novo.

Coberto por `tests/test_duplicado_vs_enviado.py`.

### Configuração e mensagem global travadas com o envio em andamento

A edição de contatos já era bloqueada durante o envio, mas a configuração
(quantidade, tempo, horário, comportamento humano, permitir duplicados) e a
mensagem global continuavam aceitando alteração. O sender relê `state.config` e
`state.global_message` a cada contato, então uma alteração aceita no meio do
caminho mudava o ritmo — ou o **texto** — dos contatos restantes de um envio já
em curso, sem nada indicar isso na tela.

A trava mora no backend: `POST /config` e `POST /global-message` agora recusam
com 400 enquanto `sender.is_running()`, pelo mesmo helper `_recusar_se_enviando()`
que `POST /contacts` passou a usar. `is_running()` cobre também o estado
`pausado` — pausa entre rajadas e espera por horário comercial são envio em
andamento, e antes davam uma janela confortável para alterar o ritmo entre uma
leva e outra.

Havia um caminho que fazia isso sozinho, sem o usuário pedir: `toggleGlobalMessage()`
roda na carga da página restaurando o toggle do `localStorage` e, no fim, reposta
a mensagem global no servidor. Recarregar a tela no meio de um envio reescrevia a
mensagem global com o que estava salvo no navegador daquele computador.

Na tela, `lockSettingsEditing()` espelha o `lockContactsEditing()` já existente:
desabilita os campos, mostra "🔒 Bloqueado durante o envio" e impede os POSTs
antes de saírem. Duas sutilezas:

- destravar não pode reabilitar o textarea da mensagem global quando o toggle
  está desligado — os dois estados são combinados em `aplicarEstadoMensagemGlobal()`;
- `startSending()` grava config, mensagem global e contatos **antes** de chamar
  `/start`, e nesse instante o `starting = true` já pode ter travado a tela pelo
  heartbeat do `/status`. A flag `salvandoParaIniciar` libera exatamente esses
  três saves. Sem ela, o envio começaria com a configuração anterior — o mesmo
  desfecho do bug de "comportamento humano ficou no padrão OFF sem o usuário
  saber".

Coberto por `tests/test_trava_durante_envio.py` e `tests/test_trava_config_ui.js`.

### Correção: quatro janelas do Chrome e "Chrome instance exited"

Com uma janela do Chrome já aberta no WhatsApp Web, iniciar o envio abria quatro
janelas e terminava em:

```
ERRO: Não foi possível iniciar o Chrome: Message: session not created:
Chrome instance exited.
```

Um segundo Chrome lançado com o mesmo `--user-data-dir` não abre instância nova:
ele entrega o pedido para a que já está rodando e **encerra o próprio processo**.
O ChromeDriver, que esperava esse processo, reporta "Chrome instance exited" — uma
mensagem que não diz nada sobre a causa real.

As janelas extras vinham dos fallbacks em cascata (webdriver-manager →
`chromedriver.exe` local → chromedriver do PATH). Eles existem para chromedriver
ausente ou incompatível, e não têm relação nenhuma com perfil ocupado: cada um
lançava mais um Chrome para morrer do mesmo jeito.

Agora `_init_driver()` verifica antes de tentar se algum processo Chrome já está
com o perfil aberto (`_pids_chrome_no_perfil()`, via `Get-CimInstance` — sem
`wmic`, que não existe mais no Windows 11 recente; processos filhos com `--type=`
são descartados, senão a mensagem sairia com uma dezena de PIDs inúteis). Se
estiver, levanta `ChromeProfileInUseError` com o PID e a instrução de fechar a
janela, sem lançar Chrome nenhum. E um erro de perfil em uso vindo do
ChromeDriver deixou de cair nos fallbacks — os fallbacks continuam valendo para
chromedriver incompatível, que é o que eles resolvem.

Um agravante que saiu junto: o código apagava `SingletonLock`, `SingletonSocket`
e `SingletonCookie` do perfil **antes** de cada tentativa. Isso só faz sentido
para lock órfão; com um Chrome vivo usando o perfil, é mexer no estado de um
processo em funcionamento. A limpeza agora só acontece depois de confirmado que
ninguém está usando o perfil.

Coberto por `tests/test_chrome_perfil_em_uso.py`.

### Diagnóstico: por que a licença é pedida de novo

O relato é intermitente e a tela mostra o mesmo formulário para todas as causas
possíveis — cache ausente, `machine_id` divergente, licença expirada, erro de rede.
Sem registro, não havia como saber qual foi depois do fato.

`license.py` agora registra no `log.txt` cada caminho que resulta em "inválida",
com o motivo exato, e toda chamada de `_clear_cache()` (é ela que obriga a redigitar
a chave) sai no log com a razão. Cada sessão passa a começar com uma linha-base:
caminho do arquivo de licença, se ele existe, o `machine_id` e **de que fonte ele
veio**. A árvore de decisão de validade não mudou — inclusive exceções inesperadas
(`response.json()` recebendo HTML de portal de rede, por exemplo) continuam subindo
como antes; a diferença é que agora ficam registradas.

Suspeito principal já visível: `get_machine_id()` obtém o UUID da placa via
`wmic csproduct get UUID`, e o `wmic` **não existe mais** nas builds recentes do
Windows 11 (confirmado numa máquina 26200: `FileNotFoundError` imediato). Ele cai
no fallback `hostname-usuário-arquitetura`, o que significa que o `machine_id`
mudou de valor sozinho quando a Microsoft removeu a ferramenta. O log agora avisa
em WARNING se a fonte mudar durante a execução.

Também ficou registrado quanto tempo `/license/status` demora: ele chama `requests`
bloqueante de dentro de uma rota `async`, então enquanto espera o Supabase (até 10s
por requisição) o event loop não atende `/contacts`, `/status` nem `/events`. Acima
de 3s isso sai no log como aviso — é um candidato direto para os dois sintomas
aparecerem juntos.

### Mensagens que exigem ação do usuário ganharam destaque no log

"Feche essa janela do Chrome e clique em Iniciar novamente" saía verde, a mesma
cor das mensagens de sucesso: `addLogEntry()` só destacava linhas com `❌`,
`ERRO` ou `Erro`, e tudo o mais caía no `else`. Mensagens com `🚫` agora usam a
classe `.log-acao` — fundo âmbar, borda à esquerda e negrito — porque são as
únicas em que o envio fica parado esperando o usuário fazer algo.

### Manutenção: duas suítes de teste que a espera de sincronização travou

`_aguardar_sincronizacao()` é o primeiro laço com prazo dentro de `start()`, e
isso expôs uma dublagem incompleta em duas suítes:

- `test_mensagem_global.py` troca o `time` do módulo por um relógio falso que só
  avança em `.sleep()`, mas dublava `_interruptible_sleep` com `lambda: False` —
  sem avançar nada. `while time.monotonic() < fim` rodava **para sempre**. A
  dublagem agora avança o relógio falso, que era a intenção declarada no
  comentário dela; era uma armadilha esperando qualquer laço com prazo.
- `test_numeros.py` usa o relógio real (só neutraliza `time.sleep`), então a
  espera custava dezenas de segundos de verdade em cada teste que chama
  `start()`. Ali `_aguardar_sincronizacao` é dublada — o comportamento dela tem
  cobertura própria em `tests/test_sync_inicial.py`.

`tests/test_contact_update.js` também estava quebrado, de antes destas mudanças:
o `fakeRow` não tinha `classList`, que `applyRowColor()` usa. Como é o teste que
garante que um evento não marca a linha errada, valia consertar o stub.

Os testes que exercitam `POST /config` passaram a apontar `CONFIG_FILE` para um
arquivo temporário — sem isso sobrescreviam a configuração real em
`uploads/config.json`, que agora persiste de verdade.

## 2026-08-19 (reenvio duplicado após queda da conexão SSE)

### Correção: mensagem reenviada para contatos já atendidos, após queda temporária da conexão em tempo real

Cliente reportou reenvio de mensagens para pessoas que já tinham recebido cerca de 1h antes. O `log.txt` mostrou a causa: a contagem de "enviados" salva pelo editor de contatos (`Contatos atualizados via editor: ... 25 enviados`) estava 13 mensagens atrasada em relação ao que o motor de envio já tinha realmente mandado (38), batendo exatamente com o total ao final da rodada anterior à última rodada completa.

A tabela de contatos no navegador só é sincronizada por eventos incrementais (`contact_update` via SSE) — não existe um "estado completo" enviado a cada atualização, como acontece com `status`. Quando a conexão SSE cai (rede instável, aba em segundo plano, notebook hibernou) e reconecta, os eventos perdidos durante a queda nunca são reenviados: a tabela local fica travada no estado de antes da queda, mesmo com o dashboard (`status`) voltando a mostrar os números certos. Se o usuário salvar os contatos nesse estado, `POST /contacts` sobrescreve a planilha inteira com base no que estava na tela — revertendo o `Enviado` de quem foi processado durante a janela sem conexão. Na rodada seguinte esses contatos voltam a aparecer como pendentes e recebem a mensagem de novo.

Agora `connectSSE()` recarrega a tabela de contatos do servidor (`loadContacts()`) sempre que a conexão SSE é reestabelecida após uma queda — exceto se houver edições não salvas na tela, para não descartar o que o usuário estava digitando.

### Build: validação automática da planilha modelo

`build.bat` agora roda `validar_planilha_modelo.py` logo depois de gerar `uploads/contatos.xlsx` via `gerar_planilha_modelo.py`, e interrompe o build se a checagem falhar. Confirma que a planilha do executável distribuído sempre sai com exatamente 1 linha de teste (Mauricio / 19994229146), o placeholder `{nome}` presente na mensagem, e nenhuma coluna de controle preenchida — reforça em código o que já era uma regra manual, para não vazar dado real de cliente num build futuro.

## 2026-08-16 (segurança e aviso de atualização)

### Correção: servidor exposto na rede local (segurança)

O `launcher.py` — ponto de entrada do `.exe` distribuído — escutava em `0.0.0.0:8000`. Qualquer máquina na mesma rede Wi-Fi podia acessar a interface sem nenhuma autenticação: ver a lista de contatos com nomes e telefones, baixar a planilha, ler o log e disparar envios.

Agora escuta apenas em `127.0.0.1:8000`. O `app.py` já fazia isso no bloco `__main__` (usado durante desenvolvimento), mas o launcher tinha ficado com o bind antigo.

### Correção: aviso de atualização parava de funcionar na versão 1.10+

A comparação de versão era textual (`latest_tag > APP_VERSION`). Em ordem alfabética, `"1.10.0" > "1.9.0"` é falso — ou seja, a partir da 1.10 o usuário nunca seria notificado de que existe uma versão nova.

Agora usa `_parse_version()` que converte `"1.10.2"` em `(1, 10, 2)` para comparação numérica. Tolerante a formatos como `"1.4"`, sufixos como `-beta`, e tags ilegíveis (nesse caso não oferece atualização, em vez de comparar lixo). Adicionado `tests/test_versao.py` com 12 testes cobrindo o caso da regressão.

### Build: planilha modelo gerada automaticamente

O `build.bat` não copia mais a pasta `uploads/` local (que pode conter planilhas com dados reais). Em vez disso, chama `gerar_planilha_modelo.py` que sempre gera uma planilha limpa com um único contato de teste pendente. Evita vazar dados pessoais no distribuível.

## 2026-08-15 (correções de painel e ritmo)

### Correção: tooltip de "Inválidos" cortado e sem reset

O balão de detalhamento ficava dentro da sidebar, que tem `overflow-hidden` / `overflow-y-auto`, e tinha largura fixa de 224px: o texto era recortado nas laterais e no topo. Agora o balão vive fora da sidebar (filho direto do `<body>`, `position: fixed`) e é posicionado por JS, preso dentro da janela — nenhum contêiner pode cortá-lo. A largura acompanha o conteúdo (`w-max`, até 22rem) e os rótulos longos não quebram mais.

Além disso, o detalhamento e o número do card agora vêm da **mesma fonte**. Antes o número grande era do envio atual (backend) e o detalhamento era contado da planilha inteira, então eles se contradiziam: card "0", tooltip listando inválidos de envios antigos. Agora:

- **Detalhamento**: motivos deste envio, vindos do backend (`invalid_motivos` no `/status`). Zera a cada novo envio e sobrevive a recarregar a página no meio do envio.
- **Histórico**: bloco separado no fim do balão com o que está gravado na planilha (inválidos e duplicados), sem reset.

Nada é perdido: os badges das linhas, as colunas `Invalido`/`Motivo` da planilha e o `log.txt` continuam guardando o histórico completo.

### Correção: "Pendentes" mostrava a planilha inteira em vez do que foi pedido

Escolher 5 mensagens e iniciar mostrava no painel os pendentes de toda a planilha (ex.: 200). O `total_msgs` só era usado para calcular o ritmo, nunca para limitar o contador.

Agora o envio tem uma **meta de sessão** = `min(mensagens pedidas, pendentes reais)`, publicada como `session_target` no `/status`. "Pendentes" passa a ser o que falta para cumprir essa meta (pediu 5 → começa em 5 e desce até 0), e a barra de progresso usa a meta como total.

### Correção: rajadas não ocupavam o tempo configurado

5 mensagens em 20 minutos terminavam muito antes do previsto. Três causas:

1. **Qualquer total de até 8 mensagens virava uma única rajada** com intervalo fixo entre as mensagens — ou seja, um metrônomo, exatamente o que o modo rajada deveria evitar.
2. **O plano era calculado antes de saber os pendentes**, usando o número configurado. Planejar para 10 e ter só 5 pendentes fazia o ritmo ser dimensionado para 10 e o envio acabar na metade da janela.
3. **Contato inválido consumia vaga da rajada.** O laço era `for msg_in_burst in range(burst_size)` com `burst_size += 1` nas falhas — mas incrementar a variável não estende um `range` já criado. Rajada com inválidos enviava menos mensagens do que o plano previa.

Agora o planejador sempre gera **rajadas irregulares** (5 msgs em 20 min → algo como 2 + 1 + 2, com pausas de vários minutos entre elas), o plano é gerado **depois** da deduplicação usando a meta real, e o laço conta mensagens **efetivamente enviadas** — inválido não gasta vaga, o próximo contato assume o lugar.

O tempo total do plano fecha a janela configurada: a soma dos intervalos internos das rajadas mais as pausas entre elas é igual ao tempo escolhido. O tempo de envio em si (abrir conversa, digitar, anexar) não é descontado, então o total real fica ligeiramente **acima** do configurado — nunca abaixo. O piso de 15s entre mensagens continua valendo; quando o tempo pedido é curto demais para tantas mensagens, o piso prevalece (a tela já avisa "Ritmo muito rápido").

### Correção: painel dizia "Enviando" durante as pausas entre rajadas

O estado `pausado` era usado apenas para a espera de horário comercial. Durante uma pausa longa de rajada o painel seguia dizendo "Enviando", parecendo travamento. Agora a pausa entre rajadas marca `pausado` e o painel mostra "Aguardando próxima rajada", com quantas mensagens ainda faltam.

### Correção: categorização de motivos no detalhamento

- `Falha no anexo: arquivo não encontrado` era classificado como "Não encontrado no WhatsApp", porque a checagem de "não encontrado" vinha antes da de "anexo".
- `Número rejeitado pelo WhatsApp (inexistente ou inválido)` caía em "Outros".
- Contato invalidado sem motivo registrado caía em "Outros" em vez de "Sem detalhes".

### Correção: aviso de ritmo na tela contava intervalos errado

A estimativa dividia o tempo por `totalMsgs` em vez de `totalMsgs - 1` (5 mensagens têm 4 esperas entre elas), então o aviso "Ritmo muito rápido" aparecia em momento diferente do limite real aplicado pelo backend. Os dois cálculos agora batem.

### Nota: tooltip do cabeçalho da coluna Status

A entrada abaixo descreve um `?` no cabeçalho "Status" da tabela. Esse elemento não existe no HTML — só sobrou o JS que tentava preenchê-lo (`status-th-tooltip-content` / `status-th-tooltip-total`), agora removido. O detalhamento segue disponível no card "Inválidos" da sidebar.

## 2026-08-15

### Novo: Tooltip de inválidos no cabeçalho da coluna Status

O cabeçalho "Status" da tabela de contatos ganhou um ícone `?`. Ao passar o mouse, exibe o total de inválidos desta sessão e o detalhamento por categoria (número bloqueado, inválido, duplicado, falha no anexo, etc.).

### Novo: Coloração de fundo nas linhas inválidas da tabela

Cada categoria de inválido tem uma cor de fundo distinta na linha da tabela:

| Categoria | Cor |
|---|---|
| Número bloqueado | Rosa (`bg-rose-50`) |
| Número inválido / ausente | Laranja (`bg-orange-50`) |
| Mensagem vazia | Âmbar (`bg-amber-50`) |
| Número duplicado | Amarelo (`bg-yellow-50`) |
| Não encontrado no WhatsApp | Vermelho (`bg-red-50`) |
| Falha no anexo | Pink (`bg-pink-50`) |
| Falha no envio | Fúcsia (`bg-fuchsia-50`) |

A cor é aplicada em tempo real via SSE e removida ao usar o botão de reenvio.

### Correção: Status resetados corretamente ao iniciar novo envio

Ao clicar "Iniciar Envio":
- Contatos já **enviados** mantêm o badge "Enviado" (sender os pula via `[SKIP]`)
- Contatos **inválidos** mantêm o badge "Inválido" (só o botão ↺ individual limpa)
- Contatos **duplicados** mantêm o badge "Duplicado"
- Contadores da sidebar refletem o estado real da planilha

### Correção: Duplicados não contam como inválidos

Duplicados são uma categoria separada e não entram na contagem de "Inválidos" em nenhum lugar: sidebar, barra inferior da tabela, tooltip e contador do sender. O badge continua mostrando "Duplicado" (laranja), não "Inválido".

### Correção: Duplicado que já foi enviado bloqueia pendentes com o mesmo número

O sender agora registra os números já enviados antes de varrer os pendentes. Um contato pendente com o mesmo número de um já-enviado é marcado como duplicado e ignorado, evitando envio duplicado entre sessões.

### Correção: Botão "Iniciar Envio" travado após finalização rápida

Quando o backend finalizava rapidamente (ex.: nenhum pendente), o botão "Iniciar Envio" ficava desabilitado e só voltava após F5. Corrigido: qualquer estado não-ativo (`finalizado`, `parado`, `erro`) reseta os flags de controle e reabilita o botão via SSE.

### Novo: Verificação de pendentes antes de abrir o browser

Ao clicar "Iniciar Envio" com todos os contatos já processados, o sistema agora detecta isso antes de abrir o Chrome e retorna imediatamente com a mensagem "Todos os contatos já foram processados!", sem abrir e fechar o navegador desnecessariamente.

### Novo: Contagem de inválidos por sessão

O contador "Inválidos" na sidebar agora mostra apenas os inválidos ocorridos **nesta sessão de envio**, não o acumulado histórico da planilha. Ao iniciar um novo envio, o contador zera e cresce apenas com as falhas da rodada atual.

### Novo: Módulo `contact_logic.py` e testes unitários

A lógica pura de contatos (normalização de número, validação, deduplicação) foi extraída para `contact_logic.py`, sem dependência de Selenium. Isso permite testes isolados sem browser.

Adicionados 35 testes unitários em `tests/test_deduplication.py` cobrindo:
- `clean_number`: float do Excel, DDI 55, formatação, vazio, nan
- `validate_contact`: número ausente/curto, mensagem vazia
- `get_pending_contacts`: exclusão de enviados, inválidos, df vazio
- Deduplicação entre pendentes: 2º e 3º duplicado marcados, SSE emitido
- **Bug corrigido**: pendente com número igual a já-enviado é bloqueado
- `allow_duplicates=True`: reabilita duplicados anteriores, não toca outros inválidos

## 2026-08-14

### Novo: Detecção de número bloqueado/inválido via popup do WhatsApp

Antes, quando um número estava bloqueado ou não existia no WhatsApp, o sistema esperava 20 segundos pelo timeout e mostrava uma mensagem genérica ("timeout ao abrir conversa"). Agora o sistema detecta os dois cenários em tempo real:

**Número inválido/inexistente**: detecta o popup de erro do WhatsApp Web ("número de telefone compartilhado por meio de URL é inválido") em ~2-3s.
- Log: `❌ Fulano (19999...) — número rejeitado pelo WhatsApp (inexistente ou inválido).`

**Contato bloqueado**: detecta que a conversa abriu mas com botões "Desbloquear"/"Apagar conversa" em vez do campo de digitação.
- Log: `🚫 Fulano (19999...) — contato bloqueado no seu WhatsApp. Desbloqueie para enviar.`

Em ambos os casos:
- Detecção rápida (~2-3s em vez de 20s de timeout)
- Tooltip específico na tabela de contatos
- Popup é fechado automaticamente e o envio segue para o próximo contato

## 2026-08-10

### Novo: Cores e tooltip no log para contatos inválidos/falha

Cada tipo de problema no log agora tem sua própria cor, para distinguir os casos batendo o olho:

| Cor | Classe | Quando aparece |
|---|---|---|
| 🟠 Laranja | `log-sheet` | Dado errado na planilha (mensagem vazia, número ausente, número curto) |
| 🔴 Vermelho | `log-nowhats` | Número não encontrado no WhatsApp (timeout) |
| 🩷 Rosa | `log-giveup` | Contato abandonado após N falhas (atingiu limite de tentativas) |
| 🟡 Âmbar | `log-retry` | Falha ao enviar, mas será tentado novamente na próxima rodada |
| 🔵 Azul | `log-tech` | Erro técnico inesperado |
| ⚪ Cinza | `log-skipped` | Contato já inválido de execução anterior (`[SKIP]`) |

Ao passar o mouse sobre a linha, aparece um tooltip com:
- O motivo completo da falha
- O que o usuário pode fazer para resolver

Linhas normais (envio, sucesso, rodada, `[SKIP] já enviado`) continuam sem tooltip.

### Novo: Orçamento de digitação proporcional ao tamanho do texto

O modo "comportamento humano" tinha orçamento fixo de 25 s para a digitação caractere a caractere. Mensagens longas (mensagem global, por exemplo) estouravam o limite no meio — o restante era colado de uma vez e o cliente percebia que "o modo humano não estava funcionando".

Agora o orçamento cresce com o texto:

```
orçamento = base + segundos_por_caractere × len(texto)   (com teto)
```

Padrão: base 25 s, +0,05 s/char, teto 180 s. Configurável via `human_type_max_seconds`, `human_type_seconds_per_char`, `human_type_budget_cap`.

### Novo: Mensagem global identificada no log de envio

A linha de log agora informa quando o texto usado é a mensagem global (contato sem mensagem própria):

```
Enviando para Ana (11999998888) [mensagem global]...
```

### Novo: Log de diagnóstico com texto exato e regra de nome

O arquivo de log (`log.txt`) passa a registrar para cada contato:
- O texto **exato** que será enviado (truncado em 300 chars)
- A regra de substituição de nome aplicada (`{nome}`, prefixo, ou texto puro)
- O modo de digitação (humanizado ou rápido)

Permite resolver relatos do tipo "enviou o nome errado" sem precisar reproduzir.

### Novo: Refatoração de `_format_texto` como método estático

Extrai a lógica de montagem do texto (`{nome}`, prefixo, texto puro) para um método separado `_format_texto()`, com documentação clara das regras e devolução da `regra` como string de diagnóstico. Testável independentemente.

### Novo: Procedência da planilha

O sistema agora registra de onde veio a planilha em uso:
- `upload` — enviada pelo botão de upload
- `editor` — salva pela tabela da tela (Ctrl+S)
- `restaurada` — cópia da sessão anterior (`uploads/contatos.xlsx` já existia)

Informado no:
- Log da tela ao iniciar o envio
- `log.txt` de arquivo
- Aviso na tela ao restaurar sessão anterior ("Se você editou o .xlsx no computador, faça o upload novamente para valer")
- Endpoint `/status` → campo `excel_info`

### Novo: Auto-save de configuração

Toda alteração nos inputs de configuração (mensagens/rodada, intervalos, delays, horário comercial, comportamento humano) agora sincroniza com o servidor automaticamente ao mudar o valor. Antes, alterar "Comportamento humano" e clicar "Iniciar" podia rodar com o valor antigo (padrão OFF).

O botão "Salvar Config" continua funcionando como ação manual explícita.

### Correção: Envio não inicia se config falhar ao salvar

Se o `saveConfig` falhar antes de iniciar o envio (ex: servidor offline momentaneamente), o envio é cancelado com mensagem de erro, em vez de prosseguir com a config possivelmente desatualizada.

### Testes

- `tests/test_log_tooltip.js` — valida cor, tooltip e fiação do `addLogEntry` para cada tipo de problema (20 cenários)
- `tests/test_contact_update.js` — continua passando (nenhuma regressão)
