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

    def find_elements(self, by, selector):
        # Idem FakeDriverEnvio: sem o campo do rodapé, a espera pela conversa
        # aberta rodava até o timeout para cada contato.
        if "contenteditable" in selector:
            return [FakeField("")]
        return []

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
        # As esperas do sender NÃO passam por time.sleep: ele usa
        # _interruptible_sleep -> threading.Event.wait(). Sem neutralizar isso
        # aqui, a suíte esperava as pausas entre rajadas de verdade (minutos ou
        # horas) e travava indefinidamente no meio da execução.
        self._orig_isleep = whatsapp_sender.WhatsAppSender._interruptible_sleep
        whatsapp_sender.WhatsAppSender._interruptible_sleep = lambda self, s: False
        self.addCleanup(self._restore)

    def _restore(self):
        self._ws.time.sleep = self._orig_sleep
        self._ws.WhatsAppSender._interruptible_sleep = self._orig_isleep

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
                # A configuração por rodadas (msgs_por_rodada/total_rodadas) foi
                # substituída por "quantas mensagens em quanto tempo". A cota
                # equivalente é o total de mensagens do envio.
                "total_msgs": msgs_por_rodada * total_rodadas,
                "tempo_minutos": 1,
                "human_behavior": False,  # sem variação, resultado determinístico
            },
            log_callback=lambda m: None,
        )

        def fake_send(pessoa, numero, mensagem, arquivo=""):
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
        """
        Falha de envio não gasta vaga da cota — e não fica pendente: o contato
        é marcado como inválido na hora, com o motivo para o usuário investigar.
        """
        tentados, df = self._rodar(
            ["ok", "falha", "ok", "ok"], msgs_por_rodada=3
        )
        self.assertEqual((df["Enviado"] == "X").sum(), 3)
        # Sem retentativa: a falha virou inválido, não voltou para a fila
        self.assertEqual((df["Invalido"] == "X").sum(), 1)
        self.assertTrue(str(df.at[1, "Motivo"]).strip(),
                        "contato que falhou precisa ter motivo preenchido")

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

    def test_planilha_toda_ruim_termina_sem_travar(self):
        """
        Planilha só com números ruins não pode gerar envio interminável.
        Sem retentativas, cada contato é tentado UMA vez, marcado como inválido,
        e o envio termina quando a planilha acaba.
        """
        tentados, df = self._rodar(["timeout"] * 60, msgs_por_rodada=2)
        self.assertEqual((df["Enviado"] == "X").sum(), 0)
        self.assertEqual((df["Invalido"] == "X").sum(), 60)
        # Nenhum contato foi tentado duas vezes
        self.assertEqual(len(tentados), len(set(tentados)))
        self.assertEqual(len(tentados), 60)

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


    def test_contato_que_falha_e_invalidado_na_primeira_vez(self):
        """
        Não existe retentativa: quem falha é marcado como inválido na primeira
        falha, com motivo preenchido, e não é tentado de novo no mesmo envio.
        """
        tentados, df = self._rodar(
            ["falha", "ok", "ok", "ok", "ok"],
            msgs_por_rodada=1,
            total_rodadas=6,
        )
        falho = "11999990000"
        self.assertEqual(tentados.count(falho), 1, "contato falho não pode ser retentado")
        self.assertEqual(df.at[0, "Invalido"], "X")
        self.assertTrue(str(df.at[0, "Motivo"]).strip(),
                        "o motivo é o que o usuário vai investigar no tooltip")

    def test_timeout_marca_invalido_com_motivo_explicativo(self):
        """
        Timeout ao abrir a conversa marca inválido na hora e o motivo precisa
        explicar as causas possíveis, já que o usuário vai investigar por ele.
        """
        tentados, df = self._rodar(["timeout", "ok"], msgs_por_rodada=1)
        self.assertEqual(tentados.count("11999990000"), 1)
        self.assertEqual(df.at[0, "Invalido"], "X")
        motivo = str(df.at[0, "Motivo"]).lower()
        self.assertIn("timeout", motivo)
        # Precisa citar as duas causas plausíveis, senão o usuário não sabe
        # se o problema é o número ou a conexão dele
        self.assertIn("whatsapp", motivo)
        self.assertIn("lent", motivo)

    def test_pendentes_nao_dependem_mais_de_tentativas(self):
        """
        A coluna Tentativas não filtra mais nada: sem retentativas, o que define
        pendente é só não estar enviado nem inválido. Planilhas antigas com
        Tentativas alto voltam a ser elegíveis.
        """
        import pandas as pd

        sender = self._ws.WhatsAppSender(
            excel_path="fake.xlsx", config={}, log_callback=lambda m: None
        )
        df = pd.DataFrame([
            {"Enviado": "", "Invalido": "", "Tentativas": 0},
            {"Enviado": "", "Invalido": "", "Tentativas": 3},
            {"Enviado": "", "Invalido": "X", "Tentativas": 0},
            {"Enviado": "X", "Invalido": "", "Tentativas": 0},
        ])
        pendentes = sender._get_pending_contacts(df)
        self.assertEqual(list(pendentes.index), [0, 1])


class FakeFileInput:
    """input[type=file] falso, identificado pelo atributo accept."""

    def __init__(self, accept):
        self.accept = accept
        self.enviados = []

    def get_attribute(self, name):
        return self.accept if name == "accept" else None

    def send_keys(self, value):
        self.enviados.append(value)


class TestEscolhaDoInputDeArquivo(BaseTestCase):
    """
    O formato do envio (foto grande, figurinha ou documento) é decidido pelo
    input[type=file] escolhido, não pelo item do menu de anexo.

    Bug: o código pegava o primeiro input com accept contendo "image/", que no
    WhatsApp Web é o input de FIGURINHA — a foto chegava como sticker.
    """

    def _driver_com(self, accepts):
        inputs = [FakeFileInput(a) for a in accepts]

        class FakeDriver:
            def find_elements(self, by, selector):
                return inputs

        self.sender._driver = FakeDriver()
        self.sender._reveal_file_input = lambda el: None
        return inputs

    def test_classifica_input_de_midia(self):
        self.assertEqual(
            self.sender._classify_file_input("image/*,video/mp4,video/3gpp,video/quicktime"),
            "midia",
        )

    def test_classifica_input_de_figurinha(self):
        self.assertEqual(
            self.sender._classify_file_input("image/webp,image/png,image/jpeg"),
            "figurinha",
        )

    def test_classifica_input_de_documento(self):
        self.assertEqual(self.sender._classify_file_input("*"), "documento")
        self.assertEqual(self.sender._classify_file_input("*/*"), "documento")
        self.assertEqual(self.sender._classify_file_input(""), "documento")

    def test_classifica_input_de_imagem_generica(self):
        self.assertEqual(self.sender._classify_file_input("image/*"), "imagem")

    def test_imagem_escolhe_input_de_midia_e_nao_figurinha(self):
        self._driver_com([
            "image/webp,image/png,image/jpeg",          # figurinha (vinha primeiro)
            "image/*,video/mp4,video/3gpp",             # mídia
            "*",                                        # documento
        ])
        classe, accept, _ = self.sender._pick_file_input(True, set())
        self.assertEqual(classe, "midia")
        self.assertIn("video", accept)

    def test_imagem_nunca_usa_input_de_figurinha(self):
        """Mesmo sem input de mídia, o de figurinha continua fora de cogitação."""
        self._driver_com(["image/webp,image/png,image/jpeg"])
        self.assertIsNone(self.sender._pick_file_input(True, set()))

    def test_documento_escolhe_input_de_documento(self):
        self._driver_com([
            "image/*,video/mp4",
            "*",
        ])
        classe, accept, _ = self.sender._pick_file_input(False, set())
        self.assertEqual(classe, "documento")
        self.assertEqual(accept, "*")

    def test_input_ja_tentado_e_ignorado(self):
        self._driver_com([
            "image/*,video/mp4",
            "image/*",
        ])
        classe, _, _ = self.sender._pick_file_input(True, {"image/*,video/mp4"})
        self.assertEqual(classe, "imagem")

    def test_send_media_prefere_a_janela_nativa(self):
        """
        Com o caminho oficial (menu + janela nativa) funcionando, nenhum
        input[type=file] é tocado — é ele que entrega a foto em tamanho grande.
        """
        inputs = self._driver_com(["image/*"])
        chamadas = []
        self.sender._send_media_via_dialog = (
            lambda path, img, pessoa: (chamadas.append((img, pessoa)), "")[1]
        )
        self.sender._detect_attach_preview = lambda img, timeout=25.0: "midia"
        self.sender._click_send_button_modal = lambda pessoa: "btn"
        self.sender._wait_attachment_sent = lambda btn, timeout=30.0: True

        self.sender._send_media("foto.png", "Mauricio")

        self.assertEqual(chamadas, [(True, "Mauricio")])
        self.assertEqual(inputs[0].enviados, [])

    def test_send_media_cai_para_o_input_se_a_janela_falhar(self):
        inputs = self._driver_com([
            "image/webp,image/png,image/jpeg",
            "image/*,video/mp4,video/3gpp",
            "*",
        ])
        self.sender._send_media_via_dialog = (
            lambda path, img, pessoa: "a janela de arquivos do Windows não abriu"
        )
        self.sender._detect_attach_preview = lambda img, timeout=20.0: "midia"
        self.sender._click_send_button_modal = lambda pessoa: "btn"
        self.sender._wait_attachment_sent = lambda btn, timeout=30.0: True
        self.sender._close_modal = lambda: None

        self.sender._send_media("foto.png", "Mauricio")

        self.assertEqual(inputs[0].enviados, [])           # figurinha: intocado
        self.assertEqual(len(inputs[1].enviados), 1)       # mídia: recebeu o arquivo
        self.assertTrue(inputs[1].enviados[0].endswith("foto.png"))

    def test_send_media_descarta_editor_de_figurinha_e_tenta_outro_input(self):
        """
        Se o preview aberto for o editor de figurinha, o arquivo é descartado
        e o próximo candidato é usado.
        """
        inputs = self._driver_com([
            "image/*,video/mp4",   # abrirá "figurinha" no teste
            "image/*",             # fallback
        ])
        self.sender._send_media_via_dialog = lambda path, img, pessoa: "sem janela"
        resultados = iter(["figurinha", "midia"])
        self.sender._detect_attach_preview = lambda img, timeout=20.0: next(resultados)
        self.sender._close_modal = lambda: None
        self.sender._click_send_button_modal = lambda pessoa: "btn"
        self.sender._wait_attachment_sent = lambda btn, timeout=30.0: True

        self.sender._send_media("foto.jpg", "Mauricio")

        self.assertEqual(len(inputs[0].enviados), 1)
        self.assertEqual(len(inputs[1].enviados), 1)

    def test_send_media_nunca_envia_figurinha(self):
        """
        Se todos os caminhos abrirem o editor de figurinha, o envio falha —
        melhor falhar do que entregar a imagem como sticker.
        """
        self._driver_com(["image/*"])
        self.sender._send_media_via_dialog = lambda path, img, pessoa: ""
        self.sender._detect_attach_preview = lambda img, timeout=20.0: "figurinha"
        self.sender._close_modal = lambda: None
        enviados = []
        self.sender._click_send_button_modal = lambda pessoa: enviados.append(pessoa)

        with self.assertRaises(RuntimeError):
            self.sender._send_media("foto.png", "Mauricio")
        self.assertEqual(enviados, [])

    def test_send_media_falha_quando_nao_abre_preview(self):
        self._driver_com(["image/*,video/mp4"])
        self.sender._send_media_via_dialog = lambda path, img, pessoa: ""
        self.sender._detect_attach_preview = lambda img, timeout=20.0: ""
        self.sender._close_modal = lambda: None

        with self.assertRaises(RuntimeError):
            self.sender._send_media("foto.png", "Mauricio")

    def test_extensoes_de_imagem_e_video(self):
        for nome in ("a.png", "a.JPG", "a.jpeg", "a.gif", "a.webp", "a.mp4", "a.mov"):
            self.assertTrue(self.sender._is_image_or_video(nome), nome)
        for nome in ("a.pdf", "a.docx", "a.mp3", "a.zip"):
            self.assertFalse(self.sender._is_image_or_video(nome), nome)


class TestDeteccaoDoEditorDeFigurinha(BaseTestCase):
    """
    O preview de foto tem uma ferramenta de figurinha/emoji, então a palavra
    "figurinha" sozinha não pode condenar o modal — senão o envio correto seria
    descartado em loop.
    """

    def _preparar(self, com_legenda: bool):
        self.sender._has_caption_field = lambda: com_legenda

    def test_texto_inequivoco_e_figurinha(self):
        self._preparar(com_legenda=True)
        self.assertTrue(self.sender._looks_like_sticker_editor("criar figurinha  recortar"))

    def test_figurinha_sem_campo_de_legenda_e_figurinha(self):
        self._preparar(com_legenda=False)
        self.assertTrue(self.sender._looks_like_sticker_editor("figurinha"))

    def test_ferramenta_de_figurinha_no_preview_de_foto_nao_conta(self):
        self._preparar(com_legenda=True)
        self.assertFalse(
            self.sender._looks_like_sticker_editor("figurinha adicionar uma legenda")
        )

    def test_preview_normal_nao_e_figurinha(self):
        self._preparar(com_legenda=True)
        self.assertFalse(self.sender._looks_like_sticker_editor("adicionar uma legenda"))

    def test_texto_vazio_nao_e_figurinha(self):
        self._preparar(com_legenda=False)
        self.assertFalse(self.sender._looks_like_sticker_editor(""))


class TestDeteccaoDoPreview(BaseTestCase):
    """
    _detect_attach_preview decide se o modal aberto é o preview de foto (pode
    enviar) ou o editor de figurinha (precisa descartar). O sinal decisivo é o
    campo de legenda: o diagnóstico no WhatsApp Web real mostrou o editor de
    figurinha com botão enviar visível e NENHUM campo de legenda.
    """

    def _preparar(self, texto="", legenda=False, botao=False):
        self.sender._STICKER_GRACE_SECONDS = 0.1
        self.sender._modal_text = lambda: texto
        self.sender._has_caption_field = lambda: legenda
        self.sender._find_send_button_modal = lambda timeout=0.3: "btn" if botao else None

    def test_campo_de_legenda_significa_preview_de_foto(self):
        self._preparar(legenda=True, botao=True)
        self.assertEqual(self.sender._detect_attach_preview(True, timeout=2), "midia")

    def test_imagem_sem_legenda_e_editor_de_figurinha(self):
        self._preparar(legenda=False, botao=True)
        self.assertEqual(self.sender._detect_attach_preview(True, timeout=3), "figurinha")

    def test_documento_sem_legenda_e_preview_valido(self):
        self._preparar(legenda=False, botao=True)
        self.assertEqual(self.sender._detect_attach_preview(False, timeout=3), "midia")

    def test_nada_aberto_retorna_vazio(self):
        self._preparar(legenda=False, botao=False)
        self.assertEqual(self.sender._detect_attach_preview(True, timeout=1), "")

    def test_texto_de_criar_figurinha_e_detectado_na_hora(self):
        self._preparar(texto="criar figurinha", legenda=True, botao=True)
        self.assertEqual(self.sender._detect_attach_preview(True, timeout=2), "figurinha")


class TestMenuDeAnexo(BaseTestCase):
    """
    O botão "+" do menu de anexo é um toggle: clicar com o menu já aberto fecha
    o menu e o item "Fotos e vídeos" desaparece. O sender precisa lidar com isso.
    """

    def test_menu_ja_aberto_nao_clica_no_botao(self):
        cliques = []
        self.sender._open_attach_menu = lambda pessoa: cliques.append(pessoa) or True
        self.sender._find_menu_item = lambda img: "item"

        self.assertEqual(self.sender._abrir_menu_e_achar_item(True, "Mauricio"), "item")
        self.assertEqual(cliques, [])

    def test_abre_o_menu_quando_fechado(self):
        cliques = []
        respostas = iter([None, "item"])
        self.sender._open_attach_menu = lambda pessoa: cliques.append(pessoa) or True
        self.sender._find_menu_item = lambda img: next(respostas)

        self.assertEqual(self.sender._abrir_menu_e_achar_item(True, "Mauricio"), "item")
        self.assertEqual(cliques, ["Mauricio"])

    def test_tenta_de_novo_se_o_clique_fechou_o_menu(self):
        cliques = []
        respostas = iter([None, None, "item"])
        self.sender._open_attach_menu = lambda pessoa: cliques.append(pessoa) or True
        self.sender._find_menu_item = lambda img: next(respostas)

        self.assertEqual(self.sender._abrir_menu_e_achar_item(True, "Mauricio"), "item")
        self.assertEqual(len(cliques), 2)

    def test_desiste_quando_o_item_nunca_aparece(self):
        self.sender._open_attach_menu = lambda pessoa: True
        self.sender._find_menu_item = lambda img: None

        self.assertIsNone(self.sender._abrir_menu_e_achar_item(True, "Mauricio"))

    def test_sem_botao_de_anexo_desiste(self):
        self.sender._open_attach_menu = lambda pessoa: False
        self.sender._find_menu_item = lambda img: None

        self.assertIsNone(self.sender._abrir_menu_e_achar_item(False, "Mauricio"))


if __name__ == "__main__":
    unittest.main()
