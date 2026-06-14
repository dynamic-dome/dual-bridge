# Volle Bridge-Symmetrie — Implementierungsplan (dual-bridge)

*Erstellt: 2026-06-14 · Repo: `C:\Users\domes\AI\dual-bridge` · Branch main @ 09b1bb1*
*Test-Isolation: `scripts/conftest.py` autouse `_isolate_dual_bridge_state` (tmp_path, kein echtes Drive) — ABER `loop_driver.STATE_DIR` ist eine eingefrorene Modul-Konstante, siehe Vorarbeit T13.*

## Ziel
Die Bridge soll **völlig symmetrisch** laufen: beide Modelle (claude, codex) können
sowohl **bauen** als auch **reviewen**, und auf Wunsch laufen beide als Builder, sodass
sie sich gegenseitig pushen / beide Projekte erweitern.

## Ist-Zustand (Ground Truth 2026-06-14)

| Rolle | claude | codex |
|---|---|---|
| **Bauen** | ✅ `claude-build` (capability build) | ✅ `codex` (capability build) |
| **Reviewen** | ✅ `claude` (capability read, `claude_adapter.run_claude`, text-only Verdikt) | ❌ **fehlt** |

Die Bau-Achse ist symmetrisch. Die Review-Achse nicht: `write_review_task`
(`loop_driver.py:333`) und `write_goal_review_task` (`:373`) schreiben beide
**hartkodiert `"adapter": "claude"`**. Egal wer baut — immer claude reviewt.
Der Kommentar in `_goal_build_runner` („claude baut / codex reviewt") ist
aspirational; der Code macht es nicht. Bei `--adapter claude-build` reviewt claude
seinen eigenen Build → keine Modell-Diversität, kein echtes Gegenlesen.

**Design-Entscheidung (User 2026-06-14):** Reviewer-Wahl = **Auto-Gegenmodell als
Default + explizites `--reviewer`-Override** (Option 3). Auto: codex baut → claude
reviewt; claude-build baut → codex reviewt. Override erlaubt jede Kombination.

---

## Stufe A — Reviewer-Symmetrie (Voraussetzung für alles Weitere)

> **Fortschritt 2026-06-14:** A1–A4 implementiert + grün (TDD). A5 (Real-Binary-
> Beweis) und A6 (DCO-Presets) offen. Vorarbeit T13 ✅.

### A1 — codex-review-Adapter (Kern)
**Datei:** `scripts/codex_review_adapter.py` (neu), Vorbild `scripts/claude_adapter.py`

- Neuer Runner `codex-review`: `codex exec` **text-in / text-out**, gibt nur ein
  Verdikt zurück. **Kein** Klon / Branch / Commit / Push (der Reviewer ist tool-los,
  der Diff ist im Prompt eingebettet — exakt wie `run_claude`). Re-use von
  `parse_codex_output` aus `codex_adapter` (kein Duplikat).
- **Risiko-Hotspot (CLAUDE.md §10.10):** codex-exec read-only-Sandbox-Probing-Hang.
  Ein reiner Text-Review braucht KEINEN Workdir-Write. Flags müssen so gesetzt sein,
  dass codex nicht in die `%TEMP%`-Probing-Schleife fällt:
  `-c approval_policy="never"`, Prompt via stdin (P008), `safe_subprocess_env`
  (API-Key-Strip, [[reference_dco_brain_api_key_leak]]), Tree-Kill-Timeout
  (`subprocess_util.run_with_tree_kill`). Sandbox-Modus für reinen Text-Review
  empirisch bestimmen — bevorzugt read-only; wenn das Probing auslöst, ein
  Wegwerf-Workdir + `danger-full-access` wie beim Builder, ohne Commit.
- Output-Parsing folgt P007: ERST parsen, dann Exit-Code (Exit kann lügen).

**Tests (`scripts/test_codex_review_adapter.py`, neu):**
- Verdikt-Parsing (accepted / rejected / escalate) aus realem codex-Output-Shape.
- Timeout → `RunnerResult(status="error")`, nie raise.
- Leere Antwort → error, kein stiller Pass.
- `codex` nicht im PATH → klarer error.

### A2 — risk_policy
**Datei:** `scripts/risk_policy.py:28` (`ADAPTER_CAPABILITY`)

- `"codex-review": "read"` ergänzen (analog `claude: read`).
- **Pflicht-Reihenfolge:** Policy-Eintrag ZUERST, sonst zieht der Drift-Test
  (`test_risk_policy.py`) die Suite rot (CLAUDE.md Risk-Policy-Regel).
- Test in `test_risk_policy.py`: `kind=review` + `adapter=codex-review` → erlaubt;
  `adapter=codex-review` + `kind=implement` → `level-mismatch`.

### A3 — Reviewer-Wahl im Loop
**Datei:** `scripts/loop_driver.py` (`write_review_task:318`, `write_goal_review_task:356`)

- `adapter`-Feld parametrisieren statt hardcoded `"claude"`.
- `_goal_reviewer(reviewer, builder_adapter)`-Helper (Vorbild `_goal_build_runner:651`):
  - explizites `reviewer` → nutzen;
  - sonst Auto-Gegenmodell: builder `codex` → reviewer `claude`; builder
    `claude-build` → reviewer `codex-review`; builder `echo` → reviewer `claude`
    (Smoke unverändert).
- `--reviewer {claude,codex}`-CLI-Flag (`:1017` ff., neben `--adapter`). `codex` →
  intern `codex-review`. Default `None` = Auto.
- Durchreichen durch `run_build_review_loop` / `run_goal_loop` → die beiden
  `write_*review_task`-Aufrufe.

### A4 — Registrierung & Routing
- `register_runner("codex-review", …)` im neuen Adapter.
- `scripts/conftest.py:69` `_ensure_runners_registered` um `("codex_review_adapter",
  "codex-review")` erweitern (sonst Leak-Klasse, vgl. bestehender Kommentar).
- `handoff_poll.py`-Routing prüfen: review-Tasks mit `adapter=codex-review` müssen
  den neuen Runner treffen (vermutlich automatisch über RUNNERS, verifizieren).

### A5 — Real-Binary-Beweis (kein Fake, P006)
- Gegen echtes `codex` (Version notieren): **codex reviewt einen claude-Build**.
  - Positivkontrolle: korrekter Build → `VERDICT:accepted`.
  - Negativkontrolle: lückenhafter Build → `VERDICT:rejected` mit echter Begründung.
- Ground-Truth dokumentieren (analog `docs/live-proofs/`), keine Flag-Korrekturen
  im Nachhinein verschweigen.

### A6 — DCO-Miniapp-Presets (CLAUDE.md-Pflicht)
**Dateien:** `dynamic_central_orchestrator/miniapp/js/start.js` (`BRIDGE_PRESETS`),
`start.compose.test.js`, `tests/test_miniapp_bridge_compose.py`

- Presets für die neuen Builder×Reviewer-Kombis (mind. „claude baut / codex reviewt").
- Compose-Maske bietet nur Presets — beide Test-Dateien nachziehen, Cache-Pin.

### A7 — 3-Agenten-Codex-Review (Policy §9) zum Abschluss.

---

## Stufe B — Beide bauen / gegenseitig pushen (Ausbau, User-Ziel)

> Erst nach Stufe A sinnvoll — sie liefert den fehlenden Baustein (jeder kann
> reviewen), auf dem Rollen-Wechsel überhaupt aufsetzt.

Zwei Richtungen, getrennt umsetzbar:

- **B1 Rollen-Rotation an EINEM Ziel:** im goal-loop wechselt die Bau-Seite pro Runde
  (oder bei `rejected`): Runde n codex baut / claude reviewt → Runde n+1 claude baut
  (auf dem bestehenden Loop-Branch + Review-Gaps) / codex reviewt. „Sich gegenseitig
  pushen" = jeder baut auf dem Werk des anderen auf. Erfordert: Builder-Auswahl pro
  Runde statt einmalig; Branch-Continuity über Modell-Wechsel hinweg (beide committen
  auf denselben `bridge/<loop_id>`-Branch).
- **B2 Zwei parallele Builder / zwei Projekte:** beide Endpunkte bauen unabhängig
  (codex erweitert Projekt X, claude Projekt Y), jeweils mit Gegen-Review. Nutzt die
  bestehende Lane-/Endpoint-Mechanik; primär Orchestrierung (DCO/Scheduler), wenig
  neuer Bridge-Code.

B1/B2 in eigener Brainstorm-/Spec-Runde schärfen, sobald Stufe A grün ist.

---

## Vorarbeit / Aufräumen (klein, unabhängig, vor oder parallel)

- **T13 (#7923) — Loop-Test-Isolation:** `loop_driver.STATE_DIR` ist Modul-Konstante
  (`:25`), eingefroren auf `scripts/state/` → Loop-Tests leaken echte `LOOP-*.jsonl`.
  Fix: lazy `_state_dir()` die `DUAL_BRIDGE_ROOT`/Override frisch liest (Lazy-statt-
  Konstante, CLAUDE.md §3.4) + conftest-Override + Poison-Guard. **Relevant für diesen
  Plan:** Stufe A fügt Loop-Tests hinzu, die sonst weiter leaken.
- **T14 — Wegwerf-Repo** `dynamic-dome/claude-build-live-proof` löschen
  (`gh auth refresh -h github.com -s delete_repo`, dann `gh repo delete`). Für A5 ggf.
  ein neues Wegwerf-Repo (codex-review-live-proof).
- **T11 — erledigt** (DCO `75eab5f` ist auf origin/master).
