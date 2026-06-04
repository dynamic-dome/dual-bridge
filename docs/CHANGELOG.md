# Changelog

Alle nennenswerten Änderungen an **dual-bridge** werden hier dokumentiert.

Format angelehnt an [Keep a Changelog](https://keepachangelog.com/de/1.1.0/).
Das Projekt nutzt noch keine SemVer-Tags; gruppiert wird daher nach Datum und Feature-Stufe.
Commit-Hashes verweisen auf `main`.

## [Unreleased]

### Hinzugefuegt
- **Projekt-Skelett:** `AGENTS.md` als kurze Agenten-Laufzeitdatei und
  `docs/PROJECT.md` als Projektsteckbrief ergaenzt.

### Geplant
- **Echte Verteilung (späterer Scope):** dateibasierter Transport → HTTP-Job-Pull
  mit demselben Claim-Mechanismus.
- **DCO-Anbindung (späterer Scope):** Notifier und Overnight-Scheduler sind
  DCO-ready gekapselt; die zentrale Orchestrierung über die `todos.db` ist noch
  nicht verdrahtet.

## 2026-06-03

### Hinzugefügt
- **Overnight-Scheduler** (`scripts/bridge_overnight.py`): arbeitet eine Queue
  vordefinierter goal-loop-Seeds (`docs/overnight/*.md`) nachts seriell ab und
  sendet morgens **einen** Telegram-Digest (accepted/eskaliert/Fehler).
  Lokal getriggert (Windows-Task via `register_overnight.ps1`, täglich 02:00),
  read-mostly (schreibt nur `state/_overnight/runs/<stamp>.json`), fail-soft je Seed
  (ein Fehler bricht den Batch nicht ab), fail-closed bei Fehlkonfig (nicht-leere
  Queue ohne `--repo` → Exit 2). Exit-Mapping aus dem loop_driver-Contract
  (0=accepted, 3=escalated, 2/1=error). DCO-ready: Kernlogik in `run_overnight()`
  mit injizierbarer `run_fn`. Digest baut/sendet `bridge_notify.send_overnight_digest()`.
  9 neue Tests; Queue-Doku unter `docs/overnight/README.md`.
- **Eskalations-Notifier** (`scripts/bridge_notify.py`, `789488f`): benachrichtigt
  per Telegram bei neuen `ESCALATION-<id>.md`. Lokal getriggert (Windows-Task via
  `register_notify.ps1`), idempotent (Dedup je `loop_id` über
  `state/_notify/sent.json`), at-least-once (Sendefehler markiert nicht). Read-only
  auf Eskalationen — schreibt nur den eigenen Sidecar-State. DCO-ready: Kernlogik in
  `notify_new_escalations()`, nur der Caller ändert sich. Optionaler `--digest`
  (default off), `--dry-run`, `--reconcile`. Credentials mit DCO geteilt
  (`TELEGRAM_TOKEN`/`TELEGRAM_CHAT_ID`, `DUAL_BRIDGE_TG_*` als Override).
  12 neue Tests (Telegram gemockt, State isoliert).
- **Read-only Status-Dashboard** (`scripts/bridge_status.py`, `1db5047`):
  Tasks/Loops/Eskalationen/`_errors/`-Quarantäne/Poller-Liveness je Lane, text+json,
  `--watch`. Schreibt nie.
- **Eigener Tunnel-B** (`9473450`): separater Cloudflare-Tunnel auf B mit
  on/off/status-Schalter und RESULT-Handoff an A; B-seitiges Handoff-Doc (`8e469db`).
- **Poller-Filesystem-Wakeup** (`574e826`): Poller wacht auf Bridge-Outbox-Events auf
  (`watchdog` wenn installiert, Intervall-Poll als Fallback).

### Geändert
- **README.md / HOW-TO-USE.md** (`f97eac6`, `789488f`): auf Stufe 3 + Dashboard +
  Notifier nachgezogen; Env-Vars-Tabelle um `TELEGRAM_TOKEN`/`TELEGRAM_CHAT_ID` und
  `DUAL_BRIDGE_TG_*`-Overrides ergänzt; Teststand aktualisiert.

### Behoben
- **`--repo`-Validierung vor Lock** (`9a11065`): `--repo` wird vor dem Lock geprüft;
  Sandbox-Regressionstest ergänzt.
- **codex-0.136 NDJSON-Sequenz gepinnt** (`00e5fec`, DCO #7729): Parser-Test gegen
  echte codex-Ausgabe — latenter Bug, der durch `-o answer.txt` maskiert war.
- **Flaky Lock-Test isoliert** (`57e6318`, DCO #7728): Singleton-Lock je Test
  isoliert (`test_main_goal_loop_requires_repo`).

## 2026-06-02

### Hinzugefügt
- **Goal-Loop (Stufe 3)** (`2d046a2`, `2318393`, `e26ed02`): freier Goal-Loop mit
  offenem Ziel + Done-Kriterien. CLI `--mode goal-loop` + `--resume` mit
  trigger-bewusster Validierung; deny-first Diff-Scan eskaliert gefährliche Aktionen
  vor dem Review; Stagnation und `max-rounds` eskalieren mit Kontext.
- **Tier-1 Quick-Wins gehärtet** (`eda101c`): Env-Allowlist für Subprozesse,
  robuster codex-NDJSON-Parser, UTF-8/OEM-Encoding-Fixes.
- **Live-Proof-Material** (`fe378e4`, `a16c698`): Seed + B-Pickup-Guide für den
  cross-device Live-Beweis (beide Pfade + Reseed-Resume bis `accepted`).

### Behoben
- **Eskalations-Grund-Fallback** (`9a95f79`): fällt auf das Reviewer-Payload zurück,
  wenn kein expliziter Grund vorliegt.
- **Ehrliche Eskalations-Kriterien** (`d7f2be2`): leerer Grund gilt nicht als
  Stagnation; Kriterienliste ehrlich gehalten.
- **Endpoint-Labels korrigiert** (`dbf9a81`): gerätebasiert (`@laptop-a`/`@laptop-b`),
  nicht rollenbasiert, im Stage-3-Pickup.

### Tests
- Drift-Guard für gespiegelte Secret-Sweep-Patterns (`06f2235`); Standard-JSONL-
  Completion-Sequenz abgedeckt (`f6765d8`).
