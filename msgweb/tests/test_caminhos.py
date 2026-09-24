"""
Testes de `caminhos.py`: onde os dados do cliente moram.

Motivação (relato de 23/09/2026, versão 1.4.7): *"quando fecha e abre o
programa ainda está sumindo a planilha anexada"* — e o programa reabria com a
planilha de teste de fábrica, "como se estivesse abrindo pela primeira vez".

A pasta de dados era a pasta de instalação, que é a pasta que o cliente
sobrescreve ao descompactar uma versão nova. O log de 23/09/2026 tem a coisa
inteira: extração às 16:13, `Planilha restaurada da sessão anterior (gravada em
23/09/2026 16:13)` às 16:14:56 (a planilha de fábrica sendo chamada de "sua
sessão anterior"), e `Escaneie o QR Code` às 16:43:48, porque o
`chrome_profile/` também morava lá.

O que estes testes fixam:
  1. Em desenvolvimento os caminhos continuam RELATIVOS e idênticos aos
     literais de antes — é o que mantém o `testar.bat`, o `test_app_estado.py`
     e o `tests/e2e/ambiente.py` (que troca de diretório a cada cenário)
     funcionando sem mudança nenhuma.
  2. Empacotado, saem para `%LOCALAPPDATA%`, longe da pasta do .exe.
  3. A migração roda uma vez, nunca por cima do que já existe no lugar novo, e
     não arrasta o `chrome_profile/`.

Executa com:
    venv\\Scripts\\python.exe -m unittest tests.test_caminhos -v
"""

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import caminhos  # noqa: E402


class BaseCaminhos(unittest.TestCase):
    """Cada teste com ambiente próprio: a resolução lê os dois do processo."""

    def setUp(self):
        self._env = dict(os.environ)
        os.environ.pop(caminhos.VAR_AMBIENTE, None)
        self._cwd = os.getcwd()
        self.tmp = Path(tempfile.mkdtemp(prefix="caminhos_"))

    def tearDown(self):
        os.chdir(self._cwd)
        os.environ.clear()
        os.environ.update(self._env)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _empacotado(self, valor=True):
        return patch.object(caminhos, "empacotado", lambda: valor)


class TestDesenvolvimento(BaseCaminhos):
    def test_caminhos_continuam_relativos_e_iguais_aos_de_antes(self):
        """
        Os literais que existiam espalhados pelo código, um por um.

        Relativo é o requisito, não um detalhe: `tests/e2e/ambiente.py` importa
        o `app.py` uma vez e depois dá `os.chdir` para uma pasta temporária nova
        a cada cenário. Um caminho absoluto resolvido no import prenderia todos
        os cenários na primeira pasta.
        """
        with self._empacotado(False):
            self.assertEqual(caminhos.dados_dir(), Path("."))
            self.assertEqual(caminhos.uploads_dir(), Path("uploads"))
            self.assertEqual(caminhos.planilha(), Path("uploads/contatos.xlsx"))
            self.assertEqual(caminhos.media_dir(), Path("uploads/media"))
            self.assertEqual(caminhos.log_file(), Path("log.txt"))

    def test_caminho_relativo_acompanha_a_troca_de_diretorio(self):
        """É o comportamento de que o harness e2e depende."""
        with self._empacotado(False):
            os.chdir(self.tmp)
            self.assertEqual(
                caminhos.uploads_dir().resolve(),
                (self.tmp / "uploads").resolve(),
            )

    def test_perfil_do_chrome_e_absoluto(self):
        """O Chrome recebe isto em --user-data-dir e não herda nosso cwd."""
        with self._empacotado(False):
            os.chdir(self.tmp)
            self.assertTrue(caminhos.chrome_profile_dir().is_absolute())


class TestEmpacotado(BaseCaminhos):
    def test_vai_para_localappdata(self):
        with self._empacotado(), patch.dict(
                os.environ, {"LOCALAPPDATA": str(self.tmp)}):
            self.assertEqual(
                caminhos.dados_dir(), self.tmp / caminhos.PASTA_NO_PERFIL)
            self.assertEqual(
                caminhos.planilha(),
                self.tmp / caminhos.PASTA_NO_PERFIL / "uploads" / "contatos.xlsx",
            )

    def test_fora_da_pasta_do_programa(self):
        """
        O ponto do exercício todo: descompactar por cima não pode alcançar os
        dados.
        """
        programa = self.tmp / "WhatsAppAutomacao"
        programa.mkdir()
        os.chdir(programa)
        with self._empacotado(), patch.dict(
                os.environ, {"LOCALAPPDATA": str(self.tmp / "AppData")}):
            dados = caminhos.dados_dir().resolve()
            self.assertNotIn(programa.resolve(), [dados] + list(dados.parents))

    def test_sem_localappdata_cai_na_home(self):
        """Perfil atípico ou outro SO: a home sempre existe."""
        with self._empacotado(), patch.dict(os.environ, {"LOCALAPPDATA": ""}):
            self.assertEqual(
                caminhos.dados_dir(),
                Path(os.path.expanduser("~")) / ".whatsappautomacao",
            )

    def test_variavel_de_ambiente_manda_em_tudo(self):
        with self._empacotado(), patch.dict(
                os.environ, {"LOCALAPPDATA": str(self.tmp),
                             caminhos.VAR_AMBIENTE: str(self.tmp / "forcado")}):
            self.assertEqual(caminhos.dados_dir(), self.tmp / "forcado")


class TestMigracao(BaseCaminhos):
    """A instalação antiga guardava tudo ao lado do .exe."""

    def _instalacao_antiga(self):
        programa = self.tmp / "programa"
        (programa / "uploads" / "media").mkdir(parents=True)
        (programa / "uploads" / "contatos.xlsx").write_bytes(b"planilha do cliente")
        (programa / "uploads" / "config.json").write_text("{}")
        (programa / "uploads" / "media" / "foto.jpg").write_bytes(b"jpg")
        (programa / "chrome_profile").mkdir()
        (programa / "chrome_profile" / "Default").write_bytes(b"perfil enorme")
        os.chdir(programa)
        return programa

    def test_copia_uploads_da_instalacao_antiga(self):
        programa = self._instalacao_antiga()
        destino = self.tmp / "dados"
        with patch.dict(os.environ, {caminhos.VAR_AMBIENTE: str(destino)}):
            msg = caminhos.migrar_dados_legados()

        self.assertIn("copiados", msg)
        self.assertEqual(
            (destino / "uploads" / "contatos.xlsx").read_bytes(),
            b"planilha do cliente")
        self.assertTrue((destino / "uploads" / "media" / "foto.jpg").exists())
        self.assertTrue((destino / "uploads" / "config.json").exists())
        # Cópia, não movimentação: a instalação antiga fica intacta.
        self.assertTrue((programa / "uploads" / "contatos.xlsx").exists())

    def test_nao_arrasta_o_perfil_do_chrome(self):
        """
        Centenas de MB de LevelDB de um perfil possivelmente em uso, atravessando
        volumes. Meia cópia dá perfil corrompido, que é pior que nenhum: sem ele
        o cliente lê o QR Code uma vez e pronto.
        """
        self._instalacao_antiga()
        destino = self.tmp / "dados"
        with patch.dict(os.environ, {caminhos.VAR_AMBIENTE: str(destino)}):
            caminhos.migrar_dados_legados()

        self.assertFalse((destino / "chrome_profile").exists())

    def test_nunca_sobrescreve_o_que_ja_existe_no_lugar_novo(self):
        """Rodar de novo é sempre no-op — senão a 2ª execução comeria a campanha."""
        self._instalacao_antiga()
        destino = self.tmp / "dados"
        (destino / "uploads").mkdir(parents=True)
        (destino / "uploads" / "contatos.xlsx").write_bytes(b"campanha nova")

        with patch.dict(os.environ, {caminhos.VAR_AMBIENTE: str(destino)}):
            msg = caminhos.migrar_dados_legados()

        self.assertEqual(msg, "")
        self.assertEqual(
            (destino / "uploads" / "contatos.xlsx").read_bytes(), b"campanha nova")

    def test_em_desenvolvimento_e_no_op(self):
        """Origem e destino são a mesma pasta: copiar sobre si mesmo é erro."""
        programa = self._instalacao_antiga()
        with self._empacotado(False):
            self.assertEqual(caminhos.migrar_dados_legados(), "")
        self.assertTrue((programa / "uploads" / "contatos.xlsx").exists())

    def test_sem_instalacao_antiga_nao_diz_nada(self):
        os.chdir(self.tmp)
        destino = self.tmp / "dados"
        with patch.dict(os.environ, {caminhos.VAR_AMBIENTE: str(destino)}):
            self.assertEqual(caminhos.migrar_dados_legados(), "")

    def test_falha_de_copia_nao_derruba_o_app(self):
        """
        Sem permissão, disco cheio, antivírus: o programa tem que abrir assim
        mesmo, com a lista vazia, e dizer onde os arquivos ficaram.
        """
        self._instalacao_antiga()
        destino = self.tmp / "dados"
        with patch.dict(os.environ, {caminhos.VAR_AMBIENTE: str(destino)}), \
                patch.object(caminhos.shutil, "copytree",
                             side_effect=OSError("acesso negado")):
            msg = caminhos.migrar_dados_legados()

        self.assertIn("acesso negado", msg)
        self.assertIn("continuam onde estavam", msg)


if __name__ == "__main__":
    unittest.main(verbosity=2)
