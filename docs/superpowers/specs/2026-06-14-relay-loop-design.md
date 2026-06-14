# Design: Relay-Loop — kollaborativer Erweiterungs-Bau (`--mode relay-loop`)

*Datum: 2026-06-14 · Status: approved (User-Review im Chat) · Vorstufe: Reviewer-Symmetrie (Stufe A, Commit `7efeb34`, [[2026-06-14-full-symmetry-plan]]) · Baut auf: goal-loop (Stufe 3)*

## Ziel

Ein neuer Loop-Modus, in dem **beide Modelle abwechselnd bauen** und sich
gegenseitig gegenlesen: codex baut Schritt 1 → claude reviewt → claude baut
Schritt 2 auf codex' Werk auf → codex reviewt → usw. Das Ziel ist **offen**
(„erweitere das Bestehende um einen sinnvollen Schritt in Richtung X"), es gibt
kein fixes Done-Kriterium. Jeder baut immer auf einem bereits *geprüften* Stand
auf, sodass die zwei Modelle ein Artefakt gemeinsam, Schritt für Schritt,
vorantreiben („sich gegenseitig pushen").

Erst durch die in Stufe A gebaute Reviewer-Symmetrie (jedes Modell kann bauen UND
reviewen) ist dieser Loop überhaupt möglich.

## Nicht-Ziele (YAGNI)

- **KEINE** Änderung an `goal-loop`/`build-review`/`ping-pong` — relay-loop ist ein
  eigener, getrennter Modus. Die fixe-Ziel-Semantik (accept = fertig) bleibt dort.
- **KEINE** parallelen Builder über mehrere Projekte (das war B2 im Plan — ein
  separates, späteres Vorhaben). Dieser Loop treibt **ein** Artefakt voran.
- **KEINE** neuen Adapter — nutzt die vorhandenen Builder (`codex`,
  `claude-build`) und Reviewer (`claude`, `codex-review`) unverändert.
- **KEIN** maschinelles „Fortschritts-Scoring" — ob ein Schritt „sinnvoll" ist,
  entscheidet allein das Reviewer-Verdikt (LLM-Urteil), nicht eine Metrik.
- **KEIN** Auto-Merge in die Base als Teil dieses Specs (der bestehende
  `--merge-on-accept`-Mechanismus kann später additiv angedockt werden).

## Entscheidungen (im Chat festgelegt)

| # | Frage | Entscheidung |
|---|---|---|
| D1 | Review-Gate | **Ja** — jede Erweiterung wird vom Gegenmodell gegated (accept/reject/escalate). |
| D2 | Loop-Ende | `max_rounds` \| `dangerous` \| `escalate` (Sättigung **oder** Owner-Richtungsfrage). |
| D3 | Seed | Offenes `## Ziel` (konkret bis vage) + optionale `## Leitplanken`; **keine** Done-Kriterien. |
| D4 | Architektur | **Ansatz A** — neuer Modus `relay-loop` + eigene `run_relay_loop`; Bausteine wiederverwendet. |
| D5 | Rotation | Bau-Rolle wechselt **bei `accepted`**; bei `rejected` bessert derselbe Builder nach. |
| D6 | Review-Basis | Reviewer bewertet den **Inkrement-Diff** dieser Runde (HEAD vs. vorigen akzeptierten Commit), nicht den ganzen Branch. |
| D7 | Sättigung | Über den **Builder**: leerer Build-Diff (der Bau-Agent baut nichts mehr) = saubere Sättigung (Exit 0). Reviewer-`escalate` ist **ausschließlich** eine Owner-Eskalation (fail-closed, Exit 3) — NICHT Sättigung. *(Verfeinert 2026-06-14 nach Verifier-Review: ein maschinell-zuverlässiges Trennen von „escalate=Sättigung" vs. „escalate=Owner" am selben Marker ist fragil; der Builder ist die zuverlässige Sättigungsquelle.)* |
| D8 | Startbuilder | `--adapter` (codex \| claude-build) baut Schritt 1; danach Rotation; Reviewer immer automatisch das Gegenmodell. |

## Architektur & Modul-Layout (Ansatz A)

Alles in `scripts/loop_driver.py` (wie die anderen Modi). Wiederverwendet ohne
Duplikat: `finalize_build`/`adapter_git`, der `reviewer`-Param-Mechanismus +
`fm`-Aufbau aus Stufe A, `_reviewer_adapter`, `scan_dangerous`, `append_state`,
`_escalate`/`write_escalation`, `wait_for_result`, `_state_dir()`, der
`b_tick`-Test-Hook. **Nicht** wiederverwendet: `write_goal_review_task` baut
`## Done-Kriterien` fest ins Prompt-Template — relay hat keine Kriterien, daher
eine eigene `write_relay_review_task` (gleicher `fm`-/`reviewer`-Aufbau, anderer
Auftragstext).

### Neue Funktionen
- **`parse_relay_seed(text) -> tuple[str, list[str]]`** — liefert `(ziel,
  leitplanken)`. Parst `## Ziel` (Prosa) + optional `## Leitplanken`
  (Checklist/Bullets). Fehlt `## Ziel` → `ValueError`. Leitplanken dürfen leer
  sein (das ist der „völlig offen"-Fall).
- **`write_relay_review_task(loop_id, round_no, ziel, leitplanken, loop_branch,
  loop_commit, diff, reviewer)`** — Schwester von `write_goal_review_task`:
  gleicher `fm`-/`reviewer`-Aufbau (kind:review, adapter=reviewer), aber der
  Auftragstext nennt Ziel + Leitplanken statt Done-Kriterien und fragt nach
  „sinnvolle, korrekte, abgeschlossene Erweiterung?" mit den drei Markern
  accepted/rejected/escalate (escalate-Doppelrolle Owner **oder** Sättigung).
- **`_relay_builder(adapter, round_no, start_adapter)`** — bestimmt den Builder
  der Runde: in Runde 0 `start_adapter`; danach Rotation zwischen `codex` ↔
  `claude-build` **nur wenn die Vorrunde akzeptiert wurde** (sonst gleicher
  Builder). Liefert den `build_runner` (analog `_goal_build_runner`).
- **`_relay_round(loop_id, round_no, ziel, leitplanken, builder_adapter,
  reviewer, prev_commit, repo, base_branch, round_timeout, interval, b_tick)`** —
  eine Runde: Build → dangerous-scan → Review des Inkrement-Diffs → Outcome-Dict
  (status, verdict, verdict_reason, commit, diff, saturated, task_id). Spiegelt
  `_goal_build_review_round`, aber mit Inkrement-Diff und Sättigungs-Erkennung.
- **`run_relay_loop(ziel, leitplanken, repo, base_branch, max_rounds,
  round_timeout, interval, start_adapter, build_runner_for=None, b_tick=None,
  loop_id=None)`** — der Loop. Rotiert Builder/Reviewer, akkumuliert auf
  `bridge/<loop_id>`, terminiert nach D2. Gibt ein Summary-Dict zurück.

### Builder/Reviewer pro Runde
- Builder der Runde: `_relay_builder(...)` → `codex` oder `claude-build`.
- Reviewer der Runde: `_reviewer_adapter(None, builder_adapter)` → automatisch das
  Gegenmodell (`codex`→`claude`, `claude-build`→`codex-review`). Ein explizites
  `--reviewer` ist im relay-loop **nicht** erlaubt (Gegenmodell ist konstitutiv);
  CLI weist es ab oder ignoriert es (siehe Offene Punkte O1).

## Datenfluss — eine Runde

1. **Build.** `build_runner(auftrag=relay_prompt, fm=…, workroot=_state_dir()/"work")`.
   `relay_prompt` = Ziel + Leitplanken + „Der bisherige Stand liegt auf dem
   Branch. Erweitere ihn um **genau einen** in sich abgeschlossenen, sinnvollen
   Schritt Richtung Ziel. Halte die Leitplanken ein. Wenn nichts Sinnvolles mehr
   hinzuzufügen ist, ändere nichts und begründe das." Bei `rejected` der Vorrunde
   wird das Reviewer-Feedback angehängt.
2. **Leerer Diff = Sättigungssignal des Builders.** `finalize_build` meldet
   keinen Diff/Commit → `saturated=True` → Loop endet als sauberer Erfolg
   (kein ESCALATION, Exit 0).
3. **dangerous-scan** auf den Inkrement-Diff (`scan_dangerous`) → Treffer →
   `status="dangerous"` → ESCALATION + Exit 3.
4. **Review.** Inkrement-Diff = `adapter_git._git_diff(workdir, prev_commit, HEAD)`
   (Fallback: Diff gegen base, wenn `prev_commit` None — erste Runde).
   `write_relay_review_task(..., diff=inkrement_diff, reviewer=gegenmodell)`:
   „Bewerte, ob dies eine sinnvolle, korrekte, in sich abgeschlossene Erweiterung
   Richtung Ziel (Leitplanken beachten) ist. accepted | rejected | escalate.
   escalate = entweder keine sinnvolle Erweiterung mehr möglich (Sättigung) ODER
   eine Richtungs-/Risiko-Entscheidung für den Owner."
5. **Verdikt** (D5):
   - `accepted` → `prev_commit = HEAD`, Rolle wechselt, `round_no++`.
   - `rejected` → Reviewer-Reason in den nächsten Build-Auftrag, **kein**
     Rollenwechsel, `round_no++`.
   - `escalate` → ESCALATION-Datei (trigger `reviewer_requested`), Exit 3.
6. **State.** `append_state(loop_id, {round, side:"relay", builder, reviewer,
   verdict, verdict_reason, commit, saturated, status})`.

## Verdikt- & Ende-Semantik

| Ereignis | Wirkung | Exit |
|---|---|---|
| `accepted` | Schritt bleibt, Rolle wechselt, weiter | — |
| `rejected` | derselbe Builder bessert nach | — |
| `escalate` (Owner) | ESCALATION + Stop | 3 |
| leerer Build-Diff (Builder baut nichts mehr) | saubere Sättigung „nichts Sinnvolles mehr" | 0 |
| Build-/Review-Error oder Timeout | harter Abbruch (`aborted`, kein ESCALATION) | 1 |
| `dangerous` | ESCALATION + Stop | 3 |
| `max_rounds` erreicht | Stop (so weit gekommen) | 0 |
| Build-/B-Error/Timeout | Abbruch mit Grund | 1 |

Resume (Owner-Eskalation): analog goal-loop über `--resume <loop_id>` auf demselben
Loop-Branch (Continuity). Sättigung und max_rounds sind reguläre Enden, kein Reseed nötig.

## Seed-Format

```markdown
## Ziel
Eine kleine CLI-Toolsammlung für Textverarbeitung (stdlib).
# oder maximal offen:
## Ziel
Erweitere das Repo schrittweise um sinnvolle, zusammenhängende Funktionalität — freie Richtung.

## Leitplanken          (optional, darf fehlen)
- nur Python-stdlib, keine externen Deps
- jeder Schritt bringt mindestens einen Test mit
```

`parse_relay_seed` ist tolerant: fehlende `## Leitplanken` → leere Liste.

## CLI

`--mode relay-loop` ergänzen. Wiederverwendet `--seed`, `--repo`, `--base-branch`,
`--max-rounds`, `--round-timeout`, `--interval`, `--adapter` (= Startbuilder,
`choices` auf `codex`/`claude-build` beschränkt für relay), `--resume`. `--reviewer`
gilt im relay-loop nicht (Gegenmodell ist erzwungen). `--repo` ist Pflicht (wie
goal-loop). Ausgabe analog goal-loop (Runden, akzeptiert/eskaliert, History-Pfad).

## Fehlerbehandlung

- Build-Runner wirft → Runde liefert `status:error`, Loop bricht sauber ab (nie Crash).
- Reviewer-Timeout/Error → `status:timeout`/`error`, Abbruch mit Grund (kein stiller Pass).
- `codex-review`-Hang-Härtung (read-only Sandbox + `approval_policy="never"`) gilt
  unverändert aus Stufe A (live bewiesen).
- Drive-/State-Isolation: läuft über `_state_dir()` (lazy, #7923) und die
  conftest-Isolation — Tests schreiben nie in echten State/Drive.

## Testing (TDD)

Unit (Fake-Builder/-Reviewer via `build_runner_for`-Injektion + `b_tick`-Hook, tmp-State):
- `parse_relay_seed`: Ziel+Leitplanken; nur Ziel; fehlendes Ziel → ValueError.
- `_relay_builder`: Runde 0 = start_adapter; nach accept rotiert; nach reject nicht.
- Reviewer pro Runde = Gegenmodell des aktuellen Builders.
- accepted → Rollenwechsel + prev_commit fortgeschrieben; rejected → kein Wechsel,
  Reason fließt in nächsten Auftrag.
- Sättigung (Reviewer-escalate-Sättigung) → Exit 0, kein ESCALATION; leerer
  Build-Diff → Exit 0.
- escalate (Owner) → ESCALATION-Datei + Exit 3; dangerous-Diff → Stop.
- max_rounds → Stop mit Summary.
- State-jsonl trägt builder+reviewer+verdict je Runde.

Real-Binary-Beweis (separat, Live-Proof analog `docs/live-proofs/`): ein kurzer
2–3-Schritt-Relay (codex↔claude) gegen ein Wegwerf-Repo — beweist Rotation,
Gegen-Review und sauberen Sättigungs-/max_rounds-Stop ohne Hang.

## Offene Punkte

- **O1 `--reviewer` im relay-loop:** abweisen (Exit 2 mit Hinweis) ODER still
  ignorieren. Vorschlag: still ignorieren + Log-Hinweis (das Gegenmodell ist
  konstitutiv, ein Override wäre semantisch widersprüchlich). Im Plan final klären.
- **O2 Inkrement-Diff bei Self-Commit:** wenn der Builder selbst committet (codex/
  claude-build via `finalize_build`), ist HEAD bereits der neue Commit; `prev_commit`
  ist der davor. `_git_diff(prev_commit, HEAD)` ist dann korrekt. Edge: mehrere
  Self-Commits in einer Runde → Diff `prev_commit..HEAD` umfasst alle (gewollt:
  „der Schritt dieser Runde"). Im Plan als Test absichern.
