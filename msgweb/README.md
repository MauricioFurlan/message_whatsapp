# WhatsApp Automação Web

Interface web para envio automatizado de mensagens via WhatsApp Web usando Selenium.

## 🚀 Como Executar

### 1. Instalar dependências

```bash
cd msgweb
pip install -r requirements.txt
```

### 2. Iniciar o servidor

```bash
python -m uvicorn app:app --reload
```

### 3. Abrir no navegador

Acesse: **http://localhost:8000**

## 📋 Como Usar

1. **Upload da Planilha** — Selecione seu arquivo `.xlsx` com as colunas:
   - `Pessoa` — Nome do contato
   - `Número` — Telefone com DDD (ex: 11999998888)
   - `Mensagem` — Texto personalizado para cada contato

2. **Configurar** — Ajuste os parâmetros de envio:
   - Mensagens por rodada (quantas mensagens antes de pausar)
   - Total de rodadas
   - Intervalo entre rodadas (minutos)
   - Horário comercial (início e fim)

3. **Iniciar Envio** — Clique no botão "Iniciar Envio"
   - Um navegador Chrome será aberto automaticamente
   - Escaneie o QR Code do WhatsApp Web
   - O envio começa automaticamente após o login

4. **Acompanhar** — Monitore o progresso em tempo real no painel de status e no log

## ⚠️ Importante

- O Chrome precisa estar instalado no computador
- O ChromeDriver é baixado automaticamente via `webdriver-manager`
- A planilha é atualizada a cada mensagem enviada (coluna `Enviado`)
- Números inválidos são marcados na coluna `Invalido`
- Respeita horário comercial (dias úteis, horário configurado)
- Delay aleatório de 15-30s entre mensagens para evitar bloqueio

## 📁 Estrutura

```
msgweb/
├── app.py                 # Backend FastAPI
├── whatsapp_sender.py     # Módulo de envio (Selenium)
├── requirements.txt       # Dependências
├── README.md              # Este arquivo
├── static/
│   └── index.html         # Frontend (Tailwind CSS)
├── uploads/               # Planilhas enviadas (criado automaticamente)
└── chrome_profile/        # Perfil Chrome (mantém sessão WhatsApp)
```

## 🧪 Testes

```bash
venv\Scripts\python.exe -m unittest test_numeros test_mensagem_global test_app_estado -v
```

- `test_numeros.py` — números da planilha, digitação humanizada, cota das rodadas, anexos
- `test_mensagem_global.py` — montagem do texto ({nome}, prefixo), mensagem global, comportamento humano, orçamento de digitação
- `test_app_estado.py` — procedência da planilha, deduplicação do upload, configuração que chega ao sender

```bash
node tests/test_contact_update.js
node tests/test_log_tooltip.js
```

- `tests/test_contact_update.js` — status do contato na tabela via SSE (identificação por linha)
- `tests/test_log_tooltip.js` — cor e tooltip de cada tipo de contato inválido/falha no log

## 🛑 Parar Envio

Clique em "Parar Envio" para interromper graciosamente. O sistema finaliza a mensagem atual e para. O progresso é salvo na planilha.
