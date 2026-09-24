# -*- coding: utf-8 -*-
"""
O ambiente de um teste end-to-end: app de verdade, WhatsApp Web falso.

Entra HTTP, sai planilha. Tudo entre as duas pontas é o código de produção —
rotas do FastAPI, `AppState`, `WhatsAppSender`, planejamento de rajadas,
`contact_logic`, `varredura`. Só três coisas são trocadas, e cada uma por um
motivo diferente:

1. **O driver** (`_init_driver`), pelo `FakeWhatsAppWeb`. É a costura única que
   torna tudo isto possível.
2. **O relógio.** Uma campanha real leva horas por construção — o plano de
   rajadas é um orçamento de tempo. Um relógio falso faz a mesma campanha rodar
   em milissegundos SEM mexer na lógica de ritmo: os prazos continuam sendo
   comparados, só que contra um tempo que anda quando alguém dorme. Isso é
   melhor que encurtar as pausas na config, que testaria um ritmo que ninguém
   usa.
3. **A licença e o diálogo do Windows.** São recursos externos ao processo
   (Supabase e a janela nativa de "Abrir arquivo"); nenhum dos dois tem o que
   dizer sobre o envio.

## O que este arquivo deliberadamente NÃO isola

O `state` global do `app.py` é um só — o app é de uma campanha por processo, e
fingir o contrário aqui testaria um app que não existe. Cada cenário reseta o
estado e trabalha num diretório temporário próprio, que é o que o processo de
verdade tem: um `uploads/` e uma planilha.
"""

import json
import os
import shutil
import tempfile
import threading
import time as _time_real
from pathlib import Path
from unittest.mock import patch

import pandas as pd

RAIZ = Path(__file__).resolve().parent.parent.parent


class RelogioFalso:
    """
    Relógio que só anda quando alguém dorme.

    `time.monotonic()` e `time.time()` passam a ler o tempo virtual, então todo
    prazo do app (`deadline`, `fim`, orçamento de digitação, idade mínima de
    entrega) continua valendo exatamente como em produção — o que muda é que
    dormir 4 minutos custa zero.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._base_mono = _time_real.monotonic()
        self._base_wall = _time_real.time()
        self._offset = 0.0

    def avancar(self, segundos: float) -> None:
        with self._lock:
            self._offset += max(0.0, float(segundos or 0))

    @property
    def decorrido(self) -> float:
        return self._offset

    def monotonic(self):
        return self._base_mono + self._offset

    def time(self):
        return self._base_wall + self._offset

    def sleep(self, segundos):
        self.avancar(segundos)

    def __getattr__(self, nome):
        # Qualquer outra coisa (strftime, localtime, ...) é o time de verdade.
        return getattr(_time_real, nome)


class AmbienteE2E:
    """
    Use como context manager:

        with AmbienteE2E(contatos=[...], roteiro={...}) as amb:
            amb.configurar(total_msgs=3, tempo_minutos=10)
            amb.iniciar_envio()
            amb.esperar_envio()
            df = amb.planilha()
    """

    def __init__(self, contatos=None, roteiro=None, padrao="ok",
                 linhas_da_lista=None, mensagem_global=""):
        from tests.e2e.fake_whatsapp import FakeWhatsAppWeb

        self.contatos = list(contatos or [])
        self.mensagem_global = mensagem_global
        self.driver = FakeWhatsAppWeb(
            roteiro=roteiro, padrao=padrao, linhas_da_lista=linhas_da_lista
        )
        self.relogio = RelogioFalso()
        self._patches = []
        self._cwd_original = os.getcwd()
        self._tmp = None
        self.cliente = None

    # ------------------------------------------------------------------ #
    # Montagem
    # ------------------------------------------------------------------ #
    def __enter__(self):
        import app as app_mod
        import varredura
        import whatsapp_sender
        from fastapi.testclient import TestClient

        from tests.e2e.fake_whatsapp import AcoesFalsas

        self._app_mod = app_mod

        # --- diretório de trabalho próprio ---
        # O app resolve `uploads/...` contra o CWD, então um CWD por cenário é
        # o isolamento mais fiel possível: é o mesmo caminho do processo real,
        # só que vazio.
        self._tmp = Path(tempfile.mkdtemp(prefix="e2e_whats_"))
        (self._tmp / "uploads").mkdir()
        # `static/` precisa existir: o mount do StaticFiles e o `serve_frontend`
        # leem dali.
        shutil.copytree(RAIZ / "static", self._tmp / "static")
        os.chdir(self._tmp)

        if self.contatos:
            self._escrever_planilha(self.contatos)

        # --- trocas ---
        def _driver_falso(_self):
            _self._driver = self.driver
            return self.driver

        self._aplicar(patch.object(
            whatsapp_sender.WhatsAppSender, "_init_driver", _driver_falso))
        self._aplicar(patch.object(whatsapp_sender, "time", self.relogio))
        self._aplicar(patch.object(varredura, "time", self.relogio))
        self._aplicar(patch.object(whatsapp_sender, "ActionChains", AcoesFalsas))

        # Dormir vira "adiantar o relógio", mantendo a semântica do Parar: a
        # única coisa que `_interruptible_sleep` promete é acordar na hora se
        # alguém pediu parada.
        def _dormir(_self, segundos):
            self.relogio.avancar(segundos)
            return _self._stop_event.is_set()

        self._aplicar(patch.object(
            whatsapp_sender.WhatsAppSender, "_interruptible_sleep", _dormir))

        # Licença: recurso externo, e `/start` recusa sem ela.
        self._aplicar(patch.object(
            app_mod, "validar_licenca", lambda: {"valida": True}))

        # Diálogo nativo do Windows (anexos): ctypes contra uma janela real.
        self._aplicar(patch.object(whatsapp_sender.win_dialog, "IS_WINDOWS", False))

        # --- estado limpo, e o servidor de pé ---
        self._resetar_estado()
        self.cliente = TestClient(app_mod.app)
        self.cliente.__enter__()  # dispara o startup_event de verdade

        if self.mensagem_global:
            r = self.cliente.post("/global-message", json={
                "mensagem": self.mensagem_global, "ativa": True})
            assert r.status_code == 200, r.text
        return self

    def __exit__(self, *exc):
        try:
            if self._app_mod.state.sender:
                self._app_mod.state.sender.stop()
            self.esperar_envio(timeout=10)
        except Exception:
            pass
        if self.cliente:
            self.cliente.__exit__(None, None, None)
        for p in reversed(self._patches):
            p.stop()
        self._patches.clear()
        self._resetar_estado()
        os.chdir(self._cwd_original)
        if self._tmp:
            shutil.rmtree(self._tmp, ignore_errors=True)
        return False

    def _aplicar(self, p):
        p.start()
        self._patches.append(p)

    def _resetar_estado(self):
        st = self._app_mod.state
        st.excel_path = None
        st.excel_source = ""
        st.excel_saved_at = ""
        st.sender = None
        st.sender_thread = None
        st.varredura_thread = None
        st.logs = []
        st.sse_queues = []
        st.global_message = ""
        st.global_message_active = False
        st.config = {
            "total_msgs": 10, "tempo_minutos": 60,
            "hora_inicio": "08:00", "hora_fim": "18:00",
            "skip_weekends": True, "human_behavior": True,
            "allow_duplicates": False,
        }

    # ------------------------------------------------------------------ #
    # Planilha
    # ------------------------------------------------------------------ #
    COLUNAS = [
        "Nome", "Número", "Mensagem", "Arquivo", "Enviado", "DataEnvio",
        "Invalido", "Motivo", "Respondeu", "DataResposta", "Entrega",
        "UltimaVerificacao", "RespostaTexto",
    ]

    def _escrever_planilha(self, contatos):
        base = {c: "" for c in self.COLUNAS}
        df = pd.DataFrame([{**base, **c} for c in contatos], columns=self.COLUNAS)
        df["Número"] = df["Número"].astype(str)
        caminho = Path("uploads") / "contatos.xlsx"
        df.to_excel(caminho, index=False)
        self._app_mod.state.excel_path = str(caminho)
        self._app_mod.state.excel_source = "cli"

    def planilha(self):
        """A planilha como está no disco AGORA — a saída do teste."""
        df = pd.read_excel(Path("uploads") / "contatos.xlsx", dtype=str)
        return df.fillna("")

    def linha(self, nome):
        df = self.planilha()
        achadas = df[df["Nome"] == nome]
        assert len(achadas) == 1, f"{nome!r} casou {len(achadas)} linhas"
        return achadas.iloc[0]

    # ------------------------------------------------------------------ #
    # Condução
    # ------------------------------------------------------------------ #
    def configurar(self, **kw):
        """
        Config do envio. Os padrões abrem a janela de horário inteira: o
        expediente é uma feature com testes próprios, e deixá-lo ligado faria
        cada cenário depender da hora em que a suíte roda.
        """
        cfg = {
            "total_msgs": kw.pop("total_msgs", len(self.contatos)),
            "tempo_minutos": kw.pop("tempo_minutos", 10),
            "hora_inicio": "00:00",
            "hora_fim": "23:59",
            "skip_weekends": False,
            "human_behavior": True,
            "allow_duplicates": False,
        }
        cfg.update(kw)
        r = self.cliente.post("/config", json=cfg)
        assert r.status_code == 200, r.text
        return r.json()

    def iniciar_envio(self):
        r = self.cliente.post("/start")
        assert r.status_code == 200, r.text
        return r.json()

    def esperar_envio(self, timeout=30):
        """
        Espera a thread de envio terminar. É tempo de parede DE VERDADE (o
        relógio falso não acelera o escalonador), mas sem as pausas o envio
        inteiro leva milissegundos.
        """
        th = self._app_mod.state.sender_thread
        if th:
            th.join(timeout=timeout)
            assert not th.is_alive(), "o envio não terminou dentro do timeout"

    def parar(self):
        return self.cliente.post("/stop")

    def status(self):
        return self.cliente.get("/status").json()

    def contatos_da_tela(self):
        r = self.cliente.get("/contacts")
        assert r.status_code == 200, r.text
        return r.json()

    def logs(self):
        return list(self._app_mod.state.logs)

    def log_contem(self, trecho) -> bool:
        alvo = trecho.lower()
        return any(alvo in str(l.get("message", l)).lower() for l in self.logs())

    # ---- arquivos de estado que o app mantém ----
    def marcador_de_execucao(self):
        p = Path("uploads") / "envio_em_andamento.json"
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

    def config_persistida(self):
        p = Path("uploads") / "config.json"
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
