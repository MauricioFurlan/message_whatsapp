# -*- coding: utf-8 -*-
"""
Bateria end-to-end da varredura de respostas: campanha inteira, ida e volta.

Estes testes fecham o ciclo que nenhum teste de unidade fecha — **enviar e
depois ler**. O envio grava `Enviado=X` na planilha; horas depois a varredura
lê a lista de conversas e grava `Respondeu`/`Entrega`/`RespostaTexto` NAS MESMAS
linhas. O casamento entre as duas metades é por número (e, desde 16/09/2026,
por nome para contato salvo na agenda), e é exatamente ali que um erro não
deixa rastro: a tela mostra `-`, igual a quem nunca foi verificado.

Rodar:
    python -m unittest tests.e2e.test_e2e_varredura -v
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from tests.e2e.ambiente import AmbienteE2E
from tests.e2e.test_e2e_envio import contato

# Nomes de ícone do WhatsApp Web, exatamente como o DOM os entrega — e eles
# estão DESLOCADOS do que exibem (ver `linha_conversa.py`): `wds-ic-delivered`
# é o ✓ solitário (saiu e NÃO chegou) e `wds-ic-read` é o ✓✓, cuja cor separa
# entregue de lido. Escrevê-los aqui crus é de propósito: é o que o navegador
# devolveria, e traduzir na fixture esconderia justamente a armadilha.
AZUL = "rgb(0, 123, 252)"
CINZA = "rgba(0, 0, 0, 0.6)"


def linha_da_lista(titulo, icones, cor="", nao_lidas="", horario="14:30",
                   ultima_mensagem=""):
    return {
        "titulo": titulo, "icones_status": icones, "cor_status": cor,
        "nao_lidas": nao_lidas, "horario": horario,
        "ultima_mensagem": ultima_mensagem,
    }


class TestCicloCompleto(unittest.TestCase):
    def test_envia_e_depois_le_a_resposta_na_mesma_linha(self):
        """
        O ciclo inteiro: a mensagem sai, o contato responde, a varredura acha a
        linha e grava. Se o casamento entre as duas metades quebrar, este teste
        é o único que percebe — a planilha fica com `Enviado=X` e o resto em
        branco, que é indistinguível de "ainda não verifiquei".
        """
        contatos = [
            contato("Ana", "19990000001"),
            contato("Bruno", "19990000002"),
        ]
        linhas = [
            # Ana respondeu: nenhum ícone de status = a última mensagem é dela.
            linha_da_lista("+55 19 99000-0001", [], ultima_mensagem="Tenho interesse!"),
            # Bruno leu e não respondeu: ✓✓ AZUL.
            linha_da_lista("+55 19 99000-0002", ["wds-ic-read"], cor=AZUL),
        ]
        with AmbienteE2E(contatos=contatos, linhas_da_lista=linhas) as amb:
            import app as app_mod

            amb.configurar(total_msgs=2, tempo_minutos=10)
            amb.iniciar_envio()
            amb.esperar_envio()

            r = amb.cliente.post("/verificar-respostas")
            self.assertEqual(r.status_code, 200, r.text)
            app_mod.state.varredura_thread.join(timeout=30)
            self.assertFalse(app_mod.state.varredura_thread.is_alive())

            ana = amb.linha("Ana")
            self.assertEqual(ana["Respondeu"], "Sim")
            self.assertEqual(ana["Entrega"], "Respondeu")
            self.assertEqual(ana["RespostaTexto"], "Tenho interesse!")

            bruno = amb.linha("Bruno")
            self.assertEqual(bruno["Respondeu"], "Não")
            self.assertEqual(bruno["Entrega"], "Lido")
            # Nunca grava o NOSSO texto como se fosse resposta dele.
            self.assertEqual(bruno["RespostaTexto"], "")

    def test_tique_solitario_e_nao_entregue_apesar_do_nome_do_icone(self):
        """
        `wds-ic-delivered` é o ✓ SOLITÁRIO: saiu e não chegou. Ler o nome do
        ícone ao pé da letra exibia "Entregue" para mensagem que nunca chegou —
        e, pior, calava o alarme de entrega, que existe exatamente para isso.
        """
        contatos = [contato("Ana", "19990000001")]
        linhas = [linha_da_lista("+55 19 99000-0001", ["wds-ic-delivered"], cor=CINZA)]
        with AmbienteE2E(contatos=contatos, linhas_da_lista=linhas) as amb:
            import app as app_mod

            amb.configurar(total_msgs=1, tempo_minutos=10)
            amb.iniciar_envio()
            amb.esperar_envio()
            amb.cliente.post("/verificar-respostas")
            app_mod.state.varredura_thread.join(timeout=30)

            self.assertEqual(amb.linha("Ana")["Entrega"], "Não entregue")

    def test_tique_duplo_cinza_e_entregue_e_nao_lido(self):
        """O mesmo NOME de ícone do "lido": só a cor separa os dois."""
        contatos = [contato("Ana", "19990000001")]
        linhas = [linha_da_lista("+55 19 99000-0001", ["wds-ic-read"], cor=CINZA)]
        with AmbienteE2E(contatos=contatos, linhas_da_lista=linhas) as amb:
            import app as app_mod

            amb.configurar(total_msgs=1, tempo_minutos=10)
            amb.iniciar_envio()
            amb.esperar_envio()
            amb.cliente.post("/verificar-respostas")
            app_mod.state.varredura_thread.join(timeout=30)

            self.assertEqual(amb.linha("Ana")["Entrega"], "Entregue")

    def test_contato_salvo_na_agenda_e_lido_pelo_nome(self):
        """
        A regressão de 16/09/2026, agora de ponta a ponta: a linha de quem está
        salvo mostra o NOME, não o número, e o casamento era só por número — o
        contato caía em "não encontrado", o único desfecho que não escreve nada.
        """
        contatos = [contato("Isis Campos", "19990000001")]
        linhas = [linha_da_lista("Isis Campos", ["wds-ic-read"], cor=AZUL)]
        with AmbienteE2E(contatos=contatos, linhas_da_lista=linhas) as amb:
            import app as app_mod

            amb.configurar(total_msgs=1, tempo_minutos=10)
            amb.iniciar_envio()
            amb.esperar_envio()
            amb.cliente.post("/verificar-respostas")
            app_mod.state.varredura_thread.join(timeout=30)

            self.assertEqual(amb.linha("Isis Campos")["Entrega"], "Lido")

    def test_contato_invalido_fica_fora_da_varredura(self):
        """
        Um inválido nunca teve entrega. Se o cliente já tinha conversa antiga
        com aquele número, ler a linha atribuiria a ESTA campanha o estado de
        uma mensagem de meses atrás.
        """
        import tests.e2e.fake_whatsapp as fw

        contatos = [
            contato("Ana", "19990000001"),
            contato("Bruno", "19990000002"),
        ]
        linhas = [
            linha_da_lista("+55 19 99000-0001", ["wds-ic-read"], cor=AZUL),
            # Conversa antiga do Bruno, com resposta dele lá de trás.
            linha_da_lista("+55 19 99000-0002", [], ultima_mensagem="oi de 2024"),
        ]
        with AmbienteE2E(
            contatos=contatos, linhas_da_lista=linhas,
            roteiro={"19990000002": fw.NUMERO_INVALIDO},
        ) as amb:
            import app as app_mod

            amb.configurar(total_msgs=2, tempo_minutos=10)
            amb.iniciar_envio()
            amb.esperar_envio()
            amb.cliente.post("/verificar-respostas")
            app_mod.state.varredura_thread.join(timeout=30)

            self.assertEqual(amb.linha("Bruno")["Invalido"], "X")
            self.assertEqual(amb.linha("Bruno")["Respondeu"], "")
            self.assertEqual(amb.linha("Bruno")["RespostaTexto"], "")

    def test_conversa_ausente_da_lista_nao_vira_nao_respondeu(self):
        """Silêncio bate invenção: sem linha lida, nada é escrito."""
        contatos = [contato("Ana", "19990000001")]
        with AmbienteE2E(contatos=contatos, linhas_da_lista=[]) as amb:
            import app as app_mod

            amb.configurar(total_msgs=1, tempo_minutos=10)
            amb.iniciar_envio()
            amb.esperar_envio()
            amb.cliente.post("/verificar-respostas")
            app_mod.state.varredura_thread.join(timeout=60)

            ana = amb.linha("Ana")
            self.assertEqual(ana["Respondeu"], "")
            self.assertEqual(ana["Entrega"], "")
            # E o que o envio gravou continua lá.
            self.assertEqual(ana["Enviado"], "X")


class TestDisputaPeloChrome(unittest.TestCase):
    """
    Envio e varredura seguram o MESMO `chrome_profile/` e escrevem a MESMA
    planilha. Rodar os dois juntos daria `ChromeProfileInUseError` — e, pior,
    duas escritas concorrentes no arquivo.
    """

    def test_varredura_e_recusada_durante_um_envio(self):
        import threading
        import time as tempo_real

        contatos = [contato("Ana", "19990000001"), contato("Bruno", "19990000002")]
        with AmbienteE2E(contatos=contatos) as amb:
            amb.configurar(total_msgs=2, tempo_minutos=10)

            chegou = []
            liberar = threading.Event()
            original = amb.driver.get

            def _get_lento(url):
                original(url)
                if "send?phone=" in url:
                    chegou.append(url)
                    liberar.wait(timeout=10)

            amb.driver.get = _get_lento
            amb.iniciar_envio()
            for _ in range(200):
                if chegou:
                    break
                tempo_real.sleep(0.01)
            self.assertTrue(chegou, "o envio não chegou a navegar")

            r = amb.cliente.post("/verificar-respostas")
            liberar.set()
            amb.esperar_envio()

        self.assertEqual(r.status_code, 400)


if __name__ == "__main__":
    unittest.main(verbosity=2)
