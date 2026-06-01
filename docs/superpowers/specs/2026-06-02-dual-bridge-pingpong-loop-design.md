# Design — Selbst-treibender A↔B-Ping-Pong-Loop (Dual-Bridge)

*Datum: 2026-06-02*
*Projekt: dual-bridge (`~/AI/dual-bridge`, Repo `dynamic-dome/dual-bridge`)*
*Status: Design abgenommen, bereit für writing-plans*

## Problem

Die Bridge beweist heute **eine** Runde A→B→A: `handoff_write` schreibt einen Task,
B verarbeitet ihn (`handoff_poll --watch`), `handoff_collect` sammelt das Result ein.
Es gibt aber **keinen Baustein, der nach Fertigstellung automatisch den nächsten Task
erzeugt** — also keinen selbst-treibenden Loop. Ziel des Users: von A aus einen Loop
anstoßen, der abwechselnd auf A und B echte Arbeit ausführt und so lange läuft, wie wir
ihm sagen (`--max-rounds N`).

## Entscheidungen (aus dem Brainstorming)

- **Use-Case gestuft:** Stufe 1 Echo/Counter (Mechanik-Beweis) → Stufe 2 Bau↔Review →
  Stufe 3 freier Arbeits-Ping-Pong. Jetzt wird NUR Stufe 1 gebaut.
- **A orchestriert zentral**, ein Prozess. B bleibt simpler, unveränderter Worker.
- **Echtes Ping-Pong:** Arbeit passiert WIRKLICH abwechselnd auf A und B (nicht nur B).
- **A's Arbeit inline:** der Treiber ruft den lokalen Runner im selben Prozess.
- **Generischer Umschlag** (`payload + round + loop_id`) von Anfang an — kein Protokoll-Refactor zwischen den Stufen.
- **Stopp per `--max-rounds N`** + **Per-Runde-Timeout** mit sauberem Abbruch.
- **Ansatz A:** neuer `loop_driver.py` auf A, der die bestehenden Bausteine als Bibliothek
  nutzt. Die bewiesene Bridge-Mechanik (Lanes/Claim/Mirror/Recovery) bleibt unangetastet —
  der Loop ist rein additiv.

## Architektur

```
LAPTOP A (loop_driver.py, ein Prozess)          LAPTOP B (handoff_poll.py --watch)
─────────────────────────────────────          ──────────────────────────────────
 round = 0, payload = seed
 while round < max_rounds:
   1. A-Arbeit (inline runner)                  (unverändert; weiß nichts vom Loop)
      payload = run(payload)
   2. write task (B-Lane outbox) ───────────►   claim → run(payload) → result
      kind, adapter, loop-FM                              (B-Lane inbox)
   3. wait_for_result(task_id, T) ◄─────────────────────┘
      └─ timeout/error? → clean abort
   4. payload = result.payload; round += 1
 → final summary: rounds done, last payload, offener task_id (falls Abbruch)
```

### Komponenten

1. **`scripts/loop_driver.py`** (neu, ~150 Z) — die einzige neue Logik: Schleife,
   Rundenzählung, A-seitiger Runner-Aufruf, Timeout-Abbruch, State-Schreiben, Final-Summary.
2. **`scripts/runners.py`** (bestehend) — A ruft `RUNNERS["increment"](...)` inline für
   seine eigene Runde, denselben Vertrag wie B. **+ neuer `increment`-Runner.**
3. **`scripts/bridge_common.py` / `handoff_write` / `handoff_collect`** (bestehend) — als
   Bibliothek genutzt. **Eine kleine Naht:** aufrufbare `wait_for_result(task_id, timeout)`-Funktion
   (aus `handoff_collect` extrahiert oder dünn im Treiber), die das B-Lane-inbox auf
   `result-<task_id>.md` pollt und Drive-Conflict-Copies (`(1)`) ignoriert.

## Datenprotokoll (der Loop-Umschlag)

Additive, absent-safe Frontmatter-Felder, durchgereicht über denselben verbatim-Mirror-
Mechanismus wie die bestehenden `MIRROR_FIELDS` in `handoff_poll`:

| Feld | Typ | Bedeutung |
|---|---|---|
| `loop_id` | string | identifiziert den Loop-Lauf, stabil über alle Runden |
| `round` | int | aktuelle Rundennummer (0-basiert) |
| `payload` | string | durchgereichter Arbeitszustand — St.1 die Zahl, später Code-Diff/Text |

**History** wandert NICHT ins Frontmatter (würde mit jeder Runde wachsen), sondern lebt
A-seitig in **`scripts/state/LOOP-<loop_id>.jsonl`** (append-only, eine Zeile pro Runde:
`{round, side, payload_in, payload_out, task_id, ts, status}`). A hält als Dirigent die
volle History zentral; B sieht pro Task nur den aktuellen `payload`. `state/` ist gitignored.

### payload-Fluss (Counter, Stufe 1, seed="0")

```
Runde 0 (A): increment("0") → "1"  → Task an B {round:0, payload:"1"}
        (B): increment("1") → "2"  → Result      {round:0, payload:"2"}
        A liest "2", schreibt jsonl-Zeile, round=1
Runde 1 (A): increment("2") → "3"  → Task an B {round:1, payload:"3"}
        ...
```

Nach N Runden: payload = seed + 2N (A und B inkrementieren je Runde).

### `increment`-Runner

Liest `payload` als Zahl, gibt +1 zurück. Nicht-numerischer `payload` → `status:error`
(kein stiller Default). Auf A und B registriert (gleicher Vertrag).

Hinweis zur Terminologie: Der Frontmatter-Schlüssel `adapter` wählt den Runner aus
(`handoff_poll` → `runners.RUNNERS.get(adapter)`). `increment` ist also ein neuer
Runner-Key und muss zusätzlich in den `--adapter`-`choices` von `handoff_write` ergänzt
werden (heute nur `echo/codex/claude`). "Adapter" (CLI/FM-Feld) und "Runner" (Registry-Eintrag)
bezeichnen hier dasselbe Auswahlziel.

## Fehlerbehandlung & Abbruch

Stopp-Bedingungen in Prioritätsreihenfolge:

1. **`--max-rounds N` erreicht** → normaler sauberer Stopp + Final-Summary.
2. **Per-Runde-Timeout `--round-timeout T` (Default 300s)** → kommt kein Result, kontrollierter
   Abbruch: Meldung (Runde, offener `task_id`, letzter `payload`), letzter State im jsonl.
3. **B liefert `status: error`** → fail-fast Abbruch, verschleppt keinen kaputten payload,
   meldet B's `error_text`/`stderr_excerpt`. Kein Auto-Retry in St.1.
4. **Strg+C auf A** → KeyboardInterrupt, letzter State gesichert, sauberer Abbruch.

Fail-safe-Prinzipien:
- A wartet gezielt auf **genau diesen `task_id`** (nicht "irgendein Result").
- Drive-Conflict-Copies (`(1)`) werden beim Warten ignoriert (Mechanik existiert).
- **Singleton pro `loop_id`** über das bestehende Lock-Muster aus `handoff_poll`.
- A-seitiger Runner-Crash → fail-fast wie B-Error, State gesichert, Abbruch mit Trace.
- **Offener Task bei Abbruch:** liegen lassen + melden. Der Loop greift NICHT in die
  Lane-Mechanik ein; die bestehende P0-Recovery/Requeue des Pollers bleibt zuständig.

### Bewusst NICHT in Stufe 1 (YAGNI)

- Kein Auto-Retry/Requeue eines getimeouten Tasks durch den Loop.
- Kein paralleler Multi-Loop.
- Keine Resume-Funktion (Loop ab Runde K fortsetzen) — evtl. Stufe 3.

## Testing (Stufe 1, TDD, isoliert)

Gegen ein lokales Lane-Verzeichnis im tmp (bestehendes `conftest.py` mit Env-Snapshot/
Runner-Re-Register nutzen — der Isolations-Fix aus der Vorsession). Kein echtes Drive nötig.

1. **`test_loop_envelope`** — `payload/round/loop_id` korrekt ins Task-FM geschrieben und
   aus dem Result-FM zurückgelesen (Mirror-Pfad).
2. **`test_loop_increment_roundtrip`** — simulierter B-Poll im selben tmp verarbeitet einen
   increment-Task; A liest payload+1. Eine volle A→B→A-Runde ohne Drive.
3. **`test_loop_max_rounds`** — Loop stoppt nach exakt N Runden; jsonl hat N Zeilen;
   payload = seed+2N.
4. **`test_loop_round_timeout`** — kein Result → Abbruch nach T (klein im Test), meldet
   offenen task_id, schreibt letzten State, hängt nicht.
5. **`test_loop_b_error_aborts`** — B-Result `status:error` → fail-fast, payload nicht verschleppt.
6. **`test_increment_runner`** — "3"→"4"; nicht-numerisch → `status:error`.

Ziel: bestehende 56 grün bleiben grün, +6 neue. Danach **ein echter Live-Lauf** über die
reale Bridge (B = `handoff_poll --watch`, A = `loop_driver --max-rounds 3`), Ground-Truth
gegengelesen (P006/P007): jsonl-Zeilen real ansehen, nicht nur Exit-Code.

## Gesamt-Stufung (Ausblick)

| Stufe | Was | Runner | payload-Inhalt | neu zu bauen |
|---|---|---|---|---|
| **1** | Selbst-treibender A↔B-Loop, nackt | `increment` | Zahl | `loop_driver.py`, `increment`-Runner, `wait_for_result`-Naht, 6 Tests |
| **2** | Verteilter Bau↔Review | `codex`/`claude` | Code-Diff + Verdict/Gaps | Runde-Rollen (A baut, B reviewt); payload trägt repo/branch + Verdict; nutzt bestehende `parse_verdict` |
| **3** | Freier Arbeits-Ping-Pong + Endziel | `claude`/`codex` | freier Text/Auftrag | Abbruch-Kriterium (Score/DONE-Marker); evtl. Übergang zu orchestrated-bridge als Treiber-Heimat |

Jede Stufe = eigener spec→plan→impl-Zyklus. Der generische Umschlag trägt alle drei ohne
Protokoll-Umbau. Verwandt: orchestrated-bridge (kennt Goal/Score/Iteration) ist die
natürliche Treiber-Heimat für Stufe 3 — dual-bridge bleibt dann reiner Transport.

## CLI (Stufe 1)

```bash
# auf B (unverändert):
export DUAL_BRIDGE_ENDPOINT=codex@laptop-b
python handoff_poll.py --watch

# auf A (neu):
python loop_driver.py --adapter increment --seed 0 --max-rounds 3 --round-timeout 300
```
