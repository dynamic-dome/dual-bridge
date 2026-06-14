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

`--adapter` wählt den Runner beim Empfänger (`echo`/`codex`/`claude`/`claude-build`/`codex-review`); `--to`
überschreibt den Ziel-Endpoint (Default: der Peer der eigenen Sende-Lane).
Einmal-Durchlauf statt Dauerschleife: dieselben Skripte ohne `--watch`.

`handoff_poll.py --watch` nutzt, wenn das optionale Python-Paket `watchdog`
installiert ist, einen Filesystem-Wakeup auf den Empfangs-`outbox/`-Ordnern.
Neue Task-Dateien triggern dann sofort einen Poll-Durchlauf. Ohne `watchdog`
bleibt der Poll-Fallback aktiv; `--interval` ist dann das Poll-Intervall, mit
`watchdog` zusätzlich der maximale Fallback-Abstand.

## Konfiguration

### `config.json` — zentrale Stellschrauben (händisch editierbar)

Die wichtigsten Laufzeit-Werte (Timeouts, Wartedauern, Runden) liegen in
**`config.json` im Repo-Root** — eine Datei, an EINER Stelle änderbar, ohne
Code anzufassen und ohne bei jedem Aufruf ein Flag zu tippen.

| Schlüssel | Zweck | Default | Wirkt auf |
|---|---|---|---|
| `round_timeout` | Sekunden, die A pro Runde auf B's Ergebnis wartet (**äußere** Schranke) | `600` | `loop_driver`, `bridge_overnight` |
| `codex_timeout` | Sekunden, die `codex exec` laufen darf, bevor es gekillt wird (**innere** Schranke) | `600` | `codex`-Adapter |
| `max_rounds` | Default-Rundenzahl (overnight; bei `loop_driver` bleibt `--max-rounds` Pflicht) | `4` | `bridge_overnight` |
| `poll_interval` | Sekunden zwischen Ergebnis-Pollings, während A auf B wartet | `5.0` | `loop_driver` |
| `poller_interval` | Sekunden zwischen Poll-Durchläufen des Empfängers (B, watch-Modus) | `15` | `handoff_poll` |

**Präzedenz (oben gewinnt):** explizites CLI-Flag → Env-Var → `config.json` →
Hardcoded-Fallback. Ein `--round-timeout 1800` schlägt also `config.json`; setzt
du keinen Flag, gilt der Wert aus `config.json`; fehlt die Datei oder ist sie
kaputt, greift der Hardcoded-Default (fail-soft, kein Crash). Override-Pfad für
die Datei: `DUAL_BRIDGE_CONFIG`.

> **Beide Timeout-Schranken zusammen erhöhen.** `round_timeout` (außen) UND
> `codex_timeout` (innen) greifen gemeinsam — es zählt die **kleinste**. Für
> große Aufgaben beide in `config.json` anheben (z.B. je `1800`) oder den Seed
> kleiner schneiden. Hintergrund: Eskalation „codex timeout nach 600s" in Runde 0
> trotz laufendem Clone (2026-06-06).

### Env-Vars

Env-Vars überschreiben `config.json` (siehe Präzedenz oben) und decken zusätzlich
Pfade/Secrets ab, die NICHT in `config.json` gehören (Manifest §6: keine Secrets
in versionierten Dateien). Die Timing-Env-Vars (`DUAL_BRIDGE_ROUND_TIMEOUT`,
`DUAL_BRIDGE_CODEX_TIMEOUT`, `DUAL_BRIDGE_MAX_ROUNDS`, `DUAL_BRIDGE_POLL_INTERVAL`,
`DUAL_BRIDGE_POLLER_INTERVAL`) bleiben als Override erhalten — der Normalweg ist
aber `config.json`.

| Variable | Zweck | Default |
|---|---|---|
| `DUAL_BRIDGE_CONFIG` | Pfad zu einer alternativen `config.json` | `<repo-root>/config.json` |
| `DUAL_BRIDGE_ROOT` | Bridge-Ordner überschreiben (falls Drive-Pfad auf B anders ist) | `G:\Meine Ablage\...\00_INBOX\dual-bridge` |
| `DUAL_BRIDGE_ENDPOINT` | Wer bin ich — bestimmt Sende-/Empfangs-Lane (Override; sonst hostname-erkannt) | hostname-erkannt |
| `DUAL_BRIDGE_DEVICE` | Geräte-Label in Claim/Result | `%COMPUTERNAME%` |
| `DUAL_BRIDGE_WORKROOT` | Arbeitsverzeichnis für codex/claude-Runner | `~/dual-bridge-work` |
| `DUAL_BRIDGE_REPO_ALLOWLIST` | codex-Repo-Allowlist, Komma-getrennte fnmatch-Patterns | leer = alle erlaubt |
| `DUAL_BRIDGE_CODEX_BIN` | Pfad zum `codex`-Binary | auto (`shutil.which`) |
| `DUAL_BRIDGE_CODEX_TIMEOUT` | Sekunden, die `codex exec` laufen darf, bevor es gekillt wird (→ Fehler „codex timeout nach Ns"). **Innere** Timeout-Schranke — siehe Hinweis unter der Tabelle | `600` |
| `DUAL_BRIDGE_CLAUDE_BIN` | Pfad zum `claude`-Binary (Review-Adapter und `claude-build`) | auto (`shutil.which`) |
| `DUAL_BRIDGE_CLAUDE_TIMEOUT` | Sekunden, die `claude -p` (claude-build) laufen darf, bevor es gekillt wird. **Innere** Timeout-Schranke — analog zu `DUAL_BRIDGE_CODEX_TIMEOUT` | `600` |
| `DUAL_BRIDGE_CLAUDE_MAX_TURNS` | Maximale Gesprächsrunden, die `claude -p` im claude-build-Adapter durchläuft | `40` |
| `TELEGRAM_TOKEN` | Telegram-Bot-Token für den Eskalations-Notifier (mit DCO geteilt) | — |
| `TELEGRAM_CHAT_ID` | Telegram-Chat-ID, an die der Notifier sendet (mit DCO geteilt) | — |
| `DUAL_BRIDGE_TG_TOKEN` | Override für `TELEGRAM_TOKEN` (nur dual-bridge) | leer = `TELEGRAM_TOKEN` |
| `DUAL_BRIDGE_TG_CHAT` | Override für `TELEGRAM_CHAT_ID` (nur dual-bridge) | leer = `TELEGRAM_CHAT_ID` |
| `DUAL_BRIDGE_TRANSPORT` | Job-Quelle: `file` (Lane/Drive) oder `http` (DCO-Job-Pull) | `file` |
| `DCO_BRIDGE_URL` | Basis-URL des DCO-HTTP-API (nur bei `http`; muss auf `/api` enden; fail-closed wenn leer) | — |
| `DCO_BRIDGE_TOKEN` | Bearer-Token des Workers für den DCO-Job-Pull | — |
| `DUAL_BRIDGE_WORKER_TYPE` | Worker-Typ im DCO-Job-Pull | `dual-bridge` |

> **Zwei Timeout-Schranken — gemeinsam erhöhen.** Eine zu große Aufgabe kann am
> *inneren* `codex exec`-Limit sterben (`DUAL_BRIDGE_CODEX_TIMEOUT`, Default 600s)
> **obwohl der Clone längst lief** — Symptom: Eskalation „A-build error: codex
> timeout nach 600s", Runde 0, kein Commit (beobachtet 2026-06-06, DCO-Reminder-Seed).
> Das *äußere* Limit ist `--round-timeout` (wie lange der loop_driver auf B's
> Ergebnis wartet). Es greift immer die **kleinste** Schranke, also beide anheben:
> `$env:DUAL_BRIDGE_CODEX_TIMEOUT="1800"` **und** `--round-timeout 1800`.
> Für Scheduled Tasks: `register_jobpoll.ps1` / `register_overnight.ps1` haben dafür
> `-CodexTimeout` + `-RoundTimeout` (ein `setx` in der aufrufenden Shell erreicht
> den Task-Prozess **nicht** — die Skripte setzen die Var per `cmd /c set` im Task
> selbst). Alternativer Hebel statt Timeout-Erhöhung: den Seed kleiner schneiden.

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

## Lane-Health

`scripts/bridge_health.py` ist ein strikt read-only Health-Check für die
Richtungslanes. Er nutzt die bestehende Lane-Lese-Logik aus `bridge_status.py`,
zählt offene und geclaimte Tasks sowie `_errors/` je Lane und meldet Findings,
wenn der älteste offene Task älter als der Schwellwert ist oder die
`_errors/`-Anzahl den Schwellwert überschreitet.

```bash
cd scripts
python bridge_health.py --format text
python bridge_health.py --format json
```

Exit-Code `0` bedeutet keine Findings, Exit-Code `1` bedeutet mindestens ein
Finding. Defaults sind config-fähig über `lane_health_max_age_s` /
`lane_health_max_errors` in `config.json` oder per Env-Override
`DUAL_BRIDGE_LANE_HEALTH_MAX_AGE_S` /
`DUAL_BRIDGE_LANE_HEALTH_MAX_ERRORS`; ein Config-Eintrag ist nicht Pflicht.
Der Check sendet keine Telegram-Nachrichten und schreibt/claimt/verschiebt nie.

## Bridge-Metriken

`scripts/bridge_metrics.py` ist eine strikt read-only Auswertung der
`_processed/`-Archive je Lane. Es paart `task-*.md` und `result-*.md` ueber
`task_id`, berechnet die Durchlaufzeit aus `task.created` bis `result.created`
oder `claimed_at` und zaehlt die `verdict`-Werte der Result-Frontmatter.
Kaputte oder halbe Dateien werden uebersprungen; ein einzelnes Archiv-Problem
bricht den Report nicht ab.

```bash
cd scripts
python bridge_metrics.py --format text
python bridge_metrics.py --format json --lane A-to-B
```

Die API `compute_metrics(lane=None)` liefert `count`, `verdict_counts`,
`durchlaufzeit_min`, `durchlaufzeit_median`, `durchlaufzeit_max` und eine
Lane-Aufschluesselung. `write_report(path)` schreibt einen einzelnen JSONL-
oder Text-Report nur unter `scripts/state/` bzw. dem testbaren
`DUAL_BRIDGE_STATE`-Override, niemals in den Drive-/Lane-Baum.

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
adapter: codex                      # echo|codex|claude|claude-build|codex-review (ausführendes Modell)
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
- **Secrets-Gate (Pre-Send):** `handoff_write.py` scannt das komplette
  Task-Dokument VOR dem Schreiben in die Outbox (`scripts/secret_gate.py`):
  Format-Detektoren für bekannte Token-Shapes (Telegram-Bot-Token, GitHub
  `ghp_`/`github_pat_`, `sk-`-Modellkeys, AWS `AKIA…`, PEM-Private-Key-Blöcke)
  plus Shannon-Entropie-Check für lange base64-artige Tokens (≥ 20 Zeichen,
  ≥ 4.5 Bits/Zeichen). Fund → Task wird NICHT geschrieben (Exit 2), Meldung
  nur mit redacted Auszug. Bewusste Ausnahme per `--allow-secrets`.
  Hex-only-Tokens sind ausgenommen (Commit-Hashes/SHA256-Beweise sind
  Task-Alltag); die Format-Detektoren decken die real hex-förmigen
  Credential-Shapes ab. NB: Dieses Feature ist bewusst NICHT als Bridge-Job
  baubar — der `dangerous_action`-Wächter des Goal-Loops matcht zwangsläufig
  die Secret-Muster im generierten Diff (Gate-vs-Gate).

### Risk-Level-Policy (kind/adapter → read/build/ops)

`scripts/risk_policy.py` erzwingt eine deklarative Policy: jedes Task-`kind`
hat ein Risk-Level (`echo`/`review`/`research` → read, `implement`/`test` →
build), jeder `adapter` eine Capability (`codex` → build; `echo`/`claude`/
`increment` → read). `ops` (Scheduled Tasks, Push/Merge in die Base, Admin)
erreicht kein kind — Ops-Arbeit läuft nie über die Bridge, nur interaktiv.
Geprüft fail-closed an drei Punkten: `handoff_write` (Exit 3, kein Override),
`handoff_poll` (Error-Result, Task archiviert) und `job_poll` (rc 2, Todo
bleibt offen). Zusätzlich scannt R2 den AUFTRAGSTEXT auf Ops-Verben
(`schtasks`, `Register-ScheduledTask`, Push/Merge auf main/master, Admin-PIN)
— bewusst NICHT den gebauten Diff (Gate-vs-Gate, Lehre L12) und NICHT das
Frontmatter (FP-Fläche Repo-URLs). Unbekannte kind/adapter-Werte werden
abgelehnt (R3); neue Werte brauchen einen bewussten Eintrag in der
Policy-Tabelle (der Drift-Test macht die Suite sonst rot).
Spec: `docs/superpowers/specs/2026-06-12-risk-level-mapping-design.md`.

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
  (Dedup je `notify_key` = `loop_id + reason`-Hash über `state/_notify/sent.json`),
  at-least-once. Read-only auf Eskalationen — schreibt nur den eigenen
  Sidecar-State. DCO-ready (Kernlogik in `notify_new_escalations()`, nur der
  Caller ändert sich).
  - **HTTP-Härtung der Sende-Kante:** Telegram-Fehler werden klassifiziert —
    `4xx` (außer 429) und inhaltliche Ablehnung (`ok:false`) sind **permanent**
    (keine Wiederholung, Eskalation wird `permanent_failed` im Sidecar
    `state/_notify/attempts.json`, Exit-Code 3); `429`/`5xx`/Netzfehler sind
    **transient** — der nächste Trigger-Lauf versucht es erneut, frühestens ab
    `next_retry_at` (`Retry-After`-Header zuerst, sonst exponentielles Backoff,
    max. `MAX_TRANSIENT_ATTEMPTS=6`). **Kein `sleep()` im Lauf** (Retry läuft
    cross-trigger, der Prozess bleibt kurzlebig). Dedup über `loop_id + reason`
    (`trigger|round`): verschärft sich eine Eskalation, gibt es genau **eine**
    neue Benachrichtigung. `--reconcile` räumt `sent.json` und `attempts.json`.
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
- ✅ **441 Tests grün** (Collection + voller pytest-Lauf).

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
