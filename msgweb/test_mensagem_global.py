"""
Testes unitários do comportamento de MONTAGEM e ENVIO da mensagem — incluindo
a mensagem global.

Motivação (relato de cliente, 10/08/2026):
  1. "na mensagem global ele pega o nome do WhatsApp da pessoa, não o da planilha"
  2. "a mensagem global não tem comportamento humano, ela já manda direto"

Estes testes fixam o comportamento correto de hoje:
  - o nome usado vem SEMPRE da coluna `Nome` da planilha;
  - a mensagem global é apenas o texto usado quando a coluna `Mensagem` está
    vazia — passa exatamente pelo mesmo caminho de envio das outras;
  - com comportamento humano ligado, a mensagem (global ou não) é digitada no
    campo do WhatsApp; com ele desligado, o texto vai pré-preenchido na URL;
  - o orçamento de digitação cresce com o tamanho do texto, para mensagem longa
    (o caso típico da global) não ser despejada de uma vez.

Executa com:
    venv\\Scripts\\python.exe -m unittest test_mensagem_global -v
    ou
    venv\\Scripts\\python.exe -m pytest test_mensagem_global.py -v
"""

import logging
import unittest

import pandas as pd

import whatsapp_sender
from whatsapp_sender import WhatsAppSender


# --------------------------------------------------------------------------- #
# Dublês
# --------------------------------------------------------------------------- #

class FakeTime:
    """
    Substitui o módulo `time` dentro de whatsapp_sender por um relógio falso.

    O tempo só avança quando o código dorme, então os testes de orçamento de
    digitação são determinísticos e instantâneos.
    """

    def __init__(self):
        self.agora = 0.0

    def sleep(self, segundos):
        self.agora += float(segundos or 0)

    def monotonic(self):
        return self.agora

    def time(self):
        return self.agora


class FakeInput:
    """Campo de texto do WhatsApp: registra tudo que foi digitado."""

    def __init__(self):
        self.calls = []

    def send_keys(self, value):
        self.calls.append(value)

    @property
    def text(self):
        return ""


class FakeDriverEnvio:
    """Driver mínimo para exercitar _send_message sem navegador."""

    def __init__(self):
        self.urls = []
        self.input = FakeInput()

    def get(self, url):
        self.urls.append(url)

    def find_element(self, by, selector):
        return self.input

    def find_elements(self, by, selector):
        # O campo do rodapé precisa "existir" aqui: é por ele que o sender
        # confirma que a conversa abriu (_wait_chat_or_invalid_popup). Devolver
        # lista vazia deixava essa espera em loop até o timeout, queimando CPU e
        # travando a suíte.
        if "contenteditable" in selector:
            return [self.input]
        return []

    def execute_script(self, *args, **kwargs):
        return None


class BaseSenderTest(unittest.TestCase):
    """Silencia o log de diagnóstico e troca o `time` real pelo falso."""

    def setUp(self):
        logging.getLogger("whatsapp_sender_file").setLevel(logging.CRITICAL)
        self.clock = FakeTime()
        self._time_original = whatsapp_sender.time
        whatsapp_sender.time = self.clock
        # Trocar o `time` do módulo não cobre as esperas do sender: ele usa
        # _interruptible_sleep -> threading.Event.wait(), que é um Event real e
        # ignora o relógio falso. Sem neutralizar aqui, os testes aguardavam de
        # verdade os intervalos entre mensagens e as pausas entre rajadas
        # (minutos ou horas), e a suíte travava.
        self._isleep_original = WhatsAppSender._interruptible_sleep
        WhatsAppSender._interruptible_sleep = lambda self, segundos: False
        self.addCleanup(self._restaurar_time)

    def _restaurar_time(self):
        whatsapp_sender.time = self._time_original
        WhatsAppSender._interruptible_sleep = self._isleep_original

    def novo_sender(self, config=None, global_message=""):
        return WhatsAppSender(
            excel_path="fake.xlsx",
            config=config or {},
            log_callback=lambda msg: None,
            global_message=global_message,
        )


# --------------------------------------------------------------------------- #
# 1. Montagem do texto: de onde vem o nome
# --------------------------------------------------------------------------- #

class TestFormatacaoDoTexto(BaseSenderTest):
    """
    _format_texto é o ÚNICO lugar que decide o texto enviado. Nenhum nome pode
    entrar aqui que não venha da planilha.
    """

    def setUp(self):
        super().setUp()
        self.sender = self.novo_sender()

    def test_placeholder_usa_o_nome_da_planilha(self):
        """Relato do cliente: planilha tem "Marcos", não pode sair "Marcos Antônio"."""
        texto, _ = self.sender._format_texto("Marcos", "Olá {nome}, tudo bem?")
        self.assertEqual(texto, "Olá Marcos, tudo bem?")
        self.assertNotIn("Antônio", texto)

    def test_nome_completo_na_planilha_sai_completo(self):
        """O inverso também vale: o que está na planilha é o que sai."""
        texto, _ = self.sender._format_texto("Marcos Antônio", "Olá {nome}!")
        self.assertEqual(texto, "Olá Marcos Antônio!")

    def test_placeholder_repetido_substitui_todas_ocorrencias(self):
        texto, _ = self.sender._format_texto("Ana", "{nome}, é você mesmo, {nome}?")
        self.assertEqual(texto, "Ana, é você mesmo, Ana?")

    def test_espacos_em_volta_do_nome_sao_removidos(self):
        texto, _ = self.sender._format_texto("  Marcos  ", "Olá {nome}!")
        self.assertEqual(texto, "Olá Marcos!")

    def test_nome_vazio_remove_o_placeholder(self):
        texto, _ = self.sender._format_texto("", "Olá {nome}, tudo bem?")
        self.assertEqual(texto, "Olá , tudo bem?")

    def test_nan_do_pandas_nao_vira_nome(self):
        """Célula vazia lida pelo pandas chega como 'nan' — não pode ir no texto."""
        texto, _ = self.sender._format_texto("nan", "Olá {nome}!")
        self.assertEqual(texto, "Olá !")

    def test_sem_placeholder_o_texto_e_intocado(self):
        original = "Promoção válida até amanhã.\nAproveite!"
        texto, regra = self.sender._format_texto("Marcos", original)
        self.assertEqual(texto, original)
        self.assertIn("texto puro", regra)

    def test_formatacao_do_whatsapp_preservada(self):
        original = "Olá *{nome}*, veja _isto_ e ~aquilo~."
        texto, _ = self.sender._format_texto("Ana", original)
        self.assertEqual(texto, "Olá *Ana*, veja _isto_ e ~aquilo~.")

    def test_quebras_de_linha_preservadas(self):
        original = "Oi {nome}!\n\n- Item 1\n- Item 2"
        texto, _ = self.sender._format_texto("Ana", original)
        self.assertEqual(texto, "Oi Ana!\n\n- Item 1\n- Item 2")

    def test_regra_registrada_no_log_menciona_a_planilha(self):
        """A regra vai para o log.txt: precisa dizer de onde veio o nome."""
        _, regra = self.sender._format_texto("Marcos", "Olá {nome}!")
        self.assertIn("coluna Nome da planilha", regra)
        self.assertIn("Marcos", regra)


# --------------------------------------------------------------------------- #
# 2. Mensagem global no loop de envio
# --------------------------------------------------------------------------- #

class TestMensagemGlobalNoLoop(BaseSenderTest):
    """
    A mensagem global é fallback da coluna `Mensagem`. O nome continua vindo da
    coluna `Nome` de CADA linha.
    """

    def _rodar(self, contatos, global_message, config=None):
        """
        Roda uma rodada de envio com o Selenium dublado e devolve a lista de
        textos finais, na ordem de envio.
        """
        cfg = {
            # Config atual: "quantas mensagens em quanto tempo". As chaves
            # antigas (msgs_por_rodada/total_rodadas) não existem mais.
            "total_msgs": len(contatos),
            "tempo_minutos": 1,
            "human_behavior": False,
        }
        cfg.update(config or {})

        linhas = []
        for c in contatos:
            linhas.append({
                "Nome": c.get("nome", ""),
                "Número": c.get("numero", "11999990000"),
                "Mensagem": c.get("mensagem", ""),
                "Arquivo": "",
                "Enviado": "",
                "DataEnvio": "",
                "Invalido": "",
            })

        estado = {"df": pd.DataFrame(linhas)}
        enviados = []

        sender = self.novo_sender(config=cfg, global_message=global_message)

        def fake_send(pessoa, numero, mensagem, arquivo=""):
            # Reaproveita a mesma montagem usada no envio real
            texto, _ = WhatsAppSender._format_texto(pessoa, mensagem)
            enviados.append({"pessoa": pessoa, "numero": numero, "texto": texto})
            return True

        sender._init_driver = lambda: FakeDriverEnvio()
        sender._load_contacts = lambda: estado["df"].copy()
        sender._save_contacts = lambda df: estado.update({"df": df})
        sender._send_message = fake_send
        sender._wait_for_business_hours = lambda: None
        sender.start()

        return enviados, estado["df"]

    def test_mensagem_vazia_usa_a_global(self):
        enviados, _ = self._rodar(
            [{"nome": "Marcos", "mensagem": ""}],
            global_message="Aviso importante para todos.",
        )
        self.assertEqual(enviados[0]["texto"], "Aviso importante para todos.")

    def test_global_com_placeholder_usa_o_nome_de_cada_linha(self):
        """
        O ponto central do relato: com a global ativa, cada contato recebe o
        nome da SUA linha na planilha.
        """
        enviados, _ = self._rodar(
            [
                {"nome": "Marcos", "numero": "11999990001", "mensagem": ""},
                {"nome": "Ana Paula", "numero": "11999990002", "mensagem": ""},
                {"nome": "", "numero": "11999990003", "mensagem": ""},
            ],
            global_message="Olá {nome}, temos novidade!",
        )
        textos = [e["texto"] for e in enviados]
        self.assertEqual(textos[0], "Olá Marcos, temos novidade!")
        self.assertEqual(textos[1], "Olá Ana Paula, temos novidade!")
        self.assertEqual(textos[2], "Olá , temos novidade!")

    def test_mensagem_propria_tem_prioridade_sobre_a_global(self):
        enviados, _ = self._rodar(
            [
                {"nome": "Marcos", "numero": "11999990001", "mensagem": "Mensagem só do Marcos."},
                {"nome": "Ana", "numero": "11999990002", "mensagem": ""},
            ],
            global_message="Texto global.",
        )
        self.assertEqual(enviados[0]["texto"], "Mensagem só do Marcos.")
        self.assertEqual(enviados[1]["texto"], "Texto global.")

    def test_global_inativa_deixa_contato_sem_mensagem_invalido(self):
        """Sem global e sem mensagem, o contato é marcado como inválido (não envia vazio)."""
        enviados, df = self._rodar(
            [{"nome": "Marcos", "mensagem": ""}],
            global_message="",
        )
        self.assertEqual(enviados, [])
        self.assertEqual((df["Invalido"] == "X").sum(), 1)

    def test_numero_enviado_e_o_da_linha(self):
        enviados, _ = self._rodar(
            [
                {"nome": "Marcos", "numero": "(19)99451-9934", "mensagem": ""},
                {"nome": "Ana", "numero": "11988887777", "mensagem": ""},
            ],
            global_message="Olá {nome}!",
        )
        self.assertEqual(enviados[0]["numero"], "19994519934")
        self.assertEqual(enviados[1]["numero"], "11988887777")


# --------------------------------------------------------------------------- #
# 3. Comportamento humano vale para a mensagem global
# --------------------------------------------------------------------------- #

class TestComportamentoHumanoNoEnvio(BaseSenderTest):
    """
    Relato do cliente: "mensagem global não tem comportamento humano, manda
    direto". O caminho é o mesmo de qualquer mensagem — o que muda é a config.
    """

    def _enviar(self, texto_mensagem, human, pessoa="Marcos"):
        sender = self.novo_sender(config={"human_behavior": human})
        driver = FakeDriverEnvio()
        sender._driver = driver
        sender._random_scroll = lambda: None
        sender._confirm_message_sent = lambda texto, timeout=6.0: True
        ok = sender._send_message(pessoa, "11999990001", texto_mensagem)
        return ok, driver

    def test_humano_ligado_digita_no_campo_e_nao_usa_texto_na_url(self):
        texto = "Olá {nome}, esta é a mensagem global."
        ok, driver = self._enviar(texto, human=True)
        self.assertTrue(ok)
        # A URL abre apenas a conversa, sem texto pré-preenchido
        self.assertIn("phone=5511999990001", driver.urls[0])
        self.assertNotIn("text=", driver.urls[0])
        # O texto foi digitado caractere por caractere no campo
        digitado = "".join(c for c in driver.input.calls[:-1])
        self.assertEqual(digitado, "Olá Marcos, esta é a mensagem global.")
        self.assertGreater(len(driver.input.calls), 10)

    def test_humano_desligado_manda_texto_pre_preenchido_na_url(self):
        texto = "Olá {nome}, esta é a mensagem global."
        ok, driver = self._enviar(texto, human=False)
        self.assertTrue(ok)
        self.assertIn("text=", driver.urls[0])
        # Sem digitação: só o ENTER
        self.assertEqual(len(driver.input.calls), 1)

    def test_mensagem_global_longa_com_humano_e_digitada(self):
        """
        Mensagem global longa (>200 chars) vai por palavra, mas continua sendo
        digitada — não pode virar uma única chamada (que é o que dá a impressão
        de "colou e mandou").
        """
        texto = "Olá {nome}! " + " ".join(["informacao"] * 60)
        ok, driver = self._enviar(texto, human=True)
        self.assertTrue(ok)
        chamadas_de_texto = driver.input.calls[:-1]
        self.assertGreater(len(chamadas_de_texto), 50)
        self.assertEqual("".join(chamadas_de_texto), texto.replace("{nome}", "Marcos"))


# --------------------------------------------------------------------------- #
# 4. Orçamento de digitação proporcional ao texto
# --------------------------------------------------------------------------- #

class TestOrcamentoDeDigitacao(BaseSenderTest):
    """
    O orçamento fixo de 25s fazia a mensagem longa ser despejada no meio da
    digitação. Agora ele cresce com o tamanho do texto.
    """

    def setUp(self):
        super().setUp()
        self.sender = self.novo_sender()

    def test_padrao_cresce_com_o_tamanho_do_texto(self):
        curto = self.sender._type_budget(50)
        longo = self.sender._type_budget(800)
        self.assertGreater(longo, curto)
        self.assertAlmostEqual(curto, 25 + 0.05 * 50, places=6)
        self.assertAlmostEqual(longo, 25 + 0.05 * 800, places=6)

    def test_teto_limita_texto_gigante(self):
        self.assertEqual(self.sender._type_budget(1_000_000), 180.0)

    def test_base_zero_desliga_o_orcamento(self):
        """Base 0 continua significando 'manda tudo de uma vez'."""
        self.sender.config = {"human_type_max_seconds": 0}
        self.assertEqual(self.sender._type_budget(500), 0.0)

    def test_parametros_configuraveis(self):
        self.sender.config = {
            "human_type_max_seconds": 10,
            "human_type_seconds_per_char": 0.1,
            "human_type_budget_cap": 30,
        }
        self.assertAlmostEqual(self.sender._type_budget(100), 20.0, places=6)
        self.assertEqual(self.sender._type_budget(10_000), 30.0)

    def test_teto_menor_que_a_base_nao_reduz_o_orcamento(self):
        self.sender.config = {
            "human_type_max_seconds": 40,
            "human_type_seconds_per_char": 0,
            "human_type_budget_cap": 5,
        }
        self.assertEqual(self.sender._type_budget(100), 40.0)

    def test_mensagem_longa_nao_e_despejada_de_uma_vez(self):
        """
        Regressão do sintoma relatado: com o orçamento proporcional, uma global
        longa é digitada inteira, palavra por palavra.
        """
        texto = " ".join(["informacao"] * 400)  # ~4400 chars
        self.assertGreater(len(texto), 200)
        campo = FakeInput()
        self.sender._human_type(campo, texto)
        self.assertEqual("".join(campo.calls), texto)
        self.assertEqual(len(campo.calls), 400)

    def test_texto_medio_e_digitado_palavra_por_palavra(self):
        texto = " ".join(["informacao"] * 65)  # ~714 chars
        campo = FakeInput()
        self.sender._human_type(campo, texto)
        self.assertEqual("".join(campo.calls), texto)
        self.assertEqual(len(campo.calls), 65)

    def test_orcamento_fixo_antigo_despejaria_o_resto(self):
        """
        Demonstra o comportamento anterior: orçamento fixo de 25s (sem parcela
        por caractere) estoura no meio e o resto vai numa única chamada — era
        isso que fazia a mensagem "aparecer inteira de uma vez".
        """
        texto = " ".join(["informacao"] * 400)
        self.sender.config = {
            "human_type_max_seconds": 25,
            "human_type_seconds_per_char": 0,
        }
        campo = FakeInput()
        self.sender._human_type(campo, texto)
        self.assertEqual("".join(campo.calls), texto)
        self.assertLess(len(campo.calls), 400)
        # A última chamada é o "despejo" do restante
        self.assertGreater(len(campo.calls[-1]), 20)


# --------------------------------------------------------------------------- #
# 5. Preview do texto no log de diagnóstico
# --------------------------------------------------------------------------- #

class TestPreviewDoTexto(BaseSenderTest):
    """O log precisa mostrar o texto real enviado, em uma linha e truncado."""

    def setUp(self):
        super().setUp()
        self.sender = self.novo_sender()

    def test_texto_curto_vai_inteiro(self):
        self.assertEqual(self.sender._preview_texto("Olá Marcos!"), "Olá Marcos!")

    def test_quebras_de_linha_viram_escape(self):
        self.assertEqual(self.sender._preview_texto("Oi\nMarcos"), "Oi\\nMarcos")
        self.assertNotIn("\n", self.sender._preview_texto("Oi\r\nMarcos"))

    def test_texto_longo_e_truncado_com_contagem(self):
        preview = self.sender._preview_texto("x" * 350, limite=300)
        self.assertTrue(preview.startswith("x" * 300))
        self.assertIn("+50 caracteres", preview)

    def test_texto_vazio_nao_quebra(self):
        self.assertEqual(self.sender._preview_texto(""), "")
        self.assertEqual(self.sender._preview_texto(None), "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
