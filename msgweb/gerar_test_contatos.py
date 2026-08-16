"""
Script para gerar a planilha test_contatos.xlsx com casos de teste abrangentes.

Cobre todos os cenários do sistema:
- Mensagem com/sem interpolação {nome}
- Com/sem anexo (imagem, PDF, múltiplos)
- Ausência de telefone, nome, mensagem
- Números em diversos formatos
- Casos edge (nan, None, espaços, float)
- Arquivo inexistente
- Mensagem com formatação WhatsApp
- Mensagem com quebra de linha
- Mensagem com link
"""

import pandas as pd
from pathlib import Path

# Caminhos dos arquivos de teste de mídia (relativos ao diretório do projeto)
MEDIA_DIR = "test_media"
IMG_PNG = f"{MEDIA_DIR}/teste_azul.png"
IMG_JPG = f"{MEDIA_DIR}/teste_vermelho.jpg"
IMG_GRANDE = f"{MEDIA_DIR}/teste_grande.png"
PDF_DOC = f"{MEDIA_DIR}/documento_teste.pdf"
ARQUIVO_INEXISTENTE = f"{MEDIA_DIR}/nao_existe.pdf"

contatos = [
    # =========================================================================
    # GRUPO 1: Mensagem com interpolação {nome}
    # =========================================================================
    {
        "Nome": "Carlos Silva",
        "Número": "19994229146",
        "Mensagem": "Olá {nome}, esta mensagem deve conter 'Carlos Silva' no lugar de {nome}.",
        "Arquivo": "",
    },
    {
        "Nome": "Ana",
        "Número": "19994229146",
        "Mensagem": "Oi {nome}! O {nome} deve aparecer duas vezes: 'Ana' e 'Ana'.",
        "Arquivo": "",
    },
    {
        "Nome": "  Pedro  ",
        "Número": "19994229146",
        "Mensagem": "Olá {nome}, os espaços ao redor do nome devem ser removidos. Deve aparecer 'Pedro'.",
        "Arquivo": "",
    },

    # =========================================================================
    # GRUPO 2: Mensagem SEM interpolação (texto puro)
    # =========================================================================
    {
        "Nome": "Maria",
        "Número": "19994229146",
        "Mensagem": "Esta mensagem não tem placeholder. O nome 'Maria' NÃO deve aparecer no texto enviado.",
        "Arquivo": "",
    },
    {
        "Nome": "João",
        "Número": "19994229146",
        "Mensagem": "Promoção válida até amanhã! Aproveite 50% de desconto. Texto deve chegar exatamente assim.",
        "Arquivo": "",
    },

    # =========================================================================
    # GRUPO 3: Nome ausente/vazio + {nome} na mensagem
    # =========================================================================
    {
        "Nome": "",
        "Número": "19994229146",
        "Mensagem": "Olá {nome}, o placeholder deve ficar vazio. Resultado esperado: 'Olá , o placeholder...'",
        "Arquivo": "",
    },
    {
        "Nome": "nan",
        "Número": "19994229146",
        "Mensagem": "Olá {nome}! Nome 'nan' do pandas deve ser tratado como vazio. Esperado: 'Olá !'",
        "Arquivo": "",
    },
    {
        "Nome": "None",
        "Número": "19994229146",
        "Mensagem": "Olá {nome}! Nome 'None' deve ser tratado como vazio. Esperado: 'Olá !'",
        "Arquivo": "",
    },

    # =========================================================================
    # GRUPO 4: Com ANEXO (imagem)
    # =========================================================================
    {
        "Nome": "Roberto",
        "Número": "19994229146",
        "Mensagem": "Mensagem com imagem PNG anexada. O texto deve ser enviado primeiro, depois a imagem.",
        "Arquivo": IMG_PNG,
    },
    {
        "Nome": "Fernanda",
        "Número": "19994229146",
        "Mensagem": "Mensagem com imagem JPG. O {nome} deve conter 'Fernanda'. Texto + imagem separados.",
        "Arquivo": IMG_JPG,
    },
    {
        "Nome": "Lucas",
        "Número": "19994229146",
        "Mensagem": "Imagem grande. Deve enviar texto primeiro e depois a imagem grande como foto inline.",
        "Arquivo": IMG_GRANDE,
    },

    # =========================================================================
    # GRUPO 5: Com ANEXO (PDF/documento)
    # =========================================================================
    {
        "Nome": "Juliana",
        "Número": "19994229146",
        "Mensagem": "Mensagem com PDF anexado. Texto enviado primeiro, depois o documento como arquivo.",
        "Arquivo": PDF_DOC,
    },
    {
        "Nome": "Rafael",
        "Número": "19994229146",
        "Mensagem": "Olá {nome}, segue o documento. Deve conter 'Rafael' e enviar o PDF após o texto.",
        "Arquivo": PDF_DOC,
    },

    # =========================================================================
    # GRUPO 6: MÚLTIPLOS anexos (separados por vírgula)
    # =========================================================================
    {
        "Nome": "Camila",
        "Número": "19994229146",
        "Mensagem": "Múltiplos anexos: PNG + PDF. Texto enviado primeiro, depois cada arquivo sequencialmente.",
        "Arquivo": f"{IMG_PNG}, {PDF_DOC}",
    },
    {
        "Nome": "Bruno",
        "Número": "19994229146",
        "Mensagem": "Três anexos: JPG + PNG + PDF. Todos devem ser enviados em sequência após o texto.",
        "Arquivo": f"{IMG_JPG}, {IMG_PNG}, {PDF_DOC}",
    },

    # =========================================================================
    # GRUPO 7: Arquivo INEXISTENTE
    # =========================================================================
    {
        "Nome": "Diana",
        "Número": "19994229146",
        "Mensagem": "Arquivo inexistente. Sistema deve avisar que não encontrou e enviar só o texto.",
        "Arquivo": ARQUIVO_INEXISTENTE,
    },
    {
        "Nome": "Gustavo",
        "Número": "19994229146",
        "Mensagem": "Um arquivo existe e outro não. Deve enviar texto + PNG, e avisar sobre o inexistente.",
        "Arquivo": f"{IMG_PNG}, {ARQUIVO_INEXISTENTE}",
    },

    # =========================================================================
    # GRUPO 8: NÚMERO ausente ou inválido (deve marcar como inválido)
    # =========================================================================
    {
        "Nome": "Sem Telefone",
        "Número": "",
        "Mensagem": "Este contato não tem número. Deve ser marcado como INVÁLIDO com motivo 'número ausente'.",
        "Arquivo": "",
    },
    {
        "Nome": "Numero Nan",
        "Número": "nan",
        "Mensagem": "Número 'nan' do pandas. Deve ser marcado como INVÁLIDO com motivo 'número ausente'.",
        "Arquivo": "",
    },
    {
        "Nome": "Numero Curto",
        "Número": "1234",
        "Mensagem": "Número com apenas 4 dígitos. Deve ser marcado como INVÁLIDO com motivo 'número inválido'.",
        "Arquivo": "",
    },
    {
        "Nome": "Numero 9 Digitos",
        "Número": "199945199",
        "Mensagem": "Número com 9 dígitos (falta 1). Deve ser marcado como INVÁLIDO com motivo 'número inválido'.",
        "Arquivo": "",
    },

    # =========================================================================
    # GRUPO 9: MENSAGEM ausente (deve marcar como inválido se não houver global)
    # =========================================================================
    {
        "Nome": "Sem Mensagem",
        "Número": "19994229146",
        "Mensagem": "",
        "Arquivo": "",
    },
    {
        "Nome": "Mensagem Nan",
        "Número": "19994229146",
        "Mensagem": "nan",
        "Arquivo": "",
    },
    {
        "Nome": "Mensagem None",
        "Número": "19994229146",
        "Mensagem": "None",
        "Arquivo": "",
    },

    # =========================================================================
    # GRUPO 10: Formatos de NÚMERO variados (todos válidos)
    # =========================================================================
    {
        "Nome": "Formato Parenteses",
        "Número": "(19)99422-9146",
        "Mensagem": "Número com parênteses e hífen. Deve normalizar para 19994229146.",
        "Arquivo": "",
    },
    {
        "Nome": "Formato Espacos",
        "Número": "19 99422 9146",
        "Mensagem": "Número com espaços. Deve normalizar para 19994229146.",
        "Arquivo": "",
    },
    {
        "Nome": "Formato Internacional",
        "Número": "+55 (19) 99422-9146",
        "Mensagem": "Número com +55. Deve remover o código de país e normalizar para 19994229146.",
        "Arquivo": "",
    },
    {
        "Nome": "Formato Codigo Pais Colado",
        "Número": "5519994229146",
        "Mensagem": "Número com 55 colado. Deve remover o código de país. Normaliza para 19994229146.",
        "Arquivo": "",
    },
    {
        "Nome": "Numero Float",
        "Número": 19994229146.0,
        "Mensagem": "Número como float (pandas). Deve remover o .0 e normalizar para 19994229146.",
        "Arquivo": "",
    },
    {
        "Nome": "DDD 55 RS",
        "Número": "55987654321",
        "Mensagem": "DDD 55 (Rio Grande do Sul) com 11 dígitos. NÃO deve remover o 55. Fica 55987654321.",
        "Arquivo": "",
    },

    # =========================================================================
    # GRUPO 11: Formatação WhatsApp no texto
    # =========================================================================
    {
        "Nome": "Teste Bold",
        "Número": "19994229146",
        "Mensagem": "Olá *{nome}*! O nome deve aparecer em *negrito* no WhatsApp. Esperado: *Teste Bold*.",
        "Arquivo": "",
    },
    {
        "Nome": "Teste Italico",
        "Número": "19994229146",
        "Mensagem": "Olá _{nome}_, o nome deve aparecer em _itálico_. Formatação preservada.",
        "Arquivo": "",
    },
    {
        "Nome": "Teste Riscado",
        "Número": "19994229146",
        "Mensagem": "Olá ~{nome}~, o nome deve aparecer ~riscado~. Formatação WhatsApp preservada.",
        "Arquivo": "",
    },
    {
        "Nome": "Teste Mono",
        "Número": "19994229146",
        "Mensagem": "Código: ```print('Olá {nome}')``` — deve manter a formatação monoespaçada.",
        "Arquivo": "",
    },

    # =========================================================================
    # GRUPO 12: Quebra de linha na mensagem
    # =========================================================================
    {
        "Nome": "Teste Quebra",
        "Número": "19994229146",
        "Mensagem": "Olá {nome}!\n\nEsta mensagem tem quebras de linha.\n- Item 1\n- Item 2\n\nDeve chegar com as quebras preservadas.",
        "Arquivo": "",
    },
    {
        "Nome": "Mensagem Longa",
        "Número": "19994229146",
        "Mensagem": "Olá {nome}!\n\nEsta é uma mensagem longa para testar o comportamento humano.\n\nQuando o modo humano está ativo, mensagens longas (>200 caracteres) devem ser digitadas palavra por palavra, não caractere por caractere.\n\nIsso simula o comportamento real de uma pessoa digitando no WhatsApp, evitando detecção de automação.\n\nO texto final deve conter 'Mensagem Longa' no lugar de {nome}.",
        "Arquivo": "",
    },

    # =========================================================================
    # GRUPO 13: Mensagem com LINK
    # =========================================================================
    {
        "Nome": "Teste Link",
        "Número": "19994229146",
        "Mensagem": "Olá {nome}! Veja nosso site: https://exemplo.com.br — o sistema deve aguardar o preview do link carregar antes de enviar.",
        "Arquivo": "",
    },
    {
        "Nome": "Link WWW",
        "Número": "19994229146",
        "Mensagem": "Confira: www.exemplo.com.br/promo — links com www também ativam o delay extra de preview.",
        "Arquivo": "",
    },

    # =========================================================================
    # GRUPO 14: Combinações especiais
    # =========================================================================
    {
        "Nome": "Combo Completo",
        "Número": "(19) 99422-9146",
        "Mensagem": "Olá *{nome}*!\n\nSegue o documento em anexo.\nQualquer dúvida: https://ajuda.exemplo.com\n\nAbraços!",
        "Arquivo": PDF_DOC,
    },
    {
        "Nome": "",
        "Número": "19994229146",
        "Mensagem": "Mensagem sem nome e com anexo. O {nome} deve ficar vazio. Texto + imagem enviados.",
        "Arquivo": IMG_JPG,
    },
    {
        "Nome": "Anexo Sem Msg",
        "Número": "19994229146",
        "Mensagem": "",
        "Arquivo": IMG_PNG,
    },

    # =========================================================================
    # GRUPO 15: Contato já enviado e já inválido (devem ser pulados)
    # =========================================================================
    {
        "Nome": "Ja Enviado",
        "Número": "19994229146",
        "Mensagem": "Este contato já foi marcado como enviado. Deve ser PULADO no próximo envio.",
        "Arquivo": "",
        "Enviado": "X",
        "DataEnvio": "2026-08-14 10:00:00",
    },
    {
        "Nome": "Ja Invalido",
        "Número": "19994229146",
        "Mensagem": "Este contato já foi marcado como inválido. Deve ser PULADO no próximo envio.",
        "Arquivo": "",
        "Invalido": "X",
        "Motivo": "Número não encontrado no WhatsApp (timeout ao abrir conversa).",
    },

    # =========================================================================
    # GRUPO 16: Sem nome E sem número (linha vazia — filtrada no save)
    # =========================================================================
    {
        "Nome": "",
        "Número": "",
        "Mensagem": "Linha sem nome e sem número. No upload é preservada, mas no /contacts POST é filtrada.",
        "Arquivo": "",
    },

    # =========================================================================
    # GRUPO 17: Emojis e emoticons (validação de caracteres especiais)
    # =========================================================================
    {
        "Nome": "Teste Emojis",
        "Número": "19994229146",
        "Mensagem": "Oi {nome}! 😀🎉🚀💪🔥✨👏❤️🙏😎\n\nTestando emojis variados:\n🌟 Estrela\n🎯 Alvo\n💡 Ideia\n🏆 Troféu\n📱 Celular\n✅ Check\n\nEmoticons clássicos: :) ;) :D XD <3 :P\n\nEmojis de bandeira: 🇧🇷🇺🇸🇪🇸\nFamília: 👨‍👩‍👧‍👦\nAnimais: 🐶🐱🦁🐸🦋\n\nSe tudo chegou certinho, o envio de emojis está OK! 🎊👍",
        "Arquivo": "",
    },

    # =========================================================================
    # GRUPO 18: Número duplicado (deduplicação no upload)
    # =========================================================================
    {
        "Nome": "Primeiro Duplicado",
        "Número": "19994229146",
        "Mensagem": "Número duplicado do Carlos Silva. No upload, este deve ser REMOVIDO (o primeiro vence).",
        "Arquivo": "",
    },
]

# Monta o DataFrame com todas as colunas que o sistema espera
colunas = ["Nome", "Número", "Mensagem", "Arquivo", "Enviado", "DataEnvio", "Invalido", "Motivo"]

rows = []
for c in contatos:
    rows.append({
        "Nome": c.get("Nome", ""),
        "Número": c.get("Número", ""),
        "Mensagem": c.get("Mensagem", ""),
        "Arquivo": c.get("Arquivo", ""),
        "Enviado": c.get("Enviado", ""),
        "DataEnvio": c.get("DataEnvio", ""),
        "Invalido": c.get("Invalido", ""),
        "Motivo": c.get("Motivo", ""),
    })

df = pd.DataFrame(rows, columns=colunas)

# Salva na pasta uploads/
output_path = Path("uploads") / "test_contatos.xlsx"
output_path.parent.mkdir(exist_ok=True)
df.to_excel(output_path, index=False)

print(f"✅ Planilha gerada com sucesso: {output_path}")
print(f"   Total de linhas: {len(df)}")
print(f"\nGrupos de teste:")
print(f"   1. Interpolação {{nome}} com nome presente (3 casos)")
print(f"   2. Texto puro sem interpolação (2 casos)")
print(f"   3. Nome ausente/vazio + {{nome}} (3 casos)")
print(f"   4. Anexo imagem PNG/JPG/Grande (3 casos)")
print(f"   5. Anexo PDF/documento (2 casos)")
print(f"   6. Múltiplos anexos (2 casos)")
print(f"   7. Arquivo inexistente (2 casos)")
print(f"   8. Número ausente/inválido (4 casos)")
print(f"   9. Mensagem ausente (3 casos)")
print(f"  10. Formatos de número variados (6 casos)")
print(f"  11. Formatação WhatsApp (4 casos)")
print(f"  12. Quebra de linha / msg longa (2 casos)")
print(f"  13. Mensagem com link (2 casos)")
print(f"  14. Combinações especiais (3 casos)")
print(f"  15. Já enviado / já inválido (2 casos)")
print(f"  16. Linha vazia (1 caso)")
print(f"  17. Emojis e emoticons (1 caso)")
print(f"  18. Número duplicado / deduplicação (1 caso)")
