# CLAUDE.md — Dual-Laptop-Bridge

## Projekt
Dateibasierte, **bidirektionale** Handoff-Bridge zwischen zwei Laptops über den
Google-Drive-Sharepoint. Jeder Knoten sendet UND empfängt; Rolle/Modell/Richtung
sind reine Konfiguration (`DUAL_BRIDGE_ENDPOINT`), kein Code. Stand: **Stufe 3**
(Goal-Loop + Owner-Eskalation, live bewiesen) auf Stage-2a-Fundament.

## Wegweiser (Vorrang: HOW-TO-USE)
**Wie und was gestartet wird, steht in [`HOW-TO-USE.md`](HOW-TO-USE.md)** (Index)
und [`README.md`](README.md) (Vollreferenz: Architektur, Env-Vars, Task-Protokoll,
Härtung). Diese CLAUDE.md ist nur die Schaltzentrale für Agenten + die
Task-Initiierungs-Befehle. **Nicht hier duplizieren — dort pflegen.**

## Vor jeder Änderung (Ground Truth)
1. Spec + Plan lesen: `docs/superpowers/specs/...stage2a...-design.md` + `...plans/...`.
2. Tests laufen lassen: `cd scripts && python -X utf8 -m pytest -q` — erwartet **grün**
   (Soll-Zahl steht in README/HOW-TO-USE; bei Abweichung erst klären).
3. Read-only Snapshot des Live-Zustands: `python scripts/bridge_status.py` (schreibt nie).
4. Erst dann ändern.

## Test-DB-Isolation
`scripts/conftest.py` muss Bridge-Root/State auf `tmp_path` umlenken, **bevor**
ein Test läuft. Kein Test darf gegen den echten Sharepoint
(`G:\Meine Ablage\...\dual-bridge\`) oder `state/` schreiben. Im Zweifel:
conftest lesen + Snapshot vor/nach. Hintergrund: globale Regel §3.

## Tasks initiieren

Alle Befehle aus `scripts/`. **Endpoint = Maschine, hostname-erkannt:**
`this_endpoint()` leitet die Identität automatisch aus dem Hostname ab
(`DOME-DYNAMICS→codex@laptop-b`, `K472HEXXZACKBUUM→claude@laptop-a`). Override via
`setx DUAL_BRIDGE_ENDPOINT` bleibt vorrangig; unbekannter Host ohne Override →
klarer Fehler. Agent/Adapter kommt aus dem Task-Feld `adapter:`, NICHT aus dem
Endpoint-Namen (der `claude@`/`codex@`-Präfix steuert nichts).

### 1. Cross-Device-Handoff (A↔B, manuell)
```bash
# Sender (A):
python handoff_write.py --adapter codex --kind implement --repo <url> "Auftrag"
python handoff_collect.py --watch          # wartet aufs Result
# Empfänger (B, Endpoint gesetzt):
python handoff_poll.py --watch             # claimt + runnt; watchdog-Wakeup wenn installiert
```
Einmal-Durchlauf statt Schleife: dieselben Skripte ohne `--watch`.
Adapter: `echo` (Smoke) | `codex` (committet Branch `bridge/task-<id>`) | `claude` (Text).

### 2. Goal-Loop (Stufe 3, autonom mit Reviewer-Verdikt)
```bash
python loop_driver.py --mode goal-loop --repo <url> --max-rounds 4 \
    --seed docs/live-proofs/stage3-goal-loop-seed.md --round-timeout 600
# Nach escalate: geschärften Seed schreiben, dann fortsetzen:
python loop_driver.py --mode goal-loop --resume <loop_id> --repo <url> --max-rounds 4
```
Modi: `ping-pong` (Stage 1) | `build-review` (Stage 2b) | `goal-loop` (Stage 3).
Eskaliert (fail-closed) → `state/ESCALATION-<loop_id>.md`.
**Zwei Timeout-Schranken:** `--round-timeout` (A wartet auf B) UND
`DUAL_BRIDGE_CODEX_TIMEOUT` (killt `codex exec`, Default 600s). Bei „codex timeout
nach Ns" beide anheben oder den Seed kleiner schneiden (README §Konfiguration).

**Abhängige Paket-Ketten (B baut auf A):** Jeder Loop klont frisch von der
Base (`master`/`main`, hostname-/repo-aufgelöst). Pakete akkumulieren NICHT von
selbst — A muss in die Base gemergt sein, BEVOR B's Loop klont. Dafür
`--merge-on-accept`: bei `accepted` mergt die Bridge den Loop-Branch in die Base
und pusht (fail-soft bei Konflikt → accepted bleibt gültig, Branch manuell
mergen). Im DCO-Worker (`job_poll.py`) per `DUAL_BRIDGE_MERGE_ON_ACCEPT=1`
(Default aus) schaltbar — bewusst aktivieren, wenn eine abhängige Kette läuft;
sonst pusht jeder Einzeljob in die Repo-Base.

### 3. Overnight-Scheduler (nächtliche Seed-Queue)
Seeds liegen als `docs/overnight/*.md` (Format: `docs/overnight/README.md`;
`.skip`-Suffix oder `_done/` = ignoriert).
```bash
python bridge_overnight.py --dry-run --repo https://github.com/dynamic-dome/dual-bridge   # IMMER zuerst
# Windows-Task (täglich 02:00) registrieren — erst nach grünem Dry-Run:
powershell -ExecutionPolicy Bypass -File register_overnight.ps1 -Repo <url> [-At 03:30 -MaxRounds 6 -RoundTimeout 1800 -CodexTimeout 1800 -WakeToRun]
# Deaktivieren:
Unregister-ScheduledTask -TaskName "DualBridgeOvernight" -Confirm:$false
```
Ergebnis: EIN Morgen-Digest per Telegram. read-mostly, fail-soft je Seed,
fail-closed bei Fehlkonfig (nicht-leere Queue ohne `--repo` → Exit 2).

### 4. Eskalations-Notifier (Telegram-Alert)
Braucht `TELEGRAM_TOKEN` + `TELEGRAM_CHAT_ID` (mit DCO geteilt) im Task-Kontext.
```bash
python bridge_notify.py --dry-run          # IMMER zuerst
powershell -ExecutionPolicy Bypass -File register_notify.ps1 [-Digest]   # alle 10 min, +Tages-Digest 08:00
Unregister-ScheduledTask -TaskName "DualBridgeEscalationNotifier" -Confirm:$false
```
Idempotent (Dedup je `loop_id` über `state/_notify/sent.json`), schreibt nur den
eigenen Sidecar-State.

### 5. Poller-Watchdog (B, hält Empfänger am Leben)
```bash
powershell -ExecutionPolicy Bypass -File register_watchdog.ps1   # alle 10 min handoff_poll --watch
```
Singleton-Lock verhindert Doppelstart/Doppel-Claim. Erst nach erstem manuellem Roundtrip.

## Konventionen
- Sprache: Deutsch für Kommunikation, Englisch für Code/Dateinamen.
- **Sharepoint trägt nur Daten, nie Code** (Manifest §7). Keine Secrets in Tasks.
  Verarbeitetes wird verschoben (`_processed/`/`_errors/`), nie gelöscht.
- Scheduled Tasks **nie blind aktivieren** — immer erst `--dry-run`.
- Windows-Subprocess-Härtung beachten (globale Regel §10): headless `claude -p`
  via stdin, `codex exec` Sandbox-Fallen. Live-Funde in `PICKUP-*.md`.
- Plan: `docs/plans/2026-06-02-tier1-quickwins-plan.md` (lokal, aktuell). Ein
  Wiki-Master-Plan existiert (noch) nicht — kein `~/wiki/.../dual-bridge-*`.
