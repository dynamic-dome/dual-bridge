# HOW-TO-USE — Dual-Laptop-Bridge

Wegweiser für **User UND Agent**. Vollreferenz steht im [README](README.md);
diese Datei ist nur der Index: *was ist das, wo liegt was, wie startet man*.

## Was ist dieses Projekt

Dateibasierte, **bidirektionale** Handoff-Bridge zwischen zwei Laptops über den
Google-Drive-Sharepoint. Jeder Knoten kann senden und empfangen; welcher Knoten
welches Modell fährt (Claude / Codex / Echo) und welche Richtung er bedient, ist
reine Konfiguration (`DUAL_BRIDGE_ENDPOINT`). Aktueller Ausbau: **Stufe 3**
(Goal-Loop + Owner-Eskalation, live bewiesen) auf dem Stage-2a-Fundament (Lanes +
Adapter + endpoint-relative Skripte).

## Wo liegt was

| Pfad | Inhalt |
|---|---|
| `scripts/` | Die 4 Skripte + Adapter + `bridge_common.py` + Tests |
| `scripts/handoff_write.py` | Task schreiben |
| `scripts/handoff_poll.py` | Pollen + verarbeiten (Empfänger); `--watch` nutzt optional `watchdog`-Filesystem-Wakeup |
| `scripts/handoff_collect.py` | Results einsammeln (Sender) |
| `scripts/loop_driver.py` | Goal-Loop / Build-Review-Loop (Stufe 3, `--mode goal-loop`) |
| `scripts/setup.py` | Interaktives Setup: Scout -> Wizard -> Generator -> Validator; schreibt `config.json` |
| `scripts/bridge_status.py` | **Read-only Status-Dashboard** (Tasks/Loops/Eskalationen/Liveness; `--format json`, `--watch`) |
| `scripts/bridge_notify.py` | **Eskalations-Notifier** (pusht neue `ESCALATION-*.md` per Telegram; `--dry-run`, `--digest`, `--reconcile`) |
| `scripts/register_notify.ps1` | Optionaler Windows-Task fuer den Notifier (lokaler Trigger) |
| `scripts/bridge_overnight.py` | **Overnight-Scheduler** (arbeitet `docs/overnight/*.md` nachts als goal-loop ab, Morgen-Digest per Telegram; `--dry-run`, `--queue`, `--no-notify`) |
| `scripts/register_overnight.ps1` | Optionaler Windows-Task fuer den Overnight-Scheduler (taeglich, lokaler Trigger) |
| `docs/overnight/` | Seed-Queue fuer den Overnight-Scheduler (`README.md` erklaert das Format) |
| `scripts/latency_probe.py` | Roundtrip-Latenz messen |
| `README.md` | Vollreferenz: Architektur, Env-Vars, Task-Protokoll |
| `docs/superpowers/specs/2026-05-31-dual-bridge-stage2a-modulare-v2-design.md` | Design-Spec |
| `docs/superpowers/plans/2026-05-31-dual-bridge-stage2a-modulare-v2.md` | Umsetzungs-Plan |
| `~/wiki/wiki/plans/2026-05-30-dual-bridge-master-plan.md` | Master-Plan (alle Stufen) |

## Als User starten (die 3 Befehle)

Alle Skripte laufen auf **beiden** Knoten identisch — Richtung nur per
`DUAL_BRIDGE_ENDPOINT` (Default `claude@laptop-a`).

Ersteinrichtung:

```bash
python scripts/setup.py
```

```bash
cd ~/AI/dual-bridge/scripts
python handoff_write.py --adapter codex --kind implement --repo <url> "Auftrag"
python handoff_collect.py --watch     # auf der Sender-Seite: wartet aufs Result
python handoff_poll.py --watch        # Empfänger: verarbeitet Tasks; optional sofort per watchdog, sonst Intervall-Poll
```

Auf Laptop B vorher Endpoint setzen:
`export DUAL_BRIDGE_ENDPOINT=codex@laptop-b`
(PowerShell: `$env:DUAL_BRIDGE_ENDPOINT="codex@laptop-b"`).

## Als Agent starten

1. **Spec + Plan lesen:** `docs/superpowers/specs/...stage2a...-design.md` und
   `docs/superpowers/plans/...stage2a...md` — sie definieren das Lane-/Adapter-/
   Endpoint-Modell.
2. **Tests laufen lassen** (Ground Truth vor Änderungen):
   `cd ~/AI/dual-bridge/scripts && python -X utf8 -m pytest -q`
   — erwartet **455 grün**. Schneller Snapshot des Bridge-Zustands:
   `python bridge_status.py` (read-only, ändert nichts).
3. Erst dann ändern. README ist die Detailreferenz.

## Aktueller Stand

- ✅ **Stufe 1 (echter codex-Worker) + Stage 2a + Stufe 3 (Goal-Loop) live bewiesen.**
  Lanes, Adapter, Bidirektionalität, endpoint-relative CLI; B→A config-only;
  Live-`claude -p` cross-device (im Goal-Loop-Reviewer); escalate → Reseed →
  accepted @`6ea94bc` (Continuity hart bewiesen, P007). Review-Verdikt-Semantik
  (`kind:review`) als Stage-2b-Kern enthalten.
- ✅ **Status-Dashboard** `bridge_status.py` (read-only) + **Eskalations-Notifier**
  `bridge_notify.py` (Telegram, lokal getriggert, idempotent).
- ✅ **Overnight-Scheduler** `bridge_overnight.py`: arbeitet `docs/overnight/*.md`
  nachts als goal-loop ab, Morgen-Digest per Telegram (read-mostly, fail-soft,
  DCO-ready). + 455 Tests grün.
- ✅ **HTTP-Job-Pull fuer DCO** `scripts/job_poll.py`: pollt
  `GET /api/jobs/next`, verarbeitet den Job im goal-loop und meldet per
  `POST /api/jobs/<id>/result` zurueck. Auf Laptop B aus
  `C:\Users\domes\AI\dual-bridge\scripts` starten.

## Wichtigste Env-Vars

| Variable | Zweck | Default |
|---|---|---|
| `DUAL_BRIDGE_ENDPOINT` | Wer bin ich (`claude@laptop-a` / `codex@laptop-b`) | `claude@laptop-a` |
| `DUAL_BRIDGE_ROOT` | Bridge-Ordner (falls Drive-Pfad auf B abweicht) | Sharepoint-Pfad |
| `DUAL_BRIDGE_WORKROOT` | Arbeitsverzeichnis für codex/claude-Runner | `~/dual-bridge-work` |
| `DUAL_BRIDGE_REPO_ALLOWLIST` | codex-Repo-Allowlist (fnmatch, Komma-getrennt) | leer = alle |
| `TELEGRAM_TOKEN` / `TELEGRAM_CHAT_ID` | Telegram-Credentials für `bridge_notify.py` (mit DCO geteilt; `DUAL_BRIDGE_TG_TOKEN`/`DUAL_BRIDGE_TG_CHAT` als Override) | — |
| `DUAL_BRIDGE_TRANSPORT` | Job-Quelle: fuer DCO-Queue auf `http` setzen | `file` |
| `DCO_BRIDGE_URL` | DCO-API-Basis-URL, muss auf `/api` enden | — |
| `DCO_BRIDGE_TOKEN` | Bearer-Token, identisch zu DCO `BRIDGE_API_TOKEN` | — |
| `DUAL_BRIDGE_WORKER_TYPE` | Worker-Typ fuer DCO-Jobs | `dual-bridge` |

Vollständige Env-Var-Tabelle: [README → Konfiguration](README.md#konfiguration-env-vars).
