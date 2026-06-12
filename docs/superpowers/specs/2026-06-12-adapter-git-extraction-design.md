# Design: Adapter-Gerüst extrahieren — `adapter_git.py` (Triage 1.6)

*Datum: 2026-06-12 · Status: approved (User-Review im Chat) · Quelle: docs/analysis/2026-06-11-erweiterungsliste-repo-registry-triage.md §7 Punkt 3*

## Ziel

Das git-Klon/Commit/Push-Gerüst aus `scripts/codex_adapter.py` (973 Z.) in ein
gemeinsames Modul `scripts/adapter_git.py` extrahieren — als Vorstufe für den
claude-Builder (eigene, spätere Spec; Memory `claude-adapter-is-review-only-no-build`)
und jeden weiteren bauenden Adapter (gemini/ollama erst danach bewerten).

**Reiner behavior-preserving Refactor.** Kein neues Feature, keine API-Änderung
nach außen, keine risk_policy-Änderung. Suite bleibt bei 403 passed.

## Nicht-Ziele (YAGNI)

- KEIN claude-Builder in diesem Zug (risk_policy `implement+claude` bleibt fail-fast).
- KEINE `GitWorkspace`-Klasse / öffentliche API-Umbenennung — verworfen, weil
  Verhaltensrisiko + großer Diff ohne heutigen Nutzen; kann mit dem claude-Builder kommen.
- KEIN Package-Split (`scripts/` bleibt flach, ein neues Modul genügt).

## Was umzieht (verbatim, gleiche Namen/Signaturen)

Block `codex_adapter.py` Z. 183–663 (~480 Z.), Stand `a4e721a`:

| Gruppe | Namen |
|---|---|
| Subprozess-Kern | `_run_git` |
| Credentials/ASKPASS | `_Cred`, `_resolve_https_credential`, `_ASKPASS_HELPER`, `_write_askpass_wrapper` |
| Branch-Auflösung | `_remote_default_branch`, `_resolve_base_branch` |
| Workdir-Lifecycle | `_git_clone_or_pull`, `_diagnose_clone_failure`, `_git_checkout_branch` |
| Status/Diff | `_git_status_porcelain`, `_commits_ahead_of_base`, `_changed_files_vs_base`, `_git_diff`, `_DIFF_LIMIT` |
| Commit/Push/Merge | `_git_commit_and_push`, `merge_accepted_to_base`, `push_branch_on_escalation` |

Unterstrich-Präfixe bleiben erhalten (bewusst: minimaler Diff, monkeypatch-Strings
in Tests bleiben gültig; eine Public-Rename-Runde wäre ein eigener, späterer Schritt).
Benötigte Imports (subprocess/os/Path/tempfile/...) ziehen mit; `adapter_git.py`
bleibt pure stdlib wie der Quellblock.

## Was in `codex_adapter.py` bleibt

codex-Spezifisches: `parse_codex_output` (+ Helfer), `_build_codex_cmd`,
`_run_codex_exec`, `_kill_process_tree`, `run_codex_task`, `_codex_runner`,
`CodexResult`.

**Kritische Invariante (Aufrufstellen, nicht Imports):** Verbleibender Code ruft
die umgezogenen Helfer ausschließlich über den Modul-Namespace auf
(`adapter_git._git_clone_or_pull(...)`), nie über lokal gebundene Namen. Damit
gibt es genau EINEN Monkeypatch-Punkt — Tests, die `adapter_git._run_git`
patchen, treffen auch die Aufrufe aus `codex_adapter`. Die EINE gesammelte
Re-Export-Zeile (`from adapter_git import ...  # noqa: F401 — back-compat shim`)
ist davon ausgenommen: sie bindet nur Aliase für Alt-Importeure, der
verbleibende codex-Code benutzt diese lokalen Namen NICHT.

## Konsumenten-Migration

- `loop_driver.py`: `merge_accepted_to_base` / `push_branch_on_escalation` direkt
  aus `adapter_git` (Z. 730/809).
- `codex_adapter.py`: re-exportiert alle umgezogenen Namen als **Alias**
  (`from adapter_git import ... # noqa: F401` bzw. Modul-Attribut) — Shim für
  Fremd-/Altnutzer, KEIN Code-Duplikat.
- Tests migrieren in diesem Zug auf `adapter_git` (Import + Patch-Ziel):
  `test_base_branch_resolution.py`, `test_clone_diagnose.py`,
  `test_escalation_push.py`, `test_loop_continuity_realgit.py` sowie die
  git-bezogenen Teile von `test_codex_adapter.py`, `test_stage1.py`,
  `test_pingpong_realbuild.py` (der Implementierungs-Plan enumeriert die exakten
  Import-/Patch-Stellen je Datei). codex-exec-Tests (`live_mirror`-Familie)
  bleiben auf `codex_adapter`.

## Fehlerbehandlung

Unverändert — Fehlerpfade (`_diagnose_clone_failure`, Timeout-/Credential-Fehler)
ziehen 1:1 mit um. Keine neuen Fehlerklassen.

## Teststrategie / Erfolgskriterien

1. **Suite-Invariante:** `cd scripts && python -X utf8 -m pytest -q` → 403 passed
   (vorher grün verifiziert, 2026-06-12 23:1x), plus der neue Pin-Test.
2. **Neuer Pin-Test** (`test_adapter_git_shim.py`): für eine Stichprobe der Namen
   `codex_adapter.<name> is adapter_git.<name>` (Shim = Alias, kein Duplikat) und
   ein Quelltext-Guard, dass `codex_adapter.py` keine eigene `def _run_git`/
   `def _git_clone_or_pull`-Definition mehr enthält.
3. **Namespace-Invariante:** Quelltext-Guard im Pin-Test: außerhalb der
   markierten Re-Export-Zeile ruft `codex_adapter.py` keinen umgezogenen Helfer
   über einen nackten Namen auf (Aufrufe nur als `adapter_git.<name>(`).
4. Kein Live-/Cross-Device-Beweis nötig (kein Verhaltenswechsel); der nächste
   reguläre Bridge-Lauf dient als Smoke.

## Risiken

- **Patches ins Leere** (Hauptrisiko) → durch Namespace-Invariante + migrierte
  Patch-Ziele adressiert; Pin-Test schützt die Alias-Identität.
- Vergessene dynamische Zugriffe (`getattr`/String-Patches) → Suite + Grep über
  `codex_adapter\._(run_git|git_|resolve_|write_askpass|remote_default|Cred)`.
- Parallel-Sessions im DCO-Repo sind unbeteiligt (nur dual-bridge-Repo betroffen).
