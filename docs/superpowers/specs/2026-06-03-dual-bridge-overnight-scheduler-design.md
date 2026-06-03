# Design-Spec: Overnight-Scheduler für dual-bridge

- **Datum:** 2026-06-03
- **Status:** Entwurf (zur Freigabe)
- **Autor:** DoMe + Computer
- **Scope-Komponente:** `scripts/bridge_overnight.py` (neu), `scripts/register_overnight.ps1` (neu)
- **Baut auf:** `loop_driver.py` (goal-loop), `bridge_notify.py` (Telegram), `bridge_status.py`

---

## 1. Problem

Der Goal-Loop (`loop_driver.py --mode goal-loop`) ist live bewiesen, läuft aber nur,
wenn ein Mensch ihn von Hand startet. Nachts passiert nichts. Ich möchte mehrere
vordefinierte Ziele (Seeds) über Nacht **autonom nacheinander** abarbeiten lassen und
morgens **eine** Telegram-Zusammenfassung sehen, was accepted, was eskaliert und was
fehlgeschlagen ist.

## 2. Zielbild

Ein **Batch-Runner**, der eine **Queue von Seed-Dateien** der Reihe nach als
`goal-loop` ausführt, jedes Ergebnis robust einsammelt und am Ende einen
**Morgen-Digest** per `bridge_notify.py` sendet. Eskalationen kommen ohnehin schon
einzeln per Telegram (der Notifier-Task läuft parallel) — der Scheduler ergänzt die
*Batch-Sicht*.

## 3. Entscheidungen (mit dem Owner abgestimmt)

| Thema | Entscheidung |
|---|---|
| **Aufgabe** | Queue vordefinierter Seeds (`docs/overnight/*.md`) nacheinander als `goal-loop`. |
| **Trigger** | **Lokal** (Windows-Task, `register_overnight.ps1`), aber **DCO-ready** gekapselt — nur der Caller wechselt später. |
| **Ergebnis-Meldung** | Über `bridge_notify.py`: Eskalationen einzeln (bestehender Task) + **Morgen-Digest** (accepted/escalated/failed). |
| **Resume** | Nein für v1 — jeder Seed startet einen frischen Loop. Resume bleibt manuell (bewusst, fail-closed). |

## 4. Architektur

```
register_overnight.ps1  (Trigger, lokal, OPTIONAL)
        │  täglich 02:00 →
        ▼
bridge_overnight.py  ── liest Queue (docs/overnight/*.md, alphabetisch)
        │
        ├─ je Seed:  loop_driver.main(["--mode","goal-loop","--repo",…,"--seed",…])
        │             → Exit 0=accepted | 3=escalated | 2=config | 1=fehler
        │             → Ergebnis in run-record sammeln
        │
        ├─ State:  state/_overnight/runs/<UTC-stamp>.json   (ein Record je Batch-Lauf)
        │
        └─ Abschluss:  bridge_notify.send_overnight_digest(records)  → Telegram
```

### 4.1 DCO-Readiness (gleiches Muster wie der Notifier)

Die gesamte Logik liegt in **`run_overnight(seeds, run_fn=None, …) -> BatchResult`**.
- `run_fn` ist injizierbar (Default = realer `loop_driver.main`-Aufruf in Subprozess).
  → Tests injizieren einen Fake; DCO injiziert später seinen eigenen Caller.
- Der **lokale Windows-Task ist nur ein dünner Aufrufer** von `main()`. Für DCO ändert
  sich ausschließlich, *wer* `run_overnight()` aufruft — die Kernlogik bleibt unberührt.

## 5. Queue-Format

- Verzeichnis: **`docs/overnight/`** (neu). Jede `*.md` ist ein Seed im bekannten
  goal-loop-Format (`## Ziel`, `## Done-Kriterien`) — identisch zu
  `docs/live-proofs/stage3-goal-loop-seed.md`.
- **Reihenfolge:** alphabetisch nach Dateiname (Owner steuert via Prefix `01-…`, `02-…`).
- **Leeres/fehlendes Verzeichnis:** kein Fehler → 0 Seeds → Digest „nichts zu tun".
- **`.skip`-Suffix** oder Unterordner `_done/` werden ignoriert (Owner kann Seeds
  deaktivieren, ohne sie zu löschen).

## 6. Pro-Seed-Ablauf & Exit-Mapping

`loop_driver`-Exit-Contract (verifiziert in `loop_driver.py:main`):

| Exit | Bedeutung | Scheduler-Aktion |
|---|---|---|
| `0` | accepted | als `accepted` werten, weiter zum nächsten Seed |
| `3` | escalated | als `escalated` werten (Notifier meldet Detail einzeln), weiter |
| `2` | config/resume-Fehler | als `error` werten, weiter (kein Abbruch des Batches) |
| `1` | sonstiger Fehler | als `error` werten, weiter |

**Robustheit:** Ein gescheiterter Seed bricht den Batch **nicht** ab (at-most-each-once,
fail-soft). Jeder Seed bekommt ein **Timeout** (`--round-timeout` an `loop_driver`
durchgereicht + harter Wall-Clock-Cap je Seed via Subprozess-Timeout).

## 7. State (read-mostly, eigener Sidecar)

- Verzeichnis: **`state/_overnight/runs/<UTC-ISO>.json`** — ein Record je Batch-Lauf.
  Analog zum Notifier-Sidecar (`state/_notify/`). Der Scheduler schreibt **nur** hier;
  Loop-Artefakte (`ESCALATION-*.md`, Branches) erzeugt `loop_driver` selbst.
- Record-Schema:
  ```json
  {
    "started": "2026-06-04T00:00:00Z",
    "finished": "2026-06-04T01:12:00Z",
    "seeds": [
      {"file": "01-foo.md", "goal": "…", "loop_id": "…", "exit": 0,
       "outcome": "accepted", "rounds": 2, "duration_s": 412}
    ],
    "summary": {"accepted": 1, "escalated": 1, "error": 0, "total": 2}
  }
  ```
- Schreiben atomar über `bc.write_text_atomic` (wie Notifier).

## 8. Digest (im Notifier, nicht im Scheduler)

Neue Funktion in `bridge_notify.py`:
**`send_overnight_digest(record, send_fn=None) -> int`** — baut die Nachricht und
sendet sie über denselben `_post_telegram`-Pfad (Markdown, escaped). Beispiel:

```
🌙 *dual-bridge Overnight* (2026-06-04)
2 Seeds · ✅ 1 accepted · ⚠️ 1 eskaliert · ❌ 0 Fehler
• 01-foo.md → accepted (2 Runden)
• 02-bar.md → eskaliert (max_rounds) — siehe ESCALATION
Dauer: 1h12m
```

Begründung: Telegram-Transport und Escaping leben bereits im Notifier — der Scheduler
bleibt transport-agnostisch und ruft nur `send_overnight_digest()`.

## 9. CLI

```
python bridge_overnight.py [--dry-run] [--queue docs/overnight] [--repo URL]
                           [--max-rounds N] [--round-timeout S] [--no-notify]
```

| Flag | Wirkung |
|---|---|
| `--dry-run` | listet die Queue + geplante Aufrufe, startet **keine** Loops, sendet nichts |
| `--queue` | Queue-Verzeichnis (Default `docs/overnight`) |
| `--repo` | Repo-URL für alle Seeds (verpflichtend für echten Lauf, wie goal-loop) |
| `--max-rounds` / `--round-timeout` | an `loop_driver` durchgereicht |
| `--no-notify` | Batch läuft, Digest wird **nicht** gesendet (nur State) |

**Exit-Codes des Schedulers:** `0` = Batch durchgelaufen (auch mit Einzel-Eskalationen),
`2` = Fehlkonfiguration (z.B. `--repo` fehlt bei nicht-leerer Queue), `1` = unerwarteter
Abbruch (z.B. Digest-Sendefehler nach erfolgreichem Batch → Batch-State bleibt erhalten).

## 10. Trigger — `register_overnight.ps1`

Analog zu `register_notify.ps1`:
- Task **`DualBridgeOvernight`**, `New-ScheduledTaskTrigger -Daily -At 02:00`
  (Zeit per `-At`-Param überschreibbar).
- `-AllowStartIfOnBatteries`, `-WakeToRun` optional per Schalter (Owner-Entscheidung).
- Header dokumentiert `--dry-run`-Test und `Unregister-ScheduledTask`.
- **OPTIONAL** — der Scheduler funktioniert ohne Task standalone per `python bridge_overnight.py`.

## 11. Sicherheit / Invarianten

- **Read-mostly:** schreibt nur `state/_overnight/`. Keine Loop-Artefakte, kein Repo-Write.
- **Poison-Guard bleibt aktiv:** erbt die conftest-Schutzregeln; Tests nie gegen
  `dynamic_sharepoint`.
- **Fail-soft je Seed**, aber **fail-closed bei Config** (kein `--repo` → Exit 2, nichts gestartet).
- **Idempotenz:** kein Resume in v1 → kein Risiko doppelter Schreibzugriffe auf denselben Loop.
- **Subprozess-Härtung:** `loop_driver` wird über `bc.safe_subprocess_env` + UTF-8-Runtime
  aufgerufen (wie die übrigen Runner).

## 12. Tests (TDD, dual-runnable, isoliert)

Wie bei Notifier/Dashboard: `test_bridge_overnight.py`, `_fresh()`/`_reload()`,
`run_fn`/`send_fn` injiziert, State via `DUAL_BRIDGE_STATE`-tmp isoliert.

1. Leere/fehlende Queue → 0 Seeds, Record `total:0`, Digest „nichts zu tun".
2. Queue-Reihenfolge alphabetisch; `.skip` und `_done/` ignoriert.
3. Exit-Mapping: 0→accepted, 3→escalated, 2/1→error (Fake-`run_fn`).
4. Ein fehlschlagender Seed bricht den Batch **nicht** ab (nachfolgende laufen).
5. `--dry-run`: kein `run_fn`-Aufruf, kein Send, kein State-Write.
6. State-Record-Schema korrekt + atomar geschrieben; Sidecar isoliert (kein Leak).
7. `send_overnight_digest()` baut korrekte Summary-Zeile, escaped Seed-Namen,
   sendet über injizierten `send_fn`; `--no-notify` unterdrückt den Send.
8. Config-Guard: nicht-leere Queue ohne `--repo` → Exit 2, kein `run_fn`-Aufruf.
9. Subprozess-Timeout je Seed → als `error` gewertet, Batch läuft weiter.

Akzeptanz: voller Lauf grün, Collection-Count steigt, kein State-Leak, `--dry-run`
ist beweisbar seiteneffektfrei.

## 13. Bewusst NICHT in v1

- Resume eskalierter Loops (bleibt manuell, fail-closed).
- Parallele Seeds (seriell ist nachts ausreichend und ressourcenschonend).
- DCO-Anbindung (nur vorbereitet via `run_fn`-Injektion, nicht verdrahtet).
- Dynamische Queue aus DCO-todos.db (späterer Scope).
