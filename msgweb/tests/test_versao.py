# -*- coding: utf-8 -*-
"""
Testes da comparação de versão usada pelo aviso de atualização.

Motivação: a comparação era feita como texto (`latest_tag > APP_VERSION`), o que
funciona até a 1.9 e passa a falhar silenciosamente na 1.10 — "1.10.0" > "1.9.0"
é False na ordem alfabética, então o usuário nunca seria avisado da atualização.

Rodar:
    python -m unittest tests.test_versao -v
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import _parse_version


def mais_nova(latest: str, atual: str) -> bool:
    """Reproduz a decisão do endpoint /check-update."""
    v_latest = _parse_version(latest)
    v_atual = _parse_version(atual)
    if v_latest and v_atual:
        return v_latest > v_atual
    return False


class TestParseVersion(unittest.TestCase):
    def test_formato_completo(self):
        self.assertEqual(_parse_version("1.4.2"), (1, 4, 2))

    def test_normaliza_para_tres_posicoes(self):
        self.assertEqual(_parse_version("1.4"), (1, 4, 0))
        self.assertEqual(_parse_version("2"), (2, 0, 0))

    def test_versao_igual_com_formatos_diferentes(self):
        self.assertEqual(_parse_version("1.4"), _parse_version("1.4.0"))

    def test_ignora_sufixo(self):
        self.assertEqual(_parse_version("1.4.0-beta"), (1, 4, 0))
        self.assertEqual(_parse_version("1.4.0rc1"), (1, 4, 0))

    def test_espacos(self):
        self.assertEqual(_parse_version("  1.4.0  "), (1, 4, 0))

    def test_entrada_invalida_retorna_vazio(self):
        self.assertEqual(_parse_version(""), ())
        self.assertEqual(_parse_version("abc"), ())


class TestComparacao(unittest.TestCase):
    def test_o_bug_original_1_10_maior_que_1_9(self):
        """O caso que a comparação de texto errava."""
        self.assertTrue("1.10.0" < "1.9.0", "premissa: texto compara errado")
        self.assertTrue(mais_nova("1.10.0", "1.9.0"), "1.10.0 é mais nova que 1.9.0")

    def test_dezenas_em_todas_as_posicoes(self):
        self.assertTrue(mais_nova("1.0.10", "1.0.9"))
        self.assertTrue(mais_nova("10.0.0", "9.9.9"))
        self.assertTrue(mais_nova("1.20.0", "1.3.0"))

    def test_versao_igual_nao_oferece_update(self):
        self.assertFalse(mais_nova("1.4.0", "1.4.0"))
        self.assertFalse(mais_nova("1.4", "1.4.0"))

    def test_versao_antiga_no_github_nao_oferece_update(self):
        self.assertFalse(mais_nova("1.3.0", "1.4.0"))
        self.assertFalse(mais_nova("1.9.0", "1.10.0"))

    def test_incremento_normal(self):
        self.assertTrue(mais_nova("1.4.1", "1.4.0"))
        self.assertTrue(mais_nova("1.5.0", "1.4.9"))
        self.assertTrue(mais_nova("2.0.0", "1.99.99"))

    def test_tag_invalida_nao_gera_aviso_falso(self):
        self.assertFalse(mais_nova("", "1.4.0"))
        self.assertFalse(mais_nova("latest", "1.4.0"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
