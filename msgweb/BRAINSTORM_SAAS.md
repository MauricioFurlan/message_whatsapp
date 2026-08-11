# Brainstorm: WhatsApp Sender como Serviço (SaaS)

> Data: 19/07/2026  
> Status: Planejamento inicial

---

## 📌 Sistema Atual

- App FastAPI local que recebe planilha Excel com (Pessoa, Número, Mensagem)
- Selenium abre Chrome, usuário escaneia QR Code do WhatsApp Web
- Envia mensagens com delays aleatórios, respeitando horário comercial e rodadas configuráveis
- Tudo roda na máquina do usuário

## 🎯 Objetivo

Transformar em um serviço multi-tenant onde:
- Cliente faz login, escaneia QR Code remotamente
- Selenium roda em máquina na AWS
- Números de telefone **não são armazenados** (requisito de privacidade)
- Custo mínimo enquanto não há clientes

---

## 🏗️ Arquitetura Proposta

### Camada 1: Frontend + Auth

| Serviço | Função |
|---------|--------|
| S3 + CloudFront | Hospedagem do frontend estático |
| Cognito | Login/senha (free tier: 50k MAU) |

### Camada 2: API + Orquestração

| Serviço | Função |
|---------|--------|
| API Gateway | Endpoints REST |
| Lambda | Lógica leve (upload, status, config) |
| S3 | Armazena planilha temporária (lifecycle 24h) |

### Camada 3: Fila de Jobs

| Serviço | Função |
|---------|--------|
| SQS | Fila de jobs de envio |

> **Decisão**: Colocar um **job** na fila (referência ao arquivo no S3), não números individuais. Isso evita que números fiquem persistidos na fila (SQS retém mensagens até 14 dias).

### Camada 4: Worker (Selenium)

| Opção | Prós | Contras | Custo ociosa |
|-------|------|---------|--------------|
| EC2 t3.small | Simples, multi-cliente | Paga sem uso | ~$15/mês |
| ECS Fargate | Paga só quando roda | Cold start | $0 parado |
| EC2 Spot | Barato | Pode ser interrompido | ~$5/mês |

**Recomendação inicial**: EC2 t3.small com auto-stop quando não tem jobs.

### Camada 5: Sessão WhatsApp (QR Code)

Fluxo:
1. Cliente faz login no site
2. Inicia sessão → backend sobe Chrome (ou reaproveita existente)
3. Captura screenshot do QR Code via Selenium → envia pro frontend (WebSocket ou polling)
4. Cliente escaneia no celular
5. Sessão fica ativa no `chrome_profile` do servidor (um profile por cliente)
6. Profile armazenado em EBS ou EFS (persiste entre reinícios)

---

## 🔄 Fluxo Completo

```
Cliente → Login (Cognito)
       → Upload planilha → S3 (TTL 24h)
       → Configura envio → API Gateway/Lambda → SQS (job)
       → Escaneia QR → WebSocket → Screenshot do Chrome no EC2

Worker EC2:
       → Consome job do SQS
       → Lê planilha do S3
       → Envia mensagens via Selenium
       → Atualiza status no DynamoDB
       → Deleta planilha do S3 ao concluir
```

---

## 💰 Custo Estimado (0 a 5 clientes)

| Serviço | Custo/mês |
|---------|-----------|
| S3 + CloudFront | < $1 |
| Cognito | $0 (free tier) |
| API Gateway + Lambda | < $1 |
| SQS | $0 (free tier: 1M requests) |
| DynamoDB | $0 (free tier: 25GB) |
| EC2 t3.small | ~$15 (ou $0 se desligado) |
| **Total** | **~$15-17/mês** |

---

## ❌ O que NÃO usar

- **EKS/Kubernetes** — overkill pra esse cenário
- **Lambda para Selenium** — não funciona (precisa de browser persistente)
- **Armazenar números em banco** — viola requisito de privacidade

---

## 📋 Plano de Implementação (Fases)

### Fase 1: MVP (menor custo possível)
- [ ] Subir app atual numa EC2 com Nginx + HTTPS
- [ ] Adicionar autenticação básica (pode ser simples no início)
- [ ] Testar fluxo de QR Code remoto (screenshot → frontend)

### Fase 2: Separação de responsabilidades
- [ ] Frontend estático no S3 + CloudFront
- [ ] Adicionar Cognito para auth
- [ ] Implementar SQS para fila de jobs
- [ ] Lifecycle policy no S3 para deletar planilhas em 24h

### Fase 3: Escalabilidade
- [ ] Um container/profile por cliente
- [ ] Migrar worker para ECS Fargate (paga sob demanda)
- [ ] Dashboard com histórico de envios (DynamoDB)
- [ ] Auto-stop EC2 quando sem jobs

---

## 💡 Notas e Decisões Futuras

- Avaliar se vale usar a API oficial do WhatsApp Business (custo por mensagem, mas sem Selenium)
- Pensar em limites por plano (ex: plano free = 100 msgs/dia)
- Considerar multi-região se tiver clientes fora do Brasil
- Monitoramento: CloudWatch para alertas de falha no envio
