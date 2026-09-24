# -*- coding: utf-8 -*-
"""
Testes da leitura de uma linha do #pane-side (`linha_conversa.py`).

É a fundação das features de classificação (BRAINSTORM_IA.md #7 / #7b / #7c):
descobrir se o contato respondeu, e em que estado ficou a nossa mensagem, SEM
abrir a conversa.

Fixa os pontos que já se mostraram capazes de dar leitura errada:

  1. Ícone de TIPO DE MÍDIA mora no mesmo lugar do tique. Uma figurinha que
     ELE mandou não pode ser lida como tique nosso — o filtro do
     `chat-msg-symbol` é o que separa, e sem ele "respondeu" vira "entregue".
  2. A decisão é por AUSÊNCIA: um ícone de status desconhecido (o ✓ solitário,
     ainda não capturado em campo) tem de cair em NAO_ENTREGUE, nunca ser
     ignorado — é justamente ele que arma o alarme de entrega.
  3. Sem ícone nenhum = a última mensagem é dele = respondeu.
  4. Contato fora da agenda aparece como "+55 19 99594-7333" e tem de casar
     com o clean_number() da planilha.
  5. As marcas bidi invisíveis que cercam o texto da última mensagem quebram
     qualquer comparação se não forem removidas.

Rodar:
    python -m unittest tests.test_linha_conversa -v
"""

import json
import os
import sys
import unittest
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import linha_conversa as lc
import seletores


def linha(titulo="+55 19 99594-7333", icones=None, horario="14:32",
          nao_lidas="", ultima="teste", indice=0, cor=""):
    """Uma linha crua como o JS de extração devolve."""
    return {
        "indice": indice,
        "titulo": titulo,
        "horario": horario,
        "nao_lidas": nao_lidas,
        "icones_status": [] if icones is None else icones,
        "cor_status": cor,
        "ultima_mensagem": ultima,
    }


# Cores MEDIDAS em campo (08/09/2026, sonda_cor_tique.js, transicao ao vivo no
# mesmo contato). O azul e' o unico que prova leitura.
AZUL = "rgb(0, 123, 252)"
CINZA = "rgba(0, 0, 0, 0.6)"
# Tema escuro: o cinza vira branco translucido. Tem canal azul alto, entao a
# regra NAO pode ser "azul > 150" sozinha — precisa do azul acima do vermelho.
CINZA_TEMA_ESCURO = "rgba(255, 255, 255, 0.6)"
# Azul antigo do WhatsApp: a regra tem de continuar valendo se o tom mudar.
AZUL_ANTIGO = "rgb(83, 189, 235)"


class TestCorProvaLeitura(unittest.TestCase):
    """
    Regressao de campo (08/09/2026): mensagem entregue, tique duplo CINZA, e a
    coluna dizia "Leu". O nome do icone (`wds-ic-read`) e' o mesmo nos dois
    estados; o que os separa na tela e' a cor.

    A regra e' assimetrica de proposito: azul prova leitura, ausencia de azul
    nao prova nada. Quem desliga a confirmacao de leitura nunca fica azul, e
    afirmar "Leu" nesse caso seria inventar. Por isso o fallback e' ENTREGUE,
    que e' verdade nos dois casos.
    """

    def test_azul_prova_leitura(self):
        self.assertTrue(lc.cor_de_leitura(AZUL))
        self.assertTrue(lc.cor_de_leitura(AZUL_ANTIGO))
        self.assertTrue(lc.cor_de_leitura("rgba(0, 123, 252, 0.9)"))

    def test_cinza_nao_prova(self):
        self.assertFalse(lc.cor_de_leitura(CINZA))

    def test_branco_do_tema_escuro_nao_e_azul(self):
        """
        O cinza do tema escuro e' branco translucido: canal azul em 255. Um
        teste ingenuo de "azul alto" diria LIDO em toda mensagem entregue de
        quem usa tema escuro. E' por isso que a regra exige azul ACIMA do
        vermelho, e nao azul alto.
        """
        self.assertFalse(lc.cor_de_leitura(CINZA_TEMA_ESCURO))

    def test_sem_cor_nao_prova(self):
        """Cor ilegivel e' "nao consegui provar", nunca "leu"."""
        for valor in ("", None, "currentColor", "nao-e-cor"):
            with self.subTest(valor=valor):
                self.assertFalse(lc.cor_de_leitura(valor))

    def test_tique_duplo_cinza_e_entregue_e_nao_lido(self):
        """
        O caso exato reportado em campo, e o achado que sustenta esta classe:
        a sonda gravou o MESMO `wds-ic-read` nos dois estados do mesmo
        contato, mudando so' a cor — cinza aos 0.5s, azul aos 11.6s, quando a
        pessoa abriu a conversa. O nome do icone nao distingue nada.
        """
        self.assertEqual(lc.classificar_status(["wds-ic-read"], CINZA), lc.ENTREGUE)
        self.assertEqual(lc.classificar_status(["wds-ic-read"], AZUL), lc.LIDO)

    def test_tique_duplo_azul_e_lido(self):
        self.assertEqual(lc.classificar_status(["wds-ic-read"], AZUL), lc.LIDO)

    def test_sem_cor_cai_para_entregue(self):
        self.assertEqual(lc.classificar_status(["wds-ic-read"]), lc.ENTREGUE)

    def test_entregue_continua_contando_como_entregue(self):
        """
        Rebaixar LIDO para ENTREGUE nao pode mexer no alarme de entrega, que
        pergunta "chegou?" — e a resposta e' sim nos dois estados.
        """
        for cor in (AZUL, CINZA, None):
            with self.subTest(cor=cor):
                estado = lc.classificar_status(["wds-ic-read"], cor)
                self.assertIn(estado, lc.ESTADOS_ENTREGUES)

    def test_falha_ainda_vence_a_cor(self):
        self.assertEqual(
            lc.classificar_status(["wds-ic-read", "message-fail"], AZUL), lc.FALHOU)

    def test_interpretar_repassa_a_cor(self):
        cinza = lc.interpretar(linha(icones=["wds-ic-read"], cor=CINZA))
        self.assertEqual(cinza["estado"], lc.ENTREGUE)
        self.assertFalse(cinza["respondeu"])
        self.assertTrue(cinza["entregue"])

        azul = lc.interpretar(linha(icones=["wds-ic-read"], cor=AZUL))
        self.assertEqual(azul["estado"], lc.LIDO)

    def test_cor_vai_para_o_diagnostico(self):
        """Sem a cor no log, nao da para auditar por que deu Leu ou Entregue."""
        self.assertEqual(
            lc.interpretar(linha(icones=["wds-ic-read"], cor=AZUL))["cor_status"], AZUL)

    def test_nao_lida_ainda_vence_tudo(self):
        """Resposta dele continua acima de qualquer leitura da nossa mensagem."""
        r = lc.interpretar(linha(icones=["wds-ic-read"], cor=AZUL, nao_lidas="1"))
        self.assertTrue(r["respondeu"])


class TestClassificacaoDeStatus(unittest.TestCase):
    def test_sem_icone_significa_que_ele_mandou_por_ultimo(self):
        """Mensagem recebida não tem tique. Ausência de ícone = respondeu."""
        self.assertEqual(lc.classificar_status([]), lc.ULTIMA_DELES)

    def test_entregue_e_lido_saem_do_MESMO_icone(self):
        """
        Os dois estados vem do tique duplo (`wds-ic-read`); quem os separa e' a
        cor. Nao ha icone proprio de "entregue".
        """
        self.assertEqual(lc.classificar_status(["wds-ic-read"], CINZA), lc.ENTREGUE)
        self.assertEqual(lc.classificar_status(["wds-ic-read"], AZUL), lc.LIDO)

    def test_falha_vence_os_demais(self):
        """A mensagem não saiu: isso importa mais que qualquer outro estado."""
        self.assertEqual(
            lc.classificar_status(["wds-ic-read", "message-fail"], AZUL),
            lc.FALHOU,
        )

    def test_tique_solitario_nao_e_entrega(self):
        """
        `wds-ic-delivered` e' o ✓ SOLITARIO — saiu e NAO chegou — apesar do
        nome. Confirmado pelo cliente em 08/09/2026.

        Tratá-lo como entrega era duplamente ruim: dizia "Entregue" sobre
        mensagem que nao chegou E calava o alarme de entrega, que existe para
        detectar exatamente a mensagem que sai e nao chega (a assinatura do
        numero sendo limitado pelo WhatsApp). Este teste e' o que impede a
        leitura ingenua do nome de voltar.
        """
        estado = lc.classificar_status(["wds-ic-delivered"], CINZA)
        self.assertEqual(estado, lc.NAO_ENTREGUE)
        self.assertNotIn(estado, lc.ESTADOS_ENTREGUES)

    def test_icone_desconhecido_cai_em_nao_entregue(self):
        """
        A regra por ausencia: so' o ✓✓ e a falha tem significado proprio.
        Qualquer icone novo do WhatsApp e' tratado como "nao chegou", que e' o
        lado seguro — arma o alarme em vez de silenciá-lo.
        """
        self.assertEqual(lc.classificar_status(["wds-ic-sent"]), lc.NAO_ENTREGUE)
        self.assertEqual(lc.classificar_status(["qualquer-coisa-nova"]), lc.NAO_ENTREGUE)

    def test_nome_com_caixa_ou_espaco_ainda_casa(self):
        self.assertEqual(lc.classificar_status([" WDS-IC-Read "], AZUL), lc.LIDO)

    def test_o_ciclo_completo_medido_em_campo(self):
        """
        A sequencia que a sonda gravou no mesmo contato, em ordem. Se algum
        passo mudar de significado, e' aqui que aparece.
        """
        self.assertEqual(lc.classificar_status(["wds-ic-delivered"], CINZA), lc.NAO_ENTREGUE)
        self.assertEqual(lc.classificar_status(["wds-ic-read"], CINZA), lc.ENTREGUE)
        self.assertEqual(lc.classificar_status(["wds-ic-read"], AZUL), lc.LIDO)
        self.assertEqual(lc.classificar_status([]), lc.ULTIMA_DELES)

    def test_none_e_indeterminado_e_nao_vira_respondeu(self):
        """
        Falha de extração não pode ser confundida com "ele respondeu" — isso
        marcaria contato como respondido sem nenhuma evidência.
        """
        self.assertEqual(lc.classificar_status(None), lc.INDETERMINADO)

    def test_entradas_vazias_sao_descartadas_antes_de_decidir(self):
        self.assertEqual(lc.classificar_status(["", "   "]), lc.ULTIMA_DELES)


class TestNumeroDoTitulo(unittest.TestCase):
    def test_contato_fora_da_agenda_casa_com_a_planilha(self):
        """
        É o caso normal numa campanha. O título vem formatado; só os dígitos,
        já sem o DDI, é o que a planilha guarda.
        """
        self.assertEqual(lc.numero_do_titulo("+55 19 99594-7333"), "19995947333")

    def test_contato_salvo_nao_tem_numero(self):
        self.assertEqual(lc.numero_do_titulo("Isis Campos"), "")

    def test_nome_com_poucos_digitos_nao_vira_numero(self):
        """Um nome com dígitos não pode ser confundido com telefone."""
        self.assertEqual(lc.numero_do_titulo("Grupo 2024"), "")

    def test_titulo_vazio(self):
        self.assertEqual(lc.numero_do_titulo(""), "")
        self.assertEqual(lc.numero_do_titulo(None), "")

    def test_anuncio_de_nao_lidas_nao_polui_o_numero(self):
        """
        Regressao de campo (08/09/2026), capturada pela sonda no DOM real.

        Com mensagem nao lida, o WhatsApp Web injeta o anuncio de
        acessibilidade no MESMO elemento do titulo:

            "1 mensagem nao lida+55 19 99422-9146"

        Pegar "todos os digitos" dava "15519994229146" — 14 digitos que nao
        comecam com 55, entao nem o corte de DDI corrigia. A linha nao casava
        com a planilha, a varredura nao gravava nada, e o contato ficava com a
        leitura anterior ("Lido").

        O estrago era dirigido ao pior alvo possivel: so' quem tem nao-lida
        tem o prefixo, e so' quem respondeu tem nao-lida. O bug acertava
        exatamente os leads quentes.
        """
        self.assertEqual(
            lc.numero_do_titulo("1 mensagem nao lida+55 19 99422-9146"), "19994229146")
        self.assertEqual(
            lc.numero_do_titulo("1 mensagem não lida+55 19 99422-9146"), "19994229146")
        # Duas casas decimais de nao-lidas: o numero "12" nao pode vencer o
        # telefone na escolha do candidato.
        self.assertEqual(
            lc.numero_do_titulo("12 mensagens nao lidas+55 19 99594-7333"), "19995947333")

    def test_numero_cru_sem_formatacao(self):
        self.assertEqual(lc.numero_do_titulo("19994229146"), "19994229146")

    def test_linha_com_nao_lida_casa_e_e_lida_como_resposta(self):
        """
        O caso completo, do jeito que a sonda capturou: titulo com prefixo,
        badge de 1 nao-lida, `last-msg-status` presente mas SEM icone dentro.
        Tem de casar por numero E sair como resposta.
        """
        r = lc.interpretar(linha(
            titulo="1 mensagem nao lida+55 19 99422-9146",
            icones=[],
            nao_lidas="1",
        ))
        self.assertEqual(r["numero"], "19994229146")
        self.assertTrue(r["casa_por_numero"])
        self.assertTrue(r["respondeu"])


class TestLimparBidi(unittest.TestCase):
    def test_remove_marcas_invisiveis_do_whatsapp(self):
        """
        O `title` do last-msg-status vem cercado de U+202A/U+202C. Sem limpar,
        nenhuma comparação de texto funciona.
        """
        self.assertEqual(lc.limpar_bidi("‪teste‬"), "teste")

    def test_texto_normal_passa_intacto(self):
        self.assertEqual(lc.limpar_bidi("  Bom dia  "), "Bom dia")


class TestInterpretarHorario(unittest.TestCase):
    def setUp(self):
        self.agora = datetime(2026, 9, 6, 18, 0, 0)

    def test_hora_do_dia(self):
        self.assertEqual(
            lc.interpretar_horario("14:32", self.agora),
            datetime(2026, 9, 6, 14, 32),
        )

    def test_ontem_ancora_na_meia_noite(self):
        """
        O WhatsApp não mostra a hora de ontem. Meia-noite é a única âncora
        honesta: a latência sai como "mais de X horas", não como invenção.
        """
        self.assertEqual(
            lc.interpretar_horario("Ontem", self.agora),
            datetime(2026, 9, 5, 0, 0),
        )

    def test_data_explicita(self):
        self.assertEqual(
            lc.interpretar_horario("28/08/2026", self.agora),
            datetime(2026, 8, 28),
        )

    def test_dia_da_semana_devolve_none(self):
        """None é resposta legítima: melhor não saber que inventar."""
        self.assertIsNone(lc.interpretar_horario("segunda-feira", self.agora))

    def test_hora_invalida_devolve_none(self):
        self.assertIsNone(lc.interpretar_horario("99:99", self.agora))


class TestInterpretar(unittest.TestCase):
    def test_linha_de_quem_respondeu(self):
        r = lc.interpretar(linha(icones=[], nao_lidas="3"))
        self.assertTrue(r["respondeu"])
        self.assertFalse(r["entregue"])
        self.assertEqual(r["estado"], lc.ULTIMA_DELES)
        self.assertEqual(r["nao_lidas"], 3)

    def test_linha_entregue_sem_resposta(self):
        # Entregue e' o ✓✓ CINZA, nao o `wds-ic-delivered` (que e' o ✓ solitario).
        r = lc.interpretar(linha(icones=["wds-ic-read"], cor=CINZA))
        self.assertFalse(r["respondeu"])
        self.assertTrue(r["entregue"])

    def test_linha_do_tique_solitario_nao_conta_como_entregue(self):
        r = lc.interpretar(linha(icones=["wds-ic-delivered"], cor=CINZA))
        self.assertFalse(r["entregue"])
        self.assertEqual(r["estado"], lc.NAO_ENTREGUE)

    def test_linha_nao_entregue_nao_conta_como_entregue(self):
        """O alarme de entrega depende exatamente desta distinção."""
        r = lc.interpretar(linha(icones=["wds-ic-sent"]))
        self.assertFalse(r["entregue"])
        self.assertEqual(r["estado"], lc.NAO_ENTREGUE)

    def test_casa_por_numero_quando_fora_da_agenda(self):
        r = lc.interpretar(linha(titulo="+55 19 99594-7333"))
        self.assertTrue(r["casa_por_numero"])
        self.assertEqual(r["numero"], "19995947333")

    def test_contato_salvo_sinaliza_casamento_por_nome(self):
        r = lc.interpretar(linha(titulo="Isis Campos"))
        self.assertFalse(r["casa_por_numero"])
        self.assertEqual(r["numero"], "")

    def test_ultima_mensagem_vem_limpa_de_bidi(self):
        r = lc.interpretar(linha(ultima="‪Bom dia‬"))
        self.assertEqual(r["ultima_mensagem"], "Bom dia")

    def test_sem_badge_de_nao_lidas(self):
        self.assertEqual(lc.interpretar(linha(nao_lidas=""))["nao_lidas"], 0)

    def test_extracao_quebrada_nao_vira_respondeu(self):
        """
        Dict sem `icones_status` significa que a extração falhou, não que a
        última mensagem é dele. Confundir os dois marcaria o contato como
        respondido sem nenhuma evidência — o pior erro possível aqui, porque
        tira o contato da fila de follow-up para sempre.

        Repare a diferença com a lista VAZIA, que é evidência de verdade.
        """
        r = lc.interpretar({})
        self.assertEqual(r["estado"], lc.INDETERMINADO)
        self.assertFalse(r["respondeu"])
        self.assertEqual(r["numero"], "")

        self.assertTrue(lc.interpretar(linha(icones=[]))["respondeu"])


class TestNaoLidasVenceOTique(unittest.TestCase):
    """
    Regressao de campo (08/09/2026): contato respondeu, a linha mostrava o
    badge verde de 1 nao-lida, e a varredura gravou "Lido / nao respondeu".

    O contador de nao-lidas so' existe para mensagem RECEBIDA, e o envio abre
    a conversa (o que zera o contador daquele chat) — entao, num contato com
    `Enviado=X`, qualquer nao-lida e' mensagem nova dele. E' evidencia
    independente do icone, e mais forte que ele.
    """

    def test_badge_de_nao_lida_com_tique_de_lido_ainda_e_resposta(self):
        r = lc.interpretar(linha(icones=["wds-ic-read"], nao_lidas="1"))
        self.assertEqual(r["estado"], lc.ULTIMA_DELES)
        self.assertTrue(r["respondeu"])

    def test_vale_tambem_para_entregue_e_desconhecido(self):
        for icone in ("wds-ic-delivered", "wds-ic-sent", "icone-que-nao-existe"):
            with self.subTest(icone=icone):
                r = lc.interpretar(linha(icones=[icone], nao_lidas="2"))
                self.assertTrue(r["respondeu"], icone)

    def test_vence_ate_falha_de_entrega(self):
        """
        A falha descreve uma mensagem NOSSA; a resposta dele e' o fato mais
        recente e o unico acionavel.
        """
        r = lc.interpretar(linha(icones=["message-fail"], nao_lidas="1"))
        self.assertEqual(r["estado"], lc.ULTIMA_DELES)

    def test_sem_nao_lidas_o_icone_continua_mandando(self):
        """A regra antiga nao pode ter sido substituida, so' complementada."""
        self.assertEqual(
            lc.interpretar(linha(icones=["wds-ic-read"], cor=AZUL))["estado"], lc.LIDO)
        self.assertEqual(
            lc.interpretar(linha(icones=["wds-ic-read"], cor=CINZA, nao_lidas="0"))["estado"],
            lc.ENTREGUE,
        )

    def test_badge_com_texto_do_aria_label(self):
        """"3 mensagens nao lidas" tem de contar 3, nao virar 0."""
        self.assertEqual(lc.decidir_estado(["wds-ic-read"], 3), lc.ULTIMA_DELES)
        r = lc.interpretar(linha(icones=["wds-ic-read"], nao_lidas="3 mensagens nao lidas"))
        self.assertEqual(r["nao_lidas"], 3)
        self.assertTrue(r["respondeu"])

    def test_extracao_quebrada_com_badge_zerado_segue_indeterminada(self):
        """Nao-lidas ausente nao pode transformar leitura quebrada em resposta."""
        self.assertEqual(lc.decidir_estado(None, 0), lc.INDETERMINADO)


class TestJsDeExtracao(unittest.TestCase):
    """
    O JS não roda aqui, mas a montagem dele é onde um seletor mal injetado
    passaria despercebido até o browser.
    """

    @staticmethod
    def _seletores_do_js(js: str) -> dict:
        """Extrai de volta o objeto injetado, para comparar com o original."""
        bruto = js.split("const S = ", 1)[1].split("};", 1)[0] + "}"
        return json.loads(bruto)

    def test_seletores_sao_injetados_como_json(self):
        js = lc.js_extrair()
        self.assertNotIn("__SELETORES__", js)
        # Comparar o texto cru falharia: o json.dumps escapa as aspas dos
        # seletores. O que importa é o objeto chegar íntegro do outro lado.
        self.assertEqual(self._seletores_do_js(js), seletores.todos())

    def test_filtro_do_simbolo_de_midia_esta_presente(self):
        """
        Sem `closest(chat-msg-symbol)`, uma figurinha recebida seria lida como
        tique nosso — o erro mais caro que esta leitura pode cometer.
        """
        js = lc.js_extrair()
        self.assertIn("linha_simbolo_midia", js)
        self.assertIn("closest", js)

    def test_le_o_title_do_svg_e_o_data_icon(self):
        """Os dois esquemas de ícone convivem no DOM do WhatsApp."""
        js = lc.js_extrair()
        self.assertIn("svg > title", js)
        self.assertIn("data-icon", js)

    def test_aspas_do_seletor_nao_quebram_o_js(self):
        """
        Todo seletor do WhatsApp tem aspas (`[data-testid="..."]`). Injetá-los
        cruamente fecharia a string do JS no meio.
        """
        sels = {"linha_conversa": '[role="row"]', "linha_simbolo_midia": ""}
        self.assertEqual(self._seletores_do_js(lc.js_extrair(sels)), sels)


class TestRascunhoNaoEhResposta(unittest.TestCase):
    """
    Sonda de 12/09/2026 (`sonda_texto_resposta.js`), 19 linhas cuja ultima
    mensagem era DELE: em 18 o `last-msg-status` estava presente. A unica
    excecao era uma conversa com RASCUNHO — texto digitado e nao enviado, que
    substitui a previa e leva o elemento de status junto.

    Sem este guard a linha nao tinha icone nenhum, caia na regra por ausencia e
    virava `Respondeu=Sim` para um contato que nunca respondeu. E o caminho e'
    alcancavel numa campanha real: um envio interrompido entre `_human_type` e
    `_confirm_message_sent` deixa o texto digitado como rascunho na conversa.

    A distincao e' `None` (elemento ausente = sem evidencia) contra `[]`
    (elemento presente, sem tique = mensagem dele).
    """

    def _linha_sem_status(self, **extra):
        base = {
            "indice": 0,
            "titulo": "+55 19 99594-7333",
            "horario": "14:32",
            "nao_lidas": "",
            # O JS devolve `null` quando nao ha `last-msg-status` na linha.
            "icones_status": None,
            "cor_status": "",
            "ultima_mensagem": "",
        }
        base.update(extra)
        return base

    def test_sem_elemento_de_status_nao_vira_resposta(self):
        r = lc.interpretar(self._linha_sem_status())
        self.assertEqual(r["estado"], lc.INDETERMINADO)
        self.assertFalse(r["respondeu"])

    def test_lista_vazia_continua_sendo_resposta(self):
        """O caso normal (18 de 19): elemento presente, sem tique."""
        r = lc.interpretar(linha(icones=[]))
        self.assertEqual(r["estado"], lc.ULTIMA_DELES)
        self.assertTrue(r["respondeu"])

    def test_nao_lidas_vence_o_guard(self):
        """
        Uma conversa pode ter rascunho E mensagem nova dele. O contador e'
        prova independente do elemento de status.
        """
        r = lc.interpretar(self._linha_sem_status(nao_lidas="3"))
        self.assertEqual(r["estado"], lc.ULTIMA_DELES)
        self.assertTrue(r["respondeu"])

    def test_o_js_distingue_ausente_de_vazio(self):
        """
        `nomesDeIcone(null)` devolve `[]`, entao a diferenca tem de ser feita
        ANTES, no JS. Sem isto o Python nunca ve o `None`.
        """
        js = lc.js_extrair()
        self.assertIn("status ? nomesDeIcone(status) : null", js)


class TestTextoDaResposta(unittest.TestCase):
    """
    `ultima_mensagem` e' a materia-prima da triagem por teor — o unico eixo de
    quente/morno/frio que nao sai de metadado. A sonda de 12/09/2026 mediu de
    onde ele deve sair.
    """

    def test_vem_do_title_e_nao_da_previa(self):
        """
        A previa (`linha_previa`) e' `textContent`: absorve o `<title>` do svg
        do icone e o prefixo de remetente de grupo, e sairia
        `"wds-ic-readEu vim treinar"`. O `title` do `last-msg-status` vem
        limpo e INTEIRO (393 caracteres capturados, sem corte).
        """
        js = lc.js_extrair()
        self.assertIn("status.getAttribute('title')", js)
        # A previa continua sem consumidor. O nome dela aparece no JS porque
        # `js_extrair` injeta a tabela INTEIRA de seletores; o que nao pode
        # existir e' uma LEITURA dela (`S.linha_previa`).
        self.assertNotIn("S.linha_previa", js)

    def test_texto_da_mensagem_dele_chega_inteiro(self):
        longa = "Tenho interesse sim. " * 30
        r = lc.interpretar(linha(icones=[], ultima=longa))
        self.assertTrue(r["respondeu"])
        self.assertEqual(r["ultima_mensagem"], longa.strip())

    def test_quando_a_ultima_e_nossa_o_campo_traz_o_NOSSO_texto(self):
        """
        Medido na sonda: linha com `wds-ic-read` e title `'Eu vim treinar'` —
        texto nosso. Quem consome tem de checar `respondeu` antes de tratar
        isto como resposta do contato.
        """
        r = lc.interpretar(linha(icones=["wds-ic-read"], cor=AZUL,
                                 ultima="Eu vim treinar"))
        self.assertFalse(r["respondeu"])
        self.assertEqual(r["ultima_mensagem"], "Eu vim treinar")


class TestCasarPorNome(unittest.TestCase):
    """
    Contato SALVO na agenda aparece na lista pelo NOME, sem número nenhum, e
    todo o casamento planilha-contra-lista era por número — então ele caía em
    "conversa não encontrada", o único desfecho que não escreve nada. O cliente
    via `-` e concluía que o app não sabia dizer se a mensagem foi vista.
    """

    def test_nome_igual_casa(self):
        self.assertTrue(lc.titulo_casa_com_nome("Isis Campos", "Isis Campos"))

    def test_acento_maiuscula_e_espaco_nao_atrapalham(self):
        """Planilha e agenda são digitadas por pessoas diferentes."""
        self.assertTrue(lc.titulo_casa_com_nome("JOSE  SILVA", "José Silva"))
        self.assertTrue(lc.titulo_casa_com_nome(" José Silva ", "jose  silva"))

    def test_anuncio_de_nao_lidas_prefixado_nao_quebra(self):
        """
        O WhatsApp injeta "1 mensagem não lida" NO MESMO elemento do título, e
        sem espaço no meio — o mesmo que já envenenava a extração de número. E
        atinge exatamente quem respondeu, que é quem tem badge.
        """
        self.assertTrue(
            lc.titulo_casa_com_nome("1 mensagem não lidaIsis Campos", "Isis Campos"))
        self.assertTrue(
            lc.titulo_casa_com_nome("12 mensagens nao lidasIsis Campos", "Isis Campos"))

    def test_nome_no_fim_sem_anuncio_nao_casa(self):
        """
        Aceitar o nome no fim do título é concessão ao anúncio de não-lidas, que
        começa com o contador. Sem dígito na frente, "Ana" casaria com
        "Mariana" — e casar errado grava o estado da conversa de outra pessoa.
        """
        self.assertFalse(lc.titulo_casa_com_nome("Mariana", "Ana"))
        self.assertFalse(lc.titulo_casa_com_nome("Dr. Paulo", "Paulo"))

    def test_nome_diferente_nao_casa(self):
        self.assertFalse(lc.titulo_casa_com_nome("Isis Campos", "Bruno Lima"))

    def test_nome_curto_nunca_serve_de_chave(self):
        """Iniciais casariam com meio mundo numa lista de conversas."""
        self.assertFalse(lc.titulo_casa_com_nome("Ed", "Ed"))
        self.assertFalse(lc.titulo_casa_com_nome("Edson", "Ed"))

    def test_vazio_nao_casa(self):
        self.assertFalse(lc.titulo_casa_com_nome("", "Isis Campos"))
        self.assertFalse(lc.titulo_casa_com_nome("Isis Campos", ""))
        self.assertFalse(lc.titulo_casa_com_nome(None, None))


if __name__ == "__main__":
    unittest.main(verbosity=2)
