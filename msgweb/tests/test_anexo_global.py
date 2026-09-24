"""
Testes do ANEXO GLOBAL: parte da mensagem global, não um recurso paralelo.

A regra tem um gatilho só, e é a **coluna Mensagem em branco**. O anexo não tem
gatilho próprio: ele viaja com a mensagem global. Quem escreveu a própria
mensagem não recebe nem o texto nem o anexo globais.

Três consequências que os testes abaixo fixam, porque nenhuma é óbvia lendo o
código de fora:

  1. **Pacote sem texto é válido.** Mensagem global vazia com anexo ligado
     entrega só o arquivo — foi pedido explicitamente. Por isso
     `validate_contact` aceita mensagem vazia quando há anexo: sem isso, uma
     campanha só de imagem virava uma lista inteira de inválidos.
  2. **O arquivo do contato vence o global.** `Arquivo` preenchido é escolha
     explícita daquela linha, e o pacote não a atropela — mesmo quando o texto
     dela vem do global.
  3. **Desligar a mensagem global desliga o anexo**, no backend e não só na
     tela: `_anexo_global_ativo()` exige as duas ativas, porque uma requisição
     fora da tela chegaria igual.

Duas diferenças em relação à mensagem global, e as duas têm teste aqui:

  - **É gravado no servidor**, não no `localStorage`. A mensagem o usuário
    reconhece e reescreve em segundos; o anexo é um caminho de arquivo que ele
    não tem como adivinhar, e perdê-lo calado faz a campanha inteira sair sem
    imagem.
  - **O arquivo é conferido antes**, na restauração e no `/start`. Um caminho
    morto num contato estraga um contato; no pacote global estraga a lista
    toda, e da forma mais cara — `AttachmentError` marca inválido SEM
    retentativa, um por um.

E o ponto que liga isto ao resto do app: a **estimativa de tempo** tem que
enxergar o pacote. Com o anexo ligado, todo contato de campo em branco passa a
ter anexo, que é o componente mais caro do envio depois de abrir a conversa;
uma estimativa que lesse só as colunas prometeria um tempo que o envio não
cumpre — o erro que o CHANGELOG de 06/09/2026 descreve (previu 45min para um
envio de 2h).

Executa com:
    venv\\Scripts\\python.exe -m unittest tests.test_anexo_global -v
"""
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd  # noqa: E402

import whatsapp_sender  # noqa: E402
from contact_logic import validate_contact  # noqa: E402
from whatsapp_sender import WhatsAppSender  # noqa: E402


def sender_nu(global_message="", global_attachment="", human=True):
    """
    Um sender sem navegador, só para exercitar as funções puras.

    `human_behavior` ligado por padrão porque é o modo real do cliente — e
    porque é o único em que o tamanho do texto entra na estimativa: sem ele
    `_estimar_tempo_envio_individual` usa 5s fixos (o texto vai pré-preenchido
    na URL) e uma mensagem de 600 caracteres custa o mesmo que uma vazia.
    """
    s = WhatsAppSender.__new__(WhatsAppSender)
    s.global_message = global_message
    s.global_attachment = global_attachment
    s.config = {"human_behavior": human}
    return s


class TestPacoteGlobal(unittest.TestCase):
    """O gatilho é um só: a coluna Mensagem em branco."""

    def test_campo_em_branco_recebe_texto_e_anexo(self):
        s = sender_nu(global_message="texto global",
                      global_attachment="C:/media/promo.jpg")
        texto, anexo, usou_m, usou_a = s._resolver_globais("", "")
        self.assertEqual((texto, anexo), ("texto global", "C:/media/promo.jpg"))
        self.assertTrue(usou_m)
        self.assertTrue(usou_a)

    def test_quem_escreveu_a_propria_mensagem_nao_recebe_nada_do_pacote(self):
        """
        O anexo não tem gatilho próprio. Esta é a mudança de regra: antes ele
        entrava em qualquer contato de coluna `Arquivo` vazia, inclusive em
        quem tinha escrito a própria mensagem — e aí a pessoa recebia o texto
        dela com uma imagem que ela não pediu.
        """
        s = sender_nu(global_message="texto global",
                      global_attachment="C:/media/promo.jpg")
        texto, anexo, usou_m, usou_a = s._resolver_globais("minha mensagem", "")
        self.assertEqual((texto, anexo), ("minha mensagem", ""))
        self.assertFalse(usou_m)
        self.assertFalse(usou_a)

    def test_arquivo_proprio_vence_o_do_pacote(self):
        """Escolha explícita daquela linha; o pacote não atropela."""
        s = sender_nu(global_message="texto global",
                      global_attachment="C:/media/promo.jpg")
        texto, anexo, usou_m, usou_a = s._resolver_globais("", "C:/media/contrato.pdf")
        self.assertEqual((texto, anexo), ("texto global", "C:/media/contrato.pdf"))
        self.assertTrue(usou_m)
        self.assertFalse(usou_a)

    def test_so_anexo_sem_texto_global(self):
        """Pedido explícito: sem mensagem e com anexo, envia só o anexo."""
        s = sender_nu(global_attachment="C:/media/promo.jpg")
        texto, anexo, usou_m, usou_a = s._resolver_globais("", "")
        self.assertEqual(texto, "")
        self.assertEqual(anexo, "C:/media/promo.jpg")
        self.assertFalse(usou_m)
        self.assertTrue(usou_a)

    def test_so_anexo_e_um_contato_valido(self):
        """
        Sem isto o contato era barrado por "mensagem vazia" antes de chegar ao
        anexo, e a campanha só de imagem virava uma lista de inválidos.
        """
        self.assertEqual(
            validate_contact("19994229146", "", "C:/media/promo.jpg"), (True, ""))
        self.assertEqual(
            validate_contact("19994229146", "", ""), (False, "mensagem vazia"))

    def test_celula_nan_do_pandas_conta_como_vazia(self):
        """`str(NaN)` é "nan", e era isso que a coluna vazia virava."""
        s = sender_nu(global_message="texto global",
                      global_attachment="C:/media/promo.jpg")
        for vazio in ("", "nan", "none", "  ", "NaN"):
            texto, anexo, _, usou_a = s._resolver_globais(vazio, vazio)
            self.assertEqual(texto, "texto global", f"falhou para {vazio!r}")
            self.assertEqual(anexo, "C:/media/promo.jpg", f"falhou para {vazio!r}")
            self.assertTrue(usou_a)

    def test_sem_nada_global_nada_muda(self):
        s = sender_nu()
        self.assertEqual(s._resolver_globais("", ""), ("", "", False, False))


class TestEstimativaEnxergaOAnexo(unittest.TestCase):
    """
    O anexo global tem que entrar na conta de tempo.

    Sem isto o usuário liga o anexo global, a tela continua dizendo o mesmo
    tempo de antes, e o envio estoura a janela configurada.
    """

    def _pendentes(self):
        # Campo em branco: é quem entra no pacote global.
        return pd.DataFrame([
            {"Nome": "Ana", "Número": "19990000001", "Mensagem": "", "Arquivo": ""},
            {"Nome": "Bruno", "Número": "19990000002", "Mensagem": "", "Arquivo": ""},
        ])

    def test_ligar_o_anexo_global_aumenta_o_tempo_estimado(self):
        pend = self._pendentes()
        sem = sender_nu(global_message="oi")._estimar_tempo_envio_total(pend, 2)
        com = sender_nu(global_message="oi",
                        global_attachment="C:/media/promo.jpg")._estimar_tempo_envio_total(pend, 2)
        self.assertGreater(
            com, sem,
            "a estimativa ignorou o anexo global — o envio vai estourar a janela")

    def test_quem_nao_entra_no_pacote_nao_ganha_tempo_de_anexo(self):
        """A conta tem que seguir a mesma regra do envio, não uma parecida."""
        pend = pd.DataFrame([
            {"Nome": "Ana", "Número": "19990000001",
             "Mensagem": "escrevi a minha", "Arquivo": ""},
        ])
        sem = sender_nu(global_message="oi")._estimar_tempo_envio_total(pend, 1)
        com = sender_nu(global_message="oi",
                        global_attachment="C:/media/promo.jpg")._estimar_tempo_envio_total(pend, 1)
        self.assertEqual(com, sem)

    def test_mensagem_global_tambem_entra_na_conta(self):
        """
        Mesma falha, pelo mesmo caminho: a coluna vazia custava ~nada de
        digitação, mas o que vai ser digitado é a mensagem global.
        """
        pend = pd.DataFrame([
            {"Nome": "Ana", "Número": "19990000001", "Mensagem": "", "Arquivo": ""},
        ])
        sem = sender_nu()._estimar_tempo_envio_total(pend, 1)
        com = sender_nu(global_message="x" * 600)._estimar_tempo_envio_total(pend, 1)
        self.assertGreater(com, sem)


class TestServidor(unittest.TestCase):
    """Endpoints, persistência e as duas recusas."""

    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient  # noqa: F401

    def setUp(self):
        self._cwd = os.getcwd()
        self.tmp = Path(tempfile.mkdtemp(prefix="anexoglobal_"))
        (self.tmp / "uploads").mkdir()
        RAIZ = Path(__file__).resolve().parent.parent
        shutil.copytree(RAIZ / "static", self.tmp / "static")
        os.chdir(self.tmp)

        self.arquivo = self.tmp / "uploads" / "media" / "promo.jpg"
        self.arquivo.parent.mkdir(parents=True)
        self.arquivo.write_bytes(b"\xff\xd8\xff\xd9")

        pd.DataFrame([
            {"Nome": "Ana", "Número": "19990000001", "Mensagem": "oi"},
        ]).to_excel(self.tmp / "uploads" / "contatos.xlsx", index=False)

        import app as app_mod
        self.app_mod = app_mod

    def tearDown(self):
        os.chdir(self._cwd)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _cliente(self):
        from fastapi.testclient import TestClient
        st = self.app_mod.state
        st.excel_path = None
        st.excel_source = ""
        st.logs = []
        st.sse_queues = []
        st.sender = None
        st.global_message = ""
        st.global_message_active = False
        st.global_attachment = ""
        st.global_attachment_active = False
        c = TestClient(self.app_mod.app)
        c.__enter__()
        self.addCleanup(c.__exit__, None, None, None)
        return c

    def test_sobrevive_a_fechar_e_abrir_o_programa(self):
        """A razão de ser gravado no servidor, e não no localStorage."""
        c = self._cliente()
        r = c.post("/global-attachment",
                   json={"arquivo": str(self.arquivo), "ativo": True})
        self.assertEqual(r.status_code, 200, r.text)
        c.__exit__(None, None, None)

        depois = self._cliente().get("/global-attachment").json()
        self.assertEqual(depois["arquivo"], str(self.arquivo))
        self.assertTrue(depois["ativo"])
        self.assertEqual(depois["nome"], "promo.jpg")

    def test_recusa_arquivo_que_nao_existe(self):
        c = self._cliente()
        r = c.post("/global-attachment",
                   json={"arquivo": "C:/nao/existe.jpg", "ativo": True})
        self.assertEqual(r.status_code, 400)
        self.assertIn("não encontrado", r.json()["detail"])

    def test_arquivo_apagado_entre_sessoes_desliga_o_anexo_e_avisa(self):
        """
        Restaurar apontando para um caminho morto invalidaria a lista inteira,
        um contato por vez, sem nada na tela explicando.
        """
        c = self._cliente()
        c.post("/global-attachment", json={"arquivo": str(self.arquivo), "ativo": True})
        c.__exit__(None, None, None)

        os.remove(self.arquivo)
        c2 = self._cliente()

        estado = c2.get("/global-attachment").json()
        self.assertEqual(estado["arquivo"], "")
        self.assertFalse(estado["ativo"])
        self.assertTrue(
            any("não está mais no disco" in l for l in self.app_mod.state.logs),
            f"nenhum aviso no log: {self.app_mod.state.logs}")

    def _ligar_pacote(self, c):
        """
        O estado real: mensagem global ativa E anexo escolhido.

        O anexo sozinho é inerte — ele é parte da mensagem global, não um
        recurso paralelo.
        """
        c.post("/global-message", json={"mensagem": "oi {nome}", "ativa": True})
        c.post("/global-attachment", json={"arquivo": str(self.arquivo), "ativo": True})

    def test_start_recusa_se_o_arquivo_sumiu_durante_a_sessao(self):
        """
        A conferência do `/start`, para o arquivo que some DEPOIS de ativado —
        aí a restauração já passou e ninguém mais olharia.
        """
        c = self._cliente()
        self._ligar_pacote(c)
        os.remove(self.arquivo)

        with patch.object(self.app_mod, "validar_licenca", lambda: {"valida": True}):
            r = c.post("/start")
        self.assertEqual(r.status_code, 400)
        self.assertIn("anexo global", r.json()["detail"].lower())

    def test_anexo_sem_mensagem_global_ativa_e_inerte(self):
        """
        A garantia de backend do acoplamento. A tela também impede, mas tela
        não é garantia: uma requisição fora dela chegaria igual.
        """
        c = self._cliente()
        c.post("/global-attachment", json={"arquivo": str(self.arquivo), "ativo": True})
        self.assertEqual(self.app_mod._anexo_global_ativo(), "",
                         "o anexo valeu sem a mensagem global estar ativa")

    def test_desligar_a_mensagem_global_desliga_o_anexo(self):
        """Pedido explícito: uma desliga a outra."""
        c = self._cliente()
        self._ligar_pacote(c)
        self.assertEqual(self.app_mod._anexo_global_ativo(), str(self.arquivo))

        c.post("/global-message", json={"mensagem": "oi {nome}", "ativa": False})

        self.assertFalse(self.app_mod.state.global_attachment_active)
        self.assertEqual(self.app_mod._anexo_global_ativo(), "")
        # O CAMINHO sobrevive: religar não pode obrigar a escolher de novo.
        self.assertEqual(self.app_mod.state.global_attachment, str(self.arquivo))
        self.assertEqual(c.get("/global-attachment").json()["arquivo"],
                         str(self.arquivo))

    def test_desligar_o_anexo_sobrevive_ao_reinicio(self):
        """O desligamento em cascata também é gravado, não só o estado em RAM."""
        c = self._cliente()
        self._ligar_pacote(c)
        c.post("/global-message", json={"mensagem": "oi", "ativa": False})
        c.__exit__(None, None, None)

        depois = self._cliente().get("/global-attachment").json()
        self.assertFalse(depois["ativo"])
        self.assertEqual(depois["arquivo"], str(self.arquivo))

    def test_congelado_durante_o_envio(self):
        """
        O sender lê isto a cada contato: aceitar troca no meio mudaria calado
        o que os contatos ainda na fila recebem. Mesma trava da config e da
        mensagem global.
        """
        c = self._cliente()

        class SenderFalso:
            _driver = None

            def is_running(self):
                return True

            def is_varrendo(self):
                return False

            def stop(self):
                """O `shutdown_event` para o sender ao fechar o TestClient."""

        self.app_mod.state.sender = SenderFalso()
        r = c.post("/global-attachment",
                   json={"arquivo": str(self.arquivo), "ativo": True})
        self.assertEqual(r.status_code, 400)
        self.assertIn("durante o envio", r.json()["detail"])

    def test_desligar_nao_apaga_o_caminho_escolhido(self):
        """Religar não pode obrigar a escolher o arquivo de novo."""
        c = self._cliente()
        c.post("/global-attachment", json={"arquivo": str(self.arquivo), "ativo": True})
        c.post("/global-attachment", json={"arquivo": str(self.arquivo), "ativo": False})

        estado = c.get("/global-attachment").json()
        self.assertEqual(estado["arquivo"], str(self.arquivo))
        self.assertFalse(estado["ativo"])
        # Desligado, o sender não recebe nada.
        self.assertEqual(self.app_mod._anexo_global_ativo(), "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
