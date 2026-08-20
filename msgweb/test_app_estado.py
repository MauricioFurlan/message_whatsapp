"""
Testes unitários do estado do backend: procedência da planilha e sincronismo
da configuração de envio.

Motivação (relato de cliente, 10/08/2026): "o sistema mandou o nome antigo do
contato" e "a mensagem global não teve comportamento humano". Os dois relatos
dependem de estado do backend, não da montagem do texto:

  - o sistema trabalha SEMPRE sobre a cópia `uploads/contatos.xlsx`. Editar o
    .xlsx original no computador não muda nada até um novo upload — por isso a
    procedência da planilha ("upload" / "editor" / "restaurada") aparece no
    /status e no log;
  - a deduplicação do upload mantém a PRIMEIRA ocorrência de cada número, com o
    nome dela. Duas linhas para o mesmo telefone ("Marcos Antônio" antiga e
    "Marcos" nova) fazem a antiga vencer — comportamento intencional, aqui
    fixado em teste para não virar surpresa de novo;
  - `POST /config` é o que faz `human_behavior` chegar ao sender.

Executa com:
    venv\\Scripts\\python.exe -m unittest test_app_estado -v
"""

import asyncio
import logging
import os
import shutil
import tempfile
import unittest
import unittest.mock
from datetime import datetime
from io import BytesIO
from pathlib import Path

import pandas as pd
from fastapi import UploadFile

RAIZ = Path(__file__).resolve().parent
os.chdir(RAIZ)  # app.py monta static/ e cria log.txt a partir do diretório atual

import app as appmod  # noqa: E402
from whatsapp_sender import WhatsAppSender  # noqa: E402


def rodar(coro):
    """Executa um endpoint assíncrono fora do servidor."""
    return asyncio.run(coro)


def planilha_em_memoria(linhas) -> BytesIO:
    """Gera um .xlsx em memória a partir de uma lista de dicionários."""
    buffer = BytesIO()
    pd.DataFrame(linhas).to_excel(buffer, index=False)
    buffer.seek(0)
    return buffer


class BaseAppTest(unittest.TestCase):
    """
    Cada teste roda num diretório temporário: os endpoints gravam em
    `uploads/contatos.xlsx` relativo ao diretório atual.
    """

    def setUp(self):
        logging.getLogger("whatsapp_sender_file").setLevel(logging.CRITICAL)
        self.tmp = tempfile.mkdtemp(prefix="msgweb_test_")
        os.chdir(self.tmp)
        self.addCleanup(self._limpar)

        # Estado limpo entre testes
        appmod.state.excel_path = None
        appmod.state.excel_source = ""
        appmod.state.excel_saved_at = ""
        appmod.state.sender = None
        appmod.state.logs = []
        appmod.state.global_message = ""
        appmod.state.global_message_active = False

    def _limpar(self):
        os.chdir(RAIZ)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def enviar_planilha(self, linhas, filename="contatos.xlsx"):
        upload = UploadFile(file=planilha_em_memoria(linhas), filename=filename)
        return rodar(appmod.upload_file(upload))


# --------------------------------------------------------------------------- #
# 1. Procedência da planilha
# --------------------------------------------------------------------------- #

class TestProcedenciaDaPlanilha(BaseAppTest):

    LINHAS = [
        {"Nome": "Marcos", "Número": "11999990001", "Mensagem": "Oi {nome}"},
        {"Nome": "Ana", "Número": "11999990002", "Mensagem": ""},
    ]

    def test_upload_marca_origem_upload(self):
        resultado = self.enviar_planilha(self.LINHAS)
        self.assertEqual(resultado["status"], "ok")
        self.assertEqual(appmod.state.excel_source, "upload")
        self.assertTrue(appmod.state.excel_saved_at)
        self.assertEqual(appmod.state.excel_path, str(Path("uploads/contatos.xlsx")))

    def test_edicao_pela_tela_marca_origem_editor(self):
        self.enviar_planilha(self.LINHAS)
        payload = appmod.ContactsPayload(contacts=[
            appmod.ContactModel(pessoa="Marcos", numero="11999990001", mensagem="Oi {nome}"),
        ])
        rodar(appmod.save_contacts(payload))
        self.assertEqual(appmod.state.excel_source, "editor")

    def test_restauracao_de_sessao_anterior_marca_origem_restaurada(self):
        """
        Cenário do relato: o app subiu de novo e reaproveitou a cópia antiga.
        Quem editou o .xlsx original no computador precisa ser avisado.
        """
        Path("uploads").mkdir(exist_ok=True)
        pd.DataFrame(self.LINHAS).to_excel("uploads/contatos.xlsx", index=False)

        rodar(appmod.startup_event())

        self.assertEqual(appmod.state.excel_source, "restaurada")
        self.assertTrue(appmod.state.excel_saved_at)
        aviso = " ".join(appmod.state.logs)
        self.assertIn("sessão anterior", aviso)
        self.assertIn("novo upload", aviso)

    def test_status_expoe_a_procedencia_para_a_tela(self):
        self.enviar_planilha(self.LINHAS)
        status = appmod.get_status_dict()
        self.assertIn("excel_info", status)
        self.assertEqual(status["excel_info"]["origem"], "upload")
        self.assertTrue(status["excel_info"]["atualizado_em"])
        self.assertTrue(status["excel_loaded"])

    def test_status_sem_planilha_nao_inventa_procedencia(self):
        status = appmod.get_status_dict()
        self.assertFalse(status["excel_loaded"])
        self.assertEqual(status["excel_info"]["origem"], "")


# --------------------------------------------------------------------------- #
# 2. Deduplicação: a primeira linha do número é a que vale
# --------------------------------------------------------------------------- #

class TestDeduplicacaoDoUpload(BaseAppTest):
    """
    Comportamento de hoje, fixado em teste: número repetido mantém a PRIMEIRA
    linha. É a explicação para "enviou o nome antigo" quando a planilha tem o
    mesmo telefone duas vezes.
    """

    def test_primeira_ocorrencia_vence_inclusive_o_nome(self):
        resultado = self.enviar_planilha([
            {"Nome": "Marcos Antônio", "Número": "11999990001", "Mensagem": ""},
            {"Nome": "Marcos", "Número": "11999990001", "Mensagem": ""},
        ])
        self.assertEqual(resultado["duplicatas_removidas"], 1)
        df = pd.read_excel("uploads/contatos.xlsx")
        self.assertEqual(len(df), 1)
        self.assertEqual(df.iloc[0]["Nome"], "Marcos Antônio")

    def test_numero_com_formatacao_diferente_conta_como_duplicata(self):
        resultado = self.enviar_planilha([
            {"Nome": "Marcos Antônio", "Número": "(19)99451-9934", "Mensagem": ""},
            {"Nome": "Marcos", "Número": "5519994519934", "Mensagem": ""},
        ])
        self.assertEqual(resultado["duplicatas_removidas"], 1)
        df = pd.read_excel("uploads/contatos.xlsx")
        self.assertEqual(df.iloc[0]["Nome"], "Marcos Antônio")

    def test_numeros_distintos_nao_sao_removidos(self):
        resultado = self.enviar_planilha([
            {"Nome": "Marcos", "Número": "11999990001", "Mensagem": ""},
            {"Nome": "Ana", "Número": "11999990002", "Mensagem": ""},
        ])
        self.assertEqual(resultado["duplicatas_removidas"], 0)
        self.assertEqual(resultado["total"], 2)

    def test_contato_ja_enviado_e_preservado(self):
        resultado = self.enviar_planilha([
            {"Nome": "Marcos", "Número": "11999990001", "Mensagem": "", "Enviado": "X"},
            {"Nome": "Marcos", "Número": "11999990001", "Mensagem": ""},
        ])
        df = pd.read_excel("uploads/contatos.xlsx")
        self.assertEqual(resultado["enviados"], 1)
        self.assertEqual(len(df), 1)

    def test_upload_exige_colunas_obrigatorias(self):
        from fastapi import HTTPException
        with self.assertRaises(HTTPException):
            self.enviar_planilha([{"Nome": "Marcos", "Telefone": "11999990001"}])


# --------------------------------------------------------------------------- #
# 3. Configuração chega ao sender
# --------------------------------------------------------------------------- #

class TestConfiguracaoDeEnvio(BaseAppTest):
    """
    A tela envia a configuração por POST /config. Se o comportamento humano não
    chegar aqui, o envio roda no padrão (OFF) e a mensagem vai de uma vez.
    """

    def test_comportamento_humano_chega_ao_sender(self):
        rodar(appmod.set_config(appmod.ConfigModel(human_behavior=True)))
        self.assertTrue(appmod.state.config["human_behavior"])
        sender = WhatsAppSender(excel_path="x.xlsx", config=appmod.state.config,
                                log_callback=lambda m: None)
        self.assertTrue(sender._human_behavior_enabled())

    def test_padrao_do_backend_e_comportamento_humano_desligado(self):
        rodar(appmod.set_config(appmod.ConfigModel()))
        self.assertFalse(appmod.state.config["human_behavior"])
        sender = WhatsAppSender(excel_path="x.xlsx", config=appmod.state.config,
                                log_callback=lambda m: None)
        self.assertFalse(sender._human_behavior_enabled())

    def test_config_completa_e_persistida_no_estado(self):
        rodar(appmod.set_config(appmod.ConfigModel(
            msgs_por_rodada=7, total_rodadas=4, intervalo_rodadas_min=12,
            hora_inicio="09:00", hora_fim="17:00", skip_weekends=False,
            delay_min=5, delay_max=9, human_behavior=True,
        )))
        cfg = appmod.state.config
        self.assertEqual(cfg["msgs_por_rodada"], 7)
        self.assertEqual(cfg["total_rodadas"], 4)
        self.assertEqual(cfg["intervalo_rodadas_min"], 12)
        self.assertEqual(cfg["hora_inicio"], "09:00")
        self.assertEqual(cfg["hora_fim"], "17:00")
        self.assertFalse(cfg["skip_weekends"])
        self.assertEqual(cfg["delay_min"], 5)
        self.assertEqual(cfg["delay_max"], 9)
        self.assertTrue(cfg["human_behavior"])

    def test_status_devolve_a_config_para_a_tela(self):
        rodar(appmod.set_config(appmod.ConfigModel(human_behavior=True, total_rodadas=9)))
        status = appmod.get_status_dict()
        self.assertTrue(status["config"]["human_behavior"])
        self.assertEqual(status["config"]["total_rodadas"], 9)


class TestJanelaDeHorarioCruzandoMeiaNoite(unittest.TestCase):
    """
    Relato de cliente (20/08/2026): configurou início 08:00 / fim 00:30 e toda
    mensagem foi recusada como "fora do horário". A comparação antiga
    (`inicio <= agora < fim`) parte do princípio de que fim > início em
    minutos do dia; quando a janela cruza a meia-noite (fim < início), essa
    condição é falsa para qualquer horário do dia inteiro.
    """

    def _sender(self, hora_inicio, hora_fim, skip_weekends=False):
        return WhatsAppSender(
            excel_path="x.xlsx",
            config={"hora_inicio": hora_inicio, "hora_fim": hora_fim,
                    "skip_weekends": skip_weekends},
            log_callback=lambda m: None,
        )

    def _com_hora(self, sender, hora, minuto):
        # 2026-08-19 é uma quarta-feira; skip_weekends=False de qualquer forma
        fake_now = datetime(2026, 8, 19, hora, minuto)
        with unittest.mock.patch("whatsapp_sender.datetime") as m:
            m.now.return_value = fake_now
            return sender._is_business_hours()

    def test_dentro_da_janela_antes_da_meia_noite(self):
        sender = self._sender("08:00", "00:30")
        self.assertTrue(self._com_hora(sender, 23, 0))

    def test_dentro_da_janela_depois_da_meia_noite(self):
        sender = self._sender("08:00", "00:30")
        self.assertTrue(self._com_hora(sender, 0, 15))

    def test_fora_da_janela_no_meio_da_madrugada(self):
        sender = self._sender("08:00", "00:30")
        self.assertFalse(self._com_hora(sender, 2, 0))

    def test_janela_normal_sem_cruzar_meia_noite_continua_ok(self):
        sender = self._sender("09:00", "17:00")
        self.assertTrue(self._com_hora(sender, 12, 0))
        self.assertFalse(self._com_hora(sender, 18, 0))


# --------------------------------------------------------------------------- #
# 4. Mensagem global no estado do backend
# --------------------------------------------------------------------------- #

class TestMensagemGlobalNoEstado(BaseAppTest):
    def test_global_ativa_e_repassada_ao_sender(self):
        rodar(appmod.set_global_message(
            appmod.GlobalMessageModel(mensagem="Olá {nome}!", ativa=True)
        ))
        self.assertTrue(appmod.state.global_message_active)
        sender = WhatsAppSender(
            excel_path="x.xlsx", config={}, log_callback=lambda m: None,
            global_message=appmod.state.global_message if appmod.state.global_message_active else "",
        )
        self.assertEqual(sender.global_message, "Olá {nome}!")

    def test_global_desativada_nao_e_repassada(self):
        rodar(appmod.set_global_message(
            appmod.GlobalMessageModel(mensagem="Olá {nome}!", ativa=False)
        ))
        sender = WhatsAppSender(
            excel_path="x.xlsx", config={}, log_callback=lambda m: None,
            global_message=appmod.state.global_message if appmod.state.global_message_active else "",
        )
        self.assertEqual(sender.global_message, "")


class FakeSenderCriado:
    """Sender falso: registra a config recebida e não abre navegador nenhum."""

    ultima_instancia = None

    def __init__(self, excel_path, config, log_callback=None,
                 contact_update_callback=None, global_message=""):
        self.excel_path = excel_path
        self.config = config
        self.global_message = global_message
        self.estado = ""
        FakeSenderCriado.ultima_instancia = self

    def _set_state(self, estado):
        self.estado = estado

    def is_running(self):
        return False

    def start(self):
        pass


class FakeThread:
    def __init__(self, target=None, daemon=False):
        self.target = target

    def start(self):
        pass

    def is_alive(self):
        return False


class TestLogVisivelDoInicioDeEnvio(BaseAppTest):
    """
    O log da TELA precisa dizer, no início do envio, se o comportamento humano
    está ligado, se a mensagem global está ativa e de onde veio a planilha —
    são as três dúvidas de todo relato de "não funcionou como esperado".
    """

    def setUp(self):
        super().setUp()
        self._originais = (appmod.validar_licenca, appmod.WhatsAppSender, appmod.Thread)
        appmod.validar_licenca = lambda: {"valida": True}
        appmod.WhatsAppSender = FakeSenderCriado
        appmod.Thread = FakeThread
        self.addCleanup(self._restaurar)

        self.enviar_planilha([
            {"Nome": "Marcos", "Número": "11999990001", "Mensagem": ""},
        ])

    def _restaurar(self):
        appmod.validar_licenca, appmod.WhatsAppSender, appmod.Thread = self._originais

    def _iniciar(self):
        appmod.state.logs = []
        rodar(appmod.start_sending())
        return " | ".join(appmod.state.logs)

    def test_log_avisa_comportamento_humano_ligado(self):
        rodar(appmod.set_config(appmod.ConfigModel(human_behavior=True)))
        log = self._iniciar()
        self.assertIn("Comportamento humano: ON", log)

    def test_log_avisa_comportamento_humano_desligado(self):
        rodar(appmod.set_config(appmod.ConfigModel(human_behavior=False)))
        log = self._iniciar()
        self.assertIn("Comportamento humano: OFF", log)

    def test_log_avisa_mensagem_global_e_procedencia_da_planilha(self):
        rodar(appmod.set_global_message(
            appmod.GlobalMessageModel(mensagem="Olá {nome}!", ativa=True)
        ))
        log = self._iniciar()
        self.assertIn("Mensagem global: ATIVA", log)
        self.assertIn("Planilha: upload", log)

    def test_config_e_global_chegam_ao_sender_criado(self):
        rodar(appmod.set_config(appmod.ConfigModel(human_behavior=True, msgs_por_rodada=8)))
        rodar(appmod.set_global_message(
            appmod.GlobalMessageModel(mensagem="Olá {nome}!", ativa=True)
        ))
        self._iniciar()
        sender = FakeSenderCriado.ultima_instancia
        self.assertTrue(sender.config["human_behavior"])
        self.assertEqual(sender.config["msgs_por_rodada"], 8)
        self.assertEqual(sender.global_message, "Olá {nome}!")

    def test_global_inativa_nao_vai_para_o_sender(self):
        rodar(appmod.set_global_message(
            appmod.GlobalMessageModel(mensagem="Olá {nome}!", ativa=False)
        ))
        self._iniciar()
        self.assertEqual(FakeSenderCriado.ultima_instancia.global_message, "")


if __name__ == "__main__":
    unittest.main(verbosity=2)