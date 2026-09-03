"""
Testes do registro de queda de conexão durante o envio.

Contexto: quando a internet cai no meio de um envio, o WhatsApp Web continua de
pé (é uma PWA — o shell vem do service worker e as conversas do IndexedDB), só
que nenhuma conversa abre. O `#pane-side` existe, então a falha NÃO cai no
caminho de "WhatsApp Web não carregou" (que deixaria o contato pendente): cai no
timeout de abrir conversa, que marca o contato como inválido.

Decisão: manter o inválido — quem confere é o usuário, pelo botão de reenvio.
O que faltava era saber, lendo o log depois, que aquilo foi queda de rede. Sem
isso, uma internet instável e uma lista de números ruins produzem exatamente o
mesmo registro.

O que estes testes fixam:
  1. o desfecho NÃO muda: o contato continua sendo marcado como inválido;
  2. a queda é registrada uma vez na entrada e uma vez na volta, não a cada
     verificação;
  3. o contato invalidado durante a queda diz isso no motivo (que é o tooltip
     na tela e a coluna Motivo da planilha);
  4. o fim do envio resume quantos contatos caíram por falta de conexão;
  5. sem queda de conexão, nada disso aparece.

Executa com:
    venv\\Scripts\\python.exe -m unittest tests.test_log_queda_conexao -v
"""

import logging
import os
import sys
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

import whatsapp_sender  # noqa: E402
from whatsapp_sender import WhatsAppSender  # noqa: E402


class LogCapturado(logging.Handler):
    def __init__(self):
        super().__init__()
        self.linhas = []

    def emit(self, record):
        self.linhas.append(record.getMessage())

    @property
    def texto(self):
        return "\n".join(self.linhas)


class FakeAlerta:
    def __init__(self, texto):
        self.text = texto


class FakeDriverConexao:
    """
    Driver com estado de rede controlável.

    online: valor devolvido por navigator.onLine
    alerta: texto do aviso do WhatsApp Web (ou None)
    """

    def __init__(self, online=True, alerta=None):
        self.online = online
        self.alerta = alerta
        self.scripts = 0

    def execute_script(self, script, *a):
        self.scripts += 1
        if "navigator.onLine" in script:
            return not self.online
        return None

    def find_elements(self, by, selector):
        if "alert" in selector:
            return [FakeAlerta(self.alerta)] if self.alerta else []
        return []

    def find_element(self, by, selector):
        raise Exception("no such element")


class DeteccaoTest(unittest.TestCase):
    def setUp(self):
        logging.getLogger("whatsapp_sender_file").setLevel(logging.WARNING)
        self.captura = LogCapturado()
        logging.getLogger("whatsapp_sender_file").addHandler(self.captura)
        self.addCleanup(
            lambda: logging.getLogger("whatsapp_sender_file").removeHandler(self.captura)
        )
        self.logs_ui = []
        self.sender = WhatsAppSender(
            excel_path="fake.xlsx", config={}, log_callback=self.logs_ui.append,
        )

    def _com(self, **kw):
        self.sender._driver = FakeDriverConexao(**kw)
        return self.sender

    # --- detecção ---------------------------------------------------------- #
    def test_navigator_offline_e_detectado(self):
        s = self._com(online=False)
        self.assertIn("navigator.onLine", s._detect_sem_conexao())

    def test_aviso_do_whatsapp_e_detectado(self):
        s = self._com(online=True, alerta="Computador não conectado")
        self.assertIn("aviso do WhatsApp Web", s._detect_sem_conexao())

    def test_rede_ok_nao_acusa_nada(self):
        s = self._com(online=True)
        self.assertEqual(s._detect_sem_conexao(), "")

    def test_alerta_de_outro_assunto_nao_e_queda(self):
        """Nem todo role=alert é falta de conexão."""
        s = self._com(online=True, alerta="Suas mensagens são criptografadas")
        self.assertEqual(s._detect_sem_conexao(), "")

    def test_deteccao_nao_quebra_com_driver_ruim(self):
        class DriverRuim:
            def execute_script(self, *a):
                raise Exception("sem sessão")

            def find_elements(self, *a):
                raise Exception("sem sessão")

        self.sender._driver = DriverRuim()
        self.assertEqual(self.sender._detect_sem_conexao(), "")

    # --- transições -------------------------------------------------------- #
    def test_queda_registra_uma_vez_so(self):
        """Verificar a cada 2s não pode virar uma linha de log a cada 2s."""
        s = self._com(online=False)
        for _ in range(5):
            s._registrar_estado_de_conexao(s._detect_sem_conexao(), "Ana", "199")

        entradas = self.captura.texto.count("SEM CONEXÃO detectada")
        self.assertEqual(entradas, 1, f"log repetido:\n{self.captura.texto}")

    def test_volta_da_conexao_e_registrada(self):
        s = self._com(online=False)
        s._registrar_estado_de_conexao(s._detect_sem_conexao(), "Ana", "199")

        s._driver.online = True
        s._registrar_estado_de_conexao(s._detect_sem_conexao(), "Ana", "199")

        self.assertIn("Conexão restabelecida", self.captura.texto)
        self.assertIsNone(s._sem_conexao_desde)

    def test_sem_queda_nao_polui_o_log(self):
        s = self._com(online=True)
        for _ in range(5):
            s._registrar_estado_de_conexao(s._detect_sem_conexao(), "Ana", "199")

        self.assertNotIn("SEM CONEXÃO", self.captura.texto)
        self.assertNotIn("Conexão restabelecida", self.captura.texto)

    # --- resumo final ------------------------------------------------------ #
    def test_resumo_sai_quando_houve_invalidos_por_queda(self):
        self.sender._invalidos_sem_conexao = 7
        self.sender._log_resumo_de_conexao()

        self.assertIn("7 contato(s)", self.captura.texto)
        self.assertIn("RESUMO", self.captura.texto)
        self.assertTrue(
            any("reenvio" in m for m in self.logs_ui),
            f"a tela precisa dizer o que fazer: {self.logs_ui}",
        )

    def test_resumo_nao_sai_sem_queda(self):
        self.sender._invalidos_sem_conexao = 0
        self.sender._log_resumo_de_conexao()

        self.assertEqual(self.logs_ui, [])
        self.assertNotIn("RESUMO", self.captura.texto)


class DesfechoNaoMudouTest(unittest.TestCase):
    """A decisão foi manter o inválido — isto aqui é a trava disso."""

    def test_motivo_de_queda_continua_marcando_invalido(self):
        fonte = Path(RAIZ, "whatsapp_sender.py").read_text(encoding="utf-8")
        trecho = fonte[fonte.index("sem_conexao = self._sem_conexao_no_contato"):]
        trecho = trecho[:trecho.index("self._notify_contact_update")]

        self.assertIn('df.at[idx, "Invalido"] = "X"', trecho)
        self.assertIn("SEM CONEXÃO", trecho, "o motivo precisa dizer que foi a rede")
        self.assertIn("self._contar_invalido", trecho)


if __name__ == "__main__":
    unittest.main(verbosity=2)
