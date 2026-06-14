# Live-Proof — relay-loop (Stufe B: kollaborativer Erweiterungs-Bau)

*Datum: 2026-06-14 · Maschine: DoMe-Dynamics · codex-cli 0.136.0 + claude 2.1.x*
*Repo: dynamic-dome/relay-loop-live-proof (Wegwerf) · loop_id `loop-20260614-200156-764658-0-de10`*

## Was bewiesen wurde
Der `--mode relay-loop` treibt mit **echtem** codex + claude ein Artefakt
schrittweise voran: beide Modelle bauen abwechselnd, das jeweilige Gegenmodell
reviewt jeden Schritt. Einrichtung: Lanes/State in isoliertem tmp, B-Seite über
den Endpoint-Switching-`b_tick` (handoff_poll reviewt real) — alle Modell-Aufrufe
(codex-build, claude-review, claude-build, codex-review) sind echt, nur der
Drive-Transport ist auf einer Maschine lokal kurzgeschlossen.

## Ablauf (3 Runden, echtes Repo)
| Runde | Builder | Reviewer | Verdikt | Commit |
|---|---|---|---|---|
| 0 | **codex** | **claude** | accepted | `9d7d683` |
| 1 | **claude-build** | **codex-review** | rejected | `b64a481` |
| 2 | claude-build | codex-review | accepted | `e4d874f` |

Ground-Truth auf GitHub (loop-branch): die Modelle bauten echte Funktionen —
„Add char_count text statistic", „Add most_common_words …" — auf einem
akkumulierenden Branch `9d7d683 → 45e330a → b64a481 → e4d874f`.

## Belegte Eigenschaften
- **Rotation bei `accepted`**: R0 codex → R1 claude-build (nach accept gewechselt).
- **Kein Wechsel bei `rejected`**: R1 reject → R2 **derselbe** claude-build bessert
  nach (mit codex-review-Feedback) → accepted. Beweist die reject-Semantik live.
- **Gegenmodell-Review beidseitig**: codex baut → claude reviewt; claude-build baut
  → codex-review reviewt. Volle Symmetrie genutzt.
- **codex-review live ohne Hang** (CLAUDE.md §10.10): R1+R2 codex-review-Reviews
  liefen sauber (read-only + `approval_policy="never"`).
- **Sauberer Abschluss**: `max_rounds=3` erreicht, `accepted=true`, nicht
  escalated/aborted/saturated. Exit 0.

## Reproduktion
`scripts/_relay_live_proof.py` (throwaway, nach dem Proof entfernt) + Seed
`docs/live-proofs/relay-seed.md`. Über die echte Bridge (zwei Geräte):
`loop_driver.py --mode relay-loop --repo <url> --adapter codex --max-rounds 3`.
