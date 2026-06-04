# Live-Proof — Seed 07 (test-live-mirror)

**Ergebnis:** ÜBEREINSTIMMUNG (exit 0)

Unit-Test `test_codex_self_commit_is_seen_as_progress` und der Live-Pfad (`run_codex_task` mit echtem subprocess + echter Fake-codex-Binary, echtes lokales git) stimmen überein: self-commit wird als Fortschritt erkannt (commit gesetzt, Diff trägt `self-committed-line`, push nach origin/bridge/loop-SC bestätigt).

## Was gespiegelt wurde
Unit-Test `test_codex_self_commit_is_seen_as_progress`
(`scripts/test_loop_continuity_realgit.py`) gegen den echten
`run_codex_task`-Live-Pfad — gefahren von `scripts/live_mirror.py` in
einem isolierten `tempfile`-Klon (lokales bare origin, kein Netzwerk,
keine Production-DB, kein Drive-Bridge-Root; CLAUDE.md §3).

Anders als der Unit-Test (der `subprocess.run` wegmonkeypatcht) fährt der
Live-Pfad die echte `subprocess.run`-Schicht gegen eine echte
Fake-codex-Binary — also strikt näher an Produktion. Eine Divergenz wäre
genau die live-only-Bug-Klasse, die der Test nicht sieht (P012).
