"""
Testes unitários para a lógica de deduplicação de contatos.

Importa de contact_logic.py — sem dependência de Selenium ou browser.

Cobre os comportamentos que já apresentaram bugs em produção:
  1. Duplicados entre pendentes: apenas o 1º é mantido pendente
  2. Pendente com número igual a um JÁ ENVIADO é marcado como duplicado
  3. allow_duplicates=True reabilita contatos previamente invalidados por duplicata
  4. Números sem dígitos suficientes não geram falso-positivo de duplicata
  5. Notificações SSE são emitidas para cada duplicado detectado
  6. _validate_contact rejeita número ausente, curto ou mensagem vazia
  7. clean_number normaliza float do Excel, DDI 55 e formatação
"""

import sys
import os
import unittest
from unittest.mock import MagicMock

import pandas as pd

# Garante que o pacote raiz está no path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from contact_logic import clean_number, validate_contact, get_pending_contacts, apply_deduplication


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_df(rows: list) -> pd.DataFrame:
    """
    Monta um DataFrame de contatos. Valores omitidos assumem string vazia.
    """
    defaults = {
        "Nome": "", "Número": "", "Mensagem": "oi",
        "Enviado": "", "Invalido": "", "Motivo": "",
    }
    data = [{**defaults, **r} for r in rows]
    return pd.DataFrame(data)


def _run_dedup(df: pd.DataFrame, allow_duplicates: bool = False):
    """
    Executa apply_deduplication e devolve
    (df_modificado, pending_final, notificações, save_chamado).
    """
    notifications = []
    save_mock = MagicMock()

    df = apply_deduplication(
        df,
        allow_duplicates=allow_duplicates,
        notify_cb=lambda idx, num, status, data, motivo:
            notifications.append({"idx": idx, "num": num, "status": status, "motivo": motivo}),
        log_cb=lambda msg: None,
        save_cb=save_mock,
    )
    pending = get_pending_contacts(df)
    return df, pending, notifications, save_mock.called


# ===========================================================================
# clean_number
# ===========================================================================

class TestCleanNumber(unittest.TestCase):

    def test_numero_normal(self):
        self.assertEqual(clean_number("19994229146"), "19994229146")

    def test_numero_float_excel(self):
        """Pandas lê números como float: 19994229146.0 deve virar 19994229146."""
        self.assertEqual(clean_number("19994229146.0"), "19994229146")

    def test_remove_ddi_55(self):
        self.assertEqual(clean_number("5519994229146"), "19994229146")

    def test_numero_vazio(self):
        self.assertEqual(clean_number(""), "")

    def test_numero_nan(self):
        self.assertEqual(clean_number("nan"), "")

    def test_numero_com_formatacao(self):
        """(19)99422-9146 deve retornar apenas dígitos."""
        self.assertEqual(clean_number("(19)99422-9146"), "1999422914 6".replace(" ", ""))

    def test_numero_10_digitos_sem_ddi(self):
        self.assertEqual(clean_number("1999422914"), "1999422914")


# ===========================================================================
# validate_contact
# ===========================================================================

class TestValidateContact(unittest.TestCase):

    def test_contato_valido(self):
        ok, motivo = validate_contact("19994229146", "Olá!")
        self.assertTrue(ok)
        self.assertEqual(motivo, "")

    def test_numero_ausente(self):
        ok, motivo = validate_contact("", "Olá!")
        self.assertFalse(ok)
        self.assertIn("ausente", motivo)

    def test_numero_nan(self):
        ok, _ = validate_contact("nan", "Olá!")
        self.assertFalse(ok)

    def test_numero_curto(self):
        ok, motivo = validate_contact("1234", "Olá!")
        self.assertFalse(ok)
        self.assertIn("inválido", motivo)

    def test_mensagem_vazia(self):
        ok, motivo = validate_contact("19994229146", "")
        self.assertFalse(ok)
        self.assertIn("vazia", motivo)

    def test_mensagem_nan(self):
        ok, _ = validate_contact("19994229146", "nan")
        self.assertFalse(ok)

    def test_numero_com_ddi_ainda_valido(self):
        """5519994229146 tem DDI — após normalização tem 11 dígitos, deve ser válido."""
        ok, _ = validate_contact("5519994229146", "Olá!")
        self.assertTrue(ok)


# ===========================================================================
# get_pending_contacts
# ===========================================================================

class TestGetPendingContacts(unittest.TestCase):

    def test_exclui_enviados(self):
        df = _make_df([{"Nome": "A", "Enviado": "X"}, {"Nome": "B"}])
        pending = get_pending_contacts(df)
        self.assertNotIn("A", list(pending["Nome"]))
        self.assertIn("B", list(pending["Nome"]))

    def test_exclui_invalidos(self):
        df = _make_df([{"Nome": "A", "Invalido": "X"}, {"Nome": "B"}])
        pending = get_pending_contacts(df)
        self.assertNotIn("A", list(pending["Nome"]))
        self.assertIn("B", list(pending["Nome"]))

    def test_exclui_enviados_e_invalidos(self):
        df = _make_df([
            {"Nome": "A", "Enviado": "X"},
            {"Nome": "B", "Invalido": "X"},
            {"Nome": "C"},
        ])
        pending = get_pending_contacts(df)
        self.assertEqual(list(pending["Nome"]), ["C"])

    def test_dataframe_vazio(self):
        df = _make_df([])
        pending = get_pending_contacts(df)
        self.assertEqual(len(pending), 0)


# ===========================================================================
# Deduplicação entre pendentes
# ===========================================================================

class TestDeduplicacaoEntrePendentes(unittest.TestCase):
    """Dois ou mais pendentes com o mesmo número — o 2º em diante é marcado."""

    def test_segundo_pendente_vira_invalido(self):
        df = _make_df([
            {"Nome": "Ana",  "Número": "19994229146"},
            {"Nome": "Bob",  "Número": "19994229146"},
            {"Nome": "Cris", "Número": "11987654321"},
        ])
        df_r, pending, notifs, _ = _run_dedup(df)

        self.assertEqual(df_r.at[1, "Invalido"], "X")
        self.assertIn("duplicado", df_r.at[1, "Motivo"].lower())
        self.assertIn("Ana", list(pending["Nome"]))
        self.assertIn("Cris", list(pending["Nome"]))
        self.assertNotIn("Bob", list(pending["Nome"]))

    def test_tres_pendentes_mesmo_numero_marca_segundo_e_terceiro(self):
        df = _make_df([
            {"Nome": "A", "Número": "19994229146"},
            {"Nome": "B", "Número": "19994229146"},
            {"Nome": "C", "Número": "19994229146"},
        ])
        df_r, pending, notifs, _ = _run_dedup(df)

        self.assertEqual(df_r.at[0, "Invalido"], "")   # A: pendente
        self.assertEqual(df_r.at[1, "Invalido"], "X")  # B: duplicado
        self.assertEqual(df_r.at[2, "Invalido"], "X")  # C: duplicado
        self.assertEqual(len(notifs), 2)
        self.assertEqual(len(pending), 1)

    def test_notificacao_sse_emitida_para_cada_duplicado(self):
        df = _make_df([
            {"Nome": "Ana", "Número": "19994229146"},
            {"Nome": "Bob", "Número": "19994229146"},
        ])
        _, _, notifs, _ = _run_dedup(df)

        self.assertEqual(len(notifs), 1)
        self.assertEqual(notifs[0]["status"], "invalido")
        self.assertIn("duplicado", notifs[0]["motivo"].lower())
        self.assertEqual(notifs[0]["idx"], 1)

    def test_planilha_salva_quando_ha_duplicados(self):
        df = _make_df([
            {"Nome": "Ana", "Número": "19994229146"},
            {"Nome": "Bob", "Número": "19994229146"},
        ])
        _, _, _, save_called = _run_dedup(df)
        self.assertTrue(save_called)

    def test_planilha_nao_salva_sem_duplicados(self):
        df = _make_df([
            {"Nome": "Ana", "Número": "11111111111"},
            {"Nome": "Bob", "Número": "22222222222"},
        ])
        _, _, _, save_called = _run_dedup(df)
        self.assertFalse(save_called)


# ===========================================================================
# Deduplicação: pendente vs. já enviado  ← BUG CORRIGIDO
# ===========================================================================

class TestDeduplicacaoComEnviado(unittest.TestCase):
    """
    Cenário do bug: número já enviado não entrava no mapa de duplicados,
    então o pendente com o mesmo número era enviado novamente.
    """

    def test_pendente_com_numero_ja_enviado_vira_invalido(self):
        df = _make_df([
            {"Nome": "Ana",  "Número": "19994229146", "Enviado": "X"},
            {"Nome": "Bob",  "Número": "19994229146"},                  # deve ser bloqueado
            {"Nome": "Cris", "Número": "11987654321"},                  # número diferente — ok
        ])
        df_r, pending, notifs, save_called = _run_dedup(df)

        self.assertEqual(df_r.at[1, "Invalido"], "X")
        self.assertIn("duplicado", df_r.at[1, "Motivo"].lower())
        self.assertIn("Ana", df_r.at[1, "Motivo"])
        self.assertNotIn("Bob", list(pending["Nome"]))
        self.assertIn("Cris", list(pending["Nome"]))
        self.assertEqual(len(notifs), 1)
        self.assertEqual(notifs[0]["idx"], 1)
        self.assertTrue(save_called)

    def test_multiplos_pendentes_com_numero_ja_enviado(self):
        df = _make_df([
            {"Nome": "Ana",   "Número": "19994229146", "Enviado": "X"},
            {"Nome": "Bob",   "Número": "19994229146"},
            {"Nome": "Carol", "Número": "19994229146"},
        ])
        df_r, pending, notifs, _ = _run_dedup(df)

        self.assertEqual(df_r.at[1, "Invalido"], "X")
        self.assertEqual(df_r.at[2, "Invalido"], "X")
        self.assertEqual(len(notifs), 2)
        self.assertEqual(len(pending), 0)

    def test_enviado_nao_bloqueia_numero_diferente(self):
        df = _make_df([
            {"Nome": "Ana", "Número": "19994229146", "Enviado": "X"},
            {"Nome": "Bob", "Número": "11987654321"},
        ])
        df_r, pending, notifs, _ = _run_dedup(df)

        self.assertEqual(df_r.at[1, "Invalido"], "")
        self.assertEqual(len(notifs), 0)
        self.assertIn("Bob", list(pending["Nome"]))

    def test_numero_com_ddi_55_equivale_ao_sem_ddi(self):
        """5519994229146 (com DDI) e 19994229146 (sem DDI) são o mesmo número."""
        df = _make_df([
            {"Nome": "Ana", "Número": "5519994229146", "Enviado": "X"},
            {"Nome": "Bob", "Número": "19994229146"},
        ])
        df_r, _, notifs, _ = _run_dedup(df)

        self.assertEqual(df_r.at[1, "Invalido"], "X")
        self.assertEqual(len(notifs), 1)

    def test_numero_float_excel_equivale_ao_inteiro(self):
        """Pandas pode ler 19994229146 como float '19994229146.0'."""
        df = _make_df([
            {"Nome": "Ana", "Número": "19994229146.0", "Enviado": "X"},
            {"Nome": "Bob", "Número": "19994229146"},
        ])
        df_r, _, notifs, _ = _run_dedup(df)

        self.assertEqual(df_r.at[1, "Invalido"], "X")
        self.assertEqual(len(notifs), 1)

    def test_apenas_enviados_sem_pendentes(self):
        """Nenhum pendente — não deve marcar nada nem salvar."""
        df = _make_df([
            {"Nome": "Ana", "Número": "19994229146", "Enviado": "X"},
            {"Nome": "Bob", "Número": "19994229146", "Enviado": "X"},
        ])
        df_r, pending, notifs, save_called = _run_dedup(df)

        self.assertEqual(len(notifs), 0)
        self.assertFalse(save_called)
        self.assertEqual(len(pending), 0)


# ===========================================================================
# Sem duplicados
# ===========================================================================

class TestSemDuplicados(unittest.TestCase):

    def test_todos_diferentes_nenhum_marcado(self):
        df = _make_df([
            {"Nome": "A", "Número": "11111111111"},
            {"Nome": "B", "Número": "22222222222"},
            {"Nome": "C", "Número": "33333333333"},
        ])
        df_r, pending, notifs, save_called = _run_dedup(df)

        self.assertTrue((df_r["Invalido"] == "").all())
        self.assertEqual(len(notifs), 0)
        self.assertFalse(save_called)
        self.assertEqual(len(pending), 3)

    def test_numero_vazio_ignorado_nao_gera_falso_positivo(self):
        """Dois contatos sem número não devem ser marcados como duplicados."""
        df = _make_df([
            {"Nome": "A", "Número": ""},
            {"Nome": "B", "Número": ""},
            {"Nome": "C", "Número": "19994229146"},
        ])
        _, pending, notifs, _ = _run_dedup(df)

        self.assertEqual(len(notifs), 0)
        self.assertEqual(len(pending), 3)


# ===========================================================================
# allow_duplicates = True
# ===========================================================================

class TestAllowDuplicates(unittest.TestCase):

    def test_reabilita_duplicados_de_execucao_anterior(self):
        df = _make_df([
            {"Nome": "Ana", "Número": "19994229146"},
            {"Nome": "Bob", "Número": "19994229146",
             "Invalido": "X", "Motivo": "Número duplicado (mesmo que Ana)"},
        ])
        df_r, pending, _, save_called = _run_dedup(df, allow_duplicates=True)

        self.assertEqual(df_r.at[1, "Invalido"], "")
        self.assertEqual(df_r.at[1, "Motivo"], "")
        self.assertTrue(save_called)
        self.assertIn("Bob", list(pending["Nome"]))

    def test_nao_reabilita_invalidos_por_outro_motivo(self):
        """Inválido por bloqueio não deve ser reabilitado pelo modo teste."""
        df = _make_df([
            {"Nome": "Ana", "Número": "19994229146",
             "Invalido": "X", "Motivo": "número bloqueado"},
        ])
        df_r, pending, _, _ = _run_dedup(df, allow_duplicates=True)

        self.assertEqual(df_r.at[0, "Invalido"], "X")
        self.assertNotIn("Ana", list(pending["Nome"]))

    def test_nao_marca_novos_duplicados_quando_permitido(self):
        """Com allow_duplicates=True, novos duplicados NÃO são marcados."""
        df = _make_df([
            {"Nome": "Ana", "Número": "19994229146"},
            {"Nome": "Bob", "Número": "19994229146"},
        ])
        df_r, pending, notifs, _ = _run_dedup(df, allow_duplicates=True)

        self.assertEqual(df_r.at[1, "Invalido"], "")
        self.assertEqual(len(notifs), 0)
        self.assertEqual(len(pending), 2)

    def test_reabilita_apenas_os_duplicados_mantem_outros_invalidos(self):
        """Planilha mista: duplicado deve ser reabilitado; bloqueado deve continuar inválido."""
        df = _make_df([
            {"Nome": "A", "Invalido": "X", "Motivo": "Número duplicado (mesmo que B)"},
            {"Nome": "B", "Invalido": "X", "Motivo": "número bloqueado"},
            {"Nome": "C"},
        ])
        df_r, pending, _, _ = _run_dedup(df, allow_duplicates=True)

        self.assertEqual(df_r.at[0, "Invalido"], "")   # reabilitado
        self.assertEqual(df_r.at[1, "Invalido"], "X")  # mantém bloqueado
        pending_nomes = list(pending["Nome"])
        self.assertIn("A", pending_nomes)
        self.assertNotIn("B", pending_nomes)
        self.assertIn("C", pending_nomes)


if __name__ == "__main__":
    unittest.main()
