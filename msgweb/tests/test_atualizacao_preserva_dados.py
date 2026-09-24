"""
A campanha do cliente sobrevive a atualizar o programa.

Motivação (relato de 23/09/2026, 1.4.7): *"quando fecha e abre o programa ainda
está sumindo a planilha anexada"* — e o programa reabria com a planilha de
teste, "como se estivesse abrindo pela primeira vez".

Não era o restaurar que estava quebrado (esse sempre funcionou): era o lugar. A
pasta de dados era a pasta de instalação, e o .zip do build levava um
`uploads/contatos.xlsx` de fábrica. Descompactar a versão nova por cima
substituía a campanha pelo contato de teste. O log de 23/09/2026: extração às
16:13, `Planilha restaurada da sessão anterior (gravada em 23/09/2026 16:13)`
às 16:14:56.

Estes testes encenam a atualização inteira, em processo separado — o `app.py`
resolve os caminhos no import, então trocar o ambiente depois não provaria nada.

Executa com:
    venv\\Scripts\\python.exe -m unittest tests.test_atualizacao_preserva_dados -v
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

# Roda o app num processo limpo e conta o que ele viu.
SONDA = r'''
import json, os, sys
from pathlib import Path
from unittest.mock import patch

programa, dados, raiz = sys.argv[1], sys.argv[2], sys.argv[3]
sys.path.insert(0, raiz)
os.chdir(programa)
os.environ["WHATSAPP_AUTOMACAO_DADOS"] = dados

import app as app_mod
from fastapi.testclient import TestClient

with patch.object(app_mod, "validar_licenca", lambda: {"valida": True}):
    c = TestClient(app_mod.app)
    c.__enter__()
    r = c.get("/contacts")
    nomes = [x["pessoa"] for x in r.json()["contacts"]] if r.status_code == 200 else []
    c.__exit__(None, None, None)

print("RESULTADO" + json.dumps({
    "status": r.status_code,
    "nomes": nomes,
    "config_file": str(app_mod.CONFIG_FILE),
    "log_file": str(app_mod.LOG_FILE),
}))
'''


def _planilha(destino: Path, nomes) -> None:
    import pandas as pd
    destino.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([
        {"Nome": n, "Número": f"1999000{i:04d}", "Mensagem": "Olá {nome}"}
        for i, n in enumerate(nomes)
    ]).to_excel(destino, index=False)


class TestAtualizacaoPreservaDados(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="atualiza_"))
        # A pasta que o cliente descompacta. Na 1.4.7 os dados moravam aqui.
        self.programa = self.tmp / "WhatsAppAutomacao"
        self._pasta_do_programa(self.programa)
        self.dados = self.tmp / "AppData" / "WhatsAppAutomacao"

    @staticmethod
    def _pasta_do_programa(destino: Path) -> None:
        """O que o .zip entrega ao lado do .exe: entre outros, o `static/`."""
        (destino / "static").mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _rodar_app(self):
        proc = subprocess.run(
            [sys.executable, "-c", SONDA, str(self.programa), str(self.dados), str(RAIZ)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        marca = proc.stdout.rfind("RESULTADO")
        if marca == -1:
            self.fail(f"a sonda nao reportou nada.\nSTDOUT:\n{proc.stdout}\n"
                      f"STDERR:\n{proc.stderr}")
        return json.loads(proc.stdout[marca + len("RESULTADO"):].splitlines()[0])

    def _descompactar_versao_nova(self):
        """
        O que o cliente faz para atualizar: extrair o .zip por cima.

        O zip de hoje leva `uploads/modelo_contatos.xlsx` (ver build.bat) — de
        propósito NÃO `contatos.xlsx`, que era o nome do arquivo vivo dele.
        """
        _planilha(self.programa / "uploads" / "modelo_contatos.xlsx", ["Mauricio"])

    def test_campanha_sobrevive_a_atualizar_por_cima(self):
        """O caso do cliente, do começo ao fim."""
        # 1.4.7: a campanha mora dentro da pasta do programa.
        _planilha(self.programa / "uploads" / "contatos.xlsx",
                  ["Adailton", "Adalberto", "Adilson"])

        # Primeira abertura da versão nova: migra para fora da pasta do programa.
        primeira = self._rodar_app()
        self.assertEqual(primeira["status"], 200)
        self.assertEqual(primeira["nomes"], ["Adailton", "Adalberto", "Adilson"])
        self.assertTrue((self.dados / "uploads" / "contatos.xlsx").exists(),
                        "a planilha nao foi para a pasta de dados")

        # O cliente atualiza de novo, extraindo por cima.
        self._descompactar_versao_nova()

        depois = self._rodar_app()
        self.assertEqual(depois["nomes"], ["Adailton", "Adalberto", "Adilson"],
                         "atualizar por cima trocou a campanha do cliente")
        self.assertNotIn("Mauricio", depois["nomes"],
                         "o programa reabriu com a planilha de teste de fabrica")

    def test_instalar_em_pasta_nova_tambem_acha_a_campanha(self):
        """
        O outro jeito de atualizar, e o que o cliente fez: descompactar numa
        pasta ao lado (a dele se chama "Whats 3"). Antes isso dava uma
        instalação virgem; agora os dados não dependem de onde o .exe está.
        """
        _planilha(self.programa / "uploads" / "contatos.xlsx", ["Adailton"])
        self.assertEqual(self._rodar_app()["nomes"], ["Adailton"])

        self.programa = self.tmp / "Whats 3" / "WhatsAppAutomacao"
        self._pasta_do_programa(self.programa)
        self._descompactar_versao_nova()

        self.assertEqual(self._rodar_app()["nomes"], ["Adailton"],
                         "instalacao em pasta nova nao achou a campanha")

    def test_primeira_instalacao_de_verdade_abre_vazia(self):
        """
        Sem instalação anterior, `/contacts` responde 404 — que a tela trata
        como primeira execução, não como erro (ver `mostrarPrimeiraVez`).
        """
        self._descompactar_versao_nova()
        r = self._rodar_app()
        self.assertEqual(r["status"], 404)
        self.assertEqual(r["nomes"], [])

    def test_estado_do_app_fica_fora_da_pasta_do_programa(self):
        """
        Não só a planilha: config e log também. Qualquer um deles dentro da
        pasta do programa é uma coisa a menos que sobrevive à atualização.
        """
        _planilha(self.programa / "uploads" / "contatos.xlsx", ["Adailton"])
        r = self._rodar_app()

        programa = self.programa.resolve()
        for rotulo in ("config_file", "log_file"):
            caminho = Path(r[rotulo]).resolve()
            self.assertNotIn(programa, caminho.parents,
                             f"{rotulo} ({caminho}) ficou dentro da pasta do programa")


class TestNenhumCaminhoEscritoNaMao(unittest.TestCase):
    """
    Nenhum caminho de dados volta a ser literal no código.

    Mesma ideia do grep de seletores em `tests/test_seletores.py`: o jeito
    realista de reintroduzir o bug é alguém escrever `Path("uploads/...")` de
    novo num arquivo novo, o que passa despercebido num diff.
    """

    ARQUIVOS = ("app.py", "whatsapp_sender.py", "seletores.py", "varredura.py",
                "linha_conversa.py", "contact_logic.py")
    # Inclui as strings soltas, não só as embrulhadas em Path(): o default do
    # `--planilha` era exatamente isso, uma string crua, e passava batido.
    LITERAIS = ('"uploads/', "'uploads/", '"uploads"', "'uploads'",
                '"log.txt"', "'log.txt'", '"chrome_profile"', "'chrome_profile'")

    def test_sem_literais_de_caminho_de_dados(self):
        for nome in self.ARQUIVOS:
            caminho = RAIZ / nome
            if not caminho.exists():
                continue
            fonte = caminho.read_text(encoding="utf-8")
            # Fora comentários e docstrings, que citam os caminhos ao explicar.
            codigo = "\n".join(
                l for l in fonte.splitlines()
                if not l.strip().startswith(("#", "*", '"""', "'''"))
            )
            for literal in self.LITERAIS:
                self.assertNotIn(
                    literal, codigo,
                    f"{nome} escreve {literal!r} na mao — use caminhos.py, "
                    f"senao o dado volta para dentro da pasta do programa")


if __name__ == "__main__":
    unittest.main(verbosity=2)
