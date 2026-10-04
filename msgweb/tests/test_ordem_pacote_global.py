"""
A ordem do pacote global: "anexo primeiro" (padrão) ou "texto primeiro".

Inverter a ordem parece trocar dois blocos de lugar, e não é. Na ordem padrão
o anexo vai antes e uma falha dele impede o texto: NADA chega, o contato vira
inválido e o ↺ reenvia tudo sem duplicar. Com o texto primeiro isso deixa de
valer — depois do ENTER o contato já recebeu algo. Os desfechos que este
arquivo fixa:

  - antes do ENTER nada mudou: Stop deixa pendente (False), bolha falhada é
    `MensagemNaoSaiuError` (inválido), e o anexo não chega a ser tentado;
  - texto NÃO confirmado não segue para o anexo: se ficou no campo, viraria
    legenda do anexo (ou seria apagado pela limpeza e só a imagem sairia,
    gravada como envio completo);
  - depois do texto, TODO desfecho do anexo — falha, Stop, bolha falhada,
    navegador fechado — vira `EnvioParcialError`. Regra do usuário
    (29/09/2026): o contato fica `Enviado=X` com o motivo, nunca inválido,
    porque o ↺ repetiria o texto.

A fiação ponta a ponta (qual contato recebe qual ordem, o que a planilha
grava) está em `tests/e2e/test_e2e_envio.py::TestOrdemDoPacoteGlobal`.

Executa com:
    venv\\Scripts\\python.exe -m unittest tests.test_ordem_pacote_global -v
"""
import json
import logging
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from whatsapp_sender import (  # noqa: E402
    ORDEM_ANEXO_PRIMEIRO,
    ORDEM_TEXTO_PRIMEIRO,
    AttachmentError,
    BrowserClosedError,
    EnvioParcialError,
    MensagemNaoSaiuError,
    WhatsAppSender,
)

logging.disable(logging.CRITICAL)


def montar(texto=WhatsAppSender._TEXTO_CONFIRMADO, anexo=None, pausa_ok=True,
           falha_de_saida=False, parado=False):
    """
    Sender com os dois passos trocados por gravadores.

    `texto` é o desfecho de `_enviar_texto` (ou uma exceção para levantar);
    `anexo` é uma exceção para `_enviar_anexos` levantar, `False` para Stop,
    ou None para dar certo.
    """
    s = WhatsAppSender.__new__(WhatsAppSender)
    s.passos = []

    def _texto(*_a, **_k):
        s.passos.append("texto")
        if isinstance(texto, Exception):
            raise texto
        return texto

    def _anexos(*_a, **_k):
        s.passos.append("anexo")
        if isinstance(anexo, Exception):
            raise anexo
        return anexo is not False

    s._enviar_texto = _texto
    s._enviar_anexos = _anexos
    s._pausa_entre_passos = lambda _human: pausa_ok
    s._contar_falhas_de_saida = lambda: 0
    s._detectar_falha_de_saida = lambda _antes: falha_de_saida
    s._should_stop = lambda: parado
    s._is_session_dead = lambda e: "invalid session id" in str(e)
    return s


def enviar(s):
    return s._enviar_texto_e_depois_anexos(
        "Olá Ana", ["promo.jpg"], "Ana", "5519990000001", human=True
    )


class TestAntesDoTextoSairNadaMuda(unittest.TestCase):
    def test_caminho_feliz_texto_depois_anexo(self):
        s = montar()
        self.assertTrue(enviar(s))
        self.assertEqual(s.passos, ["texto", "anexo"])

    def test_stop_antes_do_enter_deixa_pendente_e_nao_anexa(self):
        s = montar(texto=WhatsAppSender._TEXTO_PARADO)
        self.assertFalse(enviar(s))
        self.assertEqual(s.passos, ["texto"])

    def test_bolha_do_texto_falhada_segue_invalido_e_nao_anexa(self):
        """Nada chegou: é o `MensagemNaoSaiuError` de sempre, não parcial."""
        s = montar(texto=MensagemNaoSaiuError("erro de envio"))
        with self.assertRaises(MensagemNaoSaiuError):
            enviar(s)
        self.assertEqual(s.passos, ["texto"])


class TestTextoNaoConfirmado(unittest.TestCase):
    def test_nao_segue_para_o_anexo(self):
        """
        Texto que ficou no campo viraria legenda do anexo — ou seria apagado
        pela limpeza e só a imagem sairia, gravada como envio completo.
        """
        s = montar(texto=WhatsAppSender._TEXTO_NAO_CONFIRMADO)
        with self.assertRaises(EnvioParcialError) as ctx:
            enviar(s)
        self.assertEqual(s.passos, ["texto"])
        self.assertIn("anexo NÃO", str(ctx.exception))
        self.assertFalse(ctx.exception.sessao_morta)


class TestDepoisDoTextoTudoEParcial(unittest.TestCase):
    """O texto já chegou: nenhum desfecho pode devolver o contato à fila."""

    def test_anexo_falhou(self):
        s = montar(anexo=AttachmentError("o preview não abriu"))
        with self.assertRaises(EnvioParcialError) as ctx:
            enviar(s)
        self.assertIn("Só o texto chegou", str(ctx.exception))
        self.assertIn("preview", str(ctx.exception))
        self.assertFalse(ctx.exception.sessao_morta)

    def test_stop_entre_os_passos(self):
        s = montar(pausa_ok=False)
        with self.assertRaises(EnvioParcialError) as ctx:
            enviar(s)
        self.assertEqual(s.passos, ["texto"])
        self.assertIn("Parar", str(ctx.exception))

    def test_stop_durante_o_anexo(self):
        s = montar(anexo=False)
        with self.assertRaises(EnvioParcialError) as ctx:
            enviar(s)
        self.assertIn("Parar", str(ctx.exception))

    def test_stop_no_modal_embrulhado_em_attachment_error(self):
        """
        `_finalizar_envio_de_anexo` levanta RuntimeError no Stop e
        `_enviar_anexos` o embrulha em AttachmentError: o motivo tem de dizer
        que foi o Stop, não "o anexo falhou".
        """
        s = montar(anexo=AttachmentError("Parada solicitada"), parado=True)
        with self.assertRaises(EnvioParcialError) as ctx:
            enviar(s)
        self.assertIn("Parar", str(ctx.exception))

    def test_bolha_do_anexo_falhada(self):
        """O anexo agora é a última bolha: é ele quem precisa ser conferido."""
        s = montar(falha_de_saida=True)
        with self.assertRaises(EnvioParcialError) as ctx:
            enviar(s)
        self.assertIn("erro de envio", str(ctx.exception))

    def test_navegador_fechou_marca_e_manda_abortar(self):
        s = montar(anexo=BrowserClosedError("chrome not reachable"))
        with self.assertRaises(EnvioParcialError) as ctx:
            enviar(s)
        self.assertTrue(ctx.exception.sessao_morta)

    def test_sessao_morta_por_excecao_generica(self):
        s = montar(anexo=RuntimeError("invalid session id"))
        with self.assertRaises(EnvioParcialError) as ctx:
            enviar(s)
        self.assertTrue(ctx.exception.sessao_morta)

    def test_erro_inesperado_no_anexo(self):
        s = montar(anexo=ValueError("xyz"))
        with self.assertRaises(EnvioParcialError) as ctx:
            enviar(s)
        self.assertFalse(ctx.exception.sessao_morta)


class TestEscapaDoTryDoSendMessage(unittest.TestCase):
    def test_send_message_repassa_o_parcial(self):
        """
        `EnvioParcialError` é um RuntimeError. Sem o `except` próprio em
        `_send_message`, o `except Exception` genérico o engoliria e
        devolveria False — que o laço grava como INVÁLIDO, e o ↺ repetiria o
        texto. Exatamente o que a regra proíbe.
        """
        import inspect

        fonte = inspect.getsource(WhatsAppSender._send_message)
        parcial = fonte.find("except EnvioParcialError:")
        generico = fonte.find("except Exception as e:")
        self.assertNotEqual(parcial, -1)
        self.assertLess(parcial, generico)


class TestConstrutor(unittest.TestCase):
    def test_padrao_e_anexo_primeiro(self):
        s = WhatsAppSender("x.xlsx", {})
        self.assertEqual(s.global_order, ORDEM_ANEXO_PRIMEIRO)

    def test_ordem_desconhecida_cai_no_padrao(self):
        s = WhatsAppSender("x.xlsx", {}, global_order="legenda")
        self.assertEqual(s.global_order, ORDEM_ANEXO_PRIMEIRO)

    def test_texto_primeiro_e_aceito(self):
        s = WhatsAppSender("x.xlsx", {}, global_order=ORDEM_TEXTO_PRIMEIRO)
        self.assertEqual(s.global_order, ORDEM_TEXTO_PRIMEIRO)


class TestPersistencia(unittest.TestCase):
    """A ordem mora em `anexo_global.json`, junto do anexo."""

    def setUp(self):
        import app as app_mod

        self.app = app_mod
        self.tmp = Path(tempfile.mkdtemp(prefix="ordem_pacote_"))
        self.arquivo = self.tmp / "anexo_global.json"
        self._p = patch.object(app_mod, "ANEXO_GLOBAL_FILE", self.arquivo)
        self._p.start()
        self._salvo = (app_mod.state.global_attachment,
                       app_mod.state.global_attachment_active,
                       app_mod.state.global_order)

    def tearDown(self):
        self._p.stop()
        (self.app.state.global_attachment,
         self.app.state.global_attachment_active,
         self.app.state.global_order) = self._salvo
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _gravar(self, dados):
        self.arquivo.write_text(json.dumps(dados), encoding="utf-8")

    def test_sobrevive_a_fechar_e_abrir_o_programa(self):
        self.app.state.global_order = ORDEM_TEXTO_PRIMEIRO
        self.app._persistir_anexo_global()
        self.app.state.global_order = ORDEM_ANEXO_PRIMEIRO

        self.app._restaurar_anexo_global()
        self.assertEqual(self.app.state.global_order, ORDEM_TEXTO_PRIMEIRO)

    def test_arquivo_de_versao_anterior_sem_a_chave_fica_no_padrao(self):
        self.app.state.global_order = ORDEM_TEXTO_PRIMEIRO
        self._gravar({"arquivo": "", "ativo": False})
        self.app._restaurar_anexo_global()
        self.assertEqual(self.app.state.global_order, ORDEM_ANEXO_PRIMEIRO)

    def test_valor_desconhecido_fica_no_padrao(self):
        self._gravar({"arquivo": "", "ativo": False, "ordem": "legenda"})
        self.app._restaurar_anexo_global()
        self.assertEqual(self.app.state.global_order, ORDEM_ANEXO_PRIMEIRO)


if __name__ == "__main__":
    unittest.main(verbosity=2)
