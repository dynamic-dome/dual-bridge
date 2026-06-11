# Changelog

Alle nennenswerten Änderungen an **dual-bridge** werden hier dokumentiert.

Format angelehnt an [Keep a Changelog](https://keepachangelog.com/de/1.1.0/).
Das Projekt nutzt noch keine SemVer-Tags; gruppiert wird daher nach Datum und Feature-Stufe.
Commit-Hashes verweisen auf `main`.

## [Unreleased]

### Behoben
- **Mojibake im Result-/Verdikt-Text behoben (`scripts/job_poll.py` +
  `scripts/bridge_overnight.py`, 2026-06-06):** `_real_run_fn` rief
  `subprocess.run`/`Popen` mit `text=True`, aber ohne `encoding="utf-8"` auf.
  `loop_driver` gibt UTF-8 aus (z.B. den em-dash `—` = `E2 80 94`); ohne
  expliziten Encoding-Pin dekodiert `text=True` auf Windows mit der Locale
  (CP1252) zu `â€"`. Dieser Text ging als JSON an den DCO und erschien dort
  doppelt-kodiert im Verdikt (`ESKALIERT (stagnation) â€" siehe …`). Fix: beide
  Subprozess-Aufrufe in beiden Modulen mit `encoding="utf-8", errors="replace"`.
  3 Regressionstests (job_poll: run + Popen, bridge_overnight: run). Greift fuer
  alle neuen Jobs; bestehende DB-Verdikte bleiben unveraendert. (CLAUDE.md §10)
- **Reviewer-Watchdog Default-Endpoint korrigiert (`scripts/register_watchdog.ps1`,
  2026-06-04, live gefunden):** Der Default-Endpoint war faelschlich
  `codex@laptop-b`. Der Reviewer-Knoten laeuft aber auf Laptop A und muss aus der
  Lane `B-to-A` lesen, wo der Builder (B) seine `kind:review`-Tasks ablegt. Mit dem
  falschen Default pollte der Reviewer die Lane `A-to-B`: B's Review-Tasks blieben
  liegen, und ein zweiter (B-seitiger) Poller mit gleichem Endpoint kollidierte um
  dieselben Tasks (sichtbar als wechselseitige `P0-Recovery: ... requeued (open)`
  und `Result ... existiert bereits - anderer Claim gewann`). Fix: Default auf
  `claude@laptop-a`; `-Endpoint codex@laptop-b` bleibt als dokumentierter Sonderfall
  (Reviewer auf B) erhalten. Reine Default-/Doku-Korrektur, kein Logikpfad geaendert.
- **HttpSource-Client gegen Cloudflare + nicht-JSON-Antworten gehaertet
  (`bridge_transport.py`, 2026-06-04, live gefunden):** Der B-Worker crashte beim
  ersten echten Tunnel-Poll mit `JSONDecodeError`. Zwei Ursachen: (1) Cloudflare
  blockte den stdlib-Default-User-Agent (`Python-urllib/X`) mit `403 "error code:
  1010"`; (2) `_urllib_client` warf `json.loads()` blind auf den `text/plain`-
  Fehlerbody. Fix: expliziter `User-Agent` + `_safe_json()` (Parse-Fehler ->
  `None` statt Crash, sowohl im OK- als auch im HTTPError-Pfad). 4 neue Tests
  fuer den vorher ungetesteten (`pragma: no cover`) Netz-Pfad; live gegen den
  echten Tunnel verifiziert (204 + voller claim->completed-Durchstich).

### Hinzugefuegt
- **Bridge-Metriken (`scripts/bridge_metrics.py`, 2026-06-11):** neues strikt
  read-only Modul `compute_metrics(lane=None)` ueber die `_processed/`-Archive.
  Paart `task-*.md` und `result-*.md` je Lane, zaehlt Result-`verdict`-Werte und
  berechnet Durchlaufzeiten aus `task.created` bis `result.created` bzw.
  `claimed_at` (min/median/max). Kaputte/halbe Dateien werden fail-soft
  uebersprungen. CLI: `python bridge_metrics.py [--format text|json]
  [--lane <lane>]`; `write_report(path)` schreibt nur unter lokalem `state/`
  bzw. `DUAL_BRIDGE_STATE`.
- **Lane-Health-Check (`scripts/bridge_health.py`, 2026-06-11):** neues strikt
  read-only Modul `check_lane_health(now=None, max_age_s=..., max_errors=...)`
  auf Basis der bestehenden `bridge_status.scan_lane()`-Logik. Zaehlt offene und
  geclaimte Tasks sowie `_errors/` je Lane, meldet ueberalterte aelteste offene
  Tasks oder zu viele `_errors/`, rendert text/json und beendet mit Exit 1 bei
  Findings. Schwellwerte sind optional per Parameter, `config.json` oder Env
  konfigurierbar; keine Telegram-Sendung in diesem Schritt.
- **HTTP-Worker-Poll-Loop (`scripts/job_poll.py`, 2026-06-04):** der fehlende
  Daemon, der den DCO-Job-Pull tatsaechlich anschmeisst. Holt ueber
  `bridge_transport.get_source()` (`DUAL_BRIDGE_TRANSPORT=http`) einen Job aus dem
  DCO, arbeitet ihn ueber `loop_driver.py --mode goal-loop` ab (Run-Pfad identisch
  zum Overnight-Scheduler) und meldet via `source.publish_result` zurueck.
  `result_status=None` — der DCO `_EXIT_MAP` ist Single Source of Truth fuer
  rc->Status. `parse_input_text` spiegelt den DCO-Parser `parse_seed_line` (fehlt
  `repo=` -> rc 2 statt Wurf). Eigener Singleton-Lock (`dual-bridge-jobpoll.lock`),
  fail-soft (run-Crash -> rc 1, `publish_result` im `finally` garantiert, kein
  stranded Job). CLI: `--once | --watch [--interval N]`. 17 Tests (TDD), kein Netz/
  Subprozess/Repo im Test (injizierter HTTP-Client + run_fn). Schliesst die
  "Echte Verteilung"-Luecke unten. `handoff_poll.py` bleibt unberuehrt.
- **Projekt-Skelett:** `AGENTS.md` als kurze Agenten-Laufzeitdatei und
  `docs/PROJECT.md` als Projektsteckbrief ergaenzt.

### Geplant
- **Echte Verteilung (späterer Scope):** dateibasierter Transport → HTTP-Job-Pull
  mit demselben Claim-Mechanismus.
- **DCO-Anbindung (späterer Scope):** Notifier und Overnight-Scheduler sind
  DCO-ready gekapselt; die zentrale Orchestrierung über die `todos.db` ist noch
  nicht verdrahtet.

## 2026-06-04

### Hinzugefügt
- **Transport-Abstraktion** (`scripts/bridge_transport.py`): entkoppelt den Worker
  von der Herkunft eines Jobs. `Source`-Vertrag mit `claim_next() -> WorkItem` und
  `publish_result()`; zwei Implementierungen — `FileSource` (kapselt die heutige
  Lane/Datei-Welt, Claim via `bc.claim_task`/`os.rename`) und `HttpSource`
  (DCO-Job-Pull: `GET /jobs/next`, `POST /jobs/<id>/result`, Bearer-Token, injizier-
  barer HTTP-Client → kein Netz im Test). Treiberwahl per `DUAL_BRIDGE_TRANSPORT`
  (Default `file`), **fail-closed** (http ohne `DCO_BRIDGE_URL` wirft, unbekannter
  Wert wirft). 10 neue Tests. Verdichtet die Design-Spec
  `2026-06-04-dual-bridge-dco-job-pull-design.md`. **Additiv:** `handoff_poll` bleibt
  unberührt; Verdrahtung folgt mit den DCO-Endpunkten.

### Behoben
- **`test_loop_driver.py`-Regression** aus `3fc99ea`: die `b_tick`-Hooks
  (`_run_b_tick`, `_b_error_tick`, zwei Lambdas) nehmen jetzt `task_id` entgegen,
  passend zum neuen `loop_driver`-Aufruf `b_tick(task_id)`. Reine Signatur-Angleichung.

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
