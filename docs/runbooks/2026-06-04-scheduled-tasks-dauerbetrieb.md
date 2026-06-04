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

## A (Reviewer) — auf Laptop A registrieren

Reviewer-Watchdog muss mit explizitem Endpoint laufen, sonst defaultet
`handoff_poll.py` auf `claude@laptop-a` und liest die falsche Lane. Der
Reviewer fuer DCO-Job-Pull-Auftraege ist in dieser Topologie
`codex@laptop-b`, auch wenn der Prozess auf Laptop A laeuft.

```powershell
cd C:\Users\domes\AI\dual-bridge\scripts
powershell -ExecutionPolicy Bypass -File .\register_watchdog.ps1 -Endpoint codex@laptop-b -Interval 15
```

Erwartung:

```
Task   : DualBridgePollerWatchdog
Argument: powershell ... $env:DUAL_BRIDGE_ENDPOINT='codex@laptop-b'; python -X utf8 handoff_poll.py --watch --interval 15
```

Der Reviewer liest die Drive-Datei-Bridge — **keine** HTTP-/TG-Env nötig.
Voraussetzung (erfüllt): Google-Drive-Mount `G:\…\00_INBOX\dual-bridge` vorhanden.

Deaktivieren: `Unregister-ScheduledTask -TaskName 'DualBridgePollerWatchdog' -Confirm:$false`

> Falle (2026-06-04, L7): Ein stale Singleton-Lock mit recycelter PID 236
> (= Windows „Secure System", stirbt nie) blockierte jeden Start
> („Poller läuft bereits"). Gelöst durch Löschen der Lock-Dateien unter
> `%TEMP%\dual-bridge-poller.lock` (+ `%TEMP%\claude\…`). Tritt das wieder auf:
> Lock-Datei löschen, der frische Start schreibt seine lebende PID rein.

> Live-Fund 2026-06-04: Ein laufender Watchdog ohne explizites
> `DUAL_BRIDGE_ENDPOINT` liess Review-Tasks offen liegen. Ein manueller Pass mit
> `$env:DUAL_BRIDGE_ENDPOINT='codex@laptop-b'` verarbeitete den Task sofort; der
> DCO-Job `5b26c02c35e0` wurde danach `completed/accepted`.

---

## B (Builder) — vom User auszuführen

### Schritt 1 — HTTP-Pull-Env persistent setzen (`setx`!)

Ein in-Session `set` reicht NICHT — der Scheduled Task läuft in einem eigenen
Kontext und sieht nur persistente (User-/System-)Env-Variablen. **Ohne diese
Variablen pollt `job_poll` still die Datei-Bridge statt den DCO** (Default
`DUAL_BRIDGE_TRANSPORT=file`).

```cmd
setx DUAL_BRIDGE_TRANSPORT "http"
setx DCO_BRIDGE_URL  "https://bot.dynamic-dome.com/api"
setx DCO_BRIDGE_TOKEN "<BRIDGE_API_TOKEN aus der DCO-.env, Zeile 32>"
setx DUAL_BRIDGE_WORKER_TYPE "dual-bridge"
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
cd C:\Users\domes\AI\dual-bridge\scripts
python -X utf8 .\job_poll.py --once
```

Erwartung: claimt einen offenen Job oder meldet „0 Jobs"; **kein** Config-Fehler
(rc 2). Ein rc 2 „DUAL_BRIDGE_TRANSPORT=http erfordert DCO_BRIDGE_URL" → Schritt 1
nicht in dieser Shell sichtbar (neue Shell öffnen).

### Schritt 3 — Builder als Scheduled Task registrieren

```cmd
powershell -ExecutionPolicy Bypass -File .\register_jobpoll.ps1 -Interval 15 -MaxRounds 4 -RoundTimeout 600
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

> **Live-Output (--stream / DUAL_BRIDGE_STREAM)** — Nachtrag 2026-06-04.
> Im stillen Daemon-Betrieb (Default) erscheint der loop_driver-Output erst NACH
> Prozess-Ende; bei langen Builds sieht man auf B minutenlang nichts. Für eine
> Diagnose-/Beobachtungs-Session (NICHT für den Scheduled Task) den Worker mit
> Live-Stream starten:
>
> ```cmd
> python job_poll.py --watch --interval 15 --stream
> ```
>
> Alternativ persistent `setx DUAL_BRIDGE_STREAM 1`. stdout/stderr laufen dann
> getrennt live über die Konsole; der result_payload (Tail) bleibt erhalten, der
> Wall-Clock-Cap (round_timeout*max_rounds+120) gilt unverändert. Für den
> Dauerbetrieb als Scheduled Task wieder weglassen (stiller Betrieb).

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

## Job in die Queue legen — Format & Repo-Default (DCO-Seite)

*Nachtrag 2026-06-04: Hybrid-Repo-Auswahl im DCO (Commit `1c5a35d`).*

Der „ToDo in Queue"-Button routet ein bridge-getaggtes Todo in einen
dual-bridge-Job. Damit der Builder auf B etwas zu tun bekommt, muss der Job ein
Ziel-Repo haben. Dieses kommt — in dieser Priorität — aus:

1. **Dropdown** im Queue-Dialog (Repo-Override pro Job),
2. **`repo=` in Zeile 1** des Todo-Texts, oder
3. **`BRIDGE_DEFAULT_REPO`** (DCO-`.env`, z.B. `https://github.com/dynamic-dome/ToDoDcO`).

Ist keines davon gesetzt, antwortet der Endpoint mit **422** und es entsteht KEIN
Job (häufige Stolperfalle: reiner Freitext OHNE gesetzten Default → nichts kommt
bei B an). Mit gesetztem Default genügt reiner Freitext als Auftrag:

```
Implementiere Feature X laut Spec …            (Zeile 1 = Auftrag, Repo = Default)
```

Mit explizitem Repo (überschreibt den Default):

```
repo=https://github.com/dynamic-dome/dual-bridge kind=implement adapter=codex
Implementiere Feature X laut Spec …
```

DCO-Endpunkte zur Kontrolle: `GET /api/bridge/repos` (Allowlist + Default),
`GET /api/bridge/pending` (gepufferte Todos bei vollem Cap, `BRIDGE_MAX_ACTIVE`,
Default 3).

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
