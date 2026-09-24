# -*- coding: utf-8 -*-
"""
Testes do alarme de entrega (BRAINSTORM_IA.md #7c).

O aviso de lentidão que já existe cobre "a conversa não abre": custa relógio.
Este cobre outra coisa, e mais grave: a mensagem **sai e não chega**, que é a
assinatura do número sendo limitado ou bloqueado pelo WhatsApp. É o risco
existencial do produto, e até aqui nada o detectava — o cliente só descobria
abrindo a planilha no dia seguinte com tudo não entregue.

O que estes testes fixam:

  1. **Não pode dar alarme falso.** Logo depois do envio é NORMAL a mensagem
     estar só "enviada". Sem a idade mínima, todo envio dispararia o popup.
  2. **Uma resposta prova a entrega.** Ele não teria como responder sem
     receber — nunca contar isso como não entregue.
  3. **O popup abre uma vez.** O status é rebroadcast a cada 5s; sem o `seq`,
     o popup reabriria para sempre, inclusive logo após o usuário fechá-lo.
  4. **A leitura na pausa NUNCA derruba um envio.** Qualquer exceção do
     Selenium ali dentro é engolida.
  5. **A leitura não estoura a pausa** nem segura o botão Parar — estourar
     atrasaria a próxima rajada e faria o envio passar do tempo prometido.
  6. **Contato inválido não entra**, e uma extração quebrada não sobrescreve
     o que já se sabia.

Rodar:
    python -m unittest tests.test_alerta_entrega -v
"""

import os
import sys
import time
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import linha_conversa
from whatsapp_sender import WhatsAppSender


def sender() -> WhatsAppSender:
    s = WhatsAppSender.__new__(WhatsAppSender)
    import threading

    s._lock = threading.RLock()
    s._stop_event = threading.Event()
    s._driver = MagicMock()
    s._enviados_nesta_execucao = []
    s._estado_de_entrega = {}
    s._alerta_entrega = None
    s._alerta_entrega_em = 0
    s._log = MagicMock()
    return s


def linha(numero, estado):
    return {"numero": numero, "estado": estado}


def envia(s, quantos, idade_seg=999, prefixo="1999000"):
    """Registra `quantos` envios com a idade dada."""
    for i in range(quantos):
        num = f"{prefixo}{i:04d}"
        s._registrar_envio_para_entrega(num, f"Contato {i}")
        s._estado_de_entrega[num]["enviado_em"] = time.time() - idade_seg
    return [f"{prefixo}{i:04d}" for i in range(quantos)]


class TestDisparoDoAlarme(unittest.TestCase):
    def test_dispara_quando_o_bloco_nao_foi_entregue(self):
        s = sender()
        nums = envia(s, 10)
        s._absorver_leitura_de_entrega(
            [linha(n, linha_conversa.NAO_ENTREGUE) for n in nums]
        )
        self.assertIsNotNone(s._alerta_entrega)
        self.assertEqual(s._alerta_entrega["percentual"], 100)
        self.assertEqual(s._alerta_entrega["nao_entregues"], 10)

    def test_nao_dispara_com_entregas_normais(self):
        s = sender()
        nums = envia(s, 10)
        s._absorver_leitura_de_entrega([linha(n, linha_conversa.ENTREGUE) for n in nums])
        self.assertIsNone(s._alerta_entrega)

    def test_mensagem_recem_enviada_nao_conta(self):
        """
        Sem a idade mínima, TODO envio dispararia o alarme: logo depois de
        mandar, "ainda não entregue" é o estado normal, não sintoma de nada.
        """
        s = sender()
        nums = envia(s, 10, idade_seg=5)
        s._absorver_leitura_de_entrega(
            [linha(n, linha_conversa.NAO_ENTREGUE) for n in nums]
        )
        self.assertIsNone(s._alerta_entrega)

    def test_amostra_pequena_nao_dispara(self):
        """Duas mensagens não entregues no começo não dizem nada."""
        s = sender()
        nums = envia(s, 3)
        s._absorver_leitura_de_entrega(
            [linha(n, linha_conversa.NAO_ENTREGUE) for n in nums]
        )
        self.assertIsNone(s._alerta_entrega)

    def test_resposta_prova_a_entrega(self):
        """Ele não teria como responder sem receber."""
        s = sender()
        nums = envia(s, 10)
        s._absorver_leitura_de_entrega(
            [linha(n, linha_conversa.ULTIMA_DELES) for n in nums]
        )
        self.assertIsNone(s._alerta_entrega)

    def test_lido_conta_como_entregue(self):
        s = sender()
        nums = envia(s, 10)
        s._absorver_leitura_de_entrega([linha(n, linha_conversa.LIDO) for n in nums])
        self.assertIsNone(s._alerta_entrega)

    def test_falha_de_envio_conta_como_nao_entregue(self):
        s = sender()
        nums = envia(s, 10)
        s._absorver_leitura_de_entrega([linha(n, linha_conversa.FALHOU) for n in nums])
        self.assertIsNotNone(s._alerta_entrega)
        self.assertEqual(s._alerta_entrega["falharam"], 10)

    def test_maioria_entregue_nao_dispara(self):
        """A taxa é o critério, não a existência de um caso ruim."""
        s = sender()
        nums = envia(s, 10)
        leitura = [linha(n, linha_conversa.ENTREGUE) for n in nums[:7]]
        leitura += [linha(n, linha_conversa.NAO_ENTREGUE) for n in nums[7:]]
        s._absorver_leitura_de_entrega(leitura)
        self.assertIsNone(s._alerta_entrega)

    def test_alarme_avisa_o_usuario_no_log(self):
        s = sender()
        nums = envia(s, 10)
        s._absorver_leitura_de_entrega(
            [linha(n, linha_conversa.NAO_ENTREGUE) for n in nums]
        )
        texto = " ".join(str(c) for c in s._log.call_args_list).lower()
        self.assertIn("limitando", texto)
        self.assertIn("parar", texto)


class TestPopupAbreUmaVez(unittest.TestCase):
    def test_seq_nao_muda_sem_casos_novos(self):
        """
        O status é rebroadcast a cada 5s. Sem isto, o popup reabriria para
        sempre — inclusive no instante seguinte ao usuário fechá-lo.
        """
        s = sender()
        nums = envia(s, 10)
        leitura = [linha(n, linha_conversa.NAO_ENTREGUE) for n in nums]
        s._absorver_leitura_de_entrega(leitura)
        seq = s._alerta_entrega["seq"]

        for _ in range(5):
            s._absorver_leitura_de_entrega(leitura)
        self.assertEqual(s._alerta_entrega["seq"], seq)

    def test_rearma_depois_de_acumular_casos_novos(self):
        s = sender()
        nums = envia(s, 10)
        s._absorver_leitura_de_entrega(
            [linha(n, linha_conversa.NAO_ENTREGUE) for n in nums]
        )
        seq = s._alerta_entrega["seq"]

        novos = envia(s, 6, prefixo="1998000")
        s._absorver_leitura_de_entrega(
            [linha(n, linha_conversa.NAO_ENTREGUE) for n in nums + novos]
        )
        self.assertGreater(s._alerta_entrega["seq"], seq)


class TestCasamentoDeLinhas(unittest.TestCase):
    def test_conversa_que_nao_e_da_campanha_e_ignorada(self):
        """
        A lista traz as conversas pessoais do cliente. Só o que ESTE envio
        mandou tem algo a dizer sobre a entrega desta campanha.
        """
        s = sender()
        envia(s, 10)
        s._absorver_leitura_de_entrega(
            [linha("11988887777", linha_conversa.NAO_ENTREGUE)]
        )
        self.assertIsNone(s._alerta_entrega)

    def test_linha_sem_numero_e_ignorada(self):
        """Contato salvo na agenda aparece pelo nome, sem número na linha."""
        s = sender()
        envia(s, 10)
        s._absorver_leitura_de_entrega([linha("", linha_conversa.NAO_ENTREGUE)])
        self.assertIsNone(s._alerta_entrega)

    def test_extracao_quebrada_nao_apaga_o_que_ja_se_sabia(self):
        """
        INDETERMINADO não é evidência. Gravá-lo perderia uma leitura boa
        anterior e poderia desarmar um alarme legítimo.
        """
        s = sender()
        nums = envia(s, 10)
        s._absorver_leitura_de_entrega([linha(n, linha_conversa.ENTREGUE) for n in nums])
        s._absorver_leitura_de_entrega(
            [linha(n, linha_conversa.INDETERMINADO) for n in nums]
        )
        for n in nums:
            self.assertEqual(s._estado_de_entrega[n]["estado"], linha_conversa.ENTREGUE)

    def test_envio_sem_numero_nao_entra_na_conta(self):
        s = sender()
        s._registrar_envio_para_entrega("", "Sem número")
        s._registrar_envio_para_entrega("abc", "Sem dígitos")
        self.assertEqual(s._estado_de_entrega, {})

    def test_reenvio_do_mesmo_numero_nao_duplica(self):
        s = sender()
        s._registrar_envio_para_entrega("19995947333", "João")
        s._registrar_envio_para_entrega("19995947333", "João")
        self.assertEqual(len(s._enviados_nesta_execucao), 1)


class TestLeituraNaPausa(unittest.TestCase):
    def test_pausa_curta_nao_e_usada(self):
        """
        Com a janela apertada, _generate_burst_plan cai no fallback e todo
        intervalo vira DELAY_INTRA_MIN. A leitura é oportunista, não obrigatória.
        """
        s = sender()
        envia(s, 10)
        with patch.object(linha_conversa, "ler_linhas") as ler:
            s._verificar_entregas_na_pausa(10)
        ler.assert_not_called()

    def test_pausa_folgada_le(self):
        s = sender()
        envia(s, 10)
        with patch.object(linha_conversa, "ler_linhas", return_value=[]) as ler:
            s._verificar_entregas_na_pausa(200)
        ler.assert_called_once()

    def test_excecao_na_leitura_nunca_derruba_o_envio(self):
        """
        A regra mais importante daqui. Um StaleElementReference cascateando
        para o laço de envio marcaria contato como inválido ou mataria a
        rajada — a leitura é um bônus, nunca um risco.
        """
        s = sender()
        envia(s, 10)
        from selenium.common.exceptions import StaleElementReferenceException

        for erro in (StaleElementReferenceException(), RuntimeError("qualquer"), KeyError("x")):
            with self.subTest(erro=type(erro).__name__):
                with patch.object(linha_conversa, "ler_linhas", side_effect=erro):
                    s._verificar_entregas_na_pausa(200)  # não pode levantar

    def test_parada_pedida_interrompe_antes_de_ler(self):
        """Senão o botão Parar durante a pausa espera a leitura terminar."""
        s = sender()
        envia(s, 10)
        s._stop_event.set()
        with patch.object(linha_conversa, "ler_linhas") as ler:
            s._verificar_entregas_na_pausa(200)
        ler.assert_not_called()

    def test_sem_envios_nao_le(self):
        s = sender()
        with patch.object(linha_conversa, "ler_linhas") as ler:
            s._verificar_entregas_na_pausa(200)
        ler.assert_not_called()

    def test_sem_driver_nao_le(self):
        s = sender()
        envia(s, 10)
        s._driver = None
        with patch.object(linha_conversa, "ler_linhas") as ler:
            s._verificar_entregas_na_pausa(200)
        ler.assert_not_called()

    def test_leitura_lenta_nao_estoura_a_pausa(self):
        """
        Estourar a pausa atrasa a próxima rajada e faz o envio passar do tempo
        prometido — o orçamento do plano é um total, não uma sugestão.
        """
        s = sender()
        nums = envia(s, 10)

        def devagar(*_a, **_kw):
            time.sleep(0.3)
            return [linha(n, linha_conversa.NAO_ENTREGUE) for n in nums]

        # Baixa o piso da pausa para que ESTE teste chegue de fato ao
        # orçamento — senão ele passaria por ser barrado antes, sem nunca
        # exercitar o que se quer verificar.
        s._VERIFICACAO_PAUSA_MINIMA_SEG = 0.1
        with patch.object(linha_conversa, "ler_linhas", side_effect=devagar) as ler:
            s._verificar_entregas_na_pausa(1.0)  # orçamento = 25% = 0,25s

        ler.assert_called_once()  # leu de verdade...
        self.assertIsNone(s._alerta_entrega)  # ...e descartou por ter estourado

    def test_leitura_dentro_do_orcamento_e_aproveitada(self):
        """Contraparte do teste acima: no prazo, o resultado é usado."""
        s = sender()
        nums = envia(s, 10)
        s._VERIFICACAO_PAUSA_MINIMA_SEG = 0.1
        with patch.object(
            linha_conversa,
            "ler_linhas",
            return_value=[linha(n, linha_conversa.NAO_ENTREGUE) for n in nums],
        ):
            s._verificar_entregas_na_pausa(1.0)
        self.assertIsNotNone(s._alerta_entrega)


class TestContatoSalvoNaAgenda(unittest.TestCase):
    """
    Contato salvo aparece na lista pelo NOME, sem número, e o casamento era só
    por número. Isso não errava a leitura — simplesmente mantinha esses
    contatos FORA da amostra, e a amostra é o que decide se o alarme dispara:
    uma lista majoritariamente de contatos salvos podia nunca alcançar
    `_ENTREGA_AMOSTRA_MINIMA` e calar o alarme inteiro.
    """

    def _linha_por_nome(self, titulo, estado):
        return {"numero": "", "titulo": titulo, "estado": estado}

    def test_linha_sem_numero_casa_pelo_nome_do_contato(self):
        s = sender()
        s._registrar_envio_para_entrega("19995947333", "Isis Campos")
        s._estado_de_entrega["19995947333"]["enviado_em"] = time.time() - 999
        s._absorver_leitura_de_entrega(
            [self._linha_por_nome("Isis Campos", linha_conversa.NAO_ENTREGUE)]
        )
        self.assertEqual(
            s._estado_de_entrega["19995947333"]["estado"],
            linha_conversa.NAO_ENTREGUE,
        )

    def test_contato_salvo_entra_na_amostra_do_alarme(self):
        """A regressão que importa: sem isso o alarme nunca junta amostra."""
        s = sender()
        nomes = [f"Contato Salvo {i}" for i in range(10)]
        for i, nome in enumerate(nomes):
            num = f"1999000{i:04d}"
            s._registrar_envio_para_entrega(num, nome)
            s._estado_de_entrega[num]["enviado_em"] = time.time() - 999
        s._absorver_leitura_de_entrega(
            [self._linha_por_nome(n, linha_conversa.NAO_ENTREGUE) for n in nomes]
        )
        self.assertIsNotNone(s._alerta_entrega)
        self.assertEqual(s._alerta_entrega["nao_entregues"], 10)

    def test_nome_repetido_nao_serve_de_prova(self):
        """
        Dois envios para o mesmo nome: atribuir a entrega a um deles empurraria
        o alarme para um lado sem deixar rastro nenhum.
        """
        s = sender()
        for num in ("19995947333", "19994229146"):
            s._registrar_envio_para_entrega(num, "João")
            s._estado_de_entrega[num]["enviado_em"] = time.time() - 999
        s._absorver_leitura_de_entrega(
            [self._linha_por_nome("João", linha_conversa.NAO_ENTREGUE)]
        )
        for num in ("19995947333", "19994229146"):
            self.assertIsNone(s._estado_de_entrega[num]["estado"])

    def test_conversa_de_fora_da_campanha_continua_ignorada(self):
        s = sender()
        s._registrar_envio_para_entrega("19995947333", "Isis Campos")
        s._absorver_leitura_de_entrega(
            [self._linha_por_nome("Tia Marta", linha_conversa.ULTIMA_DELES)]
        )
        self.assertIsNone(s._estado_de_entrega["19995947333"]["estado"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
