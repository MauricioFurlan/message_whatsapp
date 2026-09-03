"""
Testes do status "Duplicado" versus "Enviado" na tabela de contatos.

Relato (26/08/2026): iniciando com `python app.py --planilha test`, com a
planilha já carregada, fechar o servidor e abrir de novo fazia contatos que
estavam como **Enviado** aparecerem como **Duplicado** — mesmo com a opção
"permitir números duplicados" LIGADA. Um F5 devolvia o status correto.

Duas causas somadas:

  1. `state.config` não sobrevivia ao reinício. A configuração real do usuário
     morava só no `localStorage` do navegador e só chegava ao backend num
     `POST /config`, disparado quando o usuário mexe em algum campo. Até lá o
     servidor respondia com o padrão (`allow_duplicates=False`) e `GET
     /contacts` marcava duplicados que não deveria. O F5 "consertava" porque a
     essa altura a configuração já tinha sido reenviada.

  2. Mesmo com a configuração certa, marcar como duplicada uma linha já
     ENVIADA é errado: "Enviado" é fato gravado na planilha, "duplicado" é
     classificação derivada e só diz algo sobre quem ainda está na fila.

Por que não era só cosmético: o botão de reenvio (↺) aparece em toda linha já
processada. Vendo "Duplicado" onde deveria ler "Enviado", o usuário clica no ↺
para "corrigir" — e `resetContact()` zera o Enviado, devolvendo o contato à
fila. Na próxima rodada ele recebe a mensagem de novo.

Executa com:
    venv\\Scripts\\python.exe -m unittest tests.test_duplicado_vs_enviado -v
"""

import asyncio
import json
import logging
import os
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
os.chdir(RAIZ)

import app as appmod  # noqa: E402


def rodar(coro):
    return asyncio.run(coro)


class BaseContatos(unittest.TestCase):
    def setUp(self):
        logging.getLogger("whatsapp_sender_file").setLevel(logging.CRITICAL)
        self._tmp = tempfile.TemporaryDirectory()
        self._cwd = os.getcwd()
        os.chdir(self._tmp.name)
        os.makedirs("uploads", exist_ok=True)
        self.addCleanup(self._tmp.cleanup)
        self.addCleanup(lambda: os.chdir(self._cwd))

        self._config_original = dict(appmod.state.config)
        self._path_original = appmod.state.excel_path
        self._config_file_original = appmod.CONFIG_FILE
        appmod.CONFIG_FILE = Path("uploads/config.json")
        self.addCleanup(self._restaurar)

    def _restaurar(self):
        appmod.state.config = self._config_original
        appmod.state.excel_path = self._path_original
        appmod.CONFIG_FILE = self._config_file_original

    def planilha(self, linhas):
        df = pd.DataFrame(linhas)
        caminho = Path("uploads/contatos.xlsx")
        df.to_excel(caminho, index=False)
        appmod.state.excel_path = str(caminho)

    def contatos(self):
        return rodar(appmod.get_contacts())["contacts"]


class DuplicadoVersusEnviadoTest(BaseContatos):
    def _planilha_com_repetido(self):
        """Mesmo número em três linhas: duas já enviadas, uma pendente."""
        self.planilha([
            {"Nome": "Ana", "Número": "19994229146", "Mensagem": "Oi",
             "Enviado": "X", "DataEnvio": "2026-08-26 10:00:00", "Invalido": "", "Motivo": "", "Arquivo": ""},
            {"Nome": "Ana 2", "Número": "19994229146", "Mensagem": "Oi",
             "Enviado": "X", "DataEnvio": "2026-08-26 10:05:00", "Invalido": "", "Motivo": "", "Arquivo": ""},
            {"Nome": "Ana 3", "Número": "19994229146", "Mensagem": "Oi",
             "Enviado": "", "DataEnvio": "", "Invalido": "", "Motivo": "", "Arquivo": ""},
        ])

    def test_enviado_nao_vira_duplicado_com_duplicados_bloqueados(self):
        """
        O caso do relato. Mesmo com allow_duplicates DESLIGADO — que é o pior
        cenário, e era o estado do backend logo após reiniciar — uma linha já
        enviada não pode ser exibida como duplicada.
        """
        appmod.state.config["allow_duplicates"] = False
        self._planilha_com_repetido()

        contatos = self.contatos()

        self.assertTrue(contatos[0]["enviado"])
        self.assertFalse(contatos[0]["duplicado"])
        self.assertTrue(contatos[1]["enviado"], "a segunda linha foi enviada de verdade")
        self.assertFalse(
            contatos[1]["duplicado"],
            "linha enviada aparecendo como 'Duplicado' leva o usuário a clicar "
            "no reenvio e a mensagem sai duas vezes",
        )

    def test_pendente_repetido_continua_marcado(self):
        """A marcação segue valendo para quem ainda está na fila."""
        appmod.state.config["allow_duplicates"] = False
        self._planilha_com_repetido()

        contatos = self.contatos()

        self.assertFalse(contatos[2]["enviado"])
        self.assertTrue(contatos[2]["duplicado"])
        self.assertIn("duplicado", contatos[2]["motivo_duplicado"].lower())

    def test_enviado_ancora_a_deteccao_dos_pendentes(self):
        """
        Não marcar a linha enviada não pode fazê-la sumir da detecção: ela
        continua sendo a primeira ocorrência do número.
        """
        appmod.state.config["allow_duplicates"] = False
        self.planilha([
            {"Nome": "Ana", "Número": "19994229146", "Mensagem": "Oi",
             "Enviado": "X", "DataEnvio": "2026-08-26 10:00:00", "Invalido": "", "Motivo": "", "Arquivo": ""},
            {"Nome": "Ana 2", "Número": "19994229146", "Mensagem": "Oi",
             "Enviado": "", "DataEnvio": "", "Invalido": "", "Motivo": "", "Arquivo": ""},
        ])

        contatos = self.contatos()
        self.assertFalse(contatos[0]["duplicado"])
        self.assertTrue(
            contatos[1]["duplicado"],
            "o pendente repete um número que já foi enviado — tem que ser pego",
        )

    def test_com_duplicados_permitidos_ninguem_e_marcado(self):
        appmod.state.config["allow_duplicates"] = True
        self._planilha_com_repetido()

        contatos = self.contatos()
        self.assertEqual([c["duplicado"] for c in contatos], [False, False, False])


class ConfigSobreviveAoReinicioTest(BaseContatos):
    def _config(self, **extra):
        base = dict(
            total_msgs=50, tempo_minutos=60, hora_inicio="08:00", hora_fim="18:00",
            skip_weekends=True, human_behavior=True, allow_duplicates=False,
        )
        base.update(extra)
        return appmod.ConfigModel(**base)

    def test_config_e_gravada_em_disco(self):
        appmod.state.sender = None
        rodar(appmod.set_config(self._config(allow_duplicates=True, total_msgs=77)))

        salvo = json.loads(appmod.CONFIG_FILE.read_text(encoding="utf-8"))
        self.assertTrue(salvo["allow_duplicates"])
        self.assertEqual(salvo["total_msgs"], 77)

    def test_reinicio_recupera_allow_duplicates(self):
        """
        O cerne do relato: depois de fechar e abrir o servidor, o backend
        precisa saber que duplicados estão permitidos ANTES de a tela pedir os
        contatos — senão responde com o padrão e erra o status.
        """
        appmod.state.sender = None
        rodar(appmod.set_config(self._config(allow_duplicates=True)))

        # Simula o reinício: estado de processo novo, com os padrões.
        appmod.state.config = {
            "total_msgs": 10, "tempo_minutos": 60, "hora_inicio": "08:00",
            "hora_fim": "18:00", "skip_weekends": True, "human_behavior": True,
            "allow_duplicates": False,
        }
        appmod._restaurar_config_do_disco()

        self.assertTrue(
            appmod.state.config["allow_duplicates"],
            "sem isso o primeiro GET /contacts após reiniciar marca duplicados "
            "que o usuário mandou permitir",
        )

    def test_arquivo_corrompido_nao_derruba_o_startup(self):
        appmod.CONFIG_FILE.write_text("{isso não é json", encoding="utf-8")
        antes = dict(appmod.state.config)

        appmod._restaurar_config_do_disco()  # não pode levantar

        self.assertEqual(appmod.state.config, antes)

    def test_chaves_desconhecidas_sao_ignoradas(self):
        appmod.CONFIG_FILE.write_text(
            json.dumps({"allow_duplicates": True, "coisa_inventada": 1}), encoding="utf-8",
        )
        appmod._restaurar_config_do_disco()

        self.assertTrue(appmod.state.config["allow_duplicates"])
        self.assertNotIn("coisa_inventada", appmod.state.config)

    def test_sem_arquivo_mantem_os_padroes(self):
        antes = dict(appmod.state.config)
        appmod._restaurar_config_do_disco()
        self.assertEqual(appmod.state.config, antes)


if __name__ == "__main__":
    unittest.main(verbosity=2)
