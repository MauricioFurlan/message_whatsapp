# WhatsApp Automação - Comparação

## 📁 Arquivos

### `main.py` - Selenium (Atual)
- ✅ Funciona agora sem configuração complexa
- ✅ Gratuito
- ⚠️ Risco de banimento
- ⚠️ Lento (abre navegador)
- ⚠️ Limite de ~15 mensagens por execução

### `main_business_api.py` - API Oficial
- ✅ **SEM risco de banimento**
- ✅ Muito mais rápido
- ✅ Escalável (milhares de mensagens)
- ✅ Suporte oficial da Meta
- ⚠️ Requer configuração inicial complexa
- ⚠️ Custo após 1000 mensagens/mês

---

## 🚀 Como Usar a API Oficial (Business API)

### 1. Criar Conta e App

1. Acesse: https://developers.facebook.com/
2. Faça login com sua conta Facebook/Meta
3. Vá em "Meus Apps" → "Criar App"
4. Escolha tipo: **Business**
5. Adicione produto: **WhatsApp**

### 2. Configurar WhatsApp Business

1. No painel do app, vá em **WhatsApp** → **Início**
2. Adicione um número de telefone comercial
3. Verifique o número (receberá código via SMS)
4. Copie:
   - **Token de Acesso Temporário** (válido 24h)
   - **Phone Number ID**

### 3. Obter Token Permanente

Para produção, você precisa de um token permanente:

1. Vá em **WhatsApp** → **Configurações**
2. Configure um **Token de Acesso do Sistema** (não expira)
3. Ou use tokens com validade (recomendado para segurança)

### 4. Criar Templates de Mensagem

**IMPORTANTE:** Você NÃO pode enviar texto livre para novos contatos!
Precisa usar templates PRÉ-APROVADOS pela Meta.

1. Vá em **WhatsApp** → **Gerenciador de Mensagens**
2. Clique em "Criar Modelo"
3. Exemplo de template:

```
Nome: saudacao_cliente
Categoria: MARKETING
Idioma: Português (BR)

Conteúdo:
Olá {{1}}, {{2}}

Onde:
{{1}} = nome da pessoa
{{2}} = mensagem personalizada
```

4. Envie para aprovação (leva 24-48h)
5. Use o nome do template no código

### 5. Configurar o Código

1. Instale dependências:
```bash
pip install requests python-dotenv pandas openpyxl
```

2. Copie `.env.example` para `.env`:
```bash
copy .env.example .env
```

3. Edite `.env` com suas credenciais:
```
WHATSAPP_TOKEN=EAAxxxxxxxxxxxxx
PHONE_NUMBER_ID=123456789012345
```

4. No código `main_business_api.py`, atualize:
```python
TEMPLATE_NAME = "saudacao_cliente"  # Nome do seu template aprovado
```

### 6. Executar

```bash
python main_business_api.py
```

---

## 💰 Custos

### Estrutura de Preços (Brasil - 2026)

- **1.000 conversas gratuitas por mês**
- Após isso:
  - Conversas iniciadas por você: ~R$ 0,30 cada
  - Conversas iniciadas pelo cliente: ~R$ 0,15 cada
  - Janela de 24h (pode trocar várias mensagens no período)

**Exemplo:** 
- 50 clientes × R$ 0,30 = R$ 15,00/mês
- Você só paga quando INICIA a conversa

Preços atualizados: https://developers.facebook.com/docs/whatsapp/pricing

---

## 🔒 Segurança

### ⚠️ NUNCA:
- Commitar arquivo `.env` no Git
- Compartilhar seu token
- Expor credenciais em código público

### ✅ Adicione ao `.gitignore`:
```
.env
*.pyc
__pycache__/
venv/
```

---

## 📊 Qual Escolher?

### Use `main.py` (Selenium) se:
- Está testando/aprendendo
- Menos de 20 contatos
- Não tem orçamento
- Não precisa de velocidade

### Use `main_business_api.py` (API Oficial) se:
- É uma empresa/profissional
- Precisa enviar muitas mensagens
- Quer confiabilidade e suporte
- Pode investir ~R$ 15-50/mês
- Precisa de features avançadas (botões, mídias, webhooks)

---

## 🆘 Suporte

- Documentação oficial: https://developers.facebook.com/docs/whatsapp/cloud-api/
- Fórum de desenvolvedores: https://developers.facebook.com/community/
- Status da API: https://developers.facebook.com/status/

---

## 📝 Notas Importantes

1. **Templates são obrigatórios** para mensagens proativas (primeiro contato)
2. Após o cliente responder, você tem **24h de janela** para enviar mensagens livres
3. A Meta revisa e pode rejeitar templates com:
   - Conteúdo promocional agressivo
   - Links suspeitos
   - Informações enganosas
4. Categorias de template:
   - **MARKETING**: Promoções, ofertas
   - **UTILITY**: Confirmações, lembretes, atualizações
   - **AUTHENTICATION**: Códigos de verificação (OTP)
