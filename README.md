# Dual-Laptop-Bridge

Dateibasierte, **bidirektionale** Handoff-Bridge zwischen zwei Knoten über den
Google-Drive-Sharepoint. Jeder Knoten kann **senden und empfangen** — welcher
Knoten welche Rolle und welches Modell hat (Claude / Codex / Echo), ist reine
**Konfiguration**, kein Code. **Stage 2a** liefert das modulare Lane-/Adapter-/
Endpoint-Modell: richtungsgetrennte Lanes, ein Adapter-Feld, das Modell von
Fachabsicht trennt, und endpoint-relative Skripte, die auf A und B identisch laufen.

> **Master-Plan (vollständige Strategie, alle Stufen):**
> `~/wiki/wiki/plans/2026-05-30-dual-bridge-master-plan.md`
>
> **Stage-2a Design-Spec + Plan:**
> `docs/superpowers/specs/2026-05-31-dual-bridge-stage2a-modulare-v2-design.md`
> `docs/superpowers/plans/2026-05-31-dual-bridge-stage2a-modulare-v2.md`

## Architektur (richtungsgetrennte Lanes)

```
ENDPOINT claude@laptop-a                         ENDPOINT codex@laptop-b
  handoff_write.py ──┐                       ┌── handoff_poll.py
  handoff_poll.py    │  lane-A-to-B/         │   handoff_write.py
  handoff_collect.py │   outbox/  (A→B Tasks)│   handoff_collect.py
                     ▼   inbox/   (B→A Result)▼
   G:\Meine Ablage\dynamic-AI\dynamic_sharepoint\00_INBOX\dual-bridge\
     lane-A-to-B/   outbox/ inbox/ _processed/ _errors/   (Richtung A→B)
     lane-B-to-A/   outbox/ inbox/ _processed/ _errors/   (Richtung B→A)
```

- **Zwei getrennte Lanes** statt einer flachen outbox/inbox: `lane-A-to-B/` und
  `lane-B-to-A/`, je mit eigenem `outbox/ inbox/ _processed/ _errors/`. Weil jede
  Richtung ihren eigenen Claim-Pool hat, ist ein Cross-Device-Claim-Race
  **strukturell ausgeschlossen** — kein gemeinsamer Topf, um den beide Maschinen
  konkurrieren.
- **Jeder Knoten sendet UND empfängt.** Ein Endpoint schreibt in das `outbox/`
  seiner Sende-Lane (`send_lane`) und pollt das `outbox/` seiner Empfangs-Lane(s)
  (`receive_lanes`). A↔B umkehrbar = nur `DUAL_BRIDGE_ENDPOINT` umsetzen.
- **`_errors/`** quarantänt Tasks mit invalider `task_id` (Path-Traversal- /
  Branch-Injection-Schutz), sichtbar getrennt vom normalen `_processed/`-Archiv.

**Code liegt lokal** (`~/AI/dual-bridge/scripts/`), **nie im Sharepoint** — der
Sharepoint trägt nur Daten (Manifest §7). Keine Secrets in Tasks (Regel 6).
Verarbeitetes wird verschoben, nie gelöscht (Regel 7).

## Adapter / Runner (Modell ≠ Fachabsicht)

Das Frontmatter-Feld **`adapter`** trennt das ausführende **Modell** von der
fachlichen **`kind`**-Absicht. Drei Runner:

| Adapter | Was passiert | Git-Publishing |
|---|---|---|
| `echo` | kein LLM, spiegelt den Auftrag zurück (Fundament-/Smoke-Lauf) | nein |
| `codex` | echter `codex exec`, arbeitet in einem Repo, **committet + pusht** einen Branch `bridge/task-<id>` | ja |
| `claude` | echter `claude -p`, reine Text-Antwort | nein |

## Bedienung (endpoint-relativ — identisch auf A und B)

`handoff_write` / `handoff_poll` / `handoff_collect` laufen auf **beiden** Knoten
mit demselben Code; die Richtung ergibt sich allein aus `DUAL_BRIDGE_ENDPOINT`.

### Beispiel A→B (Codex-Auftrag)

```bash
# Auf claude@laptop-a (Default-Endpoint):
cd ~/AI/dual-bridge/scripts
python handoff_write.py --adapter codex --kind implement \
    --repo <repo-url> "Implementiere X in Repo Y"
python handoff_collect.py --watch              # wartet auf das Result aus lane-B-to-A

# Auf codex@laptop-b:
export DUAL_BRIDGE_ENDPOINT=codex@laptop-b     # PowerShell: $env:DUAL_BRIDGE_ENDPOINT="codex@laptop-b"
cd ~/AI/dual-bridge/scripts
python handoff_poll.py --watch                 # pollt lane-A-to-B/outbox, runnt codex
```

### Beispiel B→A (Claude-Auftrag, umgekehrte Richtung)

```bash
# Auf codex@laptop-b:
export DUAL_BRIDGE_ENDPOINT=codex@laptop-b
cd ~/AI/dual-bridge/scripts
python handoff_write.py --adapter claude --to claude@laptop-a "Erkläre Z"
python handoff_collect.py --watch

# Auf claude@laptop-a (Default-Endpoint, kein Export nötig):
cd ~/AI/dual-bridge/scripts
python handoff_poll.py --watch                 # pollt lane-B-to-A/outbox, ruft claude -p
```

`--adapter` wählt den Runner beim Empfänger (`echo`/`codex`/`claude`); `--to`
überschreibt den Ziel-Endpoint (Default: der Peer der eigenen Sende-Lane).
Einmal-Durchlauf statt Dauerschleife: dieselben Skripte ohne `--watch`.

`handoff_poll.py --watch` nutzt, wenn das optionale Python-Paket `watchdog`
installiert ist, einen Filesystem-Wakeup auf den Empfangs-`outbox/`-Ordnern.
Neue Task-Dateien triggern dann sofort einen Poll-Durchlauf. Ohne `watchdog`
bleibt der Poll-Fallback aktiv; `--interval` ist dann das Poll-Intervall, mit
`watchdog` zusätzlich der maximale Fallback-Abstand.

## Konfiguration (Env-Vars)

| Variable | Zweck | Default |
|---|---|---|
| `DUAL_BRIDGE_ROOT` | Bridge-Ordner überschreiben (falls Drive-Pfad auf B anders ist) | `G:\Meine Ablage\...\00_INBOX\dual-bridge` |
| `DUAL_BRIDGE_ENDPOINT` | Wer bin ich — bestimmt Sende-/Empfangs-Lane (Override; sonst hostname-erkannt) | hostname-erkannt |
| `DUAL_BRIDGE_DEVICE` | Geräte-Label in Claim/Result | `%COMPUTERNAME%` |
| `DUAL_BRIDGE_WORKROOT` | Arbeitsverzeichnis für codex/claude-Runner | `~/dual-bridge-work` |
| `DUAL_BRIDGE_REPO_ALLOWLIST` | codex-Repo-Allowlist, Komma-getrennte fnmatch-Patterns | leer = alle erlaubt |
| `DUAL_BRIDGE_CODEX_BIN` | Pfad zum `codex`-Binary | auto (`shutil.which`) |
| `DUAL_BRIDGE_CODEX_TIMEOUT` | codex-Timeout in Sekunden | `600` |
| `DUAL_BRIDGE_CLAUDE_BIN` | Pfad zum `claude`-Binary | auto (`shutil.which`) |
| `TELEGRAM_TOKEN` | Telegram-Bot-Token für den Eskalations-Notifier (mit DCO geteilt) | — |
| `TELEGRAM_CHAT_ID` | Telegram-Chat-ID, an die der Notifier sendet (mit DCO geteilt) | — |
| `DUAL_BRIDGE_TG_TOKEN` | Override für `TELEGRAM_TOKEN` (nur dual-bridge) | leer = `TELEGRAM_TOKEN` |
| `DUAL_BRIDGE_TG_CHAT` | Override für `TELEGRAM_CHAT_ID` (nur dual-bridge) | leer = `TELEGRAM_CHAT_ID` |
| `DUAL_BRIDGE_TRANSPORT` | Job-Quelle: `file` (Lane/Drive) oder `http` (DCO-Job-Pull) | `file` |
| `DCO_BRIDGE_URL` | Basis-URL des DCO-HTTP-API (nur bei `http`; muss auf `/api` enden; fail-closed wenn leer) | — |
| `DCO_BRIDGE_TOKEN` | Bearer-Token des Workers für den DCO-Job-Pull | — |
| `DUAL_BRIDGE_WORKER_TYPE` | Worker-Typ im DCO-Job-Pull | `dual-bridge` |

Endpoint-Werte: `claude@laptop-a` (sendet A→B, empfängt B→A) oder
`codex@laptop-b` (sendet B→A, empfängt A→B).

### Endpoint-Identität (Maschine, nicht Agent)

Der Endpoint bestimmt die **Lane-Richtung** und hängt an der **Maschine**, nicht an
Rolle oder Agent. `this_endpoint()` löst dreistufig auf:

1. `DUAL_BRIDGE_ENDPOINT` (per `setx`) — expliziter Override, höchster Vorrang.
2. Hostname-Auto-Erkennung (case-insensitiv): `DOME-DYNAMICS → codex@laptop-b`,
   `K472HEXXZACKBUUM → claude@laptop-a`.
3. Unbekannter Host ohne Override → klarer Fehler (kein stilles Raten).

Der `claude@`/`codex@`-Präfix ist kosmetisch; der real laufende Adapter kommt
ausschließlich aus dem Task-Feld `adapter:`. **Migration:** Bestehende
`setx DUAL_BRIDGE_ENDPOINT`-Werte bleiben als Override gültig — kein koordinierter
Umstieg über beide Laptops nötig. Neue Maschine → entweder Hostname in
`HOSTNAME_TO_ENDPOINT` (`scripts/bridge_common.py`) eintragen oder `setx` setzen.

Die Liveness-Prüfung des Pollers (`_pid_alive`/Singleton-Lock/`bridge_status`)
verifiziert zusätzlich die Prozess-Cmdline (Marker je Poller: `handoff_poll`/
`job_poll`/`loop_driver`), damit eine vom OS recycelte Fremd-PID nicht
fälschlich als laufender Poller gilt (Stale-PID-Schutz).

**Wichtig für Laptop B:** Prüfe zuerst, ob der Google-Drive-Mount denselben
Laufwerksbuchstaben (`G:`) hat. Falls nicht, setze `DUAL_BRIDGE_ROOT`.

## Task-Protokoll

```yaml
---
created: 2026-05-31T13:45:53
schema_version: "2"
agent: claude@laptop-a              # Quelle (= from)
from: claude@laptop-a               # Sende-Endpoint
to: codex@laptop-b                  # Ziel-Endpoint
target_agent: laptop-b-worker
purpose: handoff
status: open                        # open → claimed → done → consumed
task_id: 20260531-134553-044123-1-ab12   # streng validiert (Path-Traversal-Schutz)
kind: implement                     # echo|implement|research|review|test (Fachabsicht)
adapter: codex                      # echo|codex|claude (ausführendes Modell)
repo:                               # nur für codex: Ziel-Repo
base_branch: main
claimed_by:                         # Empfänger füllt beim Claim
claimed_at:
---
## Auftrag
...
## Akzeptanzkriterien
- [ ] Ergebnis liegt im inbox/ mit demselben task_id
## Ergebnis
<wird vom Empfänger gefüllt>
```

## Sicherheit & Härtung

- **`task_id`-Validierung** (Regex auf die exakte `make_task_id()`-Form) blockt
  Path-Traversal und Branch-Injection; invalide Tasks landen in `_errors/`.
- **Repo-Allowlist** für den codex-Runner (`DUAL_BRIDGE_REPO_ALLOWLIST`,
  fnmatch-Patterns; leer = alle erlaubt).
- **P0-Crash-Requeue:** ein geclaimter Task ohne Result geht beim Poller-Crash
  nicht verloren, sondern wird re-queued.
- **Optionaler Filesystem-Wakeup:** `handoff_poll.py --watch` kann neue Tasks
  per `watchdog` sofort verarbeiten; ohne Zusatzpaket läuft der bewährte
  Intervall-Poll weiter.
- **Sibling-Surrender-Cleanup** gegen doppelte Claims desselben `task_id`.
- **Never-crash-Poller:** ein einzelner kaputter Task reißt die Schleife nicht ab.

## Verifizierter Stand (Stufe 3 live, 2026-06-03)

- ✅ **Stufe 1 (echter codex-Worker) live vertrags-bewiesen:** A schickt
  `implement`-Task → B claimt → echter `codex exec` → Branch `bridge/task-<id>`
  + Commit, byte-genau gegen `git show origin/<branch>` verifiziert (P007, nicht
  Selbstbericht). Happy- + Fehlerpfad end-to-end.
- ✅ **B→A-Roundtrip config-only bewiesen** (dieselben Skripte, Richtung allein
  per `DUAL_BRIDGE_ENDPOINT` umgedreht).
- ✅ **Live-`claude -p`-Beweis geräteübergreifend** erbracht (im Goal-Loop: echter
  claude-Reviewer auf B, Verdikt cross-device über die Bridge).
- ✅ **Stufe 3 (Goal-Loop + Owner-Eskalation) live bewiesen** (`loop_driver.py`,
  `--mode goal-loop`): offenes Ziel + Done-Kriterien, Verdikt `escalate`
  (fail-closed), 4 Eskalations-Trigger → `ESCALATION-<id>.md`; Reseed-Resume mit
  Continuity. Live: escalate → geschärfter Reseed → accepted @`6ea94bc`
  (Continuity hart bewiesen). Stufe-2b-Kern (`kind:review`-Verdikt-Semantik) als
  Vorstufe enthalten.
- ✅ **Read-only Status-Dashboard** (`bridge_status.py`): Tasks/Loops/Eskalationen/
  `_errors/`-Quarantäne/Poller-Liveness je Lane, text+json, `--watch`. Schreibt nie.
- ✅ **Eskalations-Notifier** (`bridge_notify.py`): benachrichtigt per Telegram bei
  neuen `ESCALATION-<id>.md`, lokal getriggert (Windows-Task), idempotent
  (Dedup je `loop_id` über `state/_notify/sent.json`), at-least-once. Read-only
  auf Eskalationen — schreibt nur den eigenen Sidecar-State. DCO-ready
  (Kernlogik in `notify_new_escalations()`, nur der Caller ändert sich).
- ✅ **Overnight-Scheduler** (`bridge_overnight.py`): arbeitet nachts eine Queue
  vordefinierter goal-loop-Seeds (`docs/overnight/*.md`) seriell ab und sendet
  morgens **einen** Telegram-Digest (accepted/eskaliert/Fehler). Lokal getriggert
  (Windows-Task), read-mostly (schreibt nur `state/_overnight/runs/`), fail-soft je
  Seed, fail-closed bei Fehlkonfig. DCO-ready (Kernlogik in `run_overnight()`,
  injizierbare `run_fn`).
- ✅ **Optionaler Poller-Filesystem-Wakeup** (`watchdog` wenn installiert,
  Intervall-Poll als Fallback).
- ✅ **DCO-HTTP-Job-Pull** (`scripts/job_poll.py`): `DUAL_BRIDGE_TRANSPORT=http`
  claimt Jobs aus DCO (`GET /api/jobs/next?worker_type=dual-bridge`) und meldet
  Resultate zurueck (`POST /api/jobs/<id>/result`). Auf Laptop B aus
  `C:\Users\domes\AI\dual-bridge\scripts` starten, z.B.
  `python -X utf8 .\job_poll.py --once`.
- ✅ **181 Tests grün** (Collection + voller pytest-Lauf).

> **Hinweis zur Begriffsklärung:** „Stufe 3" war im Master-Plan doppelt belegt.
> Der **freie Goal-Loop** und der DCO-HTTP-Job-Pull sind gebaut. Fuer produktive
> Ende-zu-Ende-Verarbeitung muessen weiterhin zwei Prozesse laufen: Builder
> (`job_poll.py`) und Reviewer (`handoff_poll.py`).

## Nächste Schritte

1. **Laptop-B-Dauerbetrieb verifizieren:** `job_poll.py --once` gegen DCO laufen
   lassen, danach `register_jobpoll.ps1` fuer den Builder-Dauerlauf registrieren.
2. **Notifier/Overnight spaeter zentral triggern:** `notify_new_escalations()` und
   `run_overnight()` sind DCO-ready gekapselt, aber nicht Teil des Job-Pull-Pfads.

Vollständiger Änderungsverlauf: [`docs/CHANGELOG.md`](docs/CHANGELOG.md).
