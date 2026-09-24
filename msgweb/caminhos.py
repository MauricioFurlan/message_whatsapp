# -*- coding: utf-8 -*-
"""
Onde o app guarda os dados do cliente.

Existe por um bug relatado em 23/09/2026: *"quando fecha e abre o programa
ainda está sumindo a planilha anexada"*, e o programa reabria com a planilha de
teste, "como se estivesse abrindo pela primeira vez".

A causa é que a pasta de dados e a pasta de instalação eram a mesma. O
`launcher.py` faz `os.chdir(os.path.dirname(sys.executable))`, então
`uploads/contatos.xlsx` ficava **dentro da pasta do .exe** — que é exatamente a
pasta que o cliente sobrescreve ao descompactar uma versão nova. Pior: o .zip
do build levava um `uploads/contatos.xlsx` de fábrica (um contato "Mauricio",
`Olá {nome}, tudo bem?`), então atualizar não só apagava a campanha dele como
punha a planilha de teste no lugar. O log de 23/09/2026 mostra o estrago
inteiro: extração às 16:13, `Planilha restaurada da sessão anterior (gravada em
23/09/2026 16:13)` às 16:14:56 — o app chamando a planilha de fábrica de "sua
sessão anterior", porque a única coisa que ele conferia era o arquivo existir —
e, às 16:43:48, `Escaneie o QR Code`, porque o `chrome_profile/` morava no mesmo
lugar e também tinha ido embora.

`stats_log.py` já tinha topado com isto ("todo lançamento de versão nova perde
o histórico", 21/08/2026) e resolveu só para si, mandando o histórico para a
home do usuário. Aqui a mesma ideia vale para o resto: planilha, mídia,
configuração, cache de seletores, perfil do Chrome e log.

## Em desenvolvimento nada muda, e isso é de propósito

`dados_dir()` devolve `Path(".")` quando o app NÃO está empacotado, e
`Path(".") / "uploads"` é `Path("uploads")` — um caminho **relativo**, resolvido
contra o diretório atual na hora de cada acesso ao disco, exatamente como era
antes. É isso que mantém funcionando o `testar.bat`, o `test_app_estado.py` e,
principalmente, o `tests/e2e/ambiente.py`, que dá um `os.chdir` para uma pasta
temporária NOVA a cada cenário, depois de o `app.py` já ter sido importado. Um
caminho absoluto calculado no import prenderia todos os cenários na primeira
pasta.

Empacotado, `dados_dir()` devolve um caminho absoluto em `%LOCALAPPDATA%`, que
não depende do diretório atual nem de onde o .exe foi parar.
"""

import os
import shutil
import sys
from pathlib import Path

# Nome da pasta do app dentro de %LOCALAPPDATA%.
PASTA_NO_PERFIL = "WhatsAppAutomacao"

# Escape hatch e gancho de teste: se estiver definida, manda em tudo. É o único
# jeito de exercitar o caminho empacotado sem empacotar.
VAR_AMBIENTE = "WHATSAPP_AUTOMACAO_DADOS"


def empacotado() -> bool:
    """True quando rodando de dentro do .exe do PyInstaller."""
    return bool(getattr(sys, "frozen", False))


def dados_dir() -> Path:
    """
    A raiz dos dados do cliente.

    Relativa (`.`) em desenvolvimento — ver o cabeçalho: é o que preserva o
    comportamento atual dos testes. Absoluta quando empacotado.
    """
    forcado = os.environ.get(VAR_AMBIENTE, "").strip()
    if forcado:
        return Path(forcado)
    if not empacotado():
        return Path(".")
    base = os.environ.get("LOCALAPPDATA", "").strip()
    if not base:
        # Sem LOCALAPPDATA (perfil atípico, Windows antigo, outro SO): a home
        # sempre existe, e é onde a licença e o histórico já moram.
        return Path(os.path.expanduser("~")) / f".{PASTA_NO_PERFIL.lower()}"
    return Path(base) / PASTA_NO_PERFIL


def uploads_dir() -> Path:
    """Planilha em uso, mídias, configuração e cache de seletores."""
    return dados_dir() / "uploads"


def media_dir() -> Path:
    """Anexos enviados pelo usuário (`uploads/media/`)."""
    return uploads_dir() / "media"


def planilha() -> Path:
    """A cópia sobre a qual o app SEMPRE trabalha (ver CLAUDE.md)."""
    return uploads_dir() / "contatos.xlsx"


def log_file() -> Path:
    return dados_dir() / "log.txt"


def chrome_profile_dir() -> Path:
    """
    O perfil dedicado do Chrome, em caminho ABSOLUTO.

    O Chrome recebe isto em `--user-data-dir` e não tem por que compartilhar o
    nosso diretório atual, então aqui o caminho relativo do modo
    desenvolvimento não serve.
    """
    return (dados_dir() / "chrome_profile").resolve()


def migrar_dados_legados() -> str:
    """
    Traz o `uploads/` que ficou na pasta do programa para a pasta de dados.

    Roda uma vez só: se a pasta nova já existe, não faz nada — nunca sobrescreve
    o que o usuário acumulou no lugar novo. Cópia, não movimentação, para que a
    instalação antiga continue intacta caso algo dê errado.

    O `chrome_profile/` fica DE FORA de propósito. São centenas de megabytes de
    banco LevelDB e locks de um perfil possivelmente em uso, atravessando
    volumes (o .exe do cliente está em `D:`, o `%LOCALAPPDATA%` em `C:`); uma
    cópia pela metade dá um perfil corrompido, que é pior que nenhum. Sem ele o
    cliente lê o QR Code mais uma vez, nesta atualização — e nunca mais, que é o
    ponto de tudo isto.

    Devolve uma frase para o log, ou "" quando não havia o que migrar.
    """
    destino = uploads_dir()
    if destino.exists():
        return ""
    # A instalação antiga guardava tudo ao lado do .exe, que é o diretório
    # atual — o `launcher.py` garante isso antes de qualquer import.
    legado = Path.cwd() / "uploads"
    if not legado.is_dir() or legado.resolve() == destino.resolve():
        return ""
    try:
        shutil.copytree(legado, destino)
    except OSError as e:
        return (
            f"Não foi possível trazer os dados da instalação anterior "
            f"({legado}): {e}. O programa começa com a lista de contatos vazia; "
            f"os arquivos antigos continuam onde estavam."
        )
    return (
        f"Dados da instalação anterior copiados de {legado} para {destino}. "
        f"A partir de agora eles ficam fora da pasta do programa e sobrevivem "
        f"às atualizações."
    )
