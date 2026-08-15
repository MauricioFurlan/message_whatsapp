# Changelog

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
