# Dual-Bridge — Betriebs-Übersicht

> Praxis-Doku für den laufenden Betrieb: Wer bin ich (A/B)? Welche Jobs laufen?
> Was soll zwischen A, B und DCO passieren — und was passiert tatsächlich?
> Stand: 2026-06-05. Architektur-Vollreferenz: [`../README.md`](../README.md).

---

## 1. Welcher Endpoint bin ich? (A oder B)

Rolle/Richtung sind **reine Konfiguration**, kein Code. Bestimmt durch zwei Env-Vars,
beide mit Default für **Laptop A**:

| Env-Var | Default (= A) | Override (= B) |
|---|---|---|
| `DUAL_BRIDGE_ENDPOINT` | `claude@laptop-a` | `codex@laptop-b` |
| `DUAL_BRIDGE_ROOT` | `G:\Meine Ablage\dynamic-AI\dynamic_sharepoint\00_INBOX\dual-bridge` | gerätespezifischer Mount |

**So siehst du, als wer du gerade läufst:**

```powershell
# 1. Env direkt (schnellster Blick):
$env:DUAL_BRIDGE_ENDPOINT      # leer => Default claude@laptop-a

# 2. Aus Sicht eines Skripts (druckt den aufgelösten Endpoint + Root):
cd C:\Users\domes\AI\dual-bridge\scripts
python handoff_poll.py          # Kopfzeile: "[B] Bridge-Root: ... / Device: ..."
python loop_driver.py --help    # oder via bridge_status / latency_probe
```

Jedes Poller-Skript druckt beim Start `Bridge-Root` + `Device`. Die Endpoint-Tabelle
steht in `scripts/bridge_common.py` (`ENDPOINTS`):

| Endpoint | sendet auf Lane | empfängt auf Lane |
|---|---|---|
| `claude@laptop-a` | `A-to-B` | `B-to-A` |
| `codex@laptop-b` | `B-to-A` | `A-to-B` |

Richtungs-getrennte Lanes → A und B teilen sich nie denselben Claim-Pool
(verhindert die Cross-Device-Rename-Race; `os.rename` ist nur LOKAL atomar).

**Aktueller Stand dieses Laptops:** `claude@laptop-a` (Default, kein Override gesetzt)
= **Endpoint A**, Reviewer-Knoten, liest die Drive-Datei-Bridge.

---

## 2. Welche Jobs / Skripte laufen hier?

### 2a. Registrierte Windows Scheduled Tasks

| Task | Takt | Was er tut | Skript |
|---|---|---|---|
| **DualBridgePollerWatchdog** | alle 10 min | hält den Bridge-Reviewer (`handoff_poll.py --watch`) am Leben; Singleton-Lock verhindert Doppelstart | `scripts/register_watchdog.ps1` |
| **NotebookLM Auth Refresh** | alle 20 min | erneuert das NotebookLM-Cookie (Keep-alive) | `AI/tools/notebooklm/refresh-auth.ps1` |
| **NotebookLM Boot Login** | beim Logon (+1 min) | prüft Session, stößt bei Bedarf interaktives Login an | `AI/tools/notebooklm/boot-login.ps1` |

> `LastResult 267011` (0x41303) bei Boot Login = "noch nie gelaufen / kein Trigger
> seit Registrierung" — normal, der Logon-Trigger feuert erst beim nächsten Anmelden.

**Status prüfen:**
```powershell
powershell -File C:\Users\domes\AI\dual-bridge\scripts\watch_watchdog.ps1          # einmal
powershell -File C:\Users\domes\AI\dual-bridge\scripts\watch_watchdog.ps1 -Loop    # Dauer
Get-ScheduledTaskInfo -TaskName 'DualBridgePollerWatchdog'                          # roh
```

### 2b. Die Bridge-Skripte (Rolle je Skript)

| Skript | Knoten | Rolle |
|---|---|---|
| `handoff_write.py` | Sender | legt einen Task in die eigene Outbox |
| `handoff_poll.py` | Empfänger | claimt + verarbeitet Tasks der Empfangs-Lane (`--watch` = Dauer) |
| `handoff_collect.py` | Sender | wartet auf das Result zum gesendeten Task |
| `loop_driver.py` | A | Goal-Loop / Build-Review / Ping-Pong; Reviewer-Verdikt + Eskalation |
| `bridge_overnight.py` | A | nächtliche Seed-Queue (`docs/overnight/*.md`) → ein Morgen-Digest |
| `bridge_notify.py` | A | Eskalations-Alert per Telegram (read-only auf Artefakten) |
| `job_poll.py` | **B** | HTTP-Pull vom DCO (`/jobs/next`), fährt `loop_driver --mode goal-loop`, meldet rc zurück |
| `bridge_status.py` | beide | read-only Status-Dashboard |
| `bridge_common.py` | beide | zentrale Pfad-/Endpoint-/Lane-Auflösung (Source of Truth) |

### 2c. Registrier-Skripte (Tasks an-/abmelden)

| Skript | Task |
|---|---|
| `register_watchdog.ps1` | DualBridgePollerWatchdog (Reviewer-Poller, A) |
| `register_jobpoll.ps1` | Builder-Poller (DCO-HTTP-Pull, B) |
| `register_overnight.ps1` | DualBridgeOvernight (Seed-Queue, A) |
| `register_notify.ps1` | DualBridgeEscalationNotifier (Telegram, A) |

> Aktuell registriert ist **nur** der Watchdog. Overnight/Notify/Jobpoll sind im
> Code fertig, aber als Tasks **nicht** aktiv (bewusst — erst nach `--dry-run`).

---

## 3. Was zwischen A, B und DCO passieren soll — und passiert

### 3a. Zwei orthogonale Transport-Wege

Die Dual-Bridge hat **zwei voneinander unabhängige** Kanäle:

```
  (1) DATEI-BRIDGE (Google Drive)          (2) HTTP-BRIDGE (DCO)
  ────────────────────────────────         ──────────────────────────────
  A  ──A-to-B──►  [Drive]  ◄──B-to-A── B    DCO  ──/jobs/next──►  B (job_poll)
     ◄─────────  Lanes    ─────────►            ◄──/result──────
  Reviewer (A) ↔ Builder (B)                 Job-Quelle (DCO) → Worker (B)
  loop_driver / handoff_*                    bridge_transport.HttpSource
```

- **(1) Datei-Bridge:** Peer-to-peer A↔B über den Drive-Sharepoint. Jeder Knoten
  schreibt in die Outbox seiner Sende-Lane, pollt die Outbox der Empfangs-Lane.
  Verarbeitetes wird verschoben (`_processed/`/`_errors/`), nie gelöscht.
- **(2) HTTP-Bridge:** B zieht Jobs vom DCO (`DCO_BRIDGE_URL`, `DCO_BRIDGE_TOKEN`),
  fährt sie als `loop_driver --mode goal-loop`, meldet nur den **rc** zurück
  (`0=accepted, 3=escalated, 2=config/resume, 1=other`). Der **DCO** mappt rc auf
  den finalen Status (Single Source of Truth) — B erzwingt keinen Status.

### 3b. Soll-Fluss (Datei-Bridge, A↔B)

1. **A sendet:** `handoff_write.py` → Task landet in `lane-A-to-B/outbox/`.
2. **B empfängt:** `handoff_poll.py --watch` claimt (atomar via `os.rename`),
   verarbeitet (Adapter: `echo`/`codex`/`claude`), schreibt Result in
   `lane-A-to-B/inbox/`, verschiebt den Task nach `_processed/`.
3. **A sammelt:** `handoff_collect.py --watch` liest das Result.
4. **Fehler:** kaputte/abgelaufene Tasks → `_errors/`-Quarantäne (nicht gelöscht).
5. **Goal-Loop (Stufe 3):** `loop_driver` fährt Build→Review-Runden; bei Stagnation
   → fail-closed `state/ESCALATION-<loop_id>.md`; `bridge_notify.py` alarmiert.

### 3c. Soll-Fluss (HTTP-Bridge, DCO→B)

1. DCO hat einen Job in der Queue (`jobs.claim_next`).
2. B (`job_poll.py --watch`) holt ihn via `GET /jobs/next` (204 = leer → Backoff).
3. B fährt `loop_driver --mode goal-loop` als Subprozess → rc.
4. B meldet via `POST /jobs/<id>/result` (rc + gekürztes stdout, `status=None`).
5. DCO setzt den finalen Status anhand rc.

### 3d. Ist-Stand (heute beobachtet)

| Was | Soll | Ist (2026-06-05) |
|---|---|---|
| Endpoint dieses Laptops | A oder B | **A** (`claude@laptop-a`, Default) |
| Reviewer-Poller (Datei-Bridge) | dauerhaft via Watchdog | Task **Ready**, Watch-Prozess läuft nur zwischen Triggern |
| `lane-A-to-B` | Tasks fließen | `results=4 processed=149 errors=0` (aufgeräumt) |
| `lane-B-to-A` | B→A-Verkehr | **leer** (`0/0/0`) — kein aktiver B-Sendebetrieb |
| Eskalationen | 0 offen | **0** (a8f4 heute erledigt) |
| Builder-Poller (HTTP/DCO) | als Task auf B | **nicht** registriert auf diesem Laptop (A-Rolle) |
| Telegram-Notifier | optional | Code fertig, Task nicht aktiv |

**Kurz:** Dieser Laptop ist **A/Reviewer**. Die Datei-Bridge ist gesund und leer-
gelaufen (kein offener Verkehr). Der DCO-HTTP-Pfad ist hier nicht aktiv — der
gehört auf den B/Builder-Knoten (`register_jobpoll.ps1` + DCO-Env).

---

## Verweise
- Architektur/Env/Härtung: [`../README.md`](../README.md)
- Schnellstart-Befehle: [`../HOW-TO-USE.md`](../HOW-TO-USE.md)
- Agenten-Schaltzentrale: [`../CLAUDE.md`](../CLAUDE.md)
- Sharepoint-Lifecycle: `G:\...\dynamic_sharepoint\SHAREPOINT_MANIFEST.md`
- Master-Plan: `~/wiki/wiki/plans/2026-05-30-dual-bridge-master-plan.md`
