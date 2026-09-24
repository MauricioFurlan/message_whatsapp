# -*- coding: utf-8 -*-
"""
Testes da camada de seletores remotos (`seletores.py`).

Existe para que uma mudança no DOM do WhatsApp vire um arquivo publicado em
minutos, não um build novo do `.exe` para todos os clientes.

Fixa as quatro invariantes que, se regredirem, transformam a feature de
"conserto rápido" em "novo vetor de falha":

  1. **Nunca dependência dura.** Supabase fora do ar, tabela inexistente,
     JSON corrompido, cache de outro schema — em todos os casos o app cai para
     a camada anterior e continua funcionando. Nada aqui pode impedir um envio.
  2. **Só seletores, nunca código.** O payload remoto é conteúdo de terceiro
     entrando num app que dirige a conta de WhatsApp do cliente. Só string
     curta (ou lista delas), de chave já conhecida, e com o TIPO do embutido,
     atravessa.
  3. **Refetch só em falha ESTRUTURAL, com trava.** Sem a trava, um WhatsApp
     quebrado gera uma requisição ao Supabase por contato. E o caso do campo
     de digitação é CONTADO, não reportado no primeiro timeout — senão vira
     exatamente a falha-de-contato que esta invariante proíbe.
  4. **Aplicar parte sempre do embutido.** Chave removida do payload volta ao
     padrão, em vez de ficar presa num valor velho.

Rodar:
    python -m unittest tests.test_seletores -v
"""

import json
import logging
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import seletores


class BaseSeletores(unittest.TestCase):
    """Isola o estado global do módulo e o arquivo de cache entre testes."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._cache_original = seletores.CACHE_FILE
        seletores.CACHE_FILE = Path(self._tmp.name) / "seletores_cache.json"
        seletores._aplicar({}, "embutido")
        seletores._ultimo_refetch = 0.0
        seletores._falhas_estruturais.clear()

    def tearDown(self):
        seletores.CACHE_FILE = self._cache_original
        seletores._aplicar({}, "embutido")
        self._tmp.cleanup()


class TestValidacaoDePayload(BaseSeletores):
    """A fronteira estreita: o que vem de fora e o que é descartado."""

    def test_chave_conhecida_com_string_passa(self):
        limpo = seletores._validar_payload({"pane_side": "#novo-pane"})
        self.assertEqual(limpo, {"pane_side": "#novo-pane"})

    def test_chave_desconhecida_e_descartada(self):
        """
        Aceitar chave nova permitiria que o payload introduzisse conceitos que
        o código não conhece. O `.exe` só consome o que ele já sabe usar.
        """
        limpo = seletores._validar_payload({"pane_side": "#a", "script_extra": "#b"})
        self.assertEqual(limpo, {"pane_side": "#a"})

    def test_valor_que_nao_e_string_e_descartado(self):
        """É aqui que 'só seletores, nunca código' se materializa."""
        for valor in ({"js": "alert(1)"}, ["#a"], 42, True, None):
            with self.subTest(valor=valor):
                self.assertEqual(seletores._validar_payload({"pane_side": valor}), {})

    def test_string_vazia_e_descartada(self):
        """Seletor vazio casaria com tudo ou com nada — pior que o padrão."""
        self.assertEqual(seletores._validar_payload({"pane_side": "   "}), {})

    def test_string_longa_demais_e_descartada(self):
        gigante = "#" + "a" * seletores.TAMANHO_MAXIMO_SELETOR
        self.assertEqual(seletores._validar_payload({"pane_side": gigante}), {})

    def test_payload_que_nao_e_objeto_nao_estoura(self):
        for bruto in ("texto", ["lista"], 7, None):
            with self.subTest(bruto=bruto):
                self.assertEqual(seletores._validar_payload(bruto), {})

    def test_uma_chave_ruim_nao_derruba_as_boas(self):
        limpo = seletores._validar_payload({"pane_side": "#ok", "linha_titulo": 123})
        self.assertEqual(limpo, {"pane_side": "#ok"})


class TestAplicacaoEFallback(BaseSeletores):
    def test_get_devolve_o_embutido_sem_nenhuma_atualizacao(self):
        self.assertEqual(seletores.get("pane_side"), "#pane-side")

    def test_payload_sobrepoe_o_embutido(self):
        seletores._aplicar({"pane_side": "#novo"}, "supabase")
        self.assertEqual(seletores.get("pane_side"), "#novo")
        # As demais continuam nos valores embutidos.
        self.assertEqual(
            seletores.get("linha_titulo"), seletores.PADRAO["linha_titulo"]
        )

    def test_chave_removida_do_payload_volta_ao_embutido(self):
        """
        Aplicar sempre parte do PADRAO. Se partisse do estado anterior, um
        seletor retirado de uma publicação ficaria preso no valor antigo, e o
        rollback publicando um JSON menor não funcionaria.
        """
        seletores._aplicar({"pane_side": "#antigo"}, "supabase")
        seletores._aplicar({"linha_titulo": "#outro"}, "supabase")
        self.assertEqual(seletores.get("pane_side"), seletores.PADRAO["pane_side"])

    def test_aplicar_relata_quantas_mudaram(self):
        self.assertEqual(seletores._aplicar({"pane_side": "#x"}, "supabase"), 1)
        self.assertEqual(seletores._aplicar({"pane_side": "#x"}, "supabase"), 0)

    def test_chave_inexistente_no_get_e_erro_de_programacao(self):
        with self.assertRaises(KeyError):
            seletores.get("nao_existe")

    def test_todos_devolve_copia(self):
        copia = seletores.todos()
        copia["pane_side"] = "mexido"
        self.assertEqual(seletores.get("pane_side"), "#pane-side")


class TestChavesDeLista(BaseSeletores):
    """
    Algumas chaves são listas tentadas em ordem (botão de anexar, botão de
    enviar, campo de legenda). Foram exatamente esses elementos que o WhatsApp
    já mudou mais de uma vez, e é a ordem da lista que decide qual tentativa
    vence — por isso não viraram uma string vírgula-separada.
    """

    UMA_LISTA = "botao_anexar"

    def test_lista_devolve_o_embutido(self):
        self.assertEqual(
            seletores.lista(self.UMA_LISTA), seletores.PADRAO[self.UMA_LISTA]
        )

    def test_lista_devolve_copia(self):
        copia = seletores.lista(self.UMA_LISTA)
        copia.append("button.injetado")
        self.assertNotIn("button.injetado", seletores.lista(self.UMA_LISTA))
        self.assertNotIn("button.injetado", seletores.PADRAO[self.UMA_LISTA])

    def test_todos_copia_as_listas_tambem(self):
        """`dict()` é raso: sem cópia explícita dava para mutar o embutido."""
        copia = seletores.todos()
        copia[self.UMA_LISTA].append("button.injetado")
        self.assertNotIn("button.injetado", seletores.PADRAO[self.UMA_LISTA])

    def test_payload_de_lista_e_aplicado_na_ordem_publicada(self):
        seletores._aplicar(
            seletores._validar_payload({self.UMA_LISTA: ["button.novo", "span.velho"]}),
            "supabase",
        )
        self.assertEqual(seletores.lista(self.UMA_LISTA), ["button.novo", "span.velho"])

    def test_item_ruim_nao_derruba_a_lista_inteira(self):
        """
        Uma lista de 7 fallbacks não pode ser perdida porque a oitava entrada
        veio torta — o conserto publicado valeria zero.
        """
        limpo = seletores._validar_payload(
            {self.UMA_LISTA: ["button.bom", 42, "", "span.bom"]}
        )
        self.assertEqual(limpo[self.UMA_LISTA], ["button.bom", "span.bom"])

    def test_lista_sem_nenhum_item_valido_e_descartada(self):
        limpo = seletores._validar_payload({self.UMA_LISTA: [42, None, ""]})
        self.assertNotIn(self.UMA_LISTA, limpo)

    def test_lista_longa_demais_e_descartada(self):
        gigante = ["button.x%d" % i for i in range(seletores.TAMANHO_MAXIMO_LISTA + 1)]
        limpo = seletores._validar_payload({self.UMA_LISTA: gigante})
        self.assertNotIn(self.UMA_LISTA, limpo)

    def test_item_longo_demais_e_descartado(self):
        limpo = seletores._validar_payload(
            {self.UMA_LISTA: ["button.ok", "x" * (seletores.TAMANHO_MAXIMO_SELETOR + 1)]}
        )
        self.assertEqual(limpo[self.UMA_LISTA], ["button.ok"])


class TestTipoVemDoEmbutido(BaseSeletores):
    """
    O embutido decide se uma chave é string ou lista, nunca o payload.

    O código chama `get()` ou `lista()` conforme a chave; deixar o remoto
    trocar o tipo seria deixá-lo escolher por qual caminho o app passa — e, no
    caso de `get()`, devolver uma lista onde o Selenium espera uma string.
    """

    def test_lista_publicada_para_chave_de_string_e_descartada(self):
        limpo = seletores._validar_payload({"campo_mensagem": ["footer div", "div"]})
        self.assertNotIn("campo_mensagem", limpo)

    def test_string_publicada_para_chave_de_lista_e_descartada(self):
        limpo = seletores._validar_payload({"botao_anexar": "button[aria-label]"})
        self.assertNotIn("botao_anexar", limpo)

    def test_get_numa_chave_de_lista_e_erro_de_programacao(self):
        with self.assertRaises(TypeError):
            seletores.get("botao_anexar")


class TestCaminhoDeEnvioEstaCoberto(BaseSeletores):
    """
    O ponto da mudança de 12/09/2026: até então só o lado da LEITURA (lista de
    conversas, varredura) era publicável. O campo de digitação — sem o qual
    nenhuma mensagem sai — estava escrito à mão no sender, então a quebra mais
    cara de todas era justamente a que exigia um `.exe` novo.
    """

    CHAVES_DE_ENVIO = (
        "campo_mensagem",
        "input_arquivo",
        "botao_anexar",
        "botao_enviar_modal",
        "campo_legenda_presenca",
        "campo_legenda_edicao",
        "qr_canvas",
        "modais",
        "modal_botoes",
        "alertas_conexao",
        "area_conversa",
    )

    def test_todas_as_chaves_de_envio_existem(self):
        for chave in self.CHAVES_DE_ENVIO:
            self.assertIn(chave, seletores.PADRAO, chave)

    def test_sender_nao_tem_mais_seletor_de_envio_escrito_a_mao(self):
        """
        Guarda contra a regressão de reintroduzir o literal: um seletor
        publicado só conserta os pontos que perguntam pela camada.
        """
        fonte = Path(__file__).resolve().parent.parent / "whatsapp_sender.py"
        codigo = fonte.read_text(encoding="utf-8")
        for literal in (
            '"#pane-side"',
            "footer div[contenteditable='true']",
            'input[type="file"]',
        ):
            self.assertNotIn(literal, codigo, literal)


class TestCacheEmDisco(BaseSeletores):
    def test_grava_e_le_de_volta(self):
        seletores._gravar_cache({"pane_side": "#do-cache"}, "v1")
        payload, versao = seletores._ler_cache()
        self.assertEqual(payload, {"pane_side": "#do-cache"})
        self.assertEqual(versao, "v1")

    def test_cache_ausente_devolve_vazio(self):
        self.assertEqual(seletores._ler_cache(), ({}, None))

    def test_cache_corrompido_cai_no_embutido(self):
        seletores.CACHE_FILE.write_text("{ isto não é json", encoding="utf-8")
        self.assertEqual(seletores._ler_cache(), ({}, None))

    def test_cache_de_outro_schema_e_ignorado(self):
        """
        Um JSON publicado para uma versão futura do app não pode ser aplicado
        num `.exe` antigo que não sabe interpretá-lo.
        """
        seletores.CACHE_FILE.write_text(
            json.dumps(
                {
                    "versao_schema": seletores.VERSAO_SCHEMA + 1,
                    "seletores": {"pane_side": "#do-futuro"},
                }
            ),
            encoding="utf-8",
        )
        self.assertEqual(seletores._ler_cache(), ({}, None))

    def test_cache_com_chave_invalida_e_filtrado_na_leitura(self):
        """O cache é disco local, mas nasceu de conteúdo remoto: revalidar."""
        seletores.CACHE_FILE.write_text(
            json.dumps(
                {
                    "versao_schema": seletores.VERSAO_SCHEMA,
                    "seletores": {"pane_side": "#ok", "chave_estranha": "#x"},
                }
            ),
            encoding="utf-8",
        )
        payload, _ = seletores._ler_cache()
        self.assertEqual(payload, {"pane_side": "#ok"})

    def test_carregar_usa_o_cache_e_nao_toca_a_rede(self):
        seletores._gravar_cache({"pane_side": "#do-cache"}, "v9")
        seletores.carregar(buscar_remoto=False)
        self.assertEqual(seletores.get("pane_side"), "#do-cache")
        self.assertEqual(seletores.status()["origem"], "cache")


class TestBuscaRemota(BaseSeletores):
    def test_sem_rede_mantem_o_local(self):
        """Supabase inacessível não pode impedir o app de operar."""
        import requests

        with patch("seletores.requests.get", side_effect=requests.ConnectionError()):
            self.assertFalse(seletores.atualizar_do_servidor())
        self.assertEqual(seletores.get("pane_side"), "#pane-side")

    def test_tabela_inexistente_mantem_o_local(self):
        with patch("seletores.requests.get") as g:
            g.return_value.status_code = 404
            self.assertFalse(seletores.atualizar_do_servidor())
        self.assertEqual(seletores.get("pane_side"), "#pane-side")

    def test_resposta_vazia_mantem_o_local(self):
        with patch("seletores.requests.get") as g:
            g.return_value.status_code = 200
            g.return_value.json.return_value = []
            self.assertFalse(seletores.atualizar_do_servidor())

    def test_resposta_valida_aplica_e_grava_cache(self):
        with patch("seletores.requests.get") as g:
            g.return_value.status_code = 200
            g.return_value.json.return_value = [
                {"versao": "2026-09-07", "seletores": {"pane_side": "#remoto"}}
            ]
            self.assertTrue(seletores.atualizar_do_servidor())

        self.assertEqual(seletores.get("pane_side"), "#remoto")
        self.assertEqual(seletores.status()["origem"], "supabase")
        payload, versao = seletores._ler_cache()
        self.assertEqual(payload, {"pane_side": "#remoto"})
        self.assertEqual(versao, "2026-09-07")

    def test_payload_remoto_malicioso_e_filtrado_antes_de_aplicar(self):
        with patch("seletores.requests.get") as g:
            g.return_value.status_code = 200
            g.return_value.json.return_value = [
                {
                    "versao": "x",
                    "seletores": {
                        "pane_side": "#ok",
                        "__script__": "fetch('http://exfil')",
                        "linha_titulo": {"js": "alert(1)"},
                    },
                }
            ]
            seletores.atualizar_do_servidor()

        self.assertEqual(seletores.get("pane_side"), "#ok")
        self.assertEqual(seletores.get("linha_titulo"), seletores.PADRAO["linha_titulo"])
        self.assertNotIn("__script__", seletores.todos())


class TestRefetchPorFalhaEstrutural(BaseSeletores):
    def test_primeira_falha_dispara_a_busca(self):
        with patch("seletores.atualizar_do_servidor", return_value=True) as up:
            self.assertTrue(seletores.registrar_falha_estrutural("pane_side"))
        up.assert_called_once()

    def test_segunda_falha_seguida_nao_busca_de_novo(self):
        """
        Sem a trava, um WhatsApp quebrado geraria uma requisição por contato
        durante horas de envio.
        """
        with patch("seletores.atualizar_do_servidor", return_value=False):
            seletores.registrar_falha_estrutural("pane_side")
        seletores._ultimo_refetch = __import__("time").monotonic()

        with patch("seletores.atualizar_do_servidor") as up:
            self.assertFalse(seletores.registrar_falha_estrutural("pane_side"))
        up.assert_not_called()

    def test_falhas_sao_contadas_mesmo_quando_nao_busca(self):
        """O log precisa saber quantas vezes falhou, não só quantas buscou."""
        seletores._ultimo_refetch = __import__("time").monotonic()
        for _ in range(3):
            seletores.registrar_falha_estrutural("pane_side")
        self.assertEqual(seletores.status()["falhas_estruturais"]["pane_side"], 3)

    def test_busca_sem_mudanca_nao_manda_tentar_de_novo(self):
        """
        Retornar True faria o chamador repetir a operação à toa: se nada mudou,
        o seletor continua o mesmo e a falha vai se repetir.
        """
        with patch("seletores.requests.get") as g:
            g.return_value.status_code = 200
            g.return_value.json.return_value = [
                {"versao": "v", "seletores": {"pane_side": seletores.PADRAO["pane_side"]}}
            ]
            self.assertFalse(seletores.registrar_falha_estrutural("pane_side"))


class TestContagemDoCampoDeMensagem(BaseSeletores):
    """
    O gatilho estrutural do campo de digitação é o único que precisa de
    contagem, e é por isso que ele existe separado dos outros.

    `#pane-side` ausente é inequívoco: ou o WhatsApp Web não subiu, ou o
    seletor mudou. Já o campo de digitação não aparecer é indistinguível, num
    contato só, do caso mais comum do app inteiro — número que não existe no
    WhatsApp. Ligá-lo direto ao refetch seria deixar cada número inválido bater
    no Supabase, que é a invariante 3 ao contrário.
    """

    def setUp(self):
        super().setUp()
        logging.getLogger("whatsapp_sender_file").setLevel(logging.CRITICAL)
        from whatsapp_sender import WhatsAppSender

        self.sender = WhatsAppSender(
            excel_path="fake.xlsx",
            config={"human_behavior": False},
            log_callback=lambda msg: None,
        )

    def _falhar(self, vezes):
        with patch.object(seletores, "registrar_falha_estrutural") as reg:
            reg.return_value = False
            for _ in range(vezes):
                self.sender._registrar_campo_mensagem_ausente()
            return reg

    def test_uma_falha_sozinha_nao_busca_nada(self):
        """Um número que não existe no WhatsApp produz exatamente isto."""
        self.assertEqual(self._falhar(1).call_count, 0)

    def test_abaixo_do_limiar_nao_busca(self):
        self.assertEqual(
            self._falhar(WhatsAppSenderLimiar() - 1).call_count, 0
        )

    def test_no_limiar_trata_como_estrutural(self):
        reg = self._falhar(WhatsAppSenderLimiar())
        self.assertEqual(reg.call_count, 1)
        self.assertEqual(reg.call_args[0][0], "campo_mensagem")

    def test_campo_que_aparece_zera_a_contagem(self):
        """
        É o reset (feito em _wait_chat_or_invalid_popup) que garante que só
        uma sequência ININTERRUPTA chega ao limiar: dois inválidos, um bom e
        mais dois inválidos não são "quatro falhas".
        """
        limiar = WhatsAppSenderLimiar()
        with patch.object(seletores, "registrar_falha_estrutural") as reg:
            reg.return_value = False
            for _ in range(limiar - 1):
                self.sender._registrar_campo_mensagem_ausente()
            self.sender._falhas_campo_mensagem = 0  # o campo apareceu
            for _ in range(limiar - 1):
                self.sender._registrar_campo_mensagem_ausente()
            self.assertEqual(reg.call_count, 0)

    def test_dispara_de_novo_so_apos_outra_sequencia_inteira(self):
        limiar = WhatsAppSenderLimiar()
        with patch.object(seletores, "registrar_falha_estrutural") as reg:
            reg.return_value = False
            for _ in range(limiar * 2):
                self.sender._registrar_campo_mensagem_ausente()
            self.assertEqual(reg.call_count, 2)

    def test_erro_na_busca_nunca_sobe_para_o_laco_de_envio(self):
        """
        Invariante 1 aplicada aqui: a camada de seletores não pode derrubar um
        envio em andamento. Se a busca explodir, o contato segue seu caminho
        normal (inválido) e o envio continua.
        """
        with patch.object(seletores, "registrar_falha_estrutural") as reg:
            reg.side_effect = RuntimeError("supabase caiu")
            for _ in range(WhatsAppSenderLimiar()):
                self.sender._registrar_campo_mensagem_ausente()  # não levanta

    def test_avisa_o_usuario_em_linguagem_nao_tecnica(self):
        """O texto que vai ao painel é o MSG_ATUALIZANDO, sem jargão."""
        recebidos = []
        self.sender.log_callback = recebidos.append
        with patch.object(seletores, "registrar_falha_estrutural") as reg:
            reg.return_value = True  # achou seletor novo
            for _ in range(WhatsAppSenderLimiar()):
                self.sender._registrar_campo_mensagem_ausente()
        self.assertTrue(any(seletores.MSG_ATUALIZANDO in m for m in recebidos))


def WhatsAppSenderLimiar():
    from whatsapp_sender import WhatsAppSender

    return WhatsAppSender._FALHAS_CAMPO_PARA_ESTRUTURAL


class TestMensagensAoUsuario(BaseSeletores):
    def test_nao_vazam_termos_tecnicos(self):
        """
        O usuário é leigo: ele nunca vê nome de seletor. Isso vai para o
        log.txt, não para a tela.
        """
        for msg in (seletores.MSG_ATUALIZANDO, seletores.MSG_FALHOU):
            with self.subTest(msg=msg):
                baixo = msg.lower()
                for termo in ("seletor", "dom", "css", "json", "supabase", "#pane-side"):
                    self.assertNotIn(termo, baixo)


if __name__ == "__main__":
    unittest.main(verbosity=2)
