"""
Testes do marcador de execução interrompida e do aviso de falha do app.

Motivação — o cliente perguntou por que sobraram contatos pendentes do dia
anterior. O `log.txt` de 31/08/2026 termina no meio de um envio, em
`16:56:00 | Aguardando 21s...`, sem `Envio finalizado`, sem
`Solicitação de parada` e sem `Fechando navegador`: o programa foi encerrado à
força com 48 enviados, 30 inválidos e 40 pendentes de 118.

Retomar já funcionava — os pendentes continuam na planilha. O que faltava era
avisar: no dia seguinte o app reabriu calado, restaurando "118 msgs em 240min"
da sessão anterior e aplicando esse número aos 40 que sobraram. Daí um plano de
rajadas com pausas de 24 a 37 minutos, que não fazia sentido nenhum.

Testa também o buraco no aviso de lentidão: ele contava só as falhas de abrir
CONVERSA. Naquele primeiro envio de 01/09 foram 4 sucessos, 1 falha de conversa
e 3 do WhatsApp Web inteiro não subir — 1 em 5, abaixo do limite, nenhum aviso.
Justo o caso mais grave, em que o envio não avança nem marca nada.

Executa com:
    venv\\Scripts\\python.exe -m unittest tests.test_execucao_interrompida -v
"""

import json
import logging
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from whatsapp_sender import WhatsAppSender  # noqa: E402


class MarcadorDeExecucaoTest(unittest.TestCase):
    """O arquivo que diz "morri no meio" e o aviso que ele produz."""

    def setUp(self):
        logging.getLogger("whatsapp_sender_file").setLevel(logging.CRITICAL)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

        import app as appmod
        self.app = appmod
        self._flag_original = appmod.ENVIO_FLAG_FILE
        appmod.ENVIO_FLAG_FILE = Path(self.tmp.name) / "envio_em_andamento.json"
        self.addCleanup(setattr, appmod, "ENVIO_FLAG_FILE", self._flag_original)

        self.logs = []
        self._add_log_original = appmod.add_log
        appmod.add_log = self.logs.append
        self.addCleanup(setattr, appmod, "add_log", self._add_log_original)

    def test_fim_limpo_nao_deixa_marcador(self):
        self.app._marcar_envio_em_andamento(40)
        self.assertTrue(self.app.ENVIO_FLAG_FILE.exists())

        self.app._limpar_envio_em_andamento()
        self.assertFalse(self.app.ENVIO_FLAG_FILE.exists())

        self.app._avisar_execucao_interrompida()
        self.assertEqual(self.logs, [], "envio que terminou direito não avisa nada")

    def test_marcador_sobrevivente_vira_aviso(self):
        """É o caso de 31/08: o processo morreu e o marcador ficou."""
        self.app._marcar_envio_em_andamento(40)

        self.app._avisar_execucao_interrompida()

        self.assertEqual(len(self.logs), 1, f"esperado um aviso: {self.logs}")
        aviso = self.logs[0]
        self.assertIn("não foi finalizada", aviso)
        self.assertIn("40", aviso, "o aviso precisa dizer quantos estavam pendentes")
        # E precisa mandar conferir a configuração, que é o que confundiu o
        # cliente: 240min restaurados para um punhado de contatos.
        self.assertIn("tempo de envio", aviso)

    def test_aviso_sai_uma_vez_so(self):
        """Avisou, apagou: reabrir de novo não pode repetir o alarme."""
        self.app._marcar_envio_em_andamento(40)
        self.app._avisar_execucao_interrompida()
        self.logs.clear()

        self.app._avisar_execucao_interrompida()
        self.assertEqual(self.logs, [])

    def test_marcador_corrompido_nao_quebra_o_arranque(self):
        self.app.ENVIO_FLAG_FILE.parent.mkdir(parents=True, exist_ok=True)
        self.app.ENVIO_FLAG_FILE.write_text("{lixo", encoding="utf-8")

        self.app._avisar_execucao_interrompida()

        self.assertEqual(len(self.logs), 1, "avisa mesmo sem conseguir ler os detalhes")
        self.assertFalse(self.app.ENVIO_FLAG_FILE.exists())

    def test_marcador_guarda_o_que_o_aviso_precisa(self):
        self.app._marcar_envio_em_andamento(7)
        dados = json.loads(self.app.ENVIO_FLAG_FILE.read_text(encoding="utf-8"))
        self.assertEqual(dados["pendentes_no_inicio"], 7)
        self.assertTrue(dados["iniciado_em"])


class AvisoDeFalhaDoAppTest(unittest.TestCase):
    """
    O aviso tem que enxergar as duas falhas, não só a de abrir conversa.
    """

    def setUp(self):
        logging.getLogger("whatsapp_sender_file").setLevel(logging.CRITICAL)
        self.logs = []
        self.sender = WhatsAppSender(
            excel_path="fake.xlsx",
            config={"human_behavior": False},
            log_callback=self.logs.append,
        )

    def test_falha_de_app_conta_para_a_taxa(self):
        """
        Antes isto não entrava na conta e o popup ficava mudo. 4 falhas de app
        em 6 tentativas é 67%: tem que avisar.
        """
        for _ in range(2):
            self.sender._registrar_resultado_de_abertura(True)
        for _ in range(4):
            self.sender._registrar_resultado_de_abertura(False, tipo="app")

        alerta = self.sender._alerta_lentidao
        self.assertIsNotNone(alerta)
        self.assertEqual(alerta["falhas"], 4)
        self.assertEqual(alerta["falhas_app"], 4)
        self.assertEqual(alerta["tipo"], "app")

    def test_texto_do_app_fala_em_pendente_nao_em_invalido(self):
        """
        Falha de app deixa o contato PENDENTE — não há o que reenviar depois.
        Dizer "inválido" aqui mandaria o usuário procurar linha que não existe.
        """
        for _ in range(6):
            self.sender._registrar_resultado_de_abertura(False, tipo="app")

        texto = " ".join(self.logs)
        self.assertIn("não está carregando", texto)
        self.assertIn("PENDENTES", texto)

    def test_conversa_continua_com_o_texto_antigo(self):
        for _ in range(6):
            self.sender._registrar_resultado_de_abertura(False, tipo="chat")

        alerta = self.sender._alerta_lentidao
        self.assertEqual(alerta["tipo"], "chat")
        self.assertEqual(alerta["falhas_app"], 0)
        self.assertIn("conversas não abriram", " ".join(self.logs))

    def test_tipo_segue_a_falha_predominante(self):
        """Mistura das duas: manda quem for maioria."""
        for _ in range(4):
            self.sender._registrar_resultado_de_abertura(False, tipo="chat")
        for _ in range(2):
            self.sender._registrar_resultado_de_abertura(False, tipo="app")

        self.assertEqual(self.sender._alerta_lentidao["tipo"], "chat")

    def test_cenario_real_de_01_09_agora_avisa(self):
        """
        A execução que motivou tudo: 4 envios ok, 1 timeout de conversa e 3
        falhas de app. Contando só a conversa dava 1/5 e nenhum aviso saía.
        """
        eventos = [
            (True, "chat"), (False, "app"), (False, "chat"), (True, "chat"),
            (True, "chat"), (False, "app"), (False, "app"), (True, "chat"),
        ]
        for ok, tipo in eventos:
            self.sender._registrar_resultado_de_abertura(ok, tipo=tipo)

        alerta = self.sender._alerta_lentidao
        self.assertIsNotNone(alerta, "esta execução TEM que produzir aviso")
        # O aviso é armado no INSTANTE em que a taxa cruza o limite — aqui no
        # 6º contato (3 falhas em 6 = 50%), não no fim da lista. É de propósito:
        # o valor do popup está em aparecer cedo, enquanto ainda dá para agir.
        self.assertEqual(alerta["falhas"], 3)
        self.assertEqual(alerta["tentativas"], 6)
        self.assertEqual(alerta["falhas_app"], 2)
        self.assertEqual(alerta["tipo"], "app")


if __name__ == "__main__":
    unittest.main(verbosity=2)
