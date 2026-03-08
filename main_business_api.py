"""
WhatsApp Business Cloud API - Automação Oficial
================================================

VANTAGENS:
- Sem risco de banimento
- Mais rápido (sem browser)
- Escalável (milhares de mensagens)
- Templates pré-aprovados pela Meta
- Webhooks para respostas
- Suporte oficial

REQUISITOS:
1. Criar conta Meta for Developers: https://developers.facebook.com/
2. Criar um app WhatsApp Business
3. Obter: Phone Number ID, WhatsApp Business Account ID, Access Token
4. Verificar seu número de telefone comercial
5. Criar e aprovar templates de mensagem

CUSTOS:
- 1000 conversas gratuitas por mês
- Depois: varia por país (~R$0,30 por conversa)

INSTALAÇÃO:
pip install requests pandas openpyxl python-dotenv
"""

import requests
import pandas as pd
import time
from datetime import datetime
from typing import Dict, Optional
import os
from dotenv import load_dotenv

# Carrega variáveis de ambiente do arquivo .env
load_dotenv()

# Configurações da API (NUNCA commitar essas informações!)
WHATSAPP_TOKEN = os.getenv('WHATSAPP_TOKEN', 'seu_token_aqui')
PHONE_NUMBER_ID = os.getenv('PHONE_NUMBER_ID', 'seu_phone_number_id_aqui')
WHATSAPP_API_URL = f"https://graph.facebook.com/v18.0/{PHONE_NUMBER_ID}/messages"
WHATSAPP_VERSION = "v18.0"

def normalize_flag_column(series):
    """Normaliza colunas de flag para X ou vazio"""
    if series.dtype == "bool":
        return series.map(lambda value: "X" if value else "")
    normalized = series.fillna("").astype(str).str.strip().str.upper()
    return normalized.map(lambda value: "X" if value in {"X", "TRUE", "1"} else "")

def format_phone_number(numero: str) -> str:

    numero_limpo = ''.join(filter(str.isdigit, str(numero)))
    if not numero_limpo.startswith('55'):
        numero_limpo = '55' + numero_limpo
    
    return numero_limpo

def send_template_message(to: str, template_name: str, language: str = "pt_BR", 
                         parameters: Optional[list] = None) -> Dict:
    """
    Envia mensagem usando template aprovado pela Meta
    
    Args:
        to: Número no formato internacional (ex: 5511987654321)
        template_name: Nome do template aprovado
        language: Código do idioma (pt_BR, en_US, etc)
        parameters: Lista de parâmetros para substituir no template
    
    Returns:
        Resposta da API com status do envio
    """
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }
    
    components = []
    if parameters:
        components.append({
            "type": "body",
            "parameters": [{"type": "text", "text": param} for param in parameters]
        })
    
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {
                "code": language
            }
        }
    }
    
    if components:
        payload["template"]["components"] = components
    
    try:
        response = requests.post(WHATSAPP_API_URL, headers=headers, json=payload, timeout=10)
        return {
            "success": response.status_code == 200,
            "status_code": response.status_code,
            "response": response.json()
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }

def send_text_message(to: str, message: str) -> Dict:
    """
    Envia mensagem de texto simples (apenas para conversas já iniciadas)
    
    Nota: Mensagens de texto diretas só funcionam em conversas ativas nas últimas 24h
    Para novos contatos, use send_template_message com template aprovado
    """
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {
            "body": message
        }
    }
    
    try:
        response = requests.post(WHATSAPP_API_URL, headers=headers, json=payload, timeout=10)
        return {
            "success": response.status_code == 200,
            "status_code": response.status_code,
            "response": response.json()
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }

def main():
    """Processa envio de mensagens usando WhatsApp Business API"""
    
    # Carrega planilha
    try:
        contatos_df = pd.read_excel("contatos.xlsx")
    except FileNotFoundError:
        print("Erro: arquivo contatos.xlsx não encontrado!")
        return
    
    # Inicializa colunas de controle
    if "Enviado" not in contatos_df.columns:
        contatos_df["Enviado"] = ""
    if "DataEnvio" not in contatos_df.columns:
        contatos_df["DataEnvio"] = ""
    if "Invalido" not in contatos_df.columns:
        contatos_df["Invalido"] = ""
    
    contatos_df["Enviado"] = normalize_flag_column(contatos_df["Enviado"])
    contatos_df["Invalido"] = normalize_flag_column(contatos_df["Invalido"])
    contatos_df["DataEnvio"] = contatos_df["DataEnvio"].fillna("").astype(str)
    
    # Limite de mensagens por execução (pode ser maior que Selenium)
    LIMITE_MENSAGENS_POR_EXECUCAO = 50
    
    # Nome do template aprovado pela Meta (você precisa criar e aprovar primeiro)
    # Exemplo de template: "Olá {{1}}, {{2}}"
    TEMPLATE_NAME = "nome_do_seu_template"
    
    mensagens_enviadas = 0
    
    print(f"Iniciando envio via WhatsApp Business API...")
    print(f"Token configurado: {'Sim' if WHATSAPP_TOKEN != 'seu_token_aqui' else 'NÃO - Configure o .env'}")
    print(f"Phone ID configurado: {'Sim' if PHONE_NUMBER_ID != 'seu_phone_number_id_aqui' else 'NÃO - Configure o .env'}")
    print("-" * 50)
    
    for i, row in contatos_df.iterrows():
        # Pula mensagens já enviadas ou números inválidos
        enviado = str(row.get("Enviado") or "").strip().upper() == "X"
        invalido = str(row.get("Invalido") or "").strip().upper() == "X"
        
        if enviado or invalido:
            continue
        
        # Verifica limite
        if mensagens_enviadas >= LIMITE_MENSAGENS_POR_EXECUCAO:
            print(f"\nLimite de {LIMITE_MENSAGENS_POR_EXECUCAO} mensagens atingido.")
            print("Execute novamente para continuar.")
            break
        
        pessoa = row["Pessoa"]
        numero = row["Número"]
        mensagem = row["Mensagem"]
        
        # Formata número para padrão internacional
        numero_formatado = format_phone_number(numero)
        
        print(f"\nEnviando para {pessoa} ({numero_formatado})...")
        
        # Envia usando template (recomendado para novos contatos)
        # Os parâmetros substituem {{1}}, {{2}}, etc no template
        resultado = send_template_message(
            to=numero_formatado,
            template_name=TEMPLATE_NAME,
            language="pt_BR",
            parameters=[pessoa, mensagem]  # Substitui variáveis do template
        )
        
        # Alternativa: enviar mensagem direta (apenas para conversas ativas)
        # resultado = send_text_message(
        #     to=numero_formatado,
        #     message=f"Oi {pessoa}, {mensagem}"
        # )
        
        if resultado.get("success"):
            print(f"✓ Enviado com sucesso!")
            contatos_df.at[i, "Enviado"] = "X"
            contatos_df.at[i, "DataEnvio"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            contatos_df.at[i, "Invalido"] = ""
            mensagens_enviadas += 1
        else:
            print(f"✗ Erro ao enviar: {resultado.get('error', resultado.get('response'))}")
            # Marca como inválido se erro 400/404 (número não existe)
            if resultado.get("status_code") in [400, 404]:
                contatos_df.at[i, "Invalido"] = "X"
            contatos_df.at[i, "Enviado"] = ""
            contatos_df.at[i, "DataEnvio"] = ""
        
        # Salva progresso
        contatos_df.to_excel("contatos.xlsx", index=False)
        
        # Pequeno intervalo (API suporta muito mais que Selenium)
        time.sleep(2)
    
    print(f"\n{'='*50}")
    print(f"Finalizado! {mensagens_enviadas} mensagens enviadas.")
    print(f"{'='*50}")

if __name__ == "__main__":
    # Verifica configuração antes de executar
    if WHATSAPP_TOKEN == 'seu_token_aqui' or PHONE_NUMBER_ID == 'seu_phone_number_id_aqui':
        print("⚠️  ATENÇÃO: Configure as credenciais antes de usar!")
        print("\nPasso a passo:")
        print("1. Acesse: https://developers.facebook.com/")
        print("2. Crie um app WhatsApp Business")
        print("3. Obtenha Token e Phone Number ID")
        print("4. Crie arquivo .env com:")
        print("   WHATSAPP_TOKEN=seu_token_aqui")
        print("   PHONE_NUMBER_ID=seu_id_aqui")
        print("5. Crie e aprove templates de mensagem no Meta Business")
        print("\nDocumentação: https://developers.facebook.com/docs/whatsapp/cloud-api/")
    else:
        main()
