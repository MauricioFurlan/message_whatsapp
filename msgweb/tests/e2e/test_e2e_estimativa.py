# -*- coding: utf-8 -*-
"""
/estimate nas rajadas: a tela sempre recebe quantas mensagens saem e quanto
tempo deve levar.

Relato (2026-10-04): "50 mensagens em 5 minutos" mostrava um alerta que sumia
logo em seguida. A planilha tinha 1 pendente, o servidor respondia
`inviavel: False` sem tempo nenhum, e a tela apagava o aviso sem dizer por quê.
Regra do usuário: o aviso não some e mostra quanto tempo vai levar — então o
tempo vai na resposta em todo caso, inclusive com 0 ou 1 mensagem a enviar.
O texto em si é de tests/test_aviso_ritmo_ui.js.

Rodar:
    python -m unittest tests.e2e.test_e2e_estimativa -v
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from tests.e2e.ambiente import AmbienteE2E


def _contatos(n):
    return [
        {"Nome": f"Pessoa {i}", "Número": f"1999{i:07d}", "Mensagem": "Oi {nome}"}
        for i in range(1, n + 1)
    ]


def _estimar(amb, total, minutos):
    return amb.cliente.get(
        "/estimate", params={"total_msgs": total, "tempo_minutos": minutos}
    ).json()


class TestEstimativaRajadas(unittest.TestCase):
    def test_tempo_que_nao_cabe_e_inviavel_com_o_tempo_real(self):
        with AmbienteE2E(contatos=_contatos(50)) as amb:
            amb.configurar(total_msgs=50, tempo_minutos=5)
            r = _estimar(amb, 50, 5)
            self.assertEqual(r["session_target"], 50)
            self.assertTrue(r["inviavel"])
            # Nunca abaixo dos 49 intervalos mínimos de 15s, além do envio.
            self.assertGreater(r["tempo_total_estimado_seg"], 49 * 15)
            self.assertGreater(r["tempo_total_estimado_seg"], 5 * 60)
            self.assertTrue(r["tempo_total_estimado_fmt"])

    def test_menos_pendentes_que_o_pedido_ainda_traz_o_tempo(self):
        # O caso do relato: 50 pedidas, 1 pendente.
        with AmbienteE2E(contatos=_contatos(1)) as amb:
            amb.configurar(total_msgs=50, tempo_minutos=5)
            r = _estimar(amb, 50, 5)
            self.assertEqual(r["session_target"], 1)
            self.assertEqual(r["pendentes"], 1)
            self.assertFalse(r["inviavel"])
            self.assertGreater(r["tempo_total_estimado_seg"], 0)
            self.assertTrue(r["tempo_total_estimado_fmt"])

    def test_nenhum_pendente_depois_do_envio_responde_zero(self):
        with AmbienteE2E(contatos=_contatos(2)) as amb:
            amb.configurar(total_msgs=2, tempo_minutos=10)
            amb.iniciar_envio()
            amb.esperar_envio()
            r = _estimar(amb, 50, 5)
            self.assertEqual(r["status"], "ok")
            self.assertEqual(r["pendentes"], 0)
            self.assertEqual(r["session_target"], 0)
            self.assertEqual(r["tempo_total_estimado_seg"], 0)


class TestEstimativaDaTela(unittest.TestCase):
    """
    POST /estimate: estima sobre os contatos da tela, não sobre o disco.

    Relato (2026-10-04): clicar no ↺ (voltar a Pendente) não mudava o aviso
    de tempo — o ↺ só grava no "Salvar Alterações", e a estimativa lia o
    disco. Mas é a tela que vai para o envio (o Iniciar grava antes do
    /start), então é ela que a estimativa tem que descrever.
    """

    def _tela(self, amb):
        return amb.cliente.get("/contacts").json()["contacts"]

    def _como_a_tela_manda(self, c):
        # O que collectContacts() monta a partir de cada linha.
        return {
            "pessoa": c.get("pessoa", ""), "numero": str(c.get("numero", "")),
            "mensagem": c.get("mensagem", ""), "arquivo": c.get("arquivo", ""),
            "enviado": bool(c.get("enviado")), "invalido": bool(c.get("invalido")),
            "data_envio": c.get("data_envio", "") or "", "motivo": c.get("motivo", "") or "",
        }

    def test_reenfileirar_na_tela_conta_sem_gravar(self):
        with AmbienteE2E(contatos=_contatos(3)) as amb:
            amb.configurar(total_msgs=3, tempo_minutos=10)
            amb.iniciar_envio()
            amb.esperar_envio()
            planilha_antes = amb.planilha().to_dict("records")

            tela = [self._como_a_tela_manda(c) for c in self._tela(amb)]
            self.assertTrue(all(c["enviado"] for c in tela))
            # ↺ em dois contatos: só a tela muda.
            for c in tela[:2]:
                c["enviado"] = False
                c["data_envio"] = ""

            r = amb.cliente.post("/estimate", json={
                "total_msgs": 50, "tempo_minutos": 5, "contacts": tela,
            }).json()
            self.assertEqual(r["status"], "ok")
            self.assertEqual(r["pendentes"], 2)
            self.assertEqual(r["session_target"], 2)
            self.assertGreater(r["tempo_total_estimado_seg"], 0)

            # O disco segue dizendo 0 — e a estimativa não pode tê-lo tocado.
            self.assertEqual(_estimar(amb, 50, 5)["pendentes"], 0)
            self.assertEqual(amb.planilha().to_dict("records"), planilha_antes)

    def test_modo_direto_tambem_le_a_tela(self):
        with AmbienteE2E(contatos=_contatos(4)) as amb:
            tela = [self._como_a_tela_manda(c) for c in self._tela(amb)]
            tela[0]["invalido"] = True
            r = amb.cliente.post("/estimate", json={
                "modo_envio": "direto", "contacts": tela,
            }).json()
            self.assertEqual(r["pendentes"], 3)


if __name__ == "__main__":
    unittest.main()
