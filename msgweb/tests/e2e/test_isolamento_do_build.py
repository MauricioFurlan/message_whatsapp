# -*- coding: utf-8 -*-
"""
A bateria de teste não pode entrar no `.exe` do cliente.

Hoje ela fica de fora por construção, e é bom entender por quê antes de
confiar nisso:

- o PyInstaller é invocado sobre `launcher.py` e empacota o que for
  **alcançável por import** a partir dele. Nada em `tests/` é importado por
  nada de produção, então o grafo nunca chega lá;
- depois, o `build.bat` copia à mão só `static/`, o `LEIA-ME` e uma
  `uploads/contatos.xlsx` recém-gerada pelo `gerar_planilha_modelo.py`.

Ou seja: são duas portas, e a bateria não passa por nenhuma das duas. O que
este arquivo faz é **travar** isso, porque a forma de quebrar é discreta — basta
alguém importar o dublê de dentro do `whatsapp_sender.py` "só para reaproveitar
uma constante" e o grafo do PyInstaller passa a incluir `tests/`, o `selenium`
de teste, e o que mais vier junto. Ninguém notaria: o build continuaria
funcionando, só maior e carregando código de teste para a máquina do cliente.

É o mesmo tipo de guarda que o `tests/test_seletores.py` faz por grep para os
seletores literais.
"""

import ast
import io
import os
import sys
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(RAIZ))

# O que entra no .exe: a raiz do grafo de imports do PyInstaller.
ENTRADA = "launcher"

# Pastas que existem só para desenvolver/testar e nunca devem ser alcançáveis.
PREFIXOS_DE_TESTE = ("tests", "test_", "sonda_", "gerar_planilha_teste")


def _modulos_locais() -> set:
    return {p.stem for p in RAIZ.glob("*.py")}


def _imports_de(caminho: Path) -> set:
    arvore = ast.parse(io.open(caminho, encoding="utf-8").read(), str(caminho))
    nomes = set()
    for no in ast.walk(arvore):
        if isinstance(no, ast.Import):
            for a in no.names:
                nomes.add(a.name.split(".")[0])
        elif isinstance(no, ast.ImportFrom):
            if no.level == 0 and no.module:
                nomes.add(no.module.split(".")[0])
    return nomes


def _fecho_de_imports(raiz_modulo: str):
    """
    Todo módulo LOCAL alcançável por import a partir de `raiz_modulo`.

    É a mesma pergunta que o PyInstaller responde para montar o pacote, feita
    por análise estática — não roda nada, então não depende de o import ter
    acontecido nesta máquina.
    """
    locais = _modulos_locais()
    vistos, fila, arestas = set(), [raiz_modulo], {}
    while fila:
        mod = fila.pop()
        if mod in vistos:
            continue
        vistos.add(mod)
        arquivo = RAIZ / f"{mod}.py"
        if not arquivo.exists():
            continue
        for alvo in _imports_de(arquivo):
            arestas.setdefault(mod, set()).add(alvo)
            if alvo in locais and alvo not in vistos:
                fila.append(alvo)
    return vistos, arestas


class TestNadaDeTesteEntraNoExe(unittest.TestCase):
    def test_o_grafo_de_imports_do_exe_nao_alcanca_a_bateria(self):
        alcancados, arestas = _fecho_de_imports(ENTRADA)

        culpados = []
        for origem, alvos in arestas.items():
            for alvo in alvos:
                if alvo.startswith(PREFIXOS_DE_TESTE):
                    culpados.append(f"{origem}.py importa {alvo}")

        self.assertEqual(
            culpados, [],
            "Modulo de producao importando codigo de teste — isso arrasta a "
            "bateria para dentro do .exe:\n  " + "\n  ".join(culpados),
        )

    def test_o_dublê_nao_e_alcancavel_a_partir_do_launcher(self):
        """
        O erro mais provável: reaproveitar uma constante do dublê no código de
        produção. Barato de fazer, invisível no diff, e o cliente leva junto.
        """
        alcancados, _ = _fecho_de_imports(ENTRADA)
        for proibido in ("tests", "fake_whatsapp", "ambiente"):
            self.assertNotIn(proibido, alcancados)

    def test_o_build_nao_copia_nada_de_teste(self):
        """
        A segunda porta: o `build.bat` copia arquivos à mão, fora do grafo de
        imports. Hoje são `static/`, o LEIA-ME e a planilha modelo.
        """
        build = io.open(RAIZ / "build.bat", encoding="utf-8", errors="replace").read()
        linhas_de_copia = [
            l.strip() for l in build.splitlines()
            if l.strip().lower().startswith(("xcopy", "copy "))
        ]
        for linha in linhas_de_copia:
            baixo = linha.lower()
            for proibido in ("tests", "testar.bat", "test_contatos",
                             "gerar_planilha_teste", "sonda_"):
                self.assertNotIn(
                    proibido, baixo,
                    f"build.bat copia material de teste para o dist: {linha}",
                )

    def test_a_planilha_de_teste_nao_e_a_que_o_cliente_recebe(self):
        """
        O build gera a planilha do cliente com `gerar_planilha_modelo.py` (um
        contato, limpo) e a valida. A planilha de teste tem 46 linhas, número
        real e mensagens de bancada — mandá-la no lugar seria vazar dado de
        desenvolvimento e ainda entregar uma bancada como se fosse modelo.
        """
        build = io.open(RAIZ / "build.bat", encoding="utf-8", errors="replace").read()
        self.assertIn("gerar_planilha_modelo.py", build)
        self.assertNotIn("gerar_planilha_teste.py", build)


class TestOsArquivosDeTesteExistemOndeDeveriam(unittest.TestCase):
    """
    A contraparte: a guarda acima ficaria verde também se a bateria tivesse
    sido apagada. Estes testes garantem que "não está no build" não virou
    "não existe".
    """

    def test_a_bancada_e_o_seed_estao_no_lugar(self):
        self.assertTrue((RAIZ / "test_contatos.csv").exists())
        self.assertTrue((RAIZ / "gerar_planilha_teste.py").exists())
        self.assertTrue((RAIZ / "testar.bat").exists())

    def test_o_dublê_e_o_ambiente_estao_no_lugar(self):
        self.assertTrue((RAIZ / "tests" / "e2e" / "fake_whatsapp.py").exists())
        self.assertTrue((RAIZ / "tests" / "e2e" / "ambiente.py").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
