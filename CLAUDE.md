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

## Tests

```bash
venv\Scripts\python.exe -m unittest test_numeros test_mensagem_global test_app_estado -v
python -m unittest tests.test_versao -v
python tests/test_contact_update_backend.py
python -m unittest tests.test_chat_open_timeout tests.test_sync_inicial tests.test_trava_durante_envio tests.test_chrome_perfil_em_uso tests.test_duplicado_vs_enviado tests.test_log_queda_conexao tests.test_aviso_lentidao tests.test_pane_lento tests.test_execucao_interrompida -v
python tests/test_deduplication.py
python tests/test_nav_retry.py
python tests/test_win_dialog.py      # opens a real Windows file dialog — Windows only
node tests/test_contact_update.js
node tests/test_log_tooltip.js
node tests/test_load_contacts_falha.js
node tests/test_trava_config_ui.js
node tests/test_aviso_lentidao_ui.js
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
- `tests/*.js` — Node scripts exercising frontend SSE/tooltip behavior directly.

## Build / release

```bash
build.bat 1.2.0
```
`build.bat` bumps `version.py`, rebuilds the Tailwind CSS, runs PyInstaller, and regenerates `uploads/contatos.xlsx` via `gerar_planilha_modelo.py` (a clean single-test-contact sheet) instead of copying whatever is in the local `uploads/` — never ship a build with real contact data. At the end it builds the `gh release create` command itself from the version you passed in (no more retyping the version number by hand) and, if `gh` is on PATH, asks `Publicar release vX.Y.Z no GitHub agora? (s/N)` — answer `s` to publish immediately, or decline and it prints the ready-to-paste command:
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
- `license.py` — Supabase-backed license check: machine-id binding plus a 3-day offline grace cache at `~/.whatsapp_automacao_license.json`. `/start` refuses to run without a valid license.
- `launcher.py` — packaged-exe entry point (see above).

### An interrupted run is detected by a file, not inferred

`uploads/envio_em_andamento.json` is written when a send starts and deleted when
the sender thread ends by any expected path — completion, manual stop, error. If
it survives into the next startup, the process died mid-send, and
`_avisar_execucao_interrompida()` says so with the date and the pending count.
The point is not resumption (that already worked — the rows stay pending) but
telling the user, since the app also restores the previous run's config and
would silently apply e.g. "118 msgs in 240min" to the handful left over.

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
`POST /config`, `POST /global-message` and `POST /contacts` all reject with 400
while `sender.is_running()` (helper `_recusar_se_enviando()` in `app.py`); note
that `is_running()` is also true in the `pausado` state, which is deliberate.
The UI lock (`lockSettingsEditing` / `lockContactsEditing`) is a convenience on
top of that, never the guarantee — `toggleGlobalMessage()` fires a `POST
/global-message` on page load while restoring the toggle from `localStorage`,
so a plain refresh mid-send used to rewrite the global message on its own.

### Real-time UI updates

The frontend has no client-side polling loop for logs/status — `GET /events` (SSE) pushes `status` (on-demand plus a 5s heartbeat) and `contact_update` events. Contacts are identified to the frontend by `row_index` (position in the sheet), never by phone number — a blank or repeated number must never be used as a row key (`tests/test_contact_update_backend.py` guards this regression).

### Security constraints that must not regress

- Server must bind to `127.0.0.1` only, in both `app.py` (`__main__` block) and `launcher.py`. Binding `0.0.0.0` exposes the contact list, sends, and log download to anyone on the same network with no authentication (this happened once — see `CHANGELOG.md`, 2026-08-16).
- `/upload-media` and `DELETE /media/{filename}` must resolve the final filename against `uploads/media/` and reject anything that resolves outside it — don't reintroduce a raw `file.filename` path join (path traversal).
- Version comparisons in `/check-update` must go through `_parse_version()` (numeric tuple compare), never a plain string compare — `"1.10.0" > "1.9.0"` is `False` lexicographically, which silently breaks the update notice.

## Notes for changes

- `msgweb/CHANGELOG.md` documents recent bug fixes in narrative form (root cause + fix). Read it before touching pacing, deduplication, or the invalid/duplicate tooltip logic — several non-obvious invariants (e.g. "burst slots aren't consumed by invalid contacts", "duplicate ≠ invalid for tooltip/count purposes") are explained there rather than in code comments.
