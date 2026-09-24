# -*- coding: utf-8 -*-
"""
Bateria end-to-end do envio: entra HTTP, sai planilha.

O que estes testes cobrem que os de unidade não cobrem: a **fiação**. Cada
invariante aqui já tem alguém que a implementa corretamente em isolamento — o
que ninguém garantia até agora é que as peças, ligadas umas nas outras e
atravessadas por uma campanha inteira, produzem o resultado certo NA PLANILHA,
que é o único artefato que o cliente lê.

O WhatsApp Web é falso (`fake_whatsapp.py`); o resto é produção.

Rodar:
    python -m unittest tests.e2e.test_e2e_envio -v
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from tests.e2e import fake_whatsapp as fw
from tests.e2e.ambiente import AmbienteE2E


def contato(nome, numero, mensagem="Olá {nome}, tudo bem?", **kw):
    return {"Nome": nome, "Número": numero, "Mensagem": mensagem, **kw}


TRES = [
    contato("Ana", "19990000001"),
    contato("Bruno", "19990000002"),
    contato("Carla", "19990000003"),
]


class TestCaminhoFeliz(unittest.TestCase):
    """
    A campanha que funciona. Se este teste passa, a fiação inteira está de pé:
    rota -> AppState -> sender -> plano de rajadas -> DOM -> planilha.
    """

    def test_todos_os_contatos_recebem_e_a_planilha_registra(self):
        with AmbienteE2E(contatos=TRES) as amb:
            amb.configurar(total_msgs=3, tempo_minutos=10)
            amb.iniciar_envio()
            amb.esperar_envio()

            self.assertEqual(len(amb.driver.enviadas), 3)
            self.assertEqual(
                sorted(amb.driver.numeros_enviados()),
                ["19990000001", "19990000002", "19990000003"],
            )

            df = amb.planilha()
            self.assertTrue((df["Enviado"] == "X").all())
            self.assertTrue((df["DataEnvio"] != "").all())
            self.assertTrue((df["Invalido"] == "").all())

    def test_o_placeholder_nome_e_resolvido_no_texto_que_sai(self):
        """
        O bug clássico de campanha: o {nome} literal chegando no cliente. Só um
        teste que lê o texto ENTREGUE pega isso — a planilha guarda o template.
        """
        with AmbienteE2E(contatos=TRES) as amb:
            amb.configurar(total_msgs=3, tempo_minutos=10)
            amb.iniciar_envio()
            amb.esperar_envio()

            textos = amb.driver.textos_enviados()
            self.assertEqual(len(textos), 3)
            for texto in textos:
                self.assertNotIn("{nome}", texto)
            self.assertTrue(any("Ana" in t for t in textos))
            self.assertTrue(any("Bruno" in t for t in textos))

    def test_cada_contato_recebe_exatamente_uma_mensagem(self):
        """Mensagem duplicada é o pior defeito possível numa campanha."""
        with AmbienteE2E(contatos=TRES) as amb:
            amb.configurar(total_msgs=3, tempo_minutos=10)
            amb.iniciar_envio()
            amb.esperar_envio()

            numeros = amb.driver.numeros_enviados()
            self.assertEqual(len(numeros), len(set(numeros)))

    def test_o_marcador_de_execucao_nasce_e_morre(self):
        """
        `uploads/envio_em_andamento.json` sobreviver ao fim do envio é o que o
        app usa, na abertura seguinte, para dizer "a execução anterior foi
        interrompida". Se ele não for apagado no caminho feliz, TODA abertura
        passa a mentir.
        """
        with AmbienteE2E(contatos=TRES) as amb:
            amb.configurar(total_msgs=3, tempo_minutos=10)
            amb.iniciar_envio()
            self.assertIsNotNone(amb.marcador_de_execucao())
            amb.esperar_envio()
            self.assertIsNone(amb.marcador_de_execucao())

    def test_a_mensagem_global_preenche_a_linha_vazia_e_so_ela(self):
        """
        "Mensagem global" **não** substitui a da planilha: ela entra só onde a
        coluna `Mensagem` está vazia. O nome sugere o contrário, e é por isso
        que a regra merece um teste que olhe o texto ENTREGUE — trocar isto por
        uma substituição reescreveria a campanha inteira de quem só queria
        cobrir duas linhas em branco.
        """
        contatos = [
            contato("Ana", "19990000001"),
            contato("Bruno", "19990000002", mensagem=""),
        ]
        with AmbienteE2E(contatos=contatos, mensagem_global="Aviso para {nome}") as amb:
            amb.configurar(total_msgs=2, tempo_minutos=10)
            amb.iniciar_envio()
            amb.esperar_envio()

            por_numero = {m.numero: m.texto for m in amb.driver.enviadas}
            self.assertEqual(por_numero["19990000001"], "Olá Ana, tudo bem?")
            self.assertEqual(por_numero["19990000002"], "Aviso para Bruno")

    def test_o_aquecimento_nao_abre_a_conversa_de_ninguem(self):
        """
        `_aquecer_navegacao` tem de navegar para o web.whatsapp.com pelado. Uma
        URL `send?phone=` ali abriria — e marcaria como lida — a conversa de um
        contato que ninguém mandou abrir.
        """
        with AmbienteE2E(contatos=TRES) as amb:
            amb.configurar(total_msgs=3, tempo_minutos=10)
            amb.iniciar_envio()
            amb.esperar_envio()

            primeira = amb.driver.navegacoes[0]
            self.assertNotIn("send?phone=", primeira)


class TestDesfechosDeFalha(unittest.TestCase):
    """
    O valor real da bateria: roteirizar a falha. Cada cenário aqui é uma
    invariante do CHANGELOG que hoje só se testa com sorte contra o WhatsApp
    real.
    """

    def test_numero_invalido_vira_invalido_e_os_outros_seguem(self):
        with AmbienteE2E(
            contatos=TRES,
            roteiro={"19990000002": fw.NUMERO_INVALIDO},
        ) as amb:
            amb.configurar(total_msgs=3, tempo_minutos=10)
            amb.iniciar_envio()
            amb.esperar_envio()

            self.assertEqual(amb.linha("Bruno")["Invalido"], "X")
            self.assertNotEqual(amb.linha("Bruno")["Motivo"], "")
            self.assertEqual(amb.linha("Bruno")["Enviado"], "")
            # E o contato inválido NÃO recebeu texto nenhum.
            self.assertNotIn("19990000002", amb.driver.numeros_enviados())
            # Os outros dois foram até o fim.
            self.assertEqual(amb.linha("Ana")["Enviado"], "X")
            self.assertEqual(amb.linha("Carla")["Enviado"], "X")

    def test_contato_bloqueado_nao_recebe_texto(self):
        """
        A conversa ABRE quando o contato é bloqueado — o que muda é que no lugar
        do campo de texto há "Desbloquear". Sem essa detecção o app esperaria o
        timeout inteiro e, pior, poderia achar que digitou.
        """
        with AmbienteE2E(
            contatos=TRES,
            roteiro={"19990000003": fw.BLOQUEADO},
        ) as amb:
            amb.configurar(total_msgs=3, tempo_minutos=10)
            amb.iniciar_envio()
            amb.esperar_envio()

            self.assertEqual(amb.linha("Carla")["Invalido"], "X")
            self.assertNotIn("19990000003", amb.driver.numeros_enviados())

    def test_app_que_nao_sobe_deixa_o_contato_PENDENTE(self):
        """
        A distinção que o CLAUDE.md chama de `tipo="app"` contra `tipo="chat"`,
        e que custa dinheiro errar: quando o #pane-side não aparece, o problema
        é do ambiente, não do número. O contato tem de continuar PENDENTE (será
        tentado de novo), nunca inválido — inválido é um desfecho que só o ↺
        desfaz, e o número não fez nada de errado.
        """
        with AmbienteE2E(
            contatos=TRES,
            roteiro={"19990000001": fw.APP_NAO_SOBE},
        ) as amb:
            amb.configurar(total_msgs=3, tempo_minutos=10)
            amb.iniciar_envio()
            amb.esperar_envio()

            ana = amb.linha("Ana")
            self.assertEqual(ana["Enviado"], "")
            self.assertEqual(ana["Invalido"], "")

    def test_chat_que_nao_abre_vira_invalido_recuperavel(self):
        """O oposto do teste acima: o app está de pé, a conversa é que não abriu."""
        with AmbienteE2E(
            contatos=TRES,
            roteiro={"19990000001": fw.CHAT_NAO_ABRE},
        ) as amb:
            amb.configurar(total_msgs=3, tempo_minutos=10)
            amb.iniciar_envio()
            amb.esperar_envio()

            ana = amb.linha("Ana")
            self.assertEqual(ana["Invalido"], "X")
            self.assertEqual(ana["Enviado"], "")

    def test_anexo_inexistente_nao_manda_texto_solto(self):
        """
        A promessa é "texto + anexo". Mandar só o texto quando o anexo falha
        entrega uma mensagem que fala de um arquivo que não vai chegar.
        """
        contatos = [
            contato("Ana", "19990000001"),
            contato("Bruno", "19990000002", Arquivo="nao_existe_mesmo.pdf"),
        ]
        with AmbienteE2E(contatos=contatos) as amb:
            amb.configurar(total_msgs=2, tempo_minutos=10)
            amb.iniciar_envio()
            amb.esperar_envio()

            self.assertEqual(amb.linha("Bruno")["Invalido"], "X")
            self.assertIn("anexo", amb.linha("Bruno")["Motivo"].lower())
            self.assertNotIn("19990000002", amb.driver.numeros_enviados())
            self.assertEqual(amb.linha("Ana")["Enviado"], "X")


class TestRetomadaEDuplicacao(unittest.TestCase):
    def test_contato_ja_enviado_e_pulado(self):
        contatos = [
            contato("Ana", "19990000001", Enviado="X", DataEnvio="2026-09-01 10:00:00"),
            contato("Bruno", "19990000002"),
        ]
        with AmbienteE2E(contatos=contatos) as amb:
            amb.configurar(total_msgs=2, tempo_minutos=10)
            amb.iniciar_envio()
            amb.esperar_envio()

            self.assertEqual(amb.driver.numeros_enviados(), ["19990000002"])

    def test_duplicado_e_marcado_invalido_e_nao_recebe(self):
        contatos = [
            contato("Ana", "19990000001"),
            contato("Ana de novo", "19990000001"),
            contato("Bruno", "19990000002"),
        ]
        with AmbienteE2E(contatos=contatos) as amb:
            amb.configurar(total_msgs=3, tempo_minutos=10)
            amb.iniciar_envio()
            amb.esperar_envio()

            numeros = amb.driver.numeros_enviados()
            self.assertEqual(sorted(numeros), ["19990000001", "19990000002"])
            self.assertEqual(amb.linha("Ana de novo")["Invalido"], "X")
            self.assertIn("duplicad", amb.linha("Ana de novo")["Motivo"].lower())

    def test_segunda_execucao_nao_reenvia_nada(self):
        """
        A prova de que a planilha é mesmo a fonte da verdade: rodar de novo,
        sem mexer em nada, não pode mandar uma segunda mensagem para ninguém.
        """
        with AmbienteE2E(contatos=TRES) as amb:
            amb.configurar(total_msgs=3, tempo_minutos=10)
            amb.iniciar_envio()
            amb.esperar_envio()
            self.assertEqual(len(amb.driver.enviadas), 3)

            amb.iniciar_envio()
            amb.esperar_envio()
            self.assertEqual(len(amb.driver.enviadas), 3)


class TestTravaDuranteOEnvio(unittest.TestCase):
    def test_config_e_mensagem_global_sao_recusadas_com_envio_rodando(self):
        """
        O sender relê `config` e `global_message` a CADA contato, então aceitar
        uma escrita no meio mudaria o ritmo — ou o texto — dos que ainda estão
        na fila. Aqui isso é testado com um envio de verdade em andamento, e
        não com um `is_running()` forjado.
        """
        travado = []

        with AmbienteE2E(contatos=TRES) as amb:
            amb.configurar(total_msgs=3, tempo_minutos=10)

            # Congela o envio no primeiro contato para poder bater na porta.
            porta = amb.driver

            original = porta.get
            liberar = __import__("threading").Event()

            def _get_lento(url):
                original(url)
                if "send?phone=" in url:
                    travado.append(url)
                    liberar.wait(timeout=10)

            porta.get = _get_lento
            amb.iniciar_envio()

            # Espera o envio realmente entrar no primeiro contato.
            for _ in range(200):
                if travado:
                    break
                __import__("time").sleep(0.01)
            self.assertTrue(travado, "o envio não chegou a navegar")

            r1 = amb.cliente.post("/config", json={
                "total_msgs": 99, "tempo_minutos": 5, "hora_inicio": "00:00",
                "hora_fim": "23:59", "skip_weekends": False,
                "human_behavior": True, "allow_duplicates": False})
            r2 = amb.cliente.post("/global-message", json={
                "mensagem": "trocada no meio", "ativa": True})

            liberar.set()
            amb.esperar_envio()

        self.assertEqual(r1.status_code, 400)
        self.assertEqual(r2.status_code, 400)


class TestAnexoGlobal(unittest.TestCase):
    """
    O anexo global atravessando uma campanha inteira.

    LACUNA CONHECIDA, e ela não é do anexo global: o `fake_whatsapp.py` não
    modela um anexo que dá CERTO. Ele registra o arquivo empurrado para o
    `input_arquivo`, mas não abre o preview que `_detect_attach_preview`
    procura, então todo anexo termina em `AttachmentError`. Por isso a única
    cobertura e2e de anexo que existe hoje é a do caminho de falha
    (`test_anexo_inexistente_nao_manda_texto_solto`), e por isso este arquivo
    só consegue afirmar o caso "desligado".

    Vale arrumar: com o anexo global, TODO contato passa a ter anexo, então
    essa é a fiação mais exercitada da campanha e a menos coberta ponta a
    ponta. Falta o dublê entrar em "modal aberto" depois do arquivo, responder
    `campo_legenda_edicao` e `botao_enviar_modal`, e fechar no clique.

    Enquanto isso, quem cobre a regra é `tests/test_anexo_global.py` (fallback,
    estimativa, persistência, recusas), e a ordem anexo-antes-do-texto é do
    `tests/test_rascunho_no_anexo.py`.
    """

    def _arquivo(self, amb, nome="promo.jpg"):
        """Um anexo de verdade no cwd temporário do cenário."""
        from pathlib import Path
        destino = Path("uploads") / "media" / nome
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(b"\xff\xd8\xff\xd9")
        return str(destino.resolve())

    def test_desligado_nao_anexa_nada(self):
        with AmbienteE2E(contatos=TRES) as amb:
            caminho = self._arquivo(amb)
            amb.cliente.post("/global-attachment",
                             json={"arquivo": caminho, "ativo": False})

            amb.configurar(total_msgs=3, tempo_minutos=10)
            amb.iniciar_envio()
            amb.esperar_envio()

            for msg in amb.driver.enviadas:
                self.assertEqual(msg.anexos, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
