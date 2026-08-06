"""
Testes unitários para validação e normalização de números de telefone
vindos da planilha Excel.

Executa com:
    python -m pytest test_numeros.py -v
    ou
    python -m unittest test_numeros -v
"""

import logging
import unittest
from whatsapp_sender import WhatsAppSender


class BaseTestCase(unittest.TestCase):
    """Caso base que instancia o sender com config mínima."""

    def setUp(self):
        # Silencia o logger de diagnóstico durante os testes
        logging.getLogger("whatsapp_sender_file").setLevel(logging.CRITICAL)
        self.sender = WhatsAppSender(
            excel_path="fake.xlsx",
            config={},
            log_callback=lambda msg: None,
        )


class TestCleanNumber(BaseTestCase):
    """Testes para _clean_number: normalização de números da planilha."""

    # --- Formatos válidos comuns ---

    def test_numero_puro_11_digitos(self):
        """Celular com DDD sem formatação."""
        self.assertEqual(self.sender._clean_number("19994519934"), "19994519934")

    def test_numero_puro_10_digitos(self):
        """Fixo com DDD sem formatação."""
        self.assertEqual(self.sender._clean_number("1934567890"), "1934567890")

    def test_numero_com_parenteses_e_hifen(self):
        """Formato (XX)XXXXX-XXXX."""
        self.assertEqual(self.sender._clean_number("(19)99451-9934"), "19994519934")

    def test_numero_com_espacos(self):
        """Formato com espaços: 19 99451 9934."""
        self.assertEqual(self.sender._clean_number("19 99451 9934"), "19994519934")

    def test_numero_com_ponto(self):
        """Formato com pontos: 19.99451.9934."""
        self.assertEqual(self.sender._clean_number("19.99451.9934"), "19994519934")

    def test_numero_formato_internacional_com_mais(self):
        """Formato +55 (19) 99451-9934 — remove +55."""
        self.assertEqual(self.sender._clean_number("+55 (19) 99451-9934"), "19994519934")

    def test_numero_com_codigo_pais_sem_mais(self):
        """Formato 55 19 99451-9934 — remove 55."""
        self.assertEqual(self.sender._clean_number("55 19 99451-9934"), "19994519934")

    def test_numero_codigo_pais_colado(self):
        """Formato 5519994519934 — remove 55."""
        self.assertEqual(self.sender._clean_number("5519994519934"), "19994519934")

    def test_numero_formato_americano_com_codigo_pais(self):
        """Formato (551999) 451-9934 — caso reportado pelo usuário."""
        self.assertEqual(self.sender._clean_number("(551999) 451-9934"), "19994519934")

    # --- Float do pandas ---

    def test_numero_float_com_ponto_zero(self):
        """Pandas lê número como float: 19994519934.0."""
        self.assertEqual(self.sender._clean_number("19994519934.0"), "19994519934")
        self.assertEqual(self.sender._clean_number(19994519934.0), "19994519934")

    def test_numero_float_inteiro(self):
        """Pandas lê como int direto."""
        self.assertEqual(self.sender._clean_number(19994519934), "19994519934")

    def test_numero_float_com_codigo_pais(self):
        """Float com código de país: 5519994519934.0."""
        self.assertEqual(self.sender._clean_number(5519994519934.0), "19994519934")

    # --- DDD 55 (Rio Grande do Sul) ---

    def test_ddd_55_celular(self):
        """DDD 55 (RS) não deve ser removido — tem exatamente 11 dígitos."""
        self.assertEqual(self.sender._clean_number("55987654321"), "55987654321")

    def test_ddd_55_fixo(self):
        """DDD 55 (RS) fixo — 10 dígitos."""
        self.assertEqual(self.sender._clean_number("5534567890"), "5534567890")

    def test_ddd_55_com_codigo_pais(self):
        """55 + DDD 55 + celular = 13 dígitos, remove código de país."""
        self.assertEqual(self.sender._clean_number("555598765432"), "5598765432")

    def test_ddd_55_com_codigo_pais_celular(self):
        """55 + DDD 55 + celular 9 dígitos = 13 dígitos."""
        self.assertEqual(self.sender._clean_number("5555987654321"), "55987654321")

    # --- Valores vazios/inválidos ---

    def test_vazio(self):
        self.assertEqual(self.sender._clean_number(""), "")

    def test_nan_string(self):
        self.assertEqual(self.sender._clean_number("nan"), "")

    def test_none_string(self):
        self.assertEqual(self.sender._clean_number("None"), "")

    def test_none_valor(self):
        self.assertEqual(self.sender._clean_number(None), "")

    def test_espacos_apenas(self):
        self.assertEqual(self.sender._clean_number("   "), "")

    # --- Casos edge ---

    def test_numero_com_zero_a_esquerda(self):
        """Formato 019994519934 (zero + DDD) — float() remove o zero à esquerda."""
        resultado = self.sender._clean_number("019994519934")
        # float("019994519934") = 19994519934, que é inteiro, então vira "19994519934"
        self.assertEqual(resultado, "19994519934")

    def test_numero_curto_invalido(self):
        """Número com poucos dígitos — retorna o que tem (validação é em _validate_contact)."""
        self.assertEqual(self.sender._clean_number("1234"), "1234")

    def test_numero_com_letras_misturadas(self):
        """Texto misturado com números — extrai apenas dígitos."""
        self.assertEqual(self.sender._clean_number("Tel: 19 99451-9934"), "19994519934")


class TestValidateContact(BaseTestCase):
    """Testes para _validate_contact: validação antes do envio."""

    # --- Contatos válidos ---

    def test_celular_valido(self):
        valido, motivo = self.sender._validate_contact("19994519934", "Olá!")
        self.assertTrue(valido)
        self.assertEqual(motivo, "")

    def test_fixo_valido(self):
        valido, motivo = self.sender._validate_contact("1934567890", "Olá!")
        self.assertTrue(valido)
        self.assertEqual(motivo, "")

    def test_numero_formatado_valido(self):
        valido, motivo = self.sender._validate_contact("(19)99451-9934", "Olá!")
        self.assertTrue(valido)

    def test_numero_com_codigo_pais_valido(self):
        valido, motivo = self.sender._validate_contact("5519994519934", "Olá!")
        self.assertTrue(valido)

    def test_numero_float_valido(self):
        valido, motivo = self.sender._validate_contact("19994519934.0", "Olá!")
        self.assertTrue(valido)

    # --- Número ausente ---

    def test_numero_vazio(self):
        valido, motivo = self.sender._validate_contact("", "Olá!")
        self.assertFalse(valido)
        self.assertEqual(motivo, "número ausente")

    def test_numero_nan(self):
        valido, motivo = self.sender._validate_contact("nan", "Olá!")
        self.assertFalse(valido)
        self.assertEqual(motivo, "número ausente")

    def test_numero_none_string(self):
        valido, motivo = self.sender._validate_contact("None", "Olá!")
        self.assertFalse(valido)
        self.assertEqual(motivo, "número ausente")

    # --- Número inválido (poucos dígitos) ---

    def test_numero_curto_4_digitos(self):
        valido, motivo = self.sender._validate_contact("1234", "Olá!")
        self.assertFalse(valido)
        self.assertEqual(motivo, "número inválido")

    def test_numero_curto_9_digitos(self):
        valido, motivo = self.sender._validate_contact("999451993", "Olá!")
        self.assertFalse(valido)
        self.assertEqual(motivo, "número inválido")

    def test_numero_apenas_ddd(self):
        valido, motivo = self.sender._validate_contact("19", "Olá!")
        self.assertFalse(valido)
        self.assertEqual(motivo, "número inválido")

    # --- Mensagem vazia ---

    def test_mensagem_vazia(self):
        valido, motivo = self.sender._validate_contact("19994519934", "")
        self.assertFalse(valido)
        self.assertEqual(motivo, "mensagem vazia")

    def test_mensagem_nan(self):
        valido, motivo = self.sender._validate_contact("19994519934", "nan")
        self.assertFalse(valido)
        self.assertEqual(motivo, "mensagem vazia")

    def test_mensagem_none(self):
        valido, motivo = self.sender._validate_contact("19994519934", "None")
        self.assertFalse(valido)
        self.assertEqual(motivo, "mensagem vazia")


class TestNumeroFinalParaEnvio(BaseTestCase):
    """
    Testa o fluxo completo: _clean_number + adição do 55.
    Simula o que acontece em _send_message.
    """

    def _simulate_send_number(self, raw_input) -> str:
        """Simula a lógica de _send_message para obter o número final."""
        numero_limpo = self.sender._clean_number(raw_input)
        if not numero_limpo.startswith("55"):
            numero_limpo = "55" + numero_limpo
        return numero_limpo

    def test_numero_sem_codigo_pais(self):
        """Usuário coloca só DDD+tel → sistema adiciona 55."""
        self.assertEqual(self._simulate_send_number("19994519934"), "5519994519934")

    def test_numero_com_codigo_pais(self):
        """Usuário já coloca 55 → sistema não duplica."""
        self.assertEqual(self._simulate_send_number("5519994519934"), "5519994519934")

    def test_numero_formatado_com_codigo_pais(self):
        """Formato (551999) 451-9934 → resultado correto."""
        self.assertEqual(self._simulate_send_number("(551999) 451-9934"), "5519994519934")

    def test_numero_internacional_com_mais(self):
        """+55 (19) 99451-9934 → resultado correto."""
        self.assertEqual(self._simulate_send_number("+55 (19) 99451-9934"), "5519994519934")

    def test_float_do_pandas(self):
        """19994519934.0 → não adiciona zero extra."""
        self.assertEqual(self._simulate_send_number(19994519934.0), "5519994519934")

    def test_float_com_codigo_pais(self):
        """5519994519934.0 → não duplica 55."""
        self.assertEqual(self._simulate_send_number(5519994519934.0), "5519994519934")

    def test_ddd_55_rs(self):
        """DDD 55 (RS) sem código de país — o número já começa com 55,
        então _send_message NÃO adiciona 55 novamente.
        O resultado é o próprio número (que já está correto: 55 é o DDD)."""
        # NOTA: para DDD 55, o usuário deve incluir o código do país (5555...)
        # senão o sistema não adiciona e o WhatsApp interpreta 55 como código do país.
        self.assertEqual(self._simulate_send_number("55987654321"), "55987654321")

    def test_ddd_55_rs_com_codigo_pais(self):
        """55 (país) + 55 (DDD) + celular 9 dígitos = 13 dígitos.
        _clean_number remove primeiro 55 → fica 55987654321 (11 dígitos).
        _send_message vê que começa com 55 → não adiciona.
        LIMITAÇÃO: resultado é 55987654321 (falta o código do país).
        Para DDD 55, o usuário deve digitar apenas DDD+tel (55987654321)
        sem incluir o código do país, para que o sistema adicione corretamente."""
        # Comportamento atual: resultado incorreto para este caso edge
        # O sistema interpreta o DDD 55 como código do país
        self.assertEqual(self._simulate_send_number("5555987654321"), "55987654321")


class TestSessaoMorta(BaseTestCase):
    """
    Testa a detecção de sessão morta do Chrome.

    Cenário do bug reportado: o cliente fechou a janela do Chrome porque o bot
    parecia travado. O código antigo não detectava isso e seguia "tentando"
    contato após contato, todos falhando instantaneamente.
    """

    def test_invalid_session_id_por_mensagem(self):
        exc = Exception(
            "Message: invalid session id: session deleted as the browser "
            "has closed the connection"
        )
        self.assertTrue(self.sender._is_session_dead(exc))

    def test_no_such_window_por_mensagem(self):
        exc = Exception("Message: no such window: target window already closed")
        self.assertTrue(self.sender._is_session_dead(exc))

    def test_devtools_desconectado(self):
        exc = Exception("from disconnected: not connected to DevTools")
        self.assertTrue(self.sender._is_session_dead(exc))

    def test_web_view_not_found(self):
        exc = Exception("from unknown error: web view not found")
        self.assertTrue(self.sender._is_session_dead(exc))

    def test_chrome_not_reachable(self):
        exc = Exception("chrome not reachable")
        self.assertTrue(self.sender._is_session_dead(exc))

    def test_excecao_tipada_invalid_session(self):
        from selenium.common.exceptions import InvalidSessionIdException
        self.assertTrue(self.sender._is_session_dead(InvalidSessionIdException("x")))

    def test_excecao_tipada_no_such_window(self):
        from selenium.common.exceptions import NoSuchWindowException
        self.assertTrue(self.sender._is_session_dead(NoSuchWindowException("x")))

    def test_erro_comum_nao_e_sessao_morta(self):
        """Erro de elemento não encontrado não deve abortar o envio inteiro."""
        exc = Exception("Message: no such element: Unable to locate element")
        self.assertFalse(self.sender._is_session_dead(exc))

    def test_timeout_nao_e_sessao_morta(self):
        from selenium.common.exceptions import TimeoutException
        self.assertFalse(self.sender._is_session_dead(TimeoutException("timeout")))


class FakeElement:
    """Elemento falso que registra cada chamada de send_keys."""

    def __init__(self):
        self.calls = []

    def send_keys(self, value):
        self.calls.append(value)

    @property
    def text(self):
        return "".join(self.calls)


class TestHumanType(BaseTestCase):
    """
    Testa a digitação humanizada.

    Regra: mensagens normais são digitadas caractere por caractere (fidelidade
    máxima, que é o objetivo do modo humanizado). Só textos longos são digitados
    por palavra — a versão que fazia char-a-char sempre travava em produção,
    porque cada send_keys é um round-trip ao ChromeDriver.
    """

    def setUp(self):
        super().setUp()
        # Orçamento generoso e sem sleeps reais para o teste ser rápido
        self.sender.config = {"human_type_max_seconds": 999}
        self._patch_sleep()

    def _patch_sleep(self):
        """Neutraliza time.sleep dentro do módulo durante os testes."""
        import whatsapp_sender
        self._orig_sleep = whatsapp_sender.time.sleep
        whatsapp_sender.time.sleep = lambda s: None
        self.addCleanup(self._restore_sleep)

    def _restore_sleep(self):
        import whatsapp_sender
        whatsapp_sender.time.sleep = self._orig_sleep

    # --- Texto idêntico ao original (nos dois modos) ---

    def test_texto_curto_digitado_integralmente(self):
        texto = "Olá João, tudo bem? Temos uma novidade para você."
        el = FakeElement()
        self.sender._human_type(el, texto)
        self.assertEqual("".join(el.calls), texto)

    def test_texto_longo_digitado_integralmente(self):
        texto = " ".join(["palavra"] * 200)  # ~1600 chars
        el = FakeElement()
        self.sender._human_type(el, texto)
        self.assertEqual("".join(el.calls), texto)

    def test_quebras_de_linha_preservadas(self):
        texto = "Primeira linha\nSegunda linha\nTerceira"
        el = FakeElement()
        self.sender._driver = FakeDriverSessao()
        self.sender._human_type(el, texto)
        # As quebras vão por Shift+Enter (ActionChains), não por send_keys
        self.assertEqual("".join(el.calls), texto.replace("\n", ""))

    # --- Modo caractere (mensagem normal) ---

    def test_mensagem_normal_vai_caractere_por_caractere(self):
        """
        O ponto do modo humanizado: mensagem de tamanho normal deve manter
        a digitação caractere por caractere.
        """
        texto = "Olá João, tudo bem? Temos uma novidade muito boa para você hoje."
        self.assertLessEqual(len(texto), 200)
        el = FakeElement()
        self.sender._human_type(el, texto)
        self.assertEqual(len(el.calls), len(texto))
        self.assertTrue(all(len(c) == 1 for c in el.calls))

    def test_limite_exato_ainda_e_caractere(self):
        texto = "a" * 200
        el = FakeElement()
        self.sender._human_type(el, texto)
        self.assertEqual(len(el.calls), 200)

    # --- Modo palavra (texto longo) ---

    def test_texto_longo_vai_por_palavra(self):
        """
        Regressão do bug: texto longo não pode gerar uma chamada por caractere.
        """
        texto = " ".join(["palavra"] * 100)  # 799 chars, 100 palavras
        self.assertGreater(len(texto), 200)
        el = FakeElement()
        self.sender._human_type(el, texto)
        self.assertEqual(len(el.calls), 100)
        self.assertLess(len(el.calls), len(texto) / 5)

    def test_limite_configuravel(self):
        """O limite de troca de modo pode ser ajustado pela config."""
        self.sender.config = {
            "human_type_max_seconds": 999,
            "human_type_char_limit": 10,
        }
        texto = "uma frase com varias palavras"
        el = FakeElement()
        self.sender._human_type(el, texto)
        # Acima do limite de 10 → modo palavra (5 palavras)
        self.assertEqual(len(el.calls), 5)

    # --- Rede de segurança do orçamento ---

    def test_orcamento_estourado_envia_resto_de_uma_vez(self):
        """Com orçamento zero, tudo vai em uma única chamada."""
        self.sender.config = {"human_type_max_seconds": 0}
        texto = "uma mensagem com varias palavras aqui"
        el = FakeElement()
        self.sender._human_type(el, texto)
        self.assertEqual("".join(el.calls), texto)
        self.assertEqual(len(el.calls), 1)

    def test_orcamento_vale_para_texto_curto(self):
        """
        A rede de segurança precisa valer também no modo caractere: um
        navegador degradado pode travar mesmo em mensagem curta.
        """
        self.sender.config = {"human_type_max_seconds": 0}
        texto = "Oi, tudo bem?"
        el = FakeElement()
        self.sender._human_type(el, texto)
        self.assertEqual("".join(el.calls), texto)
        self.assertEqual(len(el.calls), 1)

    # --- Casos edge ---

    def test_palavra_unica(self):
        el = FakeElement()
        self.sender._human_type(el, "Oi")
        self.assertEqual("".join(el.calls), "Oi")

    def test_texto_vazio_nao_chama_send_keys(self):
        el = FakeElement()
        self.sender._human_type(el, "")
        self.assertEqual(el.calls, [])

    def test_espacos_duplicados_preservados(self):
        texto = "palavra  com   espacos " + "x" * 200
        el = FakeElement()
        self.sender._human_type(el, texto)
        self.assertEqual("".join(el.calls), texto)


class FakeField:
    """Campo de texto falso com conteúdo controlável."""

    def __init__(self, text=""):
        self._text = text

    @property
    def text(self):
        return self._text


class FakeDriver:
    """Driver falso que devolve um campo fixo ou levanta exceção."""

    def __init__(self, field=None, raise_exc=None):
        self._field = field
        self._raise = raise_exc

    def find_element(self, by, selector):
        if self._raise:
            raise self._raise
        return self._field


class TestConfirmacaoEnvio(BaseTestCase):
    """
    Testa a confirmação de que a mensagem saiu do campo.

    Bug original: o código fazia send_keys(ENTER) e assumia sucesso, marcando
    como enviada uma mensagem que ficou presa no campo de texto.
    """

    def setUp(self):
        super().setUp()
        import whatsapp_sender
        self._orig_sleep = whatsapp_sender.time.sleep
        whatsapp_sender.time.sleep = lambda s: None
        self.addCleanup(self._restore)

    def _restore(self):
        import whatsapp_sender
        whatsapp_sender.time.sleep = self._orig_sleep

    def test_campo_vazio_confirma_envio(self):
        self.sender._driver = FakeDriver(FakeField(""))
        self.assertTrue(self.sender._confirm_message_sent("Olá João, tudo bem?"))

    def test_placeholder_nao_gera_falso_negativo(self):
        """
        Campo com o placeholder do WhatsApp deve contar como enviado —
        o que importa é o texto da mensagem não estar mais lá.
        """
        self.sender._driver = FakeDriver(FakeField("Digite uma mensagem"))
        self.assertTrue(self.sender._confirm_message_sent("Olá João, tudo bem?"))

    def test_texto_ainda_no_campo_nao_confirma(self):
        texto = "Olá João, tudo bem? Temos uma novidade."
        self.sender._driver = FakeDriver(FakeField(texto))
        self.assertFalse(self.sender._confirm_message_sent(texto, timeout=1.0))

    def test_texto_vazio_confirma_direto(self):
        self.sender._driver = FakeDriver(FakeField("qualquer coisa"))
        self.assertTrue(self.sender._confirm_message_sent(""))

    def test_sessao_morta_durante_confirmacao(self):
        from whatsapp_sender import BrowserClosedError
        from selenium.common.exceptions import NoSuchWindowException
        self.sender._driver = FakeDriver(raise_exc=NoSuchWindowException("no such window"))
        with self.assertRaises(BrowserClosedError):
            self.sender._confirm_message_sent("Olá João")

    def test_erro_generico_nao_bloqueia(self):
        """Erro que não é sessão morta não deve marcar a mensagem como falha."""
        self.sender._driver = FakeDriver(raise_exc=Exception("no such element"))
        self.assertTrue(self.sender._confirm_message_sent("Olá João"))


class FakeDriverSessao:
    """Driver falso suficiente para o start() rodar sem Chrome real."""

    def __init__(self):
        self.urls = []
        self.acoes = []

    def get(self, url):
        self.urls.append(url)

    def find_element(self, by, selector):
        return FakeField("")

    def execute(self, command, params=None):
        """Usado pelo ActionChains (Shift+Enter das quebras de linha)."""
        self.acoes.append(command)
        return {"value": None}

    def quit(self):
        pass


class TestCotaDaRodada(unittest.TestCase):
    """
    Garante que a cota de mensagens por rodada conte apenas ENVIOS EFETIVOS.

    Bug: o batch era uma fatia fixa (pending.head(batch_size)), então um número
    inexistente consumia uma vaga da rodada e o cliente recebia menos mensagens
    do que configurou. Ex.: 10 msgs/rodada com 3 números ruins = só 7 enviadas.
    """

    def setUp(self):
        logging.getLogger("whatsapp_sender_file").setLevel(logging.CRITICAL)
        import whatsapp_sender
        self._ws = whatsapp_sender
        self._orig_sleep = whatsapp_sender.time.sleep
        whatsapp_sender.time.sleep = lambda s: None
        self.addCleanup(self._restore)

    def _restore(self):
        self._ws.time.sleep = self._orig_sleep

    def _rodar(self, resultados, msgs_por_rodada, total_rodadas=1):
        """
        resultados: lista de 'ok' | 'timeout' | 'falha', um por contato.
        Retorna (numeros_tentados, df_final).
        """
        import pandas as pd
        from selenium.common.exceptions import TimeoutException

        contatos = []
        for i, _ in enumerate(resultados):
            contatos.append({
                "Nome": f"Contato{i}",
                "Número": f"1199999{i:04d}",
                "Mensagem": "Olá, mensagem de teste.",
                "Arquivo": "",
                "Prefixo": "",
                "Enviado": "",
                "DataEnvio": "",
                "Invalido": "",
            })

        estado = {"df": pd.DataFrame(contatos)}
        por_numero = {
            c["Número"]: r for c, r in zip(contatos, resultados)
        }
        tentados = []

        sender = self._ws.WhatsAppSender(
            excel_path="fake.xlsx",
            config={
                "msgs_por_rodada": msgs_por_rodada,
                "total_rodadas": total_rodadas,
                "intervalo_rodadas_min": 0,
                "human_behavior": False,  # sem variação, resultado determinístico
                "delay_min": 0,
                "delay_max": 0,
            },
            log_callback=lambda m: None,
        )

        def fake_send(pessoa, numero, mensagem, arquivo="", prefixo=""):
            tentados.append(numero)
            resultado = por_numero[numero]
            if resultado == "timeout":
                raise TimeoutException("numero nao existe")
            return resultado == "ok"

        sender._init_driver = lambda: FakeDriverSessao()
        sender._load_contacts = lambda: estado["df"].copy()
        sender._save_contacts = lambda df: estado.update({"df": df})
        sender._send_message = fake_send
        sender._wait_for_business_hours = lambda: None

        sender.start()
        return tentados, estado["df"]

    def test_numero_inexistente_nao_consome_cota(self):
        """
        3 msgs/rodada com o 2º número inexistente: deve tentar 4 contatos
        para conseguir 3 envios efetivos.
        """
        tentados, df = self._rodar(
            ["ok", "timeout", "ok", "ok", "ok"], msgs_por_rodada=3
        )
        self.assertEqual(len(tentados), 4)
        self.assertEqual((df["Enviado"] == "X").sum(), 3)
        self.assertEqual((df["Invalido"] == "X").sum(), 1)

    def test_varios_invalidos_seguidos(self):
        """3 números ruins no meio não reduzem o total enviado."""
        tentados, df = self._rodar(
            ["timeout", "timeout", "ok", "timeout", "ok", "ok", "ok"],
            msgs_por_rodada=3,
        )
        self.assertEqual((df["Enviado"] == "X").sum(), 3)
        self.assertEqual((df["Invalido"] == "X").sum(), 3)

    def test_falha_de_envio_nao_consome_cota(self):
        """Falha de envio (não é número inválido) também não gasta vaga."""
        tentados, df = self._rodar(
            ["ok", "falha", "ok", "ok"], msgs_por_rodada=3
        )
        self.assertEqual((df["Enviado"] == "X").sum(), 3)
        # A falha continua pendente para a próxima rodada
        self.assertEqual((df["Enviado"] != "X").sum(), 1)
        self.assertEqual((df["Invalido"] == "X").sum(), 0)

    def test_sem_invalidos_envia_exatamente_a_cota(self):
        """Sem problemas, a rodada envia exatamente msgs_por_rodada."""
        tentados, df = self._rodar(["ok"] * 10, msgs_por_rodada=4)
        self.assertEqual(len(tentados), 4)
        self.assertEqual((df["Enviado"] == "X").sum(), 4)

    def test_pendentes_insuficientes_nao_travam(self):
        """Se há menos pendentes que a cota, a rodada termina normalmente."""
        tentados, df = self._rodar(["ok", "ok"], msgs_por_rodada=5)
        self.assertEqual(len(tentados), 2)
        self.assertEqual((df["Enviado"] == "X").sum(), 2)

    def test_teto_de_tentativas_encerra_rodada(self):
        """
        Planilha só com números ruins não deve gerar rodada interminável:
        o teto é max(batch*3, batch+10).
        """
        tentados, df = self._rodar(["timeout"] * 60, msgs_por_rodada=2)
        # teto = max(2*3, 2+10) = 12
        self.assertLessEqual(len(tentados), 12)
        self.assertEqual((df["Enviado"] == "X").sum(), 0)

    def test_duas_rodadas_total_correto(self):
        """2 rodadas de 2 mensagens = 4 no total."""
        tentados, df = self._rodar(["ok"] * 10, msgs_por_rodada=2, total_rodadas=2)
        self.assertEqual((df["Enviado"] == "X").sum(), 4)

    def test_duas_rodadas_com_invalidos_mantem_total(self):
        """
        Números ruins não devem reduzir o total final: 2 rodadas de 2
        continuam entregando 4 mensagens.
        """
        tentados, df = self._rodar(
            ["ok", "timeout", "ok", "timeout", "ok", "ok", "ok"],
            msgs_por_rodada=2,
            total_rodadas=2,
        )
        self.assertEqual((df["Enviado"] == "X").sum(), 4)
        self.assertEqual((df["Invalido"] == "X").sum(), 2)


if __name__ == "__main__":
    unittest.main()
