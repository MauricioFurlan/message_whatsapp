"""
Testes de `_paste_text`: a mensagem entra no campo UMA vez.

Motivação (relato do cliente em 23/09/2026, versão 1.4.7): "está mandando a msg
duplicada, ele copia a mesma msg duas vezes e envia". O balão chegava no celular
do contato com o texto inteiro escrito duas vezes seguidas.

A causa está no único caminho que usa este método: mensagem com emoji fora do
BMP (o `send_keys` do ChromeDriver não transmite esses caracteres). O código
disparava um evento `paste` e, na MESMA linha de JavaScript, lia
`element.textContent` para decidir se precisava do `execCommand('insertText')`
de reserva. O campo do WhatsApp Web é um editor controlado por JavaScript: ele
aceita o `paste`, mas só escreve no DOM no seu próprio ciclo de atualização,
depois que o `dispatchEvent` retornou. A leitura, portanto, via o campo vazio e
o "reserva" entrava sempre — e logo em seguida o `paste` original também era
aplicado, resultando nas duas cópias.

O que estes testes fixam:
  1. Paste que demora a aparecer (o caso real) termina com UMA cópia — o
     insertText de reserva não pode entrar por impaciência.
  2. Paste ignorado pelo WhatsApp continua tendo o reserva: o insertText entra
     e o texto vai para o campo.
  3. Campo que ficou com o texto repetido é limpo e reescrito antes do ENTER.
  4. A comparação ignora espaço em branco — o campo devolve as quebras de linha
     remontadas à maneira dele, não como o texto entrou.

Executa com:
    venv\\Scripts\\python.exe -m unittest tests.test_colagem_duplicada -v
"""

import logging
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import whatsapp_sender  # noqa: E402
from whatsapp_sender import WhatsAppSender  # noqa: E402

logging.disable(logging.CRITICAL)

# Mensagem real do cliente, reduzida: emoji fora do BMP (o gatilho do caminho)
# e quebras de linha (o que o campo remonta do seu jeito).
TEXTO = "Ola, Adailton. Tudo bem?\nVoce pode contar comigo. \U0001f64f\n\nAbraco!"


class FakeTime:
    """Relógio falso: o tempo só anda quando alguém dorme."""

    def __init__(self):
        self.agora = 0.0

    def sleep(self, segundos):
        self.agora += float(segundos or 0)

    def monotonic(self):
        return self.agora

    def time(self):
        return self.agora


class CampoFalso:
    """O contenteditable do WhatsApp Web, com o texto que ele já desenhou."""

    def __init__(self):
        self.conteudo = ""
        self.cliques = 0

    def click(self):
        self.cliques += 1

    def send_keys(self, _valor):
        pass


class DriverComPaste:
    """
    Um navegador de mentira, com a parte do WhatsApp Web que causou o bug.

    O ponto do dublê é que o texto colado entra no DOM pela passagem do TEMPO
    (`atraso_do_paste` segundos no relógio falso), não por alguém ter lido o
    campo. É assim no navegador de verdade: o editor agenda a própria
    atualização, e nada que o Python faça a antecipa. Um dublê que aplicasse o
    paste na leitura seguinte esconderia justamente a corrida que se quer
    fixar.

    `aceita_paste=False` é o WhatsApp ignorando o evento sintético.

    O `execute_script` roda os trechos reconhecidos na ordem em que apareceriam
    no script — sem `return` entre eles — porque o código antigo mandava o
    `paste` e o `insertText` no MESMO script, e era a leitura síncrona do DOM
    entre os dois que decidia (errado) pela segunda inserção.
    """

    def __init__(self, campo, texto, relogio, atraso_do_paste=0.5,
                 aceita_paste=True):
        self.campo = campo
        self.texto = texto
        self.relogio = relogio
        self.atraso_do_paste = atraso_do_paste
        self.aceita_paste = aceita_paste
        self.paste_em = None
        self.leituras = 0
        self.inserts = 0
        self.pastes = 0

    def conteudo(self):
        """O que o campo mostra agora — aplicando um paste que já venceu."""
        if self.paste_em is not None and self.relogio.monotonic() >= self.paste_em:
            self.paste_em = None
            self.campo.conteudo += self.texto
        return self.campo.conteudo

    def execute_script(self, script, *args):
        if "ClipboardEvent" in script:
            self.pastes += 1
            if self.aceita_paste:
                # Aceito agora, escrito no DOM depois — o cerne do bug.
                self.paste_em = self.relogio.monotonic() + self.atraso_do_paste

        if "insertText" in script:
            self.inserts += 1
            self.campo.conteudo += args[1]

        if "innerText" in script:
            self.leituras += 1
            return self.conteudo()
        return None


def montar(driver):
    """Um sender sem navegador, com o relógio falso no lugar do `time`."""
    sender = WhatsAppSender.__new__(WhatsAppSender)
    sender._driver = driver
    sender.config = {}
    return sender


class TestColagemDuplicada(unittest.TestCase):
    def setUp(self):
        self.relogio = FakeTime()
        self._time_real = whatsapp_sender.time
        whatsapp_sender.time = self.relogio

    def tearDown(self):
        whatsapp_sender.time = self._time_real

    # `_send_message` dorme de 0,8s a 2,0s entre a digitação e o ENTER.
    # A pergunta que importa é o que estava no campo NAQUELE instante, não no
    # instante em que `_paste_text` retornou: é nessa fresta que uma cópia
    # atrasada da colagem cai por cima e vai junto no balão.
    PAUSA_ATE_O_ENTER = 2.0

    def _copias(self, driver, texto=TEXTO):
        """Quantas vezes a mensagem está no campo, do jeito que ela está."""
        alvo = WhatsAppSender._normalizar_composer(texto)
        return WhatsAppSender._normalizar_composer(driver.conteudo()).count(alvo)

    def _montar(self, **kw):
        campo = CampoFalso()
        driver = DriverComPaste(campo, TEXTO, self.relogio, **kw)
        sender = montar(driver)
        # `_clear_input_field` mexe em ActionChains/Keys num navegador real.
        sender._clear_input_field = lambda el: setattr(el, "conteudo", "")
        return campo, driver, sender

    def _ate_o_enter(self, sender, campo, texto=TEXTO):
        """
        A sequência real de `_send_message` para uma mensagem com emoji:
        digita, faz a pausa humana e só então confere o campo — a ordem é o que
        está sob teste, não um detalhe do arranjo.
        """
        sender._paste_text(campo, texto)
        self.relogio.sleep(self.PAUSA_ATE_O_ENTER)
        sender._garantir_texto_unico_no_campo(campo, texto)

    def test_paste_lento_nao_vira_mensagem_duplicada(self):
        """
        O CASO DO CLIENTE: o WhatsApp aceita o paste mas demora a desenhar.

        A versão antiga lia o campo na mesma linha de JS — antes de o editor
        ter escrito qualquer coisa —, via vazio, mandava o insertText, e o
        paste caía por cima depois: as duas cópias no mesmo balão. Aqui o
        Python espera o campo antes de decidir.
        """
        campo, driver, sender = self._montar(atraso_do_paste=1.5)
        self._ate_o_enter(sender, campo)

        self.assertEqual(self._copias(driver), 1,
                         "a mensagem precisa entrar no campo uma única vez")
        self.assertEqual(driver.inserts, 0,
                         "o insertText de reserva entrou mesmo com o paste funcionando")

    def test_paste_muito_lento_nao_duplica_depois_do_reserva(self):
        """
        Paste que vence DEPOIS do timeout: o reserva já entrou, e a cópia
        atrasada cai por cima. É o resto da corrida, e quem pega é a conferência
        do último instante — por isso ela não pode sair de `_send_message`.
        """
        campo, driver, sender = self._montar(
            atraso_do_paste=WhatsAppSender._PASTE_TIMEOUT_SEG + 2)
        self._ate_o_enter(sender, campo)

        self.assertEqual(self._copias(driver), 1,
                         "cópia atrasada do paste precisa ser limpa antes do ENTER")

    def test_paste_ignorado_ainda_usa_o_reserva(self):
        """O reserva não foi removido: sem ele, mensagem com emoji não sai."""
        campo, driver, sender = self._montar(aceita_paste=False)
        self._ate_o_enter(sender, campo)

        self.assertEqual(self._copias(driver), 1)
        self.assertEqual(driver.inserts, 1,
                         "o insertText precisa entrar quando o paste é ignorado")

    def test_campo_que_ficou_duplicado_e_reescrito(self):
        """
        Rede de segurança: o texto repetido é apagado antes do ENTER.

        Vale para qualquer origem da repetição, não só para a corrida acima.
        """
        campo, driver, sender = self._montar()
        # Campo que já chega sujo com a mensagem: a colagem soma a 2ª cópia.
        campo.conteudo = TEXTO
        self._ate_o_enter(sender, campo)

        self.assertEqual(self._copias(driver), 1,
                         "campo duplicado precisa ser limpo e reescrito")

    def test_send_message_confere_o_campo_antes_do_enter(self):
        """
        A conferência do último instante mora em `_send_message`, entre a pausa
        humana e o ENTER. Fora dali ela não cobre a colagem atrasada, e os
        testes acima passariam a medir uma sequência que o envio não executa.
        """
        import inspect

        fonte = inspect.getsource(WhatsAppSender._send_message)
        guarda = fonte.find("_garantir_texto_unico_no_campo")
        enter = fonte.find("input_field.send_keys(Keys.ENTER)")

        self.assertNotEqual(guarda, -1,
                            "_send_message parou de conferir o campo antes do ENTER")
        self.assertNotEqual(enter, -1, "o ENTER do envio de texto sumiu de _send_message")
        self.assertLess(guarda, enter,
                        "a conferência precisa vir ANTES do ENTER para valer de algo")

    def test_legenda_do_anexo_tambem_e_conferida(self):
        """
        A legenda do modal de anexo passa pelo mesmo `_paste_text` e é enviada
        por um clique logo depois — a mesma fresta, o mesmo remédio.

        ATENÇÃO: este caminho está DORMENTE hoje. `all_images` é uma constante
        `False` em `_send_message`, então `_type_caption_in_modal` não chega a
        ser chamado e o texto sempre sai como mensagem separada. A conferência
        fica aqui porque é barata e porque o dia em que a legenda voltar a ser
        usada é justamente o dia em que ninguém vai lembrar desta corrida.
        """
        import inspect

        fonte = inspect.getsource(WhatsAppSender._type_caption_in_modal)
        self.assertIn("_garantir_texto_unico_no_campo", fonte,
                      "_type_caption_in_modal parou de conferir a legenda")

    def test_normalizacao_ignora_quebras_de_linha(self):
        """
        O campo remonta as quebras de linha; a contagem não pode depender delas.

        Sem isto, o texto voltaria como "não encontrado" e o reserva entraria
        por cima do paste — exatamente o bug, por outro caminho.
        """
        n = WhatsAppSender._normalizar_composer
        self.assertEqual(n("Ola\nmundo"), n("Ola mundo"))
        self.assertEqual(n("a\n\nb  c"), "abc")
        self.assertEqual(n(""), "")
        self.assertEqual(n(None), "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
