# -*- coding: utf-8 -*-
"""
Testes da varredura de respostas (`varredura.py`, BRAINSTORM_IA.md #7).

O usuário dispara a campanha e, horas ou dias depois, clica em "Verificar
respostas". O app abre o Chrome, lê a lista de conversas SEM abrir nenhuma,
grava a planilha e fecha.

O que estes testes travam:

  1. **Escopo.** Só `Enviado=X`. Um contato inválido nunca teve entrega, e se o
     cliente já tinha conversa anterior com aquele número, lê-la atribuiria a
     esta campanha o estado de uma mensagem antiga.
  2. **Grava fato, não rótulo.** Nenhuma coluna `Classe`: quente/frio é
     derivado na exibição, para que mudar a régua não obrigue a varrer tudo
     de novo.
  3. **Silêncio é melhor que invenção.** Conversa não encontrada não vira
     "não respondeu"; horário desconhecido não vira data inventada;
     INDETERMINADO não sobrescreve leitura boa.
  4. **Não reconsulta quem já respondeu** — ninguém des-responde, e a
     varredura custa ~5min para 118 contatos.
  5. **O botão Parar funciona no meio.**

Rodar:
    python -m unittest tests.test_varredura -v
"""

import os
import sys
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import linha_conversa
import varredura


def planilha(linhas):
    """linhas: lista de dicts parciais; o resto vem com o padrão."""
    base = {
        "Nome": "", "Número": "", "Mensagem": "oi",
        "Enviado": "", "DataEnvio": "", "Invalido": "", "Motivo": "",
        "Respondeu": "", "DataResposta": "", "Entrega": "", "UltimaVerificacao": "",
        "RespostaTexto": "",
    }
    return pd.DataFrame([{**base, **l} for l in linhas])


def leitura(numero, estado, horario=None, texto=""):
    return {"numero": numero, "estado": estado, "horario": horario,
            "ultima_mensagem": texto}


class TestEscopo(unittest.TestCase):
    def test_so_enviados_entram(self):
        df = planilha([
            {"Número": "19995947333", "Enviado": "X"},
            {"Número": "19988887777", "Enviado": ""},
        ])
        self.assertEqual(varredura.linhas_para_verificar(df), [0])

    def test_invalido_nao_entra(self):
        """
        Um inválido nunca teve entrega (AttachmentError não manda o texto,
        WhatsAppNotLoadedError é anterior a qualquer entrega). Se houvesse
        conversa anterior com o número, ler a linha atribuiria a esta campanha
        o estado de uma mensagem antiga.
        """
        df = planilha([{"Número": "19995947333", "Enviado": "", "Invalido": "X"}])
        self.assertEqual(varredura.linhas_para_verificar(df), [])

    def test_quem_ja_respondeu_nao_e_reconsultado(self):
        """Ninguém des-responde. Reconsultar é minuto jogado fora."""
        df = planilha([
            {"Número": "19995947333", "Enviado": "X", "Respondeu": "Sim"},
            {"Número": "19988887777", "Enviado": "X", "Respondeu": "Não"},
        ])
        self.assertEqual(varredura.linhas_para_verificar(df), [1])

    def test_numero_repetido_mapeia_para_as_duas_linhas(self):
        """Uma leitura só resolve as duas linhas com o mesmo número."""
        df = planilha([
            {"Número": "19995947333", "Enviado": "X"},
            {"Número": "5519995947333", "Enviado": "X"},
        ])
        mapa = varredura.mapa_de_numeros(df, [0, 1])
        self.assertEqual(mapa, {"19995947333": [0, 1]})

    def test_numero_vazio_nao_vira_chave(self):
        df = planilha([{"Número": "", "Enviado": "X"}])
        self.assertEqual(varredura.mapa_de_numeros(df, [0]), {})


class TestGravacao(unittest.TestCase):
    def setUp(self):
        self.agora = datetime(2026, 9, 6, 18, 0, 0)

    def test_respondeu_grava_data_da_resposta(self):
        df = planilha([{"Número": "19995947333", "Enviado": "X",
                        "DataEnvio": "2026-09-06 14:00:00"}])
        varredura.aplicar_leitura(
            df, 0,
            leitura("19995947333", linha_conversa.ULTIMA_DELES, datetime(2026, 9, 6, 14, 12)),
            self.agora,
        )
        self.assertEqual(df.at[0, "Respondeu"], "Sim")
        self.assertEqual(df.at[0, "Entrega"], varredura.ENTREGA_RESPONDEU)
        self.assertEqual(df.at[0, "DataResposta"], "2026-09-06 14:12:00")

    def test_horario_desconhecido_nao_vira_data_inventada(self):
        """
        O WhatsApp mostra só o nome do dia em conversas antigas. Em branco o
        cliente ainda sabe que respondeu — só não em quanto tempo.
        """
        df = planilha([{"Número": "19995947333", "Enviado": "X"}])
        varredura.aplicar_leitura(
            df, 0, leitura("19995947333", linha_conversa.ULTIMA_DELES, None), self.agora
        )
        self.assertEqual(df.at[0, "Respondeu"], "Sim")
        self.assertEqual(df.at[0, "DataResposta"], "")

    def test_entregue_e_lido(self):
        df = planilha([{"Número": "1", "Enviado": "X"}, {"Número": "2", "Enviado": "X"}])
        varredura.aplicar_leitura(df, 0, leitura("1", linha_conversa.ENTREGUE), self.agora)
        varredura.aplicar_leitura(df, 1, leitura("2", linha_conversa.LIDO), self.agora)
        self.assertEqual(df.at[0, "Entrega"], varredura.ENTREGA_ENTREGUE)
        self.assertEqual(df.at[1, "Entrega"], varredura.ENTREGA_LIDO)
        self.assertEqual(df.at[0, "Respondeu"], "Não")

    def test_indeterminado_nao_grava_nada(self):
        """Extração quebrada não é evidência — não pode apagar leitura boa."""
        df = planilha([{"Número": "1", "Enviado": "X"}])
        varredura.aplicar_leitura(df, 0, leitura("1", linha_conversa.ENTREGUE), self.agora)
        escrito = varredura.aplicar_leitura(
            df, 0, leitura("1", linha_conversa.INDETERMINADO), self.agora
        )
        self.assertEqual(escrito, "")
        self.assertEqual(df.at[0, "Entrega"], varredura.ENTREGA_ENTREGUE)

    def test_nao_existe_coluna_de_rotulo(self):
        """
        O rótulo quente/frio é derivado na exibição, como o `duplicado`.
        Gravá-lo congelaria a régua e exigiria varrer tudo de novo para mudá-la.
        """
        df = planilha([{"Número": "1", "Enviado": "X"}])
        varredura.aplicar_leitura(df, 0, leitura("1", linha_conversa.LIDO), self.agora)
        for proibida in ("Classe", "Status", "Quente", "Temperatura"):
            self.assertNotIn(proibida, df.columns)


class TestTextoDaResposta(unittest.TestCase):
    """
    `RespostaTexto` e' o TEOR da resposta, gravado como fato — o unico eixo de
    quente/morno/frio que nao sai de metadado nenhum.

    Ele existe para que mudar a regua seja mudar uma funcao pura, como ja vale
    para `Entrega` e para o `duplicado`. Sem o texto na planilha, reclassificar
    obrigaria a reabrir o Chrome e reler a lista inteira.
    """

    def setUp(self):
        self.agora = datetime(2026, 9, 12, 18, 0, 0)

    def test_resposta_grava_o_texto(self):
        df = planilha([{"Número": "1", "Enviado": "X"}])
        varredura.aplicar_leitura(
            df, 0,
            leitura("1", linha_conversa.ULTIMA_DELES, texto="Quanto custa?"),
            self.agora,
        )
        self.assertEqual(df.at[0, "RespostaTexto"], "Quanto custa?")

    def test_texto_nosso_nunca_e_gravado_como_resposta(self):
        """
        Medido na sonda de 12/09/2026: quando a ultima mensagem e' NOSSA, o
        mesmo campo do DOM traz o NOSSO texto (`'Show'`, `'Eu vim treinar'`).
        Grava-lo faria a triagem por teor classificar a nossa propria campanha
        como se fosse a resposta do contato.
        """
        df = planilha([{"Número": "1", "Enviado": "X"},
                       {"Número": "2", "Enviado": "X"},
                       {"Número": "3", "Enviado": "X"}])
        for i, estado in enumerate((linha_conversa.LIDO,
                                    linha_conversa.ENTREGUE,
                                    linha_conversa.NAO_ENTREGUE)):
            varredura.aplicar_leitura(
                df, i, leitura(str(i + 1), estado, texto="Ola, tenho uma oferta"),
                self.agora,
            )
            self.assertEqual(df.at[i, "RespostaTexto"], "", estado)

    def test_texto_e_truncado_no_limite(self):
        """A planilha e' aberta no Excel, e o texto ainda trafega no /contacts."""
        df = planilha([{"Número": "1", "Enviado": "X"}])
        varredura.aplicar_leitura(
            df, 0,
            leitura("1", linha_conversa.ULTIMA_DELES,
                    texto="a" * (varredura.LIMITE_RESPOSTA_TEXTO + 500)),
            self.agora,
        )
        self.assertEqual(len(df.at[0, "RespostaTexto"]),
                         varredura.LIMITE_RESPOSTA_TEXTO)

    def test_resposta_em_figurinha_nao_quebra(self):
        """
        Midia vira rotulo localizado do WhatsApp ("Foto", "Figurinha"), nao
        conteudo. Continua sendo resposta — so' nao tem teor para triar.
        """
        df = planilha([{"Número": "1", "Enviado": "X"}])
        varredura.aplicar_leitura(
            df, 0,
            leitura("1", linha_conversa.ULTIMA_DELES, texto="Figurinha"),
            self.agora,
        )
        self.assertEqual(df.at[0, "Respondeu"], "Sim")
        self.assertEqual(df.at[0, "RespostaTexto"], "Figurinha")

    def test_indeterminado_nao_apaga_texto_ja_lido(self):
        """Mesma regra do resto da linha: extracao quebrada nao e' evidencia."""
        df = planilha([{"Número": "1", "Enviado": "X"}])
        varredura.aplicar_leitura(
            df, 0, leitura("1", linha_conversa.ULTIMA_DELES, texto="Tenho interesse"),
            self.agora,
        )
        varredura.aplicar_leitura(
            df, 0, leitura("1", linha_conversa.INDETERMINADO, texto=""), self.agora
        )
        self.assertEqual(df.at[0, "RespostaTexto"], "Tenho interesse")

    def test_rascunho_nao_grava_resposta(self):
        """
        Integracao com o guard de `linha_conversa`: uma linha sem
        `last-msg-status` (conversa com rascunho) chega aqui como
        INDETERMINADO e nao pode virar `Respondeu=Sim`.
        """
        crua = {
            "indice": 0, "titulo": "+55 19 99594-7333", "horario": "14:32",
            "nao_lidas": "", "icones_status": None, "cor_status": "",
            "ultima_mensagem": "",
        }
        lida = linha_conversa.interpretar(crua)
        df = planilha([{"Número": "19995947333", "Enviado": "X"}])
        escrito = varredura.aplicar_leitura(df, 0, lida, self.agora)
        self.assertEqual(escrito, "")
        self.assertEqual(df.at[0, "Respondeu"], "")
        self.assertEqual(df.at[0, "RespostaTexto"], "")

    def test_continua_sem_coluna_de_rotulo(self):
        """Texto e' fato; quente/morno/frio continua derivado na exibicao."""
        df = planilha([{"Número": "1", "Enviado": "X"}])
        varredura.aplicar_leitura(
            df, 0, leitura("1", linha_conversa.ULTIMA_DELES, texto="Sim"), self.agora
        )
        for proibida in ("Classe", "Temperatura", "Quente", "Interesse"):
            self.assertNotIn(proibida, df.columns)


class TestRetentativa(unittest.TestCase):
    """
    "Nao achei a conversa" e "o WhatsApp Web ainda nao sincronizou" sao a mesma
    coisa vistas de fora — e a segunda e' o caso comum, porque a varredura abre
    um Chrome e comeca a procurar ~15s depois.

    Regressao de campo (12/09/2026): um contato recebeu a mensagem as 13:17 e
    respondeu na hora; as verificacoes das 13:22 e 13:24 gravaram NADA e a tela
    mostrou "-". O log mostra as duas gastando exatamente os 4s de
    `TIMEOUT_BUSCA_SEG` e desistindo, com o relogio (`ic-schedule`) numa
    mensagem ja enviada — a lista estava fria. A conversa era nova, criada pelo
    proprio envio, e ainda nao existia nem na lista nem no indice da busca.

    Rodando a MESMA busca depois, ela casa em 0,43s.
    """

    def setUp(self):
        self.agora = datetime(2026, 9, 6, 18, 0, 0)
        self.df = planilha([
            {"Nome": "A", "Número": "19990000001", "Enviado": "X",
             "DataEnvio": "2026-09-06 14:00:00"},
        ])
        pausa = patch.object(varredura, "PAUSA_RETENTATIVA_SEG", 0)
        pausa.start()
        self.addCleanup(pausa.stop)

    def _varredura(self, **kw):
        return varredura.Varredura(MagicMock(), **kw)

    def test_quem_sincroniza_tarde_e_achado_na_segunda(self):
        """O caso exato do 12/09/2026: vazio na 1a volta, presente na 2a."""
        v = self._varredura()
        v._buscar = MagicMock(side_effect=[
            [],  # WhatsApp Web ainda frio
            [leitura("19990000001", linha_conversa.ULTIMA_DELES,
                     datetime(2026, 9, 6, 14, 5), texto="Hummm")],
        ])
        with patch.object(linha_conversa, "ler_linhas", return_value=[]):
            resumo = v.executar(self.df, self.agora)

        self.assertEqual(v._buscar.call_count, 2)
        self.assertEqual(resumo["nao_encontrados"], 0)
        self.assertEqual(resumo["respondeu"], 1)
        self.assertEqual(self.df.at[0, "Respondeu"], "Sim")
        self.assertEqual(self.df.at[0, "RespostaTexto"], "Hummm")

    def test_uma_retentativa_so(self):
        """
        Uma segunda volta paga o caso da sincronizacao; uma terceira so' gasta
        o tempo do cliente, porque a essa altura a conversa realmente nao esta
        la (contato salvo na agenda, conversa apagada).
        """
        v = self._varredura()
        v._buscar = MagicMock(return_value=[])
        with patch.object(linha_conversa, "ler_linhas", return_value=[]):
            resumo = v.executar(self.df, self.agora)

        self.assertEqual(v._buscar.call_count, 2)
        self.assertEqual(resumo["nao_encontrados"], 1)

    def test_quem_foi_achado_na_lista_nao_paga_a_pausa(self):
        """
        O caso normal (a campanha foi a ultima coisa na conta) resolve tudo na
        passada livre. Esperar ali seria cobrar de todo mundo o preco de um
        problema que nao aconteceu.
        """
        v = self._varredura()
        v._buscar = MagicMock()
        v._dormir = MagicMock(return_value=True)
        with patch.object(linha_conversa, "ler_linhas", return_value=[
            leitura("19990000001", linha_conversa.ULTIMA_DELES),
        ]):
            v.executar(self.df, self.agora)

        v._buscar.assert_not_called()
        v._dormir.assert_not_called()

    def test_parar_durante_a_pausa_nao_faz_a_segunda_volta(self):
        """O botao Parar tem de responder tambem enquanto se espera."""
        v = self._varredura()
        v._buscar = MagicMock(return_value=[])
        v._dormir = MagicMock(return_value=False)   # usuario parou
        with patch.object(linha_conversa, "ler_linhas", return_value=[]):
            resumo = v.executar(self.df, self.agora)

        self.assertEqual(v._buscar.call_count, 1)
        self.assertTrue(resumo["interrompida"])

    def test_parada_no_meio_nao_conta_quem_nao_foi_procurado(self):
        """
        Quem nao chegou a ser consultado nao e' "nao encontrado" — nao foi
        procurado. Contar seria reportar uma falha que nao houve.
        """
        df = planilha([
            {"Número": "19990000001", "Enviado": "X"},
            {"Número": "19990000002", "Enviado": "X"},
        ])
        v = self._varredura(stop_cb=MagicMock(return_value=True))
        v._buscar = MagicMock(return_value=[])
        with patch.object(linha_conversa, "ler_linhas", return_value=[]):
            resumo = v.executar(df, self.agora)

        self.assertTrue(resumo["interrompida"])
        self.assertEqual(resumo["nao_encontrados"], 0)
        v._buscar.assert_not_called()

    def test_nao_encontrado_deixa_rastro_no_log(self):
        """
        E' o unico desfecho que nao escreve nada na planilha: sem esta linha,
        um "-" na tela e um contato ainda nao verificado sao indistinguiveis
        depois do fato. Diagnosticar o caso de 12/09/2026 custou seis sondas.
        """
        v = self._varredura()
        v._buscar = MagicMock(return_value=[
            leitura("11955554444", linha_conversa.LIDO),   # outra conversa
        ])
        with patch.object(linha_conversa, "ler_linhas", return_value=[]):
            with self.assertLogs(varredura.file_logger, level="INFO") as capturado:
                v.executar(self.df, self.agora)

        texto = "\n".join(capturado.output)
        self.assertIn("NAO ENCONTRADO", texto)
        self.assertIn("19990000001", texto)      # qual numero falhou
        self.assertIn("tentativa=1", texto)      # e em qual volta
        self.assertIn("tentativa=2", texto)
        self.assertIn("11955554444", texto)      # o que a busca devolveu


class TestLatencia(unittest.TestCase):
    def test_calcula_o_intervalo(self):
        self.assertEqual(
            varredura.latencia_segundos("2026-09-06 14:00:00", "2026-09-06 14:12:00"),
            720,
        )

    def test_sem_data_de_resposta_devolve_none(self):
        self.assertIsNone(varredura.latencia_segundos("2026-09-06 14:00:00", ""))

    def test_resposta_no_mesmo_minuto_vale_zero(self):
        """
        Caso de campo (12/09/2026): envio as 13:17:09, resposta imediata. A
        linha do WhatsApp so' mostra "13:17", ancorado no segundo 00, entao a
        conta da -9s — e a coluna mostrava so' a palavra "Respondeu" para o
        contato que respondeu MAIS RAPIDO, alem de manda-lo para o fim da
        ordenacao por latencia.

        A imprecisao aqui e' de no maximo 60s, entao "menos de um minuto" e'
        uma afirmacao provada, nao um chute.
        """
        self.assertEqual(
            varredura.latencia_segundos("2026-09-12 13:17:09", "2026-09-12 13:17:00"),
            0.0,
        )

    def test_negativo_maior_que_um_minuto_continua_none(self):
        """
        Fronteira: "Ontem" e' ancorado na meia-noite, e ai o erro chega a 24h.
        Esse caso NAO pode virar zero — seria inventar.
        """
        self.assertIsNone(
            varredura.latencia_segundos("2026-09-12 13:17:09", "2026-09-12 13:16:00")
        )

    def test_resposta_antes_do_envio_devolve_none(self):
        """
        "Ontem" é ancorado na meia-noite porque o WhatsApp não mostra a hora.
        Isso pode dar um intervalo negativo — imprecisão, não viagem no tempo.
        Melhor não afirmar nada que mostrar latência negativa.
        """
        self.assertIsNone(
            varredura.latencia_segundos("2026-09-06 14:00:00", "2026-09-05 00:00:00")
        )

    def test_valores_lixo_nao_estouram(self):
        for a, b in (("nan", "nan"), ("", ""), ("xx", "yy"), (None, None)):
            with self.subTest(a=a, b=b):
                self.assertIsNone(varredura.latencia_segundos(a, b))


class TestExecucao(unittest.TestCase):
    def setUp(self):
        # A pausa da retentativa e' tempo de parede de verdade (20s). Zera aqui
        # para a suite nao dormir; o COMPORTAMENTO dela (que ela existe, que
        # respeita o Parar) tem testes proprios em TestRetentativa.
        pausa = patch.object(varredura, "PAUSA_RETENTATIVA_SEG", 0)
        pausa.start()
        self.addCleanup(pausa.stop)
        self.agora = datetime(2026, 9, 6, 18, 0, 0)
        self.df = planilha([
            {"Nome": "A", "Número": "19990000001", "Enviado": "X", "DataEnvio": "2026-09-06 14:00:00"},
            {"Nome": "B", "Número": "19990000002", "Enviado": "X", "DataEnvio": "2026-09-06 14:00:00"},
            {"Nome": "C", "Número": "19990000003", "Enviado": "", "Invalido": "X"},
        ])

    def _varredura(self, **kw):
        return varredura.Varredura(MagicMock(), **kw)

    def test_passada_livre_resolve_sem_usar_a_busca(self):
        """
        O #pane-side já traz ~71 linhas renderizadas. Quando a campanha foi a
        última coisa na conta, isso resolve tudo sem digitar nada — e digitar
        na busca é o único custo real da varredura.
        """
        v = self._varredura()
        v._buscar = MagicMock()
        with patch.object(linha_conversa, "ler_linhas", return_value=[
            leitura("19990000001", linha_conversa.ULTIMA_DELES, datetime(2026, 9, 6, 14, 5)),
            leitura("19990000002", linha_conversa.ENTREGUE),
        ]):
            resumo = v.executar(self.df, self.agora)

        v._buscar.assert_not_called()
        self.assertEqual(resumo["respondeu"], 1)
        self.assertEqual(resumo["verificados"], 2)
        self.assertEqual(self.df.at[0, "Respondeu"], "Sim")

    def test_quem_sobra_vai_para_a_busca(self):
        v = self._varredura()
        v._buscar = MagicMock(
            return_value=[leitura("19990000002", linha_conversa.LIDO)]
        )
        with patch.object(linha_conversa, "ler_linhas", return_value=[
            leitura("19990000001", linha_conversa.ENTREGUE),
        ]):
            v.executar(self.df, self.agora)

        v._buscar.assert_called_once_with("19990000002")
        self.assertEqual(self.df.at[1, "Entrega"], varredura.ENTREGA_LIDO)

    def test_conversa_nao_encontrada_nao_vira_nao_respondeu(self):
        """
        Pode ser contato salvo na agenda (a linha aparece pelo nome, sem
        número) ou conversa apagada. Gravar "não respondeu" seria afirmar algo
        que ninguém leu.
        """
        v = self._varredura()
        v._buscar = MagicMock(return_value=[])
        with patch.object(linha_conversa, "ler_linhas", return_value=[]):
            resumo = v.executar(self.df, self.agora)

        self.assertEqual(resumo["nao_encontrados"], 2)
        self.assertEqual(self.df.at[0, "Entrega"], "")
        self.assertEqual(self.df.at[0, "Respondeu"], "")

    def test_contato_invalido_nunca_e_consultado(self):
        v = self._varredura()
        v._buscar = MagicMock(return_value=[])
        with patch.object(linha_conversa, "ler_linhas", return_value=[]):
            v.executar(self.df, self.agora)
        buscados = [c.args[0] for c in v._buscar.call_args_list]
        self.assertNotIn("19990000003", buscados)

    def test_conversa_de_fora_da_campanha_e_ignorada(self):
        """A lista traz as conversas pessoais do cliente."""
        v = self._varredura()
        v._buscar = MagicMock(return_value=[])
        with patch.object(linha_conversa, "ler_linhas", return_value=[
            leitura("11988887777", linha_conversa.ULTIMA_DELES),
        ]):
            resumo = v.executar(self.df, self.agora)
        self.assertEqual(resumo["respondeu"], 0)

    def test_parada_interrompe_no_meio(self):
        parar = MagicMock(return_value=True)
        v = self._varredura(stop_cb=parar)
        v._buscar = MagicMock(return_value=[])
        with patch.object(linha_conversa, "ler_linhas", return_value=[]):
            resumo = v.executar(self.df, self.agora)
        self.assertTrue(resumo["interrompida"])
        v._buscar.assert_not_called()

    def test_falha_na_leitura_inicial_cai_para_a_busca(self):
        """A passada livre é otimização; falhar nela não pode abortar tudo."""
        v = self._varredura()
        v._buscar = MagicMock(
            return_value=[leitura("19990000001", linha_conversa.ENTREGUE)]
        )
        with patch.object(linha_conversa, "ler_linhas", side_effect=RuntimeError("x")):
            resumo = v.executar(self.df, self.agora)
        # 3 e nao 2: os dois numeros vao para a busca, um nao e' achado, e ele
        # ganha a retentativa. Ver TestRetentativa.
        self.assertEqual(v._buscar.call_count, 3)
        self.assertEqual(resumo["verificados"], 1)

    def test_falha_de_uma_busca_nao_derruba_as_outras(self):
        v = self._varredura()
        v._buscar = MagicMock(side_effect=[
            RuntimeError("timeout"),
            [leitura("19990000002", linha_conversa.ENTREGUE)],
            # 3a chamada: a retentativa de quem falhou na 1a.
            RuntimeError("timeout"),
        ])
        with patch.object(linha_conversa, "ler_linhas", return_value=[]):
            resumo = v.executar(self.df, self.agora)
        self.assertEqual(resumo["verificados"], 1)
        self.assertEqual(resumo["nao_encontrados"], 1)

    def test_planilha_sem_enviados_nao_abre_nada(self):
        df = planilha([{"Número": "19990000001", "Enviado": ""}])
        v = self._varredura()
        v._buscar = MagicMock()
        with patch.object(linha_conversa, "ler_linhas") as ler:
            resumo = v.executar(df, self.agora)
        ler.assert_not_called()
        v._buscar.assert_not_called()
        self.assertEqual(resumo["total"], 0)


class TestContatoSalvoNaAgenda(unittest.TestCase):
    """
    Contato salvo aparece na lista pelo NOME, sem número. Como todo o
    casamento planilha-contra-lista era por número, ele caía em "conversa não
    encontrada" — o único desfecho que não escreve NADA. Na tela isso é um
    `-`, idêntico a nunca ter sido verificado: o app simplesmente não dizia se
    a mensagem tinha sido vista, justamente para os contatos já conhecidos.

    Os dois casamentos de reserva preferem o silêncio à invenção: qualquer
    ambiguidade devolve o contato para "não encontrado", que é o
    comportamento de antes.
    """

    def setUp(self):
        pausa = patch.object(varredura, "PAUSA_RETENTATIVA_SEG", 0)
        pausa.start()
        self.addCleanup(pausa.stop)
        self.agora = datetime(2026, 9, 16, 18, 0, 0)

    def _df(self, linhas):
        return planilha([{**l, "Enviado": "X", "DataEnvio": "2026-09-16 14:00:00"}
                         for l in linhas])

    def _linha(self, titulo, estado, numero=""):
        return {"numero": numero, "titulo": titulo, "estado": estado,
                "horario": None, "ultima_mensagem": ""}

    # ---- mapa_de_nomes ----
    def test_nome_repetido_em_numeros_diferentes_nao_vira_chave(self):
        """Dois "João" na planilha são duas pessoas, e a lista não as separa."""
        df = self._df([
            {"Nome": "João Silva", "Número": "19990000001"},
            {"Nome": "João Silva", "Número": "19990000002"},
            {"Nome": "Isis Campos", "Número": "19990000003"},
        ])
        mapa = varredura.mapa_de_nomes(df, varredura.linhas_para_verificar(df))
        self.assertNotIn("joao silva", mapa)
        self.assertEqual(mapa["isis campos"], "19990000003")

    def test_mesmo_nome_no_mesmo_numero_continua_valendo(self):
        """Duas linhas do mesmo contato não são ambiguidade nenhuma."""
        df = self._df([
            {"Nome": "Isis Campos", "Número": "19990000003"},
            {"Nome": "Isis Campos", "Número": "5519990000003"},
        ])
        mapa = varredura.mapa_de_nomes(df, varredura.linhas_para_verificar(df))
        self.assertEqual(mapa["isis campos"], "19990000003")

    # ---- passada livre ----
    def test_passada_livre_casa_pelo_nome(self):
        df = self._df([{"Nome": "Isis Campos", "Número": "19990000001"}])
        v = varredura.Varredura(MagicMock())
        v._buscar = MagicMock()
        with patch.object(linha_conversa, "ler_linhas", return_value=[
            self._linha("Isis Campos", linha_conversa.LIDO),
        ]):
            resumo = v.executar(df, self.agora)

        v._buscar.assert_not_called()
        self.assertEqual(df.at[0, "Entrega"], varredura.ENTREGA_LIDO)
        self.assertEqual(resumo["nao_encontrados"], 0)

    def test_passada_livre_casa_mesmo_com_badge_de_nao_lidas(self):
        """
        O anúncio de não-lidas é prefixado ao título — e quem respondeu é
        exatamente quem tem badge.
        """
        df = self._df([{"Nome": "Isis Campos", "Número": "19990000001"}])
        v = varredura.Varredura(MagicMock())
        v._buscar = MagicMock()
        with patch.object(linha_conversa, "ler_linhas", return_value=[
            self._linha("1 mensagem não lidaIsis Campos",
                        linha_conversa.ULTIMA_DELES),
        ]):
            v.executar(df, self.agora)
        self.assertEqual(df.at[0, "Respondeu"], "Sim")

    def test_duas_linhas_com_o_mesmo_nome_nao_casam(self):
        """Dois "Isis Campos" na agenda: não há como saber qual é a nossa."""
        df = self._df([{"Nome": "Isis Campos", "Número": "19990000001"}])
        v = varredura.Varredura(MagicMock())
        v._buscar = MagicMock(return_value=[])
        with patch.object(linha_conversa, "ler_linhas", return_value=[
            self._linha("Isis Campos", linha_conversa.LIDO),
            self._linha("Isis Campos", linha_conversa.ULTIMA_DELES),
        ]):
            resumo = v.executar(df, self.agora)
        self.assertEqual(df.at[0, "Entrega"], "")
        self.assertEqual(resumo["nao_encontrados"], 1)

    def test_conversa_de_fora_da_campanha_nao_casa_por_nome(self):
        df = self._df([{"Nome": "Isis Campos", "Número": "19990000001"}])
        v = varredura.Varredura(MagicMock())
        v._buscar = MagicMock(return_value=[])
        with patch.object(linha_conversa, "ler_linhas", return_value=[
            self._linha("Tia Marta", linha_conversa.ULTIMA_DELES),
        ]):
            v.executar(df, self.agora)
        self.assertEqual(df.at[0, "Entrega"], "")

    def test_numero_continua_vencendo_o_nome(self):
        """Linha que mostra número casa por número, e só por ele."""
        df = self._df([
            {"Nome": "Isis Campos", "Número": "19990000001"},
            {"Nome": "Bruno Lima", "Número": "19990000002"},
        ])
        v = varredura.Varredura(MagicMock())
        v._buscar = MagicMock(return_value=[])
        with patch.object(linha_conversa, "ler_linhas", return_value=[
            # Título com número E o nome de OUTRO contato da planilha: o
            # número manda, e o nome não pode roubar a linha.
            self._linha("Bruno Lima", linha_conversa.ENTREGUE,
                        numero="19990000001"),
        ]):
            v.executar(df, self.agora)
        self.assertEqual(df.at[0, "Entrega"], varredura.ENTREGA_ENTREGUE)
        self.assertEqual(df.at[1, "Entrega"], "")

    # ---- passada de busca ----
    def test_busca_aceita_a_unica_conversa_que_sobrou_no_filtro(self):
        """
        A lista foi filtrada pelo número que digitamos; a única conversa que
        restou é a dele, mesmo que a planilha e a agenda escrevam o nome de
        jeitos diferentes.
        """
        df = self._df([{"Nome": "Isis", "Número": "19990000001"}])
        v = varredura.Varredura(MagicMock())
        v._buscar = MagicMock(return_value=[
            self._linha("Isis Campos - Pilates", linha_conversa.LIDO),
        ])
        with patch.object(linha_conversa, "ler_linhas", return_value=[]):
            resumo = v.executar(df, self.agora)
        self.assertEqual(df.at[0, "Entrega"], varredura.ENTREGA_LIDO)
        self.assertEqual(resumo["nao_encontrados"], 0)

    def test_busca_com_varias_conversas_ainda_aceita_pelo_nome(self):
        df = self._df([{"Nome": "Isis Campos", "Número": "19990000001"}])
        v = varredura.Varredura(MagicMock())
        v._buscar = MagicMock(return_value=[
            self._linha("Isis Campos", linha_conversa.LIDO),
            self._linha("Grupo Pilates", linha_conversa.ULTIMA_DELES),
        ])
        with patch.object(linha_conversa, "ler_linhas", return_value=[]):
            v.executar(df, self.agora)
        self.assertEqual(df.at[0, "Entrega"], varredura.ENTREGA_LIDO)

    def test_busca_ambigua_sem_nome_nao_grava_nada(self):
        """Duas conversas no filtro e nenhuma casa pelo nome: silêncio."""
        df = self._df([{"Nome": "Isis Campos", "Número": "19990000001"}])
        v = varredura.Varredura(MagicMock())
        v._buscar = MagicMock(return_value=[
            self._linha("Grupo Pilates", linha_conversa.LIDO),
            self._linha("Tia Marta", linha_conversa.ULTIMA_DELES),
        ])
        with patch.object(linha_conversa, "ler_linhas", return_value=[]):
            resumo = v.executar(df, self.agora)
        self.assertEqual(df.at[0, "Entrega"], "")
        self.assertEqual(resumo["nao_encontrados"], 1)

    def test_busca_que_devolve_outro_numero_nao_casa(self):
        """
        Uma conversa só, mas exibindo um número que não é o nosso: a busca
        trouxe a conversa errada. Se fosse o nosso, teria casado pelo número.
        """
        df = self._df([{"Nome": "Isis Campos", "Número": "19990000001"}])
        v = varredura.Varredura(MagicMock())
        v._buscar = MagicMock(return_value=[
            self._linha("+55 19 98888-7777", linha_conversa.LIDO,
                        numero="19988887777"),
        ])
        with patch.object(linha_conversa, "ler_linhas", return_value=[]):
            resumo = v.executar(df, self.agora)
        self.assertEqual(df.at[0, "Entrega"], "")
        self.assertEqual(resumo["nao_encontrados"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
