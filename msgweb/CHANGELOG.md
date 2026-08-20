# Changelog

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
