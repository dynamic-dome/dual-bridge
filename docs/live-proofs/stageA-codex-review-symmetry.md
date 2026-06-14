# Live-Proof — codex-review-Adapter (Stufe A: volle Reviewer-Symmetrie)

*Datum: 2026-06-14 · Maschine: DoMe-Dynamics (codex@laptop-b) · codex-cli 0.136.0*

## Was bewiesen wurde
Der neue `codex-review`-Adapter (`scripts/codex_review_adapter.py`, capability=read)
reviewt einen eingebetteten Diff gegen das **echte** codex-Binary und liefert ein
sauberes `VERDICT`, **ohne** in den read-only-Sandbox-/Approval-Probing-Hang zu
fallen (CLAUDE.md §10.10 — die zentrale Risikofrage der Stufe A, da codex 0.136
genau die Version ist, die in §10.10 als deadlock-anfällig dokumentiert ist).

## Flags, die den Hang verhindern
`codex exec -s read-only -c approval_policy="never" --skip-git-repo-check -`
(Prompt via stdin). `approval_policy="never"` ist der eigentliche Fix: ein
read-only-Lauf, der sonst auf eine Approval für Schreib-Probing wartet, kehrt
stattdessen sofort zurück. Ein Review schreibt nichts → read-only genügt (anders
als der Builder, der `danger-full-access` für pytest-`%TEMP%`-Writes braucht).

## Ergebnis (Positiv- + Negativkontrolle)
| Kontrolle | Diff | Dauer | VERDICT |
|---|---|---|---|
| Positiv | `add(a,b)` → `a + b` (erfüllt Kriterium) | 17,3 s | **accepted** ✓ |
| Negativ | `add(a,b)` → `a - b` (Bug) | 15,8 s | **rejected** ✓ |

Kein Hang, sauberer Exit, korrekte Begründung in beiden Fällen. `status=done`,
`branch=None` (der Reviewer erzeugt nie einen git-Branch). Damit ist die
Review-Achse symmetrisch: codex baut → claude reviewt **und** claude baut → codex
reviewt (Auto-Gegenmodell, `--reviewer`-Override).

## Reproduktion
Über die Bridge: `loop_driver --mode goal-loop --adapter claude-build` wählt jetzt
automatisch `codex-review` als Reviewer (Auto-Gegenmodell). Explizit erzwingbar
mit `--reviewer codex`. Unit-Tests: `test_codex_review_adapter.py` (6),
`test_loop_driver.py::test_reviewer_adapter_selection`,
`test_risk_policy.py::test_codex_review_is_a_reviewer`.
