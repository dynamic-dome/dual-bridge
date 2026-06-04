# Dual-Bridge Dauerbetrieb — Scheduled Tasks (Zwei-Knoten-Topologie)

*Stand: 2026-06-04. Eingerichtet von Claude Code (Opus 4.8), Laptop A.*

Der goal-loop braucht **zwei** Prozesse mit Gegen-Endpoints (Memory
`dual-bridge-goal-loop-two-node-topology`). Ein Worker allein → immer
`stagnation 0/4` (der Reviewer fehlt, NICHT „codex baut nichts").

| Knoten   | Rechner | Daemon                 | Bridge                         | Register-Skript          |
|----------|---------|------------------------|--------------------------------|--------------------------|
| Reviewer | **A**   | `handoff_poll.py`      | Drive-Datei-Bridge (`bridge_root`) | `register_watchdog.ps1`  |
| Builder  | **B**   | `job_poll.py`          | DCO-HTTP-Pull (`/api/jobs/*`)  | `register_jobpoll.ps1`   |

Beide als `--watch --interval 15`, je ein Scheduled Task mit 10-min-Re-Trigger
(Singleton-Lock verhindert Doppelstart).

---

## A (dieser Rechner) — ERLEDIGT

Reviewer-Watchdog ist **live registriert + laufend** bestätigt:

```
Task   : DualBridgePollerWatchdog  (State Ready, Prozess läuft)
Argument: handoff_poll.py --watch --interval 15
```

Der Reviewer liest die Drive-Datei-Bridge — **keine** HTTP-/TG-Env nötig.
Voraussetzung (erfüllt): Google-Drive-Mount `G:\…\00_INBOX\dual-bridge` vorhanden.

Deaktivieren: `Unregister-ScheduledTask -TaskName 'DualBridgePollerWatchdog' -Confirm:$false`

> Falle (2026-06-04, L7): Ein stale Singleton-Lock mit recycelter PID 236
> (= Windows „Secure System", stirbt nie) blockierte jeden Start
> („Poller läuft bereits"). Gelöst durch Löschen der Lock-Dateien unter
> `%TEMP%\dual-bridge-poller.lock` (+ `%TEMP%\claude\…`). Tritt das wieder auf:
> Lock-Datei löschen, der frische Start schreibt seine lebende PID rein.

---

## B (Builder) — vom User auszuführen

### Schritt 1 — HTTP-Pull-Env persistent setzen (`setx`!)

Ein in-Session `set` reicht NICHT — der Scheduled Task läuft in einem eigenen
Kontext und sieht nur persistente (User-/System-)Env-Variablen. **Ohne diese
Variablen pollt `job_poll` still die Datei-Bridge statt den DCO** (Default
`DUAL_BRIDGE_TRANSPORT=file`).

```cmd
setx DUAL_BRIDGE_TRANSPORT http
setx DCO_BRIDGE_URL  "https://bot.dynamic-dome.com/api"
setx DCO_BRIDGE_TOKEN "<BRIDGE_API_TOKEN aus der DCO-.env, Zeile 32>"
```

- `DCO_BRIDGE_URL` **muss auf `/api` enden**, sonst 404 (Runbook
  `dynamic_central_orchestrator/docs/runbooks/2026-06-04-bridge-job-pull-e2e.md`).
- `DCO_BRIDGE_TOKEN` = exakt der Wert von `BRIDGE_API_TOKEN` in der DCO-`.env`.
- Danach **eine neue Shell öffnen** (oder neu anmelden), damit die Vars sichtbar sind.

> Optional, falls über Cloudflare statt direkt: die öffentliche URL ist
> `https://bot.dynamic-dome.com/api`. Bei lokalem Test gegen denselben Rechner:
> `http://127.0.0.1:8000/api` (DCO-Port ist **8000**, via `tray.pyw` — nicht 8787).

### Schritt 2 — Trockenlauf (ein Tick, kein Dauerlauf)

```cmd
cd C:\…\dual-bridge\scripts
python job_poll.py --once
```

Erwartung: claimt einen offenen Job oder meldet „0 Jobs"; **kein** Config-Fehler
(rc 2). Ein rc 2 „DUAL_BRIDGE_TRANSPORT=http erfordert DCO_BRIDGE_URL" → Schritt 1
nicht in dieser Shell sichtbar (neue Shell öffnen).

### Schritt 3 — Builder als Scheduled Task registrieren

```cmd
powershell -ExecutionPolicy Bypass -File register_jobpoll.ps1 -Interval 15
```

Das Skript prüft die drei Env-Variablen **vor** der Registrierung und bricht
fail-closed ab (Exit 2, kein Task), wenn etwas fehlt/falsch ist. Bei Erfolg:

```
Task   : DualBridgeJobPoll  (Re-Trigger alle 10 min, Poll alle 15s)
Argument: job_poll.py --watch --interval 15 --max-rounds 4 --round-timeout 600
```

Größere Builds (vgl. L8, Seed 07 sprengte 600s):
`-RoundTimeout 1800` ergänzen.

Deaktivieren: `Unregister-ScheduledTask -TaskName 'DualBridgeJobPoll' -Confirm:$false`

### Schritt 4 — Verifikation (Ground-Truth, nicht dem „registriert" trauen)

```powershell
Start-ScheduledTask -TaskName 'DualBridgeJobPoll'
Start-Sleep 6
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
  Where-Object { $_.CommandLine -match 'job_poll' } |
  Select-Object ProcessId, CommandLine
```

Ein laufender `python.exe … job_poll … --watch` = Builder live.

---

## End-to-End-Smoke (beide Knoten zusammen)

Mit Reviewer (A) + Builder (B) live: einen Test-Job in die DCO-Queue legen
(z.B. „ToDo in Queue"-Button) und beobachten:
1. B claimt den Job (`GET /api/jobs/next`), baut per codex.
2. A reviewt das Ergebnis über die Drive-Bridge.
3. DCO-Job geht auf `completed`/`accepted`, `Runden: 1/4`.

Ground-Truth wie beim ersten Durchstich: Remote-Branch-Datei via `gh api`
prüfen, nicht dem Worker-Selbstbericht trauen (P012).

## Optional — Notifier / Overnight (separat)

- `register_notify.ps1` (Eskalations-Alerts per Telegram) — braucht
  `TELEGRAM_TOKEN` + `TELEGRAM_CHAT_ID` persistent (`setx`), sonst rc 2.
- `register_overnight.ps1` (nächtliche Seed-Queue) — eher Batch-Seeds als
  Live-Job-Pull.
