"""
Testes do que faz o envio estourar a janela de tempo quando a rede está ruim.

Motivação — envio real do cliente em 02/09/2026 (`log.txt`), configurado como
"40 mensagens em 45 minutos" e concluído em **2h 0min**:

  22 envios bem-sucedidos ....................  45min  (122s cada, em média)
  16 timeouts de abertura de conversa ........  60min  (224s cada)
  esperas entre mensagens dentro da leva .....  11min
  pausas entre as levas (o que o plano prevê) .. 9min

As pausas planejadas foram cumpridas certinho — o plano de rajadas não errou.
Quem errou foi a estimativa, por dois motivos independentes:

  1. Ela contava só digitação e anexos. Mas o intervalo entre "Enviando para" e
     o início da digitação foi de 41-58s (mediana 46s) nos envios que abriram na
     primeira tentativa. Prevendo ~25s por contato onde o real eram ~122s, a
     conta dava "16min 46s de envio" para algo que levou quase 2h.

  2. Nada previa contato que FALHA. Cada timeout custa ~3,7min e, como contato
     inválido não gasta vaga da rajada (invariante deliberada, ver
     _generate_burst_plan), a leva puxa outro contato no lugar — a leva 2, de
     "7 mensagens seguidas", sozinha levou 53 minutos.

O (1) não tem como ser previsto contato a contato, mas tem ordem de grandeza
conhecida: virou TEMPO_ESTIMADO_ABERTURA_CHAT. O (2) só dá para saber durante o
envio, então virou um aviso em tempo real que o painel mostra em popup.

O que estes testes fixam:
  1. a estimativa soma a abertura da conversa, nos dois modos de digitação;
  2. a configuração exata do cliente (40 msgs / 45min) agora sai como inviável
     ANTES de começar, em vez de só aparecer no log depois de 2h;
  3. o aviso de lentidão não dispara com amostra pequena nem com rede boa;
  4. dispara ao cruzar a taxa de falha, com número, percentual e atraso;
  5. não repete a cada falha (só a cada _ALERTA_REARME_A_CADA novas), e
  6. sai no get_status(), que é o canal que sobrevive a um F5.

Executa com:
    venv\\Scripts\\python.exe -m unittest tests.test_aviso_lentidao -v
"""

import logging
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd  # noqa: E402

from whatsapp_sender import WhatsAppSender  # noqa: E402


def novo_sender(**config):
    cfg = {"human_behavior": False}
    cfg.update(config)
    return WhatsAppSender(
        excel_path="fake.xlsx",
        config=cfg,
        log_callback=lambda msg: None,
    )


class EstimativaIncluiAberturaTest(unittest.TestCase):
    """(1) e (2): a estimativa passa a contar o que o envio realmente gasta."""

    def setUp(self):
        logging.getLogger("whatsapp_sender_file").setLevel(logging.CRITICAL)

    def test_abertura_entra_sem_digitacao_humanizada(self):
        sender = novo_sender(human_behavior=False)
        self.assertEqual(
            sender._estimar_tempo_envio_individual("Oi", ""),
            WhatsAppSender.TEMPO_ESTIMADO_ABERTURA_CHAT + 5.0,
        )

    def test_abertura_entra_tambem_com_digitacao_humanizada(self):
        """
        `driver.get` e a espera do #pane-side acontecem nos dois modos — a
        abertura não pode ficar pendurada no comportamento humano.
        """
        sender = novo_sender(human_behavior=True)
        texto = "Olá, tudo bem?" * 10
        estimado = sender._estimar_tempo_envio_individual(texto, "")
        self.assertEqual(
            estimado,
            sender._type_budget(len(texto)) + WhatsAppSender.TEMPO_ESTIMADO_ABERTURA_CHAT,
        )

    def test_anexo_continua_somando(self):
        sender = novo_sender(human_behavior=False)
        base = WhatsAppSender.TEMPO_ESTIMADO_ABERTURA_CHAT + 5.0
        self.assertEqual(
            sender._estimar_tempo_envio_individual("Oi", "a.png, b.png"),
            base + 2 * WhatsAppSender.TEMPO_ESTIMADO_POR_ANEXO,
        )

    def test_config_do_cliente_agora_sai_como_inviavel(self):
        """
        O caso exato do relato: 40 mensagens de ~240 caracteres, com digitação
        humanizada, em 45 minutos. Antes o app aceitava calado e o envio levava
        2h; agora o aviso tem que sair antes de começar.
        """
        texto = (
            "Olá {nome}, tudo bem?\n\nEstou passando para reafirmar que NÃO sou "
            "candidato a nada nessa eleição.\n\nSigo como vereador, trabalhando "
            "por Indaiatuba.\n\nSe você tiver alguma sugestão de melhoria para "
            "nossa cidade, pode me enviar, estou por aqui."
        )
        pending = pd.DataFrame(
            [{"Nome": f"P{i}", "Número": f"1999422{i:04d}", "Mensagem": texto, "Arquivo": ""}
             for i in range(40)]
        )
        sender = novo_sender(human_behavior=True)

        orcamento = sender._calcular_orcamento_de_pausas(pending, 40, 45)

        self.assertTrue(
            orcamento["inviavel"],
            "40 mensagens longas em 45min precisa avisar o usuário antes de iniciar",
        )
        # E o motivo tem que ser o tempo de envio comendo a janela inteira,
        # não um arredondamento de fronteira.
        self.assertGreater(orcamento["tempo_de_envio_seg"], 40 * 60)


class CustoDaFalhaTest(unittest.TestCase):
    def test_custo_bate_com_a_ordem_de_grandeza_medida(self):
        """
        Medição do log de 02/09/2026: 224s em média (n=16) por contato cuja
        conversa nunca abriu. A fórmula pode ficar abaixo disso (é o lado
        seguro), mas não pode desandar em ordem de grandeza.
        """
        custo = WhatsAppSender._custo_estimado_de_uma_falha()
        self.assertGreater(custo, 150)
        self.assertLess(custo, 224)


class AvisoDeLentidaoTest(unittest.TestCase):
    """(3) a (6): quando o popup de conexão ruim aparece — e quando não."""

    def setUp(self):
        logging.getLogger("whatsapp_sender_file").setLevel(logging.CRITICAL)
        self.logs = []
        self.sender = novo_sender()
        self.sender.log_callback = self.logs.append

    def registrar(self, resultados):
        for ok in resultados:
            self.sender._registrar_resultado_de_abertura(ok)

    def test_nao_avisa_com_amostra_pequena(self):
        """
        Um número ruim logo na primeira leva não é sinal de rede ruim — com 3
        contatos, uma falha já daria 33%.
        """
        self.registrar([False, True, True])
        self.assertIsNone(self.sender._alerta_lentidao)

    def test_nao_avisa_quando_a_rede_esta_boa(self):
        self.registrar([True] * 20)
        self.assertIsNone(self.sender._alerta_lentidao)
        self.registrar([False])  # 1 em 21 = 5%
        self.assertIsNone(self.sender._alerta_lentidao)

    def test_avisa_ao_cruzar_a_taxa_de_falha(self):
        # Nas 5 primeiras (2 falhas = 40%) a amostra ainda é pequena demais.
        self.registrar([True, False, True, False, True])
        self.assertIsNone(self.sender._alerta_lentidao)

        # A 6ª fecha a amostra mínima: 2 falhas em 6 = 33%, acima dos 30%.
        self.registrar([True])

        alerta = self.sender._alerta_lentidao
        self.assertIsNotNone(alerta)
        self.assertEqual(alerta["falhas"], 2)
        self.assertEqual(alerta["tentativas"], 6)
        self.assertEqual(alerta["percentual"], 33)
        self.assertTrue(alerta["atraso_estimado_fmt"])

        # E o log da tela também registra, para quem não viu o popup.
        self.assertTrue(
            any("Conexão instável" in m for m in self.logs),
            f"o aviso precisa sair no log também: {self.logs}",
        )

    def test_nao_repete_a_cada_falha(self):
        self.registrar([False] * 6)
        self.assertEqual(len(self.logs), 1)

        # Falhas seguintes, mas ainda dentro da janela de rearme: silêncio.
        self.registrar([False] * (WhatsAppSender._ALERTA_REARME_A_CADA - 1))
        self.assertEqual(len(self.logs), 1, f"popup repetindo à toa: {self.logs}")

    def test_reavisa_depois_de_acumular_novas_falhas(self):
        self.registrar([False] * 6)
        seq_inicial = self.sender._alerta_lentidao["seq"]

        self.registrar([False] * WhatsAppSender._ALERTA_REARME_A_CADA)

        self.assertEqual(len(self.logs), 2)
        self.assertNotEqual(
            self.sender._alerta_lentidao["seq"],
            seq_inicial,
            "o painel usa o seq para saber que é um aviso NOVO",
        )

    def test_sai_no_status(self):
        """
        O aviso viaja junto do status (e não como evento próprio) justamente
        para sobreviver a um F5 ou a uma queda da conexão SSE no meio do envio.
        """
        self.assertIsNone(self.sender.get_status()["alerta_lentidao"])

        self.registrar([False] * 6)

        alerta = self.sender.get_status()["alerta_lentidao"]
        self.assertIsNotNone(alerta)
        self.assertEqual(alerta["percentual"], 100)

    def test_contato_que_nem_chegou_a_abrir_conversa_nao_conta(self):
        """
        Número vazio, mensagem vazia ou duplicado são invalidados ANTES da
        navegação — não dizem nada sobre a rede e não podem contaminar a taxa.
        Este teste fixa a interface: só quem chama
        _registrar_resultado_de_abertura entra na conta.
        """
        for _ in range(10):
            self.sender._contar_invalido("Coluna Número vazia.")

        self.assertEqual(self.sender._aberturas_ok + self.sender._aberturas_timeout, 0)
        self.assertIsNone(self.sender._alerta_lentidao)


if __name__ == "__main__":
    unittest.main(verbosity=2)
