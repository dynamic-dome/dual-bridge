# Design: Claude-Builder-Adapter — `claude-build`

*Datum: 2026-06-13 · Status: approved (User-Review im Chat) · Vorstufe: [[2026-06-12-adapter-git-extraction-design]] · Memory: `claude-adapter-is-review-only-no-build`*

## Ziel

Einen **bauenden** Claude-Adapter `claude-build` einführen, der — symmetrisch zu
`codex` — im Wegwerf-Klon Code erzeugt und denselben `RunnerResult`-Vertrag
(branch/commit/diff) liefert, damit die bestehende Review-/Loop-Maschinerie
unverändert funktioniert, egal wer gebaut hat.

**Primär-Zweck: symmetrischer Loop.** Heute baut nur codex und claude reviewt
(`codex@laptop-a` baut → `claude@laptop-b` reviewt). Mit `claude-build` kann auch
B mit claude bauen (`claude-build@laptop-b` → `codex`-Review auf A) — volle
A↔B-Rollensymmetrie, Rolle/Modell/Richtung bleiben reine Konfiguration.

## Nicht-Ziele (YAGNI)

- **KEINE** Umbenennung des bestehenden `claude`-Reviewers (bleibt review-only,
  capability `read`). `claude-build` ist ein **neuer, getrennter** Adaptername.
- **KEIN** `claude`-Adapter, der je nach `kind` mal `read` mal `build` ist — ein
  Adapter hat genau eine Capability (R1-Modell strikte Gleichheit). Deshalb der
  neue Name.
- **KEINE** generische „agentic-CLI-Builder"-Engine (codex+claude als dünne
  Configs einer gemeinsamen Engine). Erst bei einem echten 3. Builder
  (gemini/ollama) bewerten — würde sonst den live-bewährten codex-Pfad
  destabilisieren.
- **KEIN** injiziertes Prompt-Preamble — der Auftragstext wird roh durchgereicht
  (symmetrisch zu codex). „Nicht committen"-Hinweise gehören in die
  Seed-Konvention, nicht in den Adapter.

## Entscheidungen (im Chat festgelegt)

| # | Frage | Entscheidung |
|---|---|---|
| D1 | Zweck | Symmetrischer Loop (claude baut / codex reviewt). |
| D2 | Naming/Capability | Neuer Adapter `claude-build` (capability `build`); `claude` bleibt review-only. |
| D3 | Tool-Reichweite | **Volle Tools** (Read/Write/Edit/Bash/Glob/Grep) + `bypassPermissions` — Gegenstück zu codex `danger-full-access`. |
| D4 | Externe MCP | **Unterdrückt** (kein playwright/wiki/notebooklm) — weniger Startkosten + kleinere Hang-Fläche. |
| D5 | `--max-turns` | Default **40** (config-überschreibbar). |
| D6 | Finalisierungs-Sequenz | **Nach `adapter_git` extrahieren** (`finalize_build`), codex + claude-build teilen sie. |
| D7 | Struktur | Ansatz A: eigenes Modul `claude_build.py` + geteilter `subprocess_util`. |

## Architektur & Modul-Layout (Ansatz A)

### Neue Dateien
- **`scripts/claude_build.py`** — der `claude-build`-Runner. Spiegelt die
  Orchestrierung von `run_codex_task` (Allowlist → Base-Branch-Resolve → Klon →
  Checkout → exec → `finalize_build`), nutzt `adapter_git` direkt (wie schon
  `_run_echo_build`). Registriert sich via `register_runner("claude-build", …)`.
- **`scripts/subprocess_util.py`** — geteilte Subprocess-Maschinerie:
  - `_kill_process_tree(pid)` — Tree-Kill (Windows `taskkill /T /F`, POSIX
    `killpg`). Claude braucht ihn **zwingend** wie codex: `claude → node →
    claude.exe → MCP-Kinder`; ein `Popen.kill` ließe die Enkel-Prozesse stehen
    (Lehre L8/2026-06-09: orphaned worker hielt den Slot ~50 min offen).
  - `run_with_tree_kill(cmd, cwd, input, timeout, env) -> CompletedProcess` —
    treibt `Popen` selbst, killt bei Timeout den ganzen Baum, raised dann
    `TimeoutExpired`. POSIX: `start_new_session=True` für eigene pgid.
    `text=True, encoding="utf-8", errors="replace"` (cp1252-Robustheit).
- **Tests:** `scripts/test_claude_build.py`, `scripts/test_subprocess_util.py`.

### Geänderte Dateien (minimal, mechanisch)
- **`codex_adapter.py`** — `_kill_process_tree`/`_run_codex_exec` delegieren an
  `subprocess_util` (Namen als Re-Export-Shim erhalten, exakt wie bei der
  `adapter_git`-Extraktion). Steps 6–7 → ein `adapter_git.finalize_build(...)`-Aufruf.
  **Verhalten bit-identisch** → bestehende codex-Tests (`test_codex_adapter`,
  `test_loop_continuity_realgit`) sind der Regressionswächter (P007: laufen lassen,
  Ground-Truth grün).
- **`adapter_git.py`** — neuer `finalize_build(...)` (s.u.). Bleibt **rein git**,
  importiert nicht `runners` → gibt ein result-typ-agnostisches `BuildOutcome`
  (NamedTuple) zurück.
- **`risk_policy.py`** — eine Zeile: `ADAPTER_CAPABILITY["claude-build"] = "build"`.
- **DCO-Miniapp** (separater chirurgischer Commit im DCO-Repo, §7): Preset
  `claude-build` (kind=implement) in `miniapp/js/start.js → BRIDGE_PRESETS` +
  `start.compose.test.js` + `tests/test_miniapp_bridge_compose.py`.
- **README / HOW-TO-USE / CHANGELOG / CLAUDE.md** (Adapter-Liste).

## Der `claude -p`-Build-Aufruf (Kern)

```
claude -p
  --output-format json
  --settings '{"disableAllHooks": true}'     # P009#1: kein Stop/SessionEnd-Hook-Crash
  --permission-mode bypassPermissions        # P009#2: PFLICHT — mit Bash an würde jeder
                                             #   Permission-Prompt am geschlossenen stdin hängen
  --max-turns 40                             # multi-turn Build (DUAL_BRIDGE_CLAUDE_MAX_TURNS)
  --tools Read,Write,Edit,Bash,Glob,Grep     # eingebaute Coding-Tools (kein "" wie Reviewer)
  --strict-mcp-config                        # D4: externe Server NICHT laden (✅ verifiziert 2026-06-13)
  cwd = workdir (Wegwerf-Klon)               # Datei-Tools wirken auf den Klon (wie codex -C)
  Prompt via stdin (P008)                    # roh, symmetrisch zu codex; nicht als Arg
  env = safe_subprocess_env()                # P009#4: ANTHROPIC_API_KEY/AUTH_TOKEN raus → Abo
  getrieben via run_with_tree_kill(...)      # NICHT subprocess.run (multi-turn → Prozessbaum)
```

**Die 5 P009-Härtungen, gemappt:**
1. `disableAllHooks` — auch der globale Block-Hook ist im Build-Subprozess aus.
   Akzeptabel: Grenze ist der Wegwerf-Klon (identisch zu codex `danger-full-access`).
2. `bypassPermissions` — PFLICHT bei Tools an, sonst Hang am DEVNULL-stdin.
3. Prompt via stdin — auf dieser Maschine ist `claude` zwar `.EXE` (nicht `.CMD`),
   stdin ist auf beiden robust.
4. API-Key droppen → Abo (sonst „Invalid API key", [[reference_dco_brain_api_key_leak]]).
5. Parse-first, Exit-Code zuletzt — **aber für einen Builder ist das Artefakt der
   git-Diff**, nicht der geparste Text. Nonzero-Exit **mit** echtem Diff = `done`.

**Unterschiede zum Review-Adapter:** Tools AN statt `""`; `max-turns 40` statt `1`;
`cwd=workdir`; Tree-Kill-Treiber statt `subprocess.run`.

## Finalisierung — `adapter_git.finalize_build`

`finalize_build(workdir, branch, base_branch, task_id, commit_msg) -> BuildOutcome`
(Logik = codex Schritt 6–7 wörtlich):
- Working-Tree-Änderung (`_git_status_porcelain`) → `_git_commit_and_push`.
- Sonst Commits-ahead (`_commits_ahead_of_base`, Self-Commit) → `push
  --force-with-lease` (Continuity-Schutz, Codex-MAJOR 2026-06-03).
- Keins von beidem → `done` mit Note „nur Text, keine Änderung".
- Push-Fehler → `error` mit lokalem Hash + stderr-Auszug (`PUSH_FAILED::`-Form).
- Liefert Diff + `changed_files` gegen Base.

`BuildOutcome = NamedTuple(status, branch, commit, changed_files, diff, error_text,
stderr_excerpt, note)`. `codex_adapter` und `claude_build` mappen es →
`RunnerResult` (jeweils mit ihrer `antwort`).

## Risk-Policy & Routing
- `ADAPTER_CAPABILITY["claude-build"] = "build"` → erlaubt `kind=implement|test` +
  `adapter=claude-build` (Level `build==build`). `kind=review` + `claude-build`
  wird R1-abgelehnt (capability-mismatch) — korrekt, Reviewer bleibt `claude`.
- **Keine Loop-Code-Änderung**: `adapter`-Feld routet generisch über `RUNNERS`;
  `claude-build` registriert sich selbst (Import via `runners`-Konvention).
- Drift-Test (argparse-choices ↔ Policy-Tabelle) wird grün gehalten.

## Fehlerbehandlung / Vertrag
`claude_build`-Runner **raised nie** (Spec-Kontrakt wie codex): jeder Pfad →
`RunnerResult(status=done|error)`. Fälle: `claude` nicht im PATH
(`DUAL_BRIDGE_CLAUDE_BIN`/`shutil.which`); Klon/Checkout-`RuntimeError`; Timeout
(Tree-Kill → error); leere Antwort **und** leerer Diff → error; Diff trotz
nonzero-Exit → done. Repo-Allowlist (`DUAL_BRIDGE_REPO_ALLOWLIST`) wie codex
vorgeschaltet. Timeout: `DUAL_BRIDGE_CLAUDE_TIMEOUT` (mirror `*_CODEX_TIMEOUT`,
`config_value`, Default 600s) — getrennt von `--round-timeout` (A wartet auf B).

## Teststrategie (hier beißen P006/P007/P009)
1. **`test_subprocess_util.py`** — Tree-Kill + Timeout gegen einen Fake-Prozessbaum;
   bestehende codex-Tests müssen grün bleiben (= Extraktions-Beweis, D6).
2. **`test_claude_build.py` mit Fake-`claude`-CLI** (Skript, das Dateien im cwd
   schreibt) — beweist die **Mechanik**: Klon → Fake-Edit → commit+push → diff;
   Self-Commit-Pfad; Leerwert-Pfad (kein Edit → Note); nonzero-Exit-mit-Diff → done;
   Allowlist-Ablehnung; Timeout-Pfad. Fake beweist **nur Mechanik** (P006).
3. **Real-Binary-Live-Beweis** (P007/P009, manuell, an Implementierungszeit):
   echter `claude-build`-Lauf gegen ein Wegwerf-Repo + Negativkontrolle. Verifiziert
   die 4 Real-Binary-Unbekannten + Ground-Truth (Commit liegt wirklich auf dem
   Branch, Tests grün, kein Hang).
4. **Test-Isolation §3**: conftest lenkt Bridge-Root/State auf `tmp_path`; kein Test
   schreibt gegen echten Sharepoint/`state/`/Lock-/Log-Ziele (P015).

## Gegen das ECHTE Binary verifiziert (P006/P007) — ✅ 2026-06-13, claude 2.1.177
Fake-CLI bewies nur Mechanik; ein echter `claude -p`-Lauf gegen ein privates
Wegwerf-Repo (`dynamic-dome/claude-build-live-proof`, Allowlist-gepinnt) klärte
alle 4 Punkte. Positiv-Lauf: `status=done`, Branch `bridge/task-liveproof1`,
Commit `2aab60e` mit `hello.py`, Ground-Truth via `git ls-remote` + Remote-Klon
bestätigt. Negativkontrolle (no-op): `status=done, branch=None, note="claude gab
nur Text, keine Datei-Aenderung"` — kein Phantom-Commit. **Keine Flag-Korrekturen
nötig**, der Aufruf aus Abschnitt 2 läuft unverändert:
- (a) **MCP-Unterdrückung**: `--strict-mcp-config` ✅ akzeptiert, kein Fehler, kein
  externer MCP-Start.
- (b) **`--tools`**: `Read,Write,Edit,Bash,Glob,Grep` ✅ akzeptiert.
- (c) **Self-Commit-Verhalten**: claude committet **nicht** selbst → Working-Tree-
  Pfad dominiert, der Adapter committet+pusht. (Self-Commit-Pfad bleibt via
  `finalize_build` als Fallback abgedeckt.)
- (d) **JSON-Form**: `parse_claude_output` + `_real_text` lieferten echte Prosa
  (`"ok"` bzw. die Build-Zusammenfassung), kein JSON-Dump-Fehlalarm.

## Reihenfolge der Umsetzung
1. `subprocess_util` extrahieren + `test_subprocess_util` (codex-Tests grün halten).
2. `adapter_git.finalize_build` + codex auf den Aufruf umstellen (codex-Tests grün).
3. `claude_build.py` + `test_claude_build` (Fake-CLI, alle Mechanik-Pfade).
4. `risk_policy`-Zeile + Drift-Test.
5. Real-Binary-Live-Beweis (Punkte a–d) → ggf. Flags nachziehen.
6. DCO-Miniapp-Preset (separater Commit, DCO-Repo).
7. Doku (README/HOW-TO-USE/CHANGELOG/CLAUDE.md).
