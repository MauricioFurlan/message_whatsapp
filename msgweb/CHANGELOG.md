# Changelog

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

### Novo: Imagem enviada como foto (não figurinha)

Commit `f9115b9`: imagens são enviadas em tamanho grande em vez de como sticker/figurinha.

### Testes

- `tests/test_log_tooltip.js` — valida cor, tooltip e fiação do `addLogEntry` para cada tipo de problema (20 cenários)
- `tests/test_contact_update.js` — continua passando (nenhuma regressão)
