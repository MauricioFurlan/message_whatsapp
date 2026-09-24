"""
O campo de mensagem tem que estar VAZIO antes de o anexo ser adicionado.

Relato de teste (23/09/2026): a conversa abriu com um texto já escrito no campo
de mensagem, o anexo foi adicionado, e o texto antigo foi embarcado junto com o
arquivo — para um contato que nunca deveria recebê-lo.

A causa é de ordem, não de falta de código: `_clear_input_field` já era chamado,
só que no **Passo 2**, depois de o anexo ter sido enviado. Protegia a digitação
e não o anexo. O WhatsApp Web promove o que estiver no campo de mensagem a
**legenda do modal de anexo**, e nada no caminho do anexo tocava nesse campo —
`_type_caption_in_modal` sequer chega a ser chamado hoje (`all_images` é uma
constante `False`), então o anexo é enviado com a legenda que o modal herdou.

Rascunho aí não é acidente raro: um envio interrompido entre `_human_type` e
`_confirm_message_sent` deixa exatamente isso para trás — o mesmo estado que a
varredura precisa distinguir (o "draft guard" de `linha_conversa.py`) — além do
que o próprio usuário pode ter digitado na conversa.

Executa com:
    venv\\Scripts\\python.exe -m unittest tests.test_rascunho_no_anexo -v
"""

import logging
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import seletores  # noqa: E402
import whatsapp_sender  # noqa: E402
from whatsapp_sender import AttachmentError, WhatsAppSender  # noqa: E402

logging.disable(logging.CRITICAL)


class CampoFalso:
    def __init__(self, conteudo=""):
        self.conteudo = conteudo
        self.cliques = 0

    def click(self):
        self.cliques += 1


class DriverFalso:
    """Devolve o campo de mensagem e lê o que está escrito nele."""

    def __init__(self, campo, campo_some=False):
        self.campo = campo
        self.campo_some = campo_some
        self.buscas = []

    def find_element(self, by, selector):
        self.buscas.append(selector)
        if self.campo_some:
            raise Exception("no such element")
        return self.campo

    def execute_script(self, script, *args):
        if "innerText" in script:
            return args[0].conteudo
        return None


def montar(campo, campo_some=False, limpeza_funciona=True):
    s = WhatsAppSender.__new__(WhatsAppSender)
    s._driver = DriverFalso(campo, campo_some)
    s.config = {}
    s.log_callback = lambda _m: None
    s.limpezas = 0

    def _limpar(el):
        s.limpezas += 1
        if limpeza_funciona:
            el.conteudo = ""

    s._clear_input_field = _limpar
    return s


class TestCampoVazioAntesDoAnexo(unittest.TestCase):
    def test_rascunho_e_apagado(self):
        """O caso relatado: texto já no campo quando a conversa abre."""
        campo = CampoFalso("texto que o usuario tinha deixado escrito")
        s = montar(campo)

        s._exigir_campo_vazio_antes_do_anexo("Ana")

        self.assertEqual(campo.conteudo, "")
        self.assertEqual(s.limpezas, 1)

    def test_campo_vazio_nao_gasta_limpeza(self):
        """
        A limpeza custa clique + Ctrl+A + Delete e roda por contato. Sem
        rascunho não há o que apagar.
        """
        campo = CampoFalso("")
        s = montar(campo)

        s._exigir_campo_vazio_antes_do_anexo("Ana")

        self.assertEqual(s.limpezas, 0)

    def test_nao_conseguir_limpar_impede_o_envio(self):
        """
        Desfecho conservador de propósito: contato inválido (recuperável pelo
        botão de reenviar) em vez de mandar para o contato de alguém um texto
        que não era para ele, que não tem desfazer.
        """
        campo = CampoFalso("rascunho grudento")
        s = montar(campo, limpeza_funciona=False)

        with self.assertRaises(AttachmentError) as ctx:
            s._exigir_campo_vazio_antes_do_anexo("Ana")

        self.assertIn("campo de mensagem", str(ctx.exception))
        self.assertEqual(s.limpezas, WhatsAppSender._LIMPEZA_MAX_TENTATIVAS)

    def test_campo_ausente_nao_derruba_o_anexo(self):
        """
        Sem campo não há rascunho para vazar. Quem reclama da falta do campo é
        o Passo 2, que é quem realmente precisa dele.
        """
        s = montar(CampoFalso(""), campo_some=True)
        s._exigir_campo_vazio_antes_do_anexo("Ana")  # não levanta

    def test_procura_o_campo_pelo_seletor_publicado(self):
        """Nada de CSS literal aqui: a tabela de seletores é quem manda."""
        campo = CampoFalso("x")
        s = montar(campo)
        s._exigir_campo_vazio_antes_do_anexo("Ana")

        self.assertIn(seletores.get("campo_mensagem"), s._driver.buscas)


class TestOrdem(unittest.TestCase):
    """
    O bug era de ORDEM: limpar depois do anexo não serve para nada.

    Por isso a garantia é estrutural — a limpeza tem que vir antes do
    `_send_media` dentro do `_send_message`.
    """

    def test_limpeza_vem_antes_do_envio_do_anexo(self):
        import inspect

        fonte = inspect.getsource(WhatsAppSender._send_message)
        limpeza = fonte.find("_exigir_campo_vazio_antes_do_anexo")
        anexo = fonte.find("self._send_media(")

        self.assertNotEqual(limpeza, -1,
                            "_send_message parou de limpar o campo antes do anexo")
        self.assertNotEqual(anexo, -1, "a chamada de _send_media sumiu de _send_message")
        self.assertLess(
            limpeza, anexo,
            "a limpeza voltou para depois do anexo — é exatamente o bug relatado")


if __name__ == "__main__":
    unittest.main(verbosity=2)
