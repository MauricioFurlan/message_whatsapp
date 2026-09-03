"""
Testes da trava de alterações enquanto o envio está em andamento.

Regra: depois de iniciar o envio, não se altera configuração nem mensagem
global (contatos já eram bloqueados).

Por que a trava tem que estar no BACKEND e não só na tela: o sender relê
`state.config` e `state.global_message` a cada contato, então uma alteração
aceita no meio do caminho muda o ritmo ou o TEXTO dos contatos restantes de um
envio já em curso. Desabilitar o campo na tela não basta — a página pode ser
recarregada durante o envio, e a restauração do localStorage chega a repostar a
mensagem global sozinha (`toggleGlobalMessage()` roda na carga da página).

Executa com:
    venv\\Scripts\\python.exe -m unittest tests.test_trava_durante_envio -v
"""

import asyncio
import logging
import os
import sys
import tempfile
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
os.chdir(RAIZ)  # app.py monta static/ a partir do diretório atual

from fastapi import HTTPException  # noqa: E402

import app as appmod  # noqa: E402


def rodar(coro):
    return asyncio.run(coro)


class SenderFalso:
    """Só o que a trava consulta: se o envio está rodando."""

    def __init__(self, rodando):
        self._rodando = rodando

    def is_running(self):
        return self._rodando


class TravaDuranteEnvioTest(unittest.TestCase):
    def setUp(self):
        logging.getLogger("whatsapp_sender_file").setLevel(logging.CRITICAL)
        self._sender_original = appmod.state.sender
        self._config_original = dict(appmod.state.config)
        self._msg_original = appmod.state.global_message
        self._ativa_original = appmod.state.global_message_active
        # set_config grava a configuração em disco. Aponta para um arquivo
        # temporário: sem isso o teste sobrescreve a configuração real que o
        # desenvolvedor tem em uploads/config.json.
        self._tmp = tempfile.TemporaryDirectory()
        self._config_file_original = appmod.CONFIG_FILE
        appmod.CONFIG_FILE = Path(self._tmp.name) / "config.json"
        self.addCleanup(self._tmp.cleanup)
        self.addCleanup(self._restaurar)

    def _restaurar(self):
        appmod.state.sender = self._sender_original
        appmod.state.config = self._config_original
        appmod.state.global_message = self._msg_original
        appmod.state.global_message_active = self._ativa_original
        appmod.CONFIG_FILE = self._config_file_original

    def _config(self, total_msgs=50):
        return appmod.ConfigModel(
            total_msgs=total_msgs,
            tempo_minutos=60,
            hora_inicio="08:00",
            hora_fim="18:00",
            skip_weekends=True,
            human_behavior=True,
            allow_duplicates=False,
        )

    def _mensagem(self, texto):
        return appmod.GlobalMessageModel(mensagem=texto, ativa=True)

    # --- com o envio rodando: recusa ---------------------------------------- #
    def test_config_recusada_durante_envio(self):
        appmod.state.config = {"total_msgs": 10}
        appmod.state.sender = SenderFalso(rodando=True)

        with self.assertRaises(HTTPException) as ctx:
            rodar(appmod.set_config(self._config(total_msgs=999)))

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("configurações", ctx.exception.detail.lower())
        self.assertEqual(
            appmod.state.config, {"total_msgs": 10},
            "a config do envio em curso não pode ter sido tocada",
        )

    def test_mensagem_global_recusada_durante_envio(self):
        appmod.state.global_message = "texto original do envio"
        appmod.state.sender = SenderFalso(rodando=True)

        with self.assertRaises(HTTPException) as ctx:
            rodar(appmod.set_global_message(self._mensagem("texto trocado no meio")))

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(
            appmod.state.global_message, "texto original do envio",
            "trocar a mensagem no meio mudaria o texto dos contatos restantes",
        )

    def test_contatos_continuam_recusados_durante_envio(self):
        """Comportamento que já existia: não pode regredir."""
        appmod.state.sender = SenderFalso(rodando=True)
        payload = appmod.ContactsPayload(contacts=[
            appmod.ContactModel(pessoa="Ana", numero="19994229146", mensagem="Oi"),
        ])
        with self.assertRaises(HTTPException) as ctx:
            rodar(appmod.save_contacts(payload))
        self.assertEqual(ctx.exception.status_code, 400)

    # --- envio parado: aceita ----------------------------------------------- #
    def test_config_aceita_com_envio_parado(self):
        appmod.state.sender = SenderFalso(rodando=False)
        resposta = rodar(appmod.set_config(self._config(total_msgs=77)))
        self.assertEqual(resposta["status"], "ok")
        self.assertEqual(appmod.state.config["total_msgs"], 77)

    def test_config_aceita_sem_sender_nenhum(self):
        """Primeira abertura do app: `state.sender` é None."""
        appmod.state.sender = None
        resposta = rodar(appmod.set_config(self._config(total_msgs=33)))
        self.assertEqual(resposta["status"], "ok")
        self.assertEqual(appmod.state.config["total_msgs"], 33)

    def test_mensagem_global_aceita_com_envio_parado(self):
        appmod.state.sender = SenderFalso(rodando=False)
        resposta = rodar(appmod.set_global_message(self._mensagem("nova mensagem")))
        self.assertEqual(resposta["status"], "ok")
        self.assertEqual(appmod.state.global_message, "nova mensagem")

    # --- estado "pausado" também é envio em andamento ----------------------- #
    def test_pausa_entre_rajadas_continua_bloqueando(self):
        """
        `pausado` cobre pausa entre rajadas e espera por horário comercial. É
        envio em andamento, não envio parado — a config precisa continuar
        travada, senão dava para alterar o ritmo entre uma leva e outra.
        """
        class SenderPausado:
            state = "pausado"

            def is_running(self):
                return True  # is_running() não distingue pausado de enviando

        appmod.state.sender = SenderPausado()
        with self.assertRaises(HTTPException):
            rodar(appmod.set_config(self._config()))
        with self.assertRaises(HTTPException):
            rodar(appmod.set_global_message(self._mensagem("x")))


if __name__ == "__main__":
    unittest.main(verbosity=2)
