# Ping-Pong-Seed (Stage 1) — diff-prüfbarer Runden-Zwang

Auftrags-Payload für `loop_driver.py --mode ping-pong` mit einem echten
git-bauenden Adapter (`codex`/`claude`). Anders als der Goal-Loop-Seed
(`stage3-goal-loop-seed*.md`) beschreibt dieser Seed **keinen Endzustand**,
sondern einen **pro-Runde-Inkrement**: jede Runde MUSS genau eine neue Funktion
hinzufügen. Der Funktionsname kodiert die laufende Nummer, damit „eine Funktion
zugekommen" allein aus dem Diff prüfbar ist — kein Projekt-Kontext nötig
(adressiert den tool-losen-Reviewer-Design-Mismatch).

Hintergrund: Der symmetrische A↔B↔A-Bau-Loop wurde 2026-06-04 mechanisch
gefixt + live bewiesen (`3fc99ea`, `test_pingpong_realbuild.py`). Beim Live-Lauf
lasen beide Agenten einen vagen Auftrag („build something") als **bereits
erledigt** und bauten nichts Neues — die Mechanik hielt, die Aufgabe trug nicht.
Dieser Seed schließt diese Lücke.

---

## Payload (an `--seed` übergeben)

```
Append exactly ONE new function to the file `pingpong_chain.py` in the repo root
(create the file if it does not exist). Build on whatever is already in the file —
never delete or rewrite existing functions.

Each function must be named `step_<N>` where <N> is the next unused integer
(the file starts empty -> add `step_1`; if `step_1..step_k` already exist ->
add `step_<k+1>`). Each `step_<N>` takes no arguments, has a one-line docstring,
and returns the integer <N>.

So a correct round adds, and ONLY adds, a block of exactly this shape:

    def step_<N>() -> int:
        """Ping-pong round <N>."""
        return <N>

Do nothing else. Commit the single-function addition.
```

## Warum das diff-prüfbar ist (Reviewer-Kriterien)

Ein Reviewer, der NUR den Diff sieht, kann jede Runde hart beurteilen:

- [ ] der Diff fügt **genau einen** `def step_<N>` hinzu (added lines, kein removed)
- [ ] `<N>` ist die **nächste** Nummer (höher als jede schon im File vorhandene `step_*`)
- [ ] die Funktion hat die exakte Form oben (type-hint `-> int`, Docstring, `return <N>`)
- [ ] **keine** bestehende `step_*`-Funktion wurde geändert oder gelöscht

Verletzt eine Runde eines davon (nichts gebaut, Nummer übersprungen/wiederholt,
Altbestand angefasst) → der Diff zeigt es, der Reviewer eskaliert/lehnt ab.

## Aufruf (A = Conductor, B = Poller via Watchdog/handoff_poll)

```bash
# B (Endpoint gesetzt): handoff_poll.py --watch
# A:
python loop_driver.py --mode ping-pong --adapter codex --repo <url> \
    --max-rounds 4 --round-timeout 600 \
    --seed "$(python -c "import pathlib,sys; t=pathlib.Path('docs/live-proofs/stage1-pingpong-seed.md').read_text(encoding='utf-8'); print(t.split('```',2)[1].strip())")"
```

(Der Payload ist der erste fenced Code-Block oben; der Einzeiler zieht ihn heraus,
damit Auftragstext und Doku eine einzige Quelle bleiben.)

## Continuity-Beweis nach dem Lauf

`pingpong_chain.py` auf dem Loop-Branch `bridge/<loop_id>` muss `step_1..step_R`
für R = `rounds_done` enthalten (eine pro Runde, lückenlos, aufsteigend). Fehlt
eine Nummer oder doppelt sich eine → Continuity- oder Auftrags-Bruch.
