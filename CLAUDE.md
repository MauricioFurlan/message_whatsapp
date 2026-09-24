# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository layout

- `msgweb/` — the active application (FastAPI web UI + Selenium WhatsApp Web automation). Do work here unless told otherwise.
- Repo root (`main.py`, root `requirements.txt`, root `README.md`) is a legacy standalone Selenium script that predates `msgweb/`. The root `README.md` also documents a `main_business_api.py` (WhatsApp Business API variant) that no longer exists in the repo — treat that doc as stale.

All commands below assume `cd msgweb` first.

## Running the app

```bash
pip install -r requirements.txt
python -m uvicorn app:app --reload      # dev, with reload
# or
python app.py --planilha test           # prod-like entrypoint (hypercorn), binds 127.0.0.1:8000 only
```
Open http://localhost:8000.

`launcher.py` is the entry point used by the packaged `.exe` (PyInstaller build) — opens the default browser, starts hypercorn, same localhost-only bind.

### The test sheet is generated, never edited in place

```bash
testar.bat          # regenerates the test sheet, then serves it
```
`testar.bat` rebuilds `uploads/test_contatos.xlsx` from the versioned seed
`test_contatos.csv` (via `gerar_planilha_teste.py`) and then runs
`app.py --planilha test`. Use it instead of `python app.py --planilha test`,
which serves whatever state the last run left behind.

That sheet is the bench: 46 hand-built cases covering empty placeholder, phone
numbers in five formats, missing attachment, emoji, line breaks, duplicate,
already-sent. A real send *writes* to it (`Enviado`, `DataEnvio`, `Invalido`,
`Motivo`, `Tentativas`, and since the reply scan also `Respondeu`, `Entrega`,
`RespostaTexto`), so from the second run on almost every row is `Enviado=X` and
is skipped — the bench silently shrinks to a handful of rows, which is worse
than it being obviously broken.

The seed is a CSV rather than a model `.xlsx` for two reasons: `uploads/` is
gitignored (it holds the client's real contacts), so nothing inside it can be
the original; and a new test case should be addable in a diff without opening
Excel. The `.xlsx` is derived — delete it whenever, the script rebuilds it.

Two rows are born marked, and they are **fixtures, not results**: "Ja Enviado"
and "Ja Invalido", both of which must be skipped by the send. Any other control
column preset in the seed would be execution state leaking back into the
original, which is the exact problem this replaces.

Whitespace is load-bearing — `"  Pedro  "` *is* the name-trimming case — so the
generator strips nothing. `testar.bat` also deletes
`uploads/envio_em_andamento.json`: it describes a run of a sheet that was just
thrown away, and would otherwise open every test session with an
"interrupted run" warning about pending contacts that no longer exist.

## Tests

```bash
rodar_testes.bat                    # everything: 567 tests, Python + Node, ~4.5min
rodar_testes.bat --rapido           # skips the 3 slow files: 421 tests, ~34s
python rodar_testes.py --so e2e     # one group: e2e, unidade, lentos, node
```

`rodar_testes.py` **discovers** the test files off disk rather than reading a
list — the list in this file was stale by nine files when the runner was
written, which is how a hand-kept list always fails: the person adding test
number 40 doesn't know it exists. The price is that exclusions must be
explicit, and they are, each with its reason in the source:

- `tests/test_win_dialog.py` never runs automatically (it opens a real Windows
  dialog and waits for a click);
- `test_app_estado.py` runs and reports, but its **4 known failures** don't fail
  the suite — and if that count *changes*, the runner says so, because a new
  failure there is a real regression hiding behind an old one;
- three files hold **247 of the suite's 283 seconds** and are grouped as
  `lentos`: `test_numeros.py` (111s) and `test_mensagem_global.py` simulate
  humanized typing character by character, and `tests/test_delay_apos_falha.py`
  (136s) waits out real backoff. That time is the thing they measure, so it
  isn't waste — but `--rapido` skips them and takes the suite from ~4.5min to
  ~34s. Don't skip them before a build.

A file with no `unittest.TestCase` is run as a **script**, not through
`-m unittest`: the one plain-script test in the repo
(`tests/test_contact_update_backend.py`) would otherwise report "Ran 0 tests:
OK" — a test that doesn't run, looking exactly like a test that passes.

The individual commands below still work and are what you want while iterating
on one thing.

```bash
venv\Scripts\python.exe -m unittest test_numeros test_mensagem_global test_app_estado -v
python -m unittest tests.test_versao -v
python tests/test_contact_update_backend.py
python -m unittest tests.test_chat_open_timeout tests.test_sync_inicial tests.test_trava_durante_envio tests.test_chrome_perfil_em_uso tests.test_duplicado_vs_enviado tests.test_log_queda_conexao tests.test_aviso_lentidao tests.test_pane_lento tests.test_execucao_interrompida tests.test_seletores tests.test_linha_conversa tests.test_alerta_entrega tests.test_varredura tests.test_cache_pagina -v
python tests/test_deduplication.py
python tests/test_nav_retry.py
python tests/test_win_dialog.py      # opens a real Windows file dialog — Windows only
node tests/test_contact_update.js
node tests/test_log_tooltip.js
node tests/test_load_contacts_falha.js
node tests/test_trava_config_ui.js
node tests/test_aviso_lentidao_ui.js
node tests/test_alerta_entrega_ui.js
node tests/test_varredura_ui.js
node tests/test_servidor_offline.js
```
Run a single test with standard unittest selection, e.g. `python -m unittest tests.test_versao.TestParseVersion.test_x -v`.

- `test_numeros.py` / `test_mensagem_global.py` / `test_app_estado.py` (repo root of `msgweb/`) — humanized typing, message assembly, burst quotas, config reaching the sender.
- `tests/test_deduplication.py`, `tests/test_versao.py` — pure-logic regression tests (no Selenium, no browser).
- `tests/test_nav_retry.py` — navigation-failure retry semantics (must not double-send/double-attach on retry).
- `tests/test_chat_open_timeout.py` — the chat-open wait window: budget, poll frequency (cheap composer check vs. expensive popup/blocked scans), and that the extra attempts still never double-send. Also pins that the burst pacing estimate was deliberately left alone.
- `tests/test_sync_inicial.py` — session detection at startup: never claim "scan the QR Code" without a QR on screen, and wait for WhatsApp Web to finish syncing before the first message.
- `tests/test_load_contacts_falha.js` — `GET /contacts` failing must not leave a silently empty table, and must block saving (which would rewrite the sheet from an incomplete screen and resend already-delivered contacts).
- `tests/test_trava_durante_envio.py` / `tests/test_trava_config_ui.js` — config and global message are frozen while a send is running (backend refuses; UI disables), while `startSending()` can still persist them right before `/start`.
- `tests/test_chrome_perfil_em_uso.py` — starting with a Chrome already holding `chrome_profile/` must fail fast with an actionable message instead of spawning a window per chromedriver fallback.
- `tests/test_duplicado_vs_enviado.py` — an already-sent row is never shown as "Duplicado", and the send config survives a server restart.
- `tests/test_aviso_lentidao.py` / `tests/test_aviso_lentidao_ui.js` — the time estimate must count chat-opening (not just typing/attachments), and the slow-connection warning must fire on the failure rate without re-opening its popup on every status heartbeat.
- `tests/test_pane_lento.py` — the cold-start path: a slow (not stuck) WhatsApp Web must be *waited on*, never reloaded, and `_aquecer_navegacao` must gate the send on a real navigation without ever blocking it.
- `tests/test_execucao_interrompida.py` — a run killed mid-flight must be reported on the next startup, and the slow-connection warning must count app-load failures, not only chat-open ones.
- `tests/test_log_queda_conexao.py` — a network outage is recorded in the log (entry/exit, per-contact note, end-of-send summary) while deliberately keeping the contact marked invalid.
- `tests/test_seletores.py` — the remote-selector layer: the payload filter (only known keys, the type pinned by the embedded default, within size caps), the embedded/cache/Supabase fallback chain never becoming a hard dependency, the throttle on structural-failure refetches, and that no send-path selector is written literally in `whatsapp_sender.py` again.
- `tests/test_linha_conversa.py` — reading a chat-list row: the media-symbol exclusion (a sticker *they* sent must not read as our tick), unknown status icons falling to "not delivered", a broken extraction never being mistaken for "they replied", the draft guard (`None` icons ≠ `[]`), and where the reply text comes from.
- `tests/test_alerta_entrega.py` / `tests/test_alerta_entrega_ui.js` — the delivery alarm: it must not fire on freshly-sent messages (still-undelivered is normal right after sending), a reply always proves delivery, the popup opens once per `seq`, the pause-time read can never raise into the send loop or overrun the pause, and the popup's wording must stay the opposite of the slowness one (that says "keep going"; this says "stop").
- `tests/test_varredura.py` / `tests/test_varredura_ui.js` — the reply scan: scope is `Enviado=X` only (an invalid contact never had a delivery, and reading its row would attribute a previous campaign's state to this one), a conversation not found never becomes "didn't reply", no `Classe` column is ever written, "didn't deliver" stays a category of its own rather than collapsing into "cold", and `RespostaTexto` is written only when they actually replied (never our own outbound text).
- `tests/test_cache_pagina.py` / `tests/test_servidor_offline.js` — with the app closed, the page must not open from browser cache, and a failed `/license/status` must never be presented as an invalid license.
- `tests/*.js` — Node scripts exercising frontend SSE/tooltip behavior directly.

### End-to-end battery: HTTP in, spreadsheet out

```bash
pip install -r requirements-dev.txt      # adds httpx, for FastAPI's TestClient
python -m unittest tests.e2e.test_e2e_envio tests.e2e.test_e2e_varredura tests.e2e.test_isolamento_do_build -v
```

`tests/e2e/` drives the **real** app — FastAPI routes, `AppState`,
`WhatsAppSender`, burst planning, `contact_logic`, `varredura` — against a fake
WhatsApp Web, and asserts on the spreadsheet, which is the only artifact the
client reads. A whole campaign runs in about a second.

This is possible because the app touches Selenium through **five** methods
(`get`, `find_element`, `find_elements`, `execute_script`, `quit`) and reaches
the DOM through selectors that all come from `seletores.py`, and because
`start()` has a single seam: `self._driver = self._init_driver()`.

`fake_whatsapp.py` has **no CSS written in it** — it matches the string the app
asked for against `seletores.get(...)`/`lista(...)`, the same table production
reads. So the double cannot drift from the app, and an unrecognized query
returns empty, exactly as a real Chrome would for a selector that matches
nothing. What it models is the *contract* the app expects, not WhatsApp Web: it
will never catch a real DOM change (that is what the `sonda_*.js` probes and the
published selector table are for). It catches our own regressions — a contact
that should stay pending going invalid, a double send, an attachment sent
without its text, the reply scan writing on the wrong row.

`ambiente.py` swaps exactly three things, each for a different reason: the
driver; the **clock** (a campaign is a time budget measured in hours, so
`time.monotonic`/`time.time` read a virtual clock that only advances when
something sleeps — every deadline in the app still holds, the pacing logic is
untouched, and the run costs milliseconds); and the license plus the native
Windows dialog, which are resources outside the process. It deliberately does
*not* fake the global `AppState` — the app is one campaign per process, and
pretending otherwise would test an app that doesn't exist; each scenario gets a
fresh temp cwd with its own `uploads/`, which is what the real process has.

**None of this reaches the `.exe`**, and `tests/e2e/test_isolamento_do_build.py`
pins that: PyInstaller packs what is import-reachable from `launcher.py`, and
`build.bat` then hand-copies only `static/`, the LEIA-ME and a freshly generated
`uploads/modelo_contatos.xlsx`. The test walks the import graph statically from
`launcher.py` and fails if anything under `tests/` (or `testar.bat`,
`test_contatos.csv`, `gerar_planilha_teste.py`, a `sonda_*`) becomes reachable
or gets copied. The realistic way to break it is someone importing the double
from `whatsapp_sender.py` "just for a constant" — invisible in a diff, and the
client ships with the test harness.

The layer this battery does not replace: one real send to one real number. What
can be automated there is the setup and the spreadsheet check, never the verdict
that the message looked right on the phone.

Known pre-existing failures in `test_app_estado.py` (4): they assert config keys `msgs_por_rodada` / `total_rodadas` and a `human_behavior` default that the current schema no longer uses. Unrelated to any current work.

## Build / release

```bash
build.bat 1.2.0
```
`build.bat` bumps `version.py`, rebuilds the Tailwind CSS, runs PyInstaller, and regenerates `uploads/modelo_contatos.xlsx` via `gerar_planilha_modelo.py` (a clean single-test-contact sheet) instead of copying whatever is in the local `uploads/` — never ship a build with real contact data. The name is **not** `contatos.xlsx` on purpose: that is the client's live file, and until 1.4.7 the release overwrote it (see CHANGELOG 2026-09-23). At the end it builds the `gh release create` command itself from the version you passed in (no more retyping the version number by hand) and, if `gh` is on PATH, asks `Publicar release vX.Y.Z no GitHub agora? (s/N)` — answer `s` to publish immediately, or decline and it prints the ready-to-paste command:
```bash
gh release create v1.2.0 "dist\WhatsAppAutomacao-v1.2.0.zip" --title "v1.2.0" --notes-file CHANGELOG.md
```
Batch-file gotcha: keep this block (and any other `echo`/`if` text in `build.bat`) plain ASCII — no em dashes, no accented Portuguese characters. `cmd.exe` reads `.bat` files in the OEM codepage, not UTF-8; a non-ASCII byte inside an `echo` line (as opposed to a `::` comment, which is skipped unparsed) can corrupt parsing of an enclosing `if (...)` block and execute garbage. This bit us once when adding the release-publish step.

CSS: edit `static/tailwind.input.css`, then `npm run build:css` to regenerate `static/tailwind.css`. There is no JS build step — `static/index.html` is vanilla JS.

## Architecture

Single-process FastAPI backend + one static HTML/JS frontend, talking over REST plus one Server-Sent Events stream (`/events`). No database, no multi-session support: one running server manages exactly one campaign/sheet at a time via a single global `AppState`.

- `app.py` — FastAPI routes and the global `AppState` dataclass (current Excel path, `WhatsAppSender` instance, in-memory log ring buffer, SSE subscriber queues).
- `whatsapp_sender.py` — `WhatsAppSender`, the Selenium engine that drives a real Chrome window against web.whatsapp.com. Owns the send loop/state machine (`start()`), the burst/pacing planner (`_generate_burst_plan`, `_particiona_rajadas`), humanized typing (`_human_type`, `_paste_text`, `_type_budget`), attachment file-input discovery (`_find_all_file_inputs`, `_pick_file_input`), and popup/failure detection (invalid number, blocked contact, dead session).
- `contact_logic.py` — pure functions with no Selenium dependency, extracted from the sender specifically so validation/deduplication (`clean_number`, `validate_contact`, `get_pending_contacts`, `apply_deduplication`) can be unit-tested without a browser.
- `chrome_profile/` is a dedicated Chrome profile, and only one Chrome process can hold it. Launching a second Chrome with the same `--user-data-dir` makes that process hand off to the running one and exit, which surfaces as ChromeDriver's `session not created: Chrome instance exited`. `_init_driver()` checks for this before launching anything (`_pids_chrome_no_perfil()`) and raises `ChromeProfileInUseError`; the chromedriver fallback chain is only for a missing/incompatible driver and must not run for this error, or the user gets one stray Chrome window per fallback. The `Singleton*` lock files may only be deleted once no process holds the profile.
- `win_dialog.py` — Windows-only ctypes control of the native "Open File" dialog (`WM_SETTEXT`/`BM_CLICK`). Exists because Selenium cannot reach that dialog, and WhatsApp Web only sends images as inline photos through it (not as a generic file attach). No-ops on non-Windows.
- `seletores.py` — WhatsApp Web's CSS selectors as data instead of code, so a DOM change becomes a published row rather than a rebuild for every client. Three layers: bundled defaults (`PADRAO`) → on-disk cache (`uploads/seletores_cache.json`) → Supabase. Four invariants, each with a test: the cache is a **file**, never `localStorage` (the consumer is Selenium in Python; the UI's `localStorage` is invisible to the sender); it is never a hard dependency (any layer failing falls back, a send always runs); the remote payload carries **only selector strings** of already-known keys, validated by `_validar_payload` — never code; and `registrar_falha_estrutural()` refetches only for structural failures, throttled, because a per-contact failure says nothing about selectors.

  **Both halves of the app go through this layer, not just the reading half.** Until 2026-09-12 only the chat-list/varredura selectors were published; everything the *send* touches — above all `campo_mensagem` (`footer div[contenteditable='true']`), without which no message goes out at all — was written literally in `whatsapp_sender.py`. That inverted the risk: the cheap breakage was fixable by a table row, the expensive one needed a new `.exe`. Note the asymmetry that made it worth fixing: the composer is not only where the text is typed, it is also the proof that the conversation opened (`_wait_chat_or_invalid_popup`) and the proof that the message left (`_confirm_message_sent`, by going empty).

  Two shapes of value, and the **embedded default pins which one a key has**. Most keys are one string; `botao_anexar`, `botao_enviar_modal`, `campo_legenda_*` and `qr_canvas` are **lists tried in order** (first visible wins), read via `lista()` instead of `get()` — those are precisely the elements WhatsApp has already renamed more than once, and keeping the old names in the list is what carried the app through those changes without a release. A payload may not swap a key's type: the code picks `get()` or `lista()` per key, so letting the remote turn a string into a list would let it choose which code path runs. Comma-joined selectors (`modais`, `area_conversa`, …) stay single strings on purpose — one `querySelectorAll`, order irrelevant.

  `pane_side` was in the table since day one, but six other sites still had `"#pane-side"` typed out (and `_conversas_carregadas` re-typed the whole `linha_conversa` selector). Publishing a fix would have repaired one site out of seven while the log said "selectors updated" — worse than not having the layer. A test greps the sender for those literals now.

  The third structural trigger is **counted, never reported on the first timeout**: `_registrar_campo_mensagem_ausente()` fires only after `_FALHAS_CAMPO_PARA_ESTRUTURAL` (3) consecutive contacts whose composer never appeared, and the counter resets the moment it does appear. One contact that doesn't open is the ordinary invalid-number case — wiring it straight to a refetch is exactly what invariant 4 forbids. Three in a row, with `#pane-side` up, is not bad luck.

  Deliberately still literal: `footer`, a bare `div[contenteditable="true"]` fallback and the `button`/`div[role="button"]`/`li` sweep of the attach menu. Those are plain HTML shapes matched by *text*, not WhatsApp classes, so they don't break the way a `data-testid` does. Blocked-contact, offline and invalid-number detection are likewise decided by **text markers** (pt/en/es) with the selector only choosing where to look — they break on rewording, not on a class change, and a list of markers per language doesn't fit `_validar_payload`'s one-string-per-key rule.

  `linha_previa` and `busca_container` are in `PADRAO` but read by nobody; publishing a fix for them does nothing.
- `linha_conversa.py` — reads a chat-list row without opening the conversation (opening costs 41-58s and marks the message read). One `execute_script` extracts the whole list into plain dicts; interpretation is pure Python, testable without a browser. The status icon is the `<title>` inside the row's `<svg>`, under `[data-testid="last-msg-status"]` and **outside** `[data-testid="chat-msg-symbol"]` — that exclusion is mandatory, since a sticker *they* sent lives in the same place and would otherwise read as our own tick. State is decided by absence, plus two positive signals.

  **WhatsApp's icon names are offset from what they display** — measured in the field on 2026-09-08 (`sonda_cor_tique.js`, live transition on one contact) and confirmed by the client. Trusting the names is what this layer got wrong twice:

  - `wds-ic-delivered` is the **single ✓**: sent, *not* delivered. Despite the name. It falls into `NAO_ENTREGUE` via the absence rule — it is the plain ✓ this file used to say had never been captured.
  - `wds-ic-read` is the **double ✓✓**, covering delivered *and* read. Only the **colour** separates them: grey `rgba(0,0,0,.6)` vs blue `rgb(0,123,252)`, captured 11s apart on the same contact. `cor_de_leitura()` requires blue dominance over red — not just a high blue channel, because dark mode's grey is translucent *white*.

  Reading `wds-ic-delivered` as delivered was doubly harmful: it displayed "Entregue" for a message that never arrived, and it **silenced the delivery alarm**, whose entire purpose is spotting messages that leave and don't arrive. Only `NAO_ENTREGUE`/`FALHOU` feed that alarm.

  Claiming "read" is deliberately asymmetric: blue proves it, absence of blue proves nothing (read receipts can be off), so anything unproven falls back to `ENTREGUE` — true in both cases. The selector keys are therefore named after the **glyph** (`icone_tique_duplo`, `icone_falha`), never the state.

  The unread badge (`nao_lidas > 0`) outranks every icon: an unread count only exists for *received* messages, and sending opens the chat (clearing it), so on a row with `Enviado=X` any unread is a new message from them. This also fixed the row-matching bug where WhatsApp prepends "1 mensagem não lida" to the title element, which polluted digit extraction and made exactly the contacts who replied fail to match the sheet — `numero_do_titulo` now looks for a phone-shaped run, not loose digits.
- `varredura.py` — the on-demand reply scan (see above). Pure functions (`linhas_para_verificar`, `mapa_de_numeros`, `aplicar_leitura`, `latencia_segundos`) plus a thin `Varredura` class that drives an already-loaded driver; the Chrome lifecycle stays in `WhatsAppSender.verificar_respostas()`, which owns `_init_driver`, QR detection and sync waiting.
- `license.py` — Supabase-backed license check: machine-id binding plus a 3-day offline grace cache at `~/.whatsapp_automacao_license.json`. `/start` refuses to run without a valid license.
- `caminhos.py` — the single place that decides where the client's data lives (see below). Everything else asks it; nothing re-types a path.
- `launcher.py` — packaged-exe entry point (see above).

### An interrupted run is detected by a file, not inferred

`uploads/envio_em_andamento.json` is written when a send starts and deleted when
the sender thread ends by any expected path — completion, manual stop, error. If
it survives into the next startup, the process died mid-send, and
`_avisar_execucao_interrompida()` says so with the date and the pending count.
The point is not resumption (that already worked — the rows stay pending) but
telling the user, since the app also restores the previous run's config and
would silently apply e.g. "118 msgs in 240min" to the handful left over.

### Where the client's data lives (`caminhos.py`)

Every data path — `uploads/contatos.xlsx`, `uploads/media/`, `uploads/config.json`,
`uploads/seletores_cache.json`, `chrome_profile/`, `log.txt` — is resolved through
`caminhos.py`. **Never re-type one of them as a literal**; `tests/test_atualizacao_preserva_dados.py`
greps for exactly that, the same way `test_seletores.py` greps the sender for selectors.

Packaged, the root is `%LOCALAPPDATA%\WhatsAppAutomacao` (home as fallback, where
the license and the stats history already lived). It used to be the **install
folder**, because `launcher.py` does `os.chdir(os.path.dirname(sys.executable))`
and every path was relative to that — so extracting a new release over the folder
deleted the client's campaign, and the release shipped a factory
`uploads/contatos.xlsx` that then took its place. See CHANGELOG 2026-09-23.

**In development nothing changed, and that is the point.** `dados_dir()` returns
`Path(".")` when not frozen, and `Path(".") / "uploads"` is `Path("uploads")` —
the same **relative** path as before, resolved against the cwd at each access.
That is what keeps `testar.bat`, `test_app_estado.py` and above all
`tests/e2e/ambiente.py` working untouched: the e2e harness imports `app.py` once
and then `chdir`s into a fresh temp dir per scenario, so an absolute path computed
at import would pin every scenario to the first one. `WHATSAPP_AUTOMACAO_DADOS`
overrides everything and is how the packaged layout is tested without packaging.

`migrar_dados_legados()` copies an `uploads/` left in the install folder by an
older version out, once, never over anything already in the new location. It deliberately leaves
`chrome_profile/` behind — hundreds of MB of LevelDB from a possibly-live profile,
across volumes; half a copy is a corrupt profile, which is worse than none. The
cost is one more QR scan, on that upgrade only.

The build ships the model sheet as `uploads/modelo_contatos.xlsx`, never
`contatos.xlsx`: the old name collided with the client's live file. So a genuine
first run has **no sheet**, `GET /contacts` answers 404, and the page treats that
as first-run rather than a load failure — routing it through `setContactsLoadError`
would lock "Salvar Alterações" and block the one person it should help, someone
building the list from scratch with "Adicionar Contato". A 404 with rows already
on screen is still an error: that is the sheet vanishing mid-session.

### The Excel file is the only source of truth

The app always operates on `uploads/contatos.xlsx`, never on whatever file the user originally selected on disk. Both `/upload` and the in-browser contact editor (`POST /contacts`) overwrite this same file. `AppState.excel_source` records whether the current copy came from `"upload"`, `"editor"`, `"restaurada"` (restored across a restart), or `"cli"` — purely to let the UI warn the user which version is actually live, since editing the original `.xlsx` on disk has no effect without a new upload. Required columns are `Nome`, `Número`, `Mensagem`; control columns `Enviado`, `DataEnvio`, `Invalido`, `Motivo`, `Arquivo` are added on upload if missing and are what makes a send resumable across restarts.

### "Enviado" outranks "duplicado" in the UI

`GET /contacts` derives a `duplicado` flag for display, gated on
`config.allow_duplicates`. It must never set that flag on a row whose `Enviado`
is `X`: "sent" is a recorded fact, "duplicate" is a derived label that only says
something about rows still queued. The row still anchors detection for later
rows with the same number. Showing "Duplicado" on a sent row doesn't corrupt
what gets saved (the row's `dataset.enviado` keeps the real value), but it
invites the user to click the row's resend button (↺) to "fix" it — which clears
`Enviado` and re-queues a contact that already got the message.

Related: `state.config` is persisted to `uploads/config.json` and restored in
`startup_event` *before* the page can request contacts. Before that, a restarted
server answered `/contacts` with default config while the browser still held the
user's real settings in `localStorage`, so the two disagreed until the next
`POST /config`.

### Deduplication happens twice, by design

Once on `/upload` (silently drops duplicate pending rows before they're ever shown), and again live in `contact_logic.apply_deduplication` during a send (marks pending duplicates `Invalido` with a "duplicado" reason, so they're skipped but stay visible/distinct from real invalids). `allow_duplicates=True` in config is the "test mode" toggle: it disables both dedup passes and reactivates any row that was previously invalidated only for being a duplicate. All duplicate/number comparisons go through the same normalizer (`clean_number`): strips a leading `55` country code and fixes pandas reading numeric phone numbers as float (`"19994229146.0"` → `"19994229146"`).

### A network outage looks like a bad number, and only the log tells them apart

WhatsApp Web is a PWA: with the network down, the service worker still serves the
shell and IndexedDB still renders the chat list, so `#pane-side` is present. A
send during an outage therefore does *not* raise `WhatsAppNotLoadedError` (which
would leave the contact pending) — it times out waiting for the conversation and
the contact is marked **invalid**, same as a number that isn't on WhatsApp.

That outcome is intentional (the user re-checks via the row's ↺ button), so the
distinction lives entirely in the log: `_detect_sem_conexao()` (navigator.onLine
plus WhatsApp's own alert banner) runs alongside the other expensive checks, and
`_registrar_estado_de_conexao()` logs one line entering the disconnected state
and one leaving it. Contacts invalidated during an outage say so in their
`Motivo`, and `_log_resumo_de_conexao()` closes the run with the count. Don't
"simplify" this into a per-check log line — the whole point is one entry per
transition.

### The reply scan reads the chat list; it never opens a conversation

`varredura.py` + `WhatsAppSender.verificar_respostas()` implement the on-demand
scan behind the UI's "Verificar respostas" button. Opening a conversation costs
41-58s and marks the message read (the user loses the unread badge they work
from), so the scan filters the search box instead — filtering opens nothing. Two
passes: a free `execute_script` over the ~71 already-rendered rows, then a search
only for whoever is left.

Scope is the rows with `Enviado=X` in the current sheet. There is no "last N
days" setting: `/upload` overwrites `uploads/contatos.xlsx`, so the sheet already
*is* the campaign, and the number would just be one more thing for a lay user to
get wrong. Rows already marked `Respondeu=Sim` are skipped — nobody un-replies.

It writes **facts** (`Respondeu`, `DataResposta`, `Entrega`, `UltimaVerificacao`,
`RespostaTexto`) and never a label: hot/cold is derived in `GET /contacts` the way
`duplicado` already is, so changing where "hot" starts is a function change rather
than a re-scan. There is still no morno/warm bucket in the UI — telling it from hot
needs the reply's *content*, and a metadata rule cannot produce it (a one-word "sim"
is the hottest possible reply; "não tenho interesse" is four words).

`RespostaTexto` is that content, **stored but deliberately not displayed**: the scan
never revisits a row already marked `Respondeu=Sim` (`linhas_para_verificar`), so the
stored text is the *first* reply seen and is never refreshed. Latency is a fact that
cannot change and is shown; the reply text can change without the screen knowing, and
showing a stale one would misrepresent the conversation. The column still earns its
place, because for triage the first reply is the right one — it is the answer to the
campaign; anything later is a conversation a human is already having.

It is stored so the rule can change without re-scanning —
same reason `Entrega` is a stored fact and the label is derived. It comes free from
the same `execute_script` that reads the tick, and three things are load-bearing:

- **Only when `estado == ULTIMA_DELES`.** When the last message is *ours*, the same
  DOM field carries *our* text (the probe captured `'Show'`, `'Eu vim treinar'`),
  and storing it would make triage classify our own campaign as the contact's reply.
- **From the `title` of `last-msg-status`, never from `linha_previa`.** The probe
  (`sonda_texto_resposta.js`, 2026-09-12) measured both: the `title` arrives whole,
  not truncated (393 chars captured); `cell-frame-secondary` is `textContent`, so it
  absorbs the svg's `<title>` and the group-sender prefix — it yields
  `"wds-ic-readEu vim treinar"`. That is why `linha_previa` still has no consumer.
- **Media is a label, not content** (`"Foto"`, `"Figurinha"`, `"Mensagem apagada"`):
  still a reply, just nothing to triage. Text is capped at 500 chars.

It round-trips through `GET /contacts` → `dataset` → `POST /contacts` like the other
four, and is excluded from `/upload`'s `.str.upper()` alongside `Arquivo`/`Motivo` —
that normalization exists for `Enviado`/`Invalido` and would return the contact's
reply SHOUTING.

**Latency has two sizes of imprecision, and only one of them is unknowable.** The
row's timestamp is minute-granular (`13:17`), anchored at second 00, so a reply in
the same minute as the send computes as negative — measured at -9s on 2026-09-12,
which made `latencia_segundos` return `None` for the fastest reply in the campaign
and sort it to the *bottom* of the latency order, among the unknowns. A negative
smaller than `GRANULARIDADE_HORARIO_SEG` (60) now yields `0`: the reply landed in
the same minute, so "under a minute" is proven, not guessed. A larger negative is
the "Ontem"-anchored-at-midnight case, where the error reaches 24h, and stays
`None`. The cell renders `< 1 min` (the long form is 85.5px against 72px of usable
width in an 80px `whitespace-nowrap` column); `latenciaPorExtenso` carries the full
wording into the tooltip.

Silence beats invention throughout: a conversation not found writes nothing (it
may be a saved contact, whose row shows a name and no number), an unknown
timestamp leaves `DataResposta` blank, and `INDETERMINADO` never overwrites a
good earlier reading.

The same principle covers the **draft guard**. A row with a draft (typed, unsent
text) has no `last-msg-status` element at all, so the absence rule concluded "the
last message is theirs" and wrote `Respondeu=Sim` for a contact who never replied —
and that state is reachable in a real campaign, since a send interrupted between
`_human_type` and `_confirm_message_sent` leaves the typed text as a draft. The JS
now returns `null` (no status element = no evidence) as distinct from `[]` (element
present, no tick = their message), and `None` already falls to `INDETERMINADO`. The
unread badge still outranks it: a chat can hold a draft *and* a new message.

**"Not found" gets one retry, and its own log line.** A conversation missing from
both passes is searched again once after `PAUSA_RETENTATIVA_SEG` (20s), because
"not found" and "WhatsApp Web hasn't synced yet" are the same thing from outside —
and the scan opens a Chrome and starts searching ~15s later. Measured on
2026-09-12: a conversation created by a send five minutes earlier was in neither
the rendered list nor the search index, and two consecutive scans each burned the
full `TIMEOUT_BUSCA_SEG` and wrote nothing (the same run showed `ic-schedule`, the
clock, on an already-sent message — the list was cold). The same cold-start lesson
`_aquecer_navegacao` encodes for the send path, paid the cheap way: only the
missing ones wait, never the ones the free pass already resolved. One retry, not a
loop — past that the conversation genuinely isn't there. The pause honours Stop,
and contacts never reached because of a Stop are not counted as "not found".

Not-found is the **only outcome that writes nothing at all**, so its row is
indistinguishable from a never-scanned one (both render `-`). `_log_nao_encontrado()`
therefore records the number, the attempt and what the search returned, to the file
log — diagnosing one occurrence otherwise cost six probes against live WhatsApp Web.

**A contact saved in the address book has no number in its row**, and every
sheet-to-list match used to be by number. Their row shows the *name*, so
`numero_do_titulo` returns `""` (correct, and always documented) and the contact
fell through both passes into "not found" — the one outcome that writes nothing,
rendering as the same `-` as a never-scanned row. The same root cause silently
kept them out of the delivery alarm's *sample* in `_absorver_leitura_de_entrega`,
and a list of mostly-saved contacts could therefore never reach
`_ENTREGA_AMOSTRA_MINIMA` and mute the alarm entirely.

The name is a **fallback match, never an identifier**: two "João Silva" in the
sheet are two people and the chat list cannot tell them apart, so a name only
counts when it identifies exactly one contact on *both* sides — ambiguity in
either direction (one name on two rows, one row matching two names) returns the
contact to "not found", which is the previous behavior. `titulo_casa_com_nome`
accepts the name at the *end* of the title only when what precedes it starts
with a digit: the unread announcement is prepended into the same element with no
space (`"1 mensagem não lidaIsis Campos"`) — the same poison that broke number
extraction, hitting exactly the contacts who replied. Without that guard "Ana"
would match "Mariana".

In the search pass the stronger proof is the filter itself: we typed the number,
so if exactly one conversation survives the filter and it doesn't display some
*other* number, it is theirs — that is what covers the sheet and the address book
spelling the name differently. `_buscar` also exits once the filter settles on a
single row (same reading twice in a row), since its only exit condition was "a
row with the number appeared", which never happens for a saved contact and cost
`TIMEOUT_BUSCA_SEG` each.

The scan has its own `is_varrendo()` flag rather than reusing `is_running()`,
which means "is sending" and is what freezes config and contacts. But both hold
the same `chrome_profile/` and both write the same sheet, so `/start` and
`_recusar_se_enviando()` refuse in both directions.

### A closed server must not read as a lost license

The page is served with `Cache-Control: no-store` (`serve_frontend` in `app.py`)
so the browser cannot render the app shell with nothing behind it — opening it
with the program closed gives the browser's own connection error. On top of
that, `checkLicense()` in `static/index.html` splits three cases that used to
share one `catch`: a network error opens `#offline-overlay` ("the program isn't
running, your license is still active"), which retries every 3s and reloads the
page once the server answers; an HTTP 500 still asks for the key but says the
check failed on the server; only `valida: false` is presented as an invalid
license. The offline overlay is deliberately a separate element from
`#license-overlay` — merging the two messages is the bug this exists to prevent.

### Two different alarms: slowness costs time, non-delivery costs the account

`_registrar_resultado_de_abertura` (slowness) and `_avaliar_alarme_de_entrega`
(delivery) look alike — both ride inside `get_status()` with a `seq` so the popup
opens once — but they must never be merged, and their popups say opposite things.
Slowness is a chat that won't open: it costs wall-clock, and the popup explicitly
says the send continues. Delivery is the message *leaving and not arriving*, the
signature of the number being rate-limited by WhatsApp; there the popup's primary
action is Stop, because continuing risks the client's account. A refactor that
unifies the wording is the failure this feature exists to prevent — `tests/test_alerta_entrega_ui.js`
pins the distinction.

The delivery read happens in `_verificar_entregas_na_pausa`, during the
inter-burst pause, which is idle by construction (90-275s for 118 msgs/240min).
Messaging a chat bumps it to the top of `#pane-side`, so the burst's contacts are
the first rows already rendered: one `execute_script`, no interaction — typing
into the search box would replace the human behavior the pause exists to simulate.
Three rules: it is wrapped so no exception can reach the send loop, it abandons
its result if it overruns its slice of the pause (overrunning delays the next
burst and breaks the total time promised to the user), and it checks
`_should_stop()` so Stop stays responsive. It deliberately does **not** feed
`_registrar_resultado_de_abertura` — that time is ours, not WhatsApp's, and would
make the slowness warning fire on our own code.

Only contacts with a completed send enter the sample (`_registrar_envio_para_entrega`),
never invalid ones: an invalid contact never had a delivery (`AttachmentError`
does not send the text, `WhatsAppNotLoadedError` precedes any delivery), and
reading its row would attribute a previous campaign's conversation state to this
one. `_ENTREGA_IDADE_MINIMA_SEG` exists because "not yet delivered" is the normal
state right after sending — without it every run would fire a false alarm.

### Sending pace: burst planning, not a fixed interval

### A cold WhatsApp Web is the single biggest predictor of failure

Failure rate tracks one variable: how long WhatsApp Web has been up. Measured
across the client's logs — 50%/43%/67% in the first 20 minutes of runs started
right after launching the app, against 5-8% throughout a run begun with the
browser already warm for two hours, on a *larger* batch.

`_aguardar_sincronizacao` was supposed to gate this and cannot: it waits for the
chat list to stop growing for 6s, but after a night offline that list is
restored instantly from IndexedDB, so it is stable from the first poll. It
logged the identical verdict ("67 conversa(s), estável por 6s", within 10-15s)
in every single session, healthy and catastrophic alike. Don't trust it as a
readiness signal, and don't "simplify" `_aquecer_navegacao()` into it.

`_aquecer_navegacao()` gates on the gesture the send actually performs — a
`driver.get` plus the `#pane-side` wait — and re-measures until it is fast or it
gives up. It must never block the send (a chronically slow machine still sends,
with a warning), must run before `_envio_iniciado_em` so its time doesn't enter
the reported duration or the burst plan, and must navigate to plain
`web.whatsapp.com` — a `send?phone=` URL would open and mark read some contact's
conversation nobody asked to open.

Related, in the navigation retry: when `#pane-side` doesn't appear, the middle
attempts **wait without renavigating**. Reloading discards the in-flight load
and restarts the WhatsApp Web boot from zero, which is the opposite of what a
merely-slow page needs (the log shows three stacked boots: 65s, 61s, 61s, back
to back). Only the final attempt reloads, for a page that is stuck rather than
slow. A chat-open failure is the opposite case — the app is up, so reopening is
the right remedy — and it keeps its backoff.

### The configured time is a total, and most of it is not pauses

The estimate (`_estimar_tempo_envio_individual` → `_calcular_orcamento_de_pausas`
→ `/estimate`) exists so the user is told *before* starting that their window
doesn't fit. It must count the chat-opening cost
(`TEMPO_ESTIMADO_ABERTURA_CHAT`), not just typing and attachments: opening the
conversation is the single largest component of a send (41-58s measured, vs.
~25s of typing), and leaving it out made the app predict 45min for a run that
took 2h. It is added in both typing modes — `driver.get` and the `#pane-side`
wait happen either way.

What the estimate *cannot* know upfront is failures. A contact whose chat never
opens costs ~3.7min and, by the deliberate invariant that an invalid contact
doesn't consume a burst slot, the burst pulls in a replacement — so a bad
network stretches the wall clock without changing the plan. That is what
`_registrar_resultado_de_abertura()` watches: past 6 navigation attempts with a
≥30% failure rate it arms `alerta_lentidao`, which the UI shows as a popup.

It counts **both** ways a contact can fail in the navigation phase, and they are
not interchangeable: `tipo="chat"` (the app is up, the conversation didn't open)
marks the contact invalid and the ↺ button recovers it, while `tipo="app"`
(`#pane-side` never appeared) leaves it **pending** with nothing to resend.
Counting only the first left the warning silent in the worst run on record — 4
successes, 1 chat failure and 3 app failures read as 1-in-5, under the
threshold. The popup drops the ↺ hint for `tipo="app"` for the same reason.

The warning rides inside `get_status()` rather than being its own SSE event, so
it survives an F5 or an SSE drop during a multi-hour send. Its `seq` field (the
failure count when it was armed) is what makes the popup open once — status is
re-broadcast every 5s, so without it the popup would reopen forever, including
right after the user closes it. Only attempts that actually reached the
navigation phase count: a blank number or a duplicate says nothing about the
network.

`_generate_burst_plan` / `_particiona_rajadas` split a requested "N messages in M minutes" into irregular bursts with pauses between them. The plan is generated **after** deduplication, sized to real pending contacts rather than the requested count, and a message that fails validation does not consume a burst slot — `CHANGELOG.md` documents the historical bugs behind each of these invariants. The `pausado` sender state covers both business-hours waiting and inter-burst pauses; don't treat it as an error state when reading `/status`.

### Nothing that feeds a running send may change mid-send

`AppState.config` and `AppState.global_message` are read by the sender on *every*
contact, not snapshotted at `/start`. So accepting a write to them mid-send
silently changes the pace — or the message text — of the contacts still queued.
`POST /config`, `POST /global-message`, `POST /global-attachment` and `POST /contacts` all reject with 400
while `sender.is_running()` (helper `_recusar_se_enviando()` in `app.py`); note
that `is_running()` is also true in the `pausado` state, which is deliberate.
The UI lock (`lockSettingsEditing` / `lockContactsEditing`) is a convenience on
top of that, never the guarantee — `toggleGlobalMessage()` fires a `POST
/global-message` on page load while restoring the toggle from `localStorage`,
so a plain refresh mid-send used to rewrite the global message on its own.

### The global message is a package: text + attachment

One trigger, and it is the **`Mensagem` column being blank**. The global
attachment has no trigger of its own — it rides with the global message. A
contact who wrote their own message gets neither the global text nor the global
attachment. `WhatsAppSender._resolver_globais()` decides it, and it has **two**
consumers that must agree: the send loop and the time estimate.

- **A package with no text is valid.** An empty global message with an
  attachment sends just the file. That is why `validate_contact` takes
  `arquivo`: it used to reject "mensagem vazia" before ever looking at the
  attachment, so an image-only campaign became a list of invalids. `_send_message`
  also skips Passo 2 when there is no text — an ENTER on an empty composer
  produces no message and, at worst, is a keystroke nobody asked for.
- **The contact's own file beats the package's.** A filled `Arquivo` is an
  explicit per-row choice, even when that row's text comes from the global.
- **Turning off the global message turns off the attachment.**
  `_anexo_global_ativo()` requires both active; the UI does it too, but the UI is
  never the guarantee. The file **path** survives on purpose — re-enabling must
  not make the user pick the file again.

The estimate is not optional here. With the attachment on, every blank-message
contact has one — the most expensive part of a send after opening the chat — so
an estimate reading the columns raw would promise a time the send cannot keep
(the 2026-09-06 bug: predicted 45min for a 2h run).

In the UI the attachment lives **inside** the Mensagem Global `<details>`, not in
a section of its own, and its state derives from the message's
(`aplicarEstadoMensagemGlobal` calls `aplicarEstadoAnexoGlobal`) so every path
that touches one updates the other. The row's pin says what that contact will
actually get — "Mensagem global + anexo", or "Anexo global" when there is no
text; saying only "mensagem global" would hide half of what goes out, and all of
it in the text-less case.

### The message field must be empty before attaching

WhatsApp Web promotes whatever is in the composer into the **caption of the
attachment modal**. So a leftover draft rides out with the file, to a contact who
should never have received it (reported in testing, 2026-09-23).

`_clear_input_field` already existed but ran in **Passo 2**, after the attachment
had been sent — it protected the typing, not the attachment. Nothing on the
attachment path touched that field: `_type_caption_in_modal` is never called
(`all_images` is a hardcoded `False`), so the modal is sent by
`_finalizar_envio_de_anexo`, which clicks send without looking at the caption.

`_exigir_campo_vazio_antes_do_anexo()` now runs before any attachment, and
raising `AttachmentError` when it cannot empty the field is deliberate: an
invalid contact is recoverable with the ↺ button, sending someone's contact the
wrong text is not. A draft there is not exotic — a send interrupted between
`_human_type` and `_confirm_message_sent` leaves exactly that behind (the same
state the reply scan's draft guard exists for).

### Real-time UI updates

The frontend has no client-side polling loop for logs/status — `GET /events` (SSE) pushes `status` (on-demand plus a 5s heartbeat) and `contact_update` events. Contacts are identified to the frontend by `row_index` (position in the sheet), never by phone number — a blank or repeated number must never be used as a row key (`tests/test_contact_update_backend.py` guards this regression).

### Security constraints that must not regress

- Server must bind to `127.0.0.1` only, in both `app.py` (`__main__` block) and `launcher.py`. Binding `0.0.0.0` exposes the contact list, sends, and log download to anyone on the same network with no authentication (this happened once — see `CHANGELOG.md`, 2026-08-16).
- `/upload-media` and `DELETE /media/{filename}` must resolve the final filename against `uploads/media/` and reject anything that resolves outside it — don't reintroduce a raw `file.filename` path join (path traversal).
- `escapeHtml()` in `static/index.html` must keep escaping `"` and `'`, not just
  what `textContent`→`innerHTML` handles. Nearly every call site interpolates into
  an attribute (`title="..."`), and a raw double quote there closes the attribute
  so the rest becomes markup. `pessoa` and `motivo` go through it, and they come
  from the sheet — which was not necessarily typed by whoever is running the app.
- Version comparisons in `/check-update` must go through `_parse_version()` (numeric tuple compare), never a plain string compare — `"1.10.0" > "1.9.0"` is `False` lexicographically, which silently breaks the update notice.

## Notes for changes

- `msgweb/CHANGELOG.md` documents recent bug fixes in narrative form (root cause + fix). Read it before touching pacing, deduplication, or the invalid/duplicate tooltip logic — several non-obvious invariants (e.g. "burst slots aren't consumed by invalid contacts", "duplicate ≠ invalid for tooltip/count purposes") are explained there rather than in code comments.
