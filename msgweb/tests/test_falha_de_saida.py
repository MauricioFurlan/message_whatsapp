"""
A bolha nasceu falhada: a mensagem NAO saiu da maquina.

O CASO (19/09/2026, medido com `sonda_bolha.py` contra o WhatsApp Web real)

    13:22:10  Enviando para Lucas (19994229146)... "Imagem grande..."
    13:22:54  OK Lucas - mensagem enviada com sucesso.   -> planilha: Enviado=X

E na tela, 12 minutos depois, a bolha daquele texto ainda carregava
`[data-testid="fail-container"]`: a mensagem nunca saiu. `_confirm_message_sent`
so' prova que o campo esvaziou, isto e', que a BOLHA foi criada — e o app
escrevia `Enviado=X` em cima disso.

Quatro invariantes, e cada uma corresponde a um jeito de esta verificacao
fazer estrago maior que o bug que ela conserta:

1. O que acusa e' o CRESCIMENTO da contagem, nunca a presenca. Uma falha de
   campanha anterior fica parada na conversa para sempre (a de 19/09 ficou),
   e a pergunta absoluta reprovaria todo contato que ja' tivesse uma.
2. Sem linha de base (-1, leitura falhou) nao se acusa. Sem o "antes" nao ha'
   comparacao, e inventa-la marcaria como invalido quem recebeu.
3. Ler nunca levanta. E' o caminho critico do envio.
4. Stop nao vira acusacao: o contato fica pendente pelo caminho do stop, que
   e' mais conservador que marca-lo invalido.
"""

import os
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import seletores
from whatsapp_sender import MensagemNaoSaiuError, WhatsAppSender


def _sender(driver):
    s = WhatsAppSender.__new__(WhatsAppSender)
    s._driver = driver
    s._stop_requested = False
    return s


class DriverFalso:
    """Devolve N elementos para o seletor de falha; conta as consultas."""

    def __init__(self, sequencia):
        # sequencia: quantas bolhas falhadas em cada consulta sucessiva
        self.sequencia = list(sequencia)
        self.consultas = []

    def find_elements(self, by, seletor):
        self.consultas.append(seletor)
        n = self.sequencia.pop(0) if self.sequencia else 0
        return [object()] * n


class TestContagem(unittest.TestCase):
    def test_conta_dentro_da_area_de_mensagens(self):
        d = DriverFalso([2])
        self.assertEqual(_sender(d)._contar_falhas_de_saida(), 2)
        # O escopo importa: `fail-container` solto na pagina pegaria outra
        # coisa que nao a conversa aberta.
        self.assertIn(seletores.get("area_mensagens"), d.consultas[0])
        self.assertIn(seletores.get("bolha_falha"), d.consultas[0])

    def test_leitura_quebrada_devolve_menos_um_e_nao_levanta(self):
        d = MagicMock()
        d.find_elements.side_effect = RuntimeError("stale")
        self.assertEqual(_sender(d)._contar_falhas_de_saida(), -1)


class TestDeteccao(unittest.TestCase):
    def test_bolha_falhada_nova_acusa(self):
        s = _sender(DriverFalso([1]))
        self.assertTrue(s._detectar_falha_de_saida(antes=0))

    def test_falha_antiga_parada_na_conversa_nao_acusa(self):
        # Tres bolhas falhadas antes, tres depois: nenhuma delas e' nossa.
        s = _sender(DriverFalso([3, 3, 3, 3, 3, 3, 3, 3, 3, 3]))
        s._interruptible_sleep = lambda _: False
        self.assertFalse(s._detectar_falha_de_saida(antes=3))

    def test_sem_linha_de_base_nao_acusa(self):
        d = DriverFalso([99])
        s = _sender(d)
        self.assertFalse(s._detectar_falha_de_saida(antes=-1))
        # E nem consulta: sem "antes" a pergunta nao existe.
        self.assertEqual(d.consultas, [])

    def test_stop_interrompe_sem_acusar(self):
        s = _sender(DriverFalso([0, 0, 0, 0]))
        s._interruptible_sleep = lambda _: True   # stop pedido
        self.assertFalse(s._detectar_falha_de_saida(antes=0))

    def test_desiste_dentro_da_janela(self):
        # Sem falha nenhuma, a verificacao termina sozinha — nao pode ficar
        # presa somando tempo a cada contato.
        s = _sender(DriverFalso([0] * 50))
        chamadas = []
        s._interruptible_sleep = lambda x: chamadas.append(x) or False
        s._TIMEOUT_FALHA_DE_SAIDA_SEG = 0.0
        self.assertFalse(s._detectar_falha_de_saida(antes=0))
        self.assertEqual(chamadas, [])


class TestDesfecho(unittest.TestCase):
    def test_excecao_existe_e_carrega_motivo(self):
        # O loop de envio distingue esta excecao das outras para escrever um
        # Motivo que diz a verdade: o contato NAO recebeu nada.
        e = MensagemNaoSaiuError("o WhatsApp marcou a mensagem com erro de envio")
        self.assertIn("erro de envio", str(e))
        self.assertIsInstance(e, RuntimeError)


if __name__ == "__main__":
    unittest.main(verbosity=2)
