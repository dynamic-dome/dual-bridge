# Dual-Bridge Stufe 2 — Bau↔Review-Loop (Stage 2b)

*Datum: 2026-06-02*
*Autor: Claude (Opus 4.8), nach Brainstorming + Ground-Truth-Code-Verifikation*
*Projekt: Dual-Laptop-Bridge (`~/AI/dual-bridge`, Repo `dynamic-dome/dual-bridge`)*
*Status: Design — zur Umsetzung freigegeben nach User-Review*

## Kontext & Motivation

Stufe 1 ist live cross-device bewiesen: ein selbst-treibender A↔B-Ping-Pong-Loop
(`loop_driver.py`), in dem A inline arbeitet, einen Task an B schreibt, auf B's Result
wartet und B's Payload in die nächste Runde nimmt. Symmetrisch: beide Seiten benutzen
denselben Adapter, der Payload ist eine Zahl (`increment`-Runner), der Loop läuft eine
feste Rundenzahl.

Stufe 2 macht aus dem symmetrischen Spielzeug-Loop einen **asymmetrischen, selbst-
korrigierenden Bau↔Review-Loop**: **A baut Code** (codex, echter Git-Branch), **B reviewt**
(claude, `kind:review` → Verdikt). `accepted` beendet den Loop; `rejected` lässt A auf
demselben Branch nachbauen, mit den Reviewer-Gaps als neuem Auftrag.

### Ground-Truth: was bereits gebaut ist (verifiziert am Code, nichts neu)

Die Stage-2a-Fundament-Arbeit UND der Review-Mechanismus pro Einzeltask sind fertig und grün:

- **Lanes + Adapter-Modell** (`bridge_common`, richtungsgetrennte Lanes, `adapter`-Frontmatter).
- **Runner-Registry** (`runners.py`): `RunnerResult`-Dataclass — bereits **mit** `verdict` /
  `verdict_reason`-Feldern und `to_markdown()`-Rendering inkl. Verdikt- und Git-Artefakt-Block.
- **`run_codex`** (`codex_adapter.run_codex_task`): cloned, branched, ruft `codex exec` (stdin-
  Prompt P008, `--skip-git-repo-check`, `-o` answer-file L22), committet + pusht.
- **`run_claude`** (`claude_adapter.run_claude`): headless `claude -p`, P006/P009-gehärtet.
- **`parse_verdict`** (`handoff_poll.py`): extrahiert `VERDICT: accepted|rejected`, **fail-closed**
  (kein Marker / leer / unbekannt → `rejected`).
- **`kind: review`-Verdrahtung** (`handoff_poll.py:147-151`): bei `kind==review` ∧ `status==done`
  wird `parse_verdict(result.antwort)` aufgerufen, Verdikt landet im Result-Frontmatter;
  `handoff_collect` zeigt es an. Tests in `test_gate_evidence.py` (accepted/rejected/fail-closed).
- **`loop_driver.py`** (Stufe 1): Ping-Pong-Mechanik, `wait_for_result` mit `round_timeout`,
  append-only JSONL-History (`state/LOOP-<loop_id>.jsonl`), Singleton-Lock, fail-safe Abbruch.

### Der Branch-Knackpunkt (am Code gefunden — Kernentscheidung)

`run_codex_task` leitet den Branch aus der task_id ab (`branch = f"bridge/task-{task_id}"`,
`codex_adapter.py:165`) und cloned von `base_branch`. Da **jeder** Aufruf eine neue task_id hat,
würde **jede Bau-Runde frisch von `base_branch` branchen** und die Arbeit der Vorrunde nicht
sehen. „A baut auf demselben Branch nach" ist also **keine** vorhandene Fähigkeit, sondern
verlangt eine (kleine, additive) Code-Änderung.

**Entscheidung (Weg A — stabiler Loop-Branch):** `codex_adapter` bekommt einen optionalen
`branch`-Override. Der Loop nutzt **einen** Branch `bridge/loop-<loop_id>` über alle Runden.
Runde 2+ cloned/pullt diesen Branch (nicht base) → codex sieht seinen eigenen Vorrunden-Stand
und fixt die Gaps am echten Code. Der Override ist additiv: ohne ihn gilt das alte
task_id-abgeleitete Verhalten → **Stage 1 bleibt regressionsfrei**. (Weg B — jede Runde neu von
base, Kontext nur im Auftragstext — wurde verworfen: verschenkt Vorrunden-Arbeit, skaliert
schlecht über 2-3 Runden.)

**Nachtrag (Befund aus dem finalen holistischen Review, 2026-06-02):** Der `branch`-Override
allein genügt NICHT für die Kontinuität. `run_codex_task` leitet den Arbeits-Ordner als
`workdir = workroot / task_id` ab. Da jede Runde eine neue `task_id` hat, bekommt jede Runde
einen frischen, nicht-existierenden Ordner → `_git_clone_or_pull` nimmt den Clone-Pfad (frisch
von base) und der `prefer_branch`-Pfad (Runde-2-Kontinuität) wird NIE erreicht. Damit baute
codex faktisch jede Runde von base neu — die Reviewer-Gaps reisten nur im Prompt, nicht im Code.
**Korrektur:** Der Loop muss einen **stabilen, loop-id-abgeleiteten Arbeits-Ordner** über alle
Runden verwenden (nicht task-id-abgeleitet), damit Runde 2+ den existing-`.git`-Pfad +
`prefer_branch` trifft. Bewiesen mit einem **echten-git**-Test (nicht `fake_build` — genau diese
Seam prüfen Fakes nicht; P006/P009). Siehe Plan-Task 9.

**Scope-Abgrenzung:** Diese Spec ist **Stage 2b** und baut auf dem fertigen Stage-2a-Fundament
auf. Der Overnight-Scheduler, freie Arbeits-Loops mit offenem Ziel und Auto-Merge sind **Stufe 3**
(eigene Spec).

## Architektur

### Neuer Loop-Modus (kein neues Skript)

Der bestehende `loop_driver.py` bekommt einen Modus-Schalter `--mode {ping-pong, build-review}`
(Default `ping-pong` = heutiges Verhalten). `run_loop` verzweigt früh: der Ping-Pong-Pfad bleibt
unverändert, der Bau↔Review-Pfad ist eine separate Schleifen-Funktion `run_build_review_loop`
(eigene, klar abgegrenzte Funktion — der bestehende `run_loop` wird nicht verschachtelt).

**Rollen sind fix** (bewusste Code-Entscheidung, kein Flag-Zoo): **A = codex-Bauer**,
**B = claude-Reviewer**. Tausch später = bewusster Code-Change. Die diverse Perspektive
(anderes Modell reviewt als baut) ist damit eingebaut.

### Loop-Umschlag (additive Frontmatter-Felder, keine Migration)

Die B-Tasks tragen:

```yaml
kind:        review            # statt heute 'echo' — aktiviert die parse_verdict-Verdrahtung
adapter:     claude            # Reviewer-Runner
loop_id:     loop-<id>         # bleibt (Stufe 1)
round:       <n>               # bleibt (Stufe 1)
loop_branch: bridge/loop-<id>  # NEU, additiv — welcher Branch reviewt wird
loop_commit: <hash>            # NEU, additiv — welcher Stand reviewt wird
payload:     <branch+commit+changed_files, kompakt>   # bleibt; trägt das Bau-Artefakt
```

Alt-Tasks (Stufe 1, ohne `loop_branch`) bleiben gültig.

### `codex_adapter` branch-Override (additiv)

`run_codex_task(..., branch: str | None = None)`. Ist `branch` gesetzt, wird **dieser** Branch
benutzt (clone/pull DIESES Branch statt base, falls er auf dem Remote existiert; sonst von base
abzweigen und anlegen). Ist `branch` None, gilt unverändert `bridge/task-<task_id>` von base.
Der Loop ruft mit `branch=f"bridge/loop-{loop_id}"`.

## Datenfluss (eine Runde r)

1. **A baut (inline, lokal auf A):**
   `run_codex_task(auftrag, repo, base_branch, branch="bridge/loop-<loop_id>")` →
   committet + pusht auf den **stabilen** Loop-Branch → `RunnerResult{branch, commit,
   changed_files, antwort}`.
   - **Stagnations-Check (Bau):** `commit == commit_der_Vorrunde` → Abbruch
     „stagniert (kein neuer Commit)".
   - codex-Fehler (`status:error`) → sauberer Abbruch mit `error_text`.

2. **A schreibt Review-Task an B:** `kind=review`, `adapter=claude`,
   `loop_branch`/`loop_commit` gesetzt, `payload` trägt branch+commit+changed_files. Der
   Auftragstext instruiert B: „Hol `bridge/loop-<id>` (Commit `<hash>`) per `git fetch &&
   git checkout`, reviewe gegen `<Ziel>`, antworte mit `VERDICT: accepted` oder
   `VERDICT: rejected` + Begründung."

3. **B reviewt (unveränderter `handoff_poll`-Worker, separater Live-Poller):**
   `run_claude` führt den Reviewer-Prompt aus; **B holt den Branch selbst** (git fetch+checkout
   im Prompt instruiert — konsistent mit der bestehenden claude-Reviewer-Mechanik aus dem
   Gate-Werk, der Loop platziert nichts auf B). claude liest den echten Code, antwortet mit
   VERDICT-Marker → `parse_verdict` (fail-closed) → `result.verdict` / `verdict_reason`.

4. **A liest B's Result (`wait_for_result`, `round_timeout`):**
   - `verdict == accepted` → **Loop-Ende, Erfolg.** Summary trägt `final_branch` + `final_commit`.
   - `verdict == rejected` → `verdict_reason` wird zum nächsten Bau-Auftrag (die Gaps).
     **Stagnations-Check (Review):** `verdict_reason == reason_der_Vorrunde` → Abbruch
     „stagniert (Reviewer wiederholt sich)".
   - `timeout` / `B-error` → sauberer Abbruch (wie heute), offener task_id im Summary.

5. **Obergrenze:** `max-rounds` erreicht ohne `accepted` → Abbruch
   „max-rounds erreicht, nicht akzeptiert".

A→B-Codex-Stufe-1 und der Ping-Pong-Modus laufen unverändert daneben.

## Drei Schutzschichten gegen Endlos-/Verschwendungs-Loops

1. **Stagnation (inhaltlich):** unveränderter Commit-Hash (A baute real nichts) ODER
   identisches `verdict_reason` (B dreht im Kreis) → früher Abbruch mit ehrlichem Grund,
   vor max-rounds. Spart verschwendete Runden.
2. **`round_timeout`** (bereits gebaut): B antwortet nicht rechtzeitig → sauberer Abbruch.
3. **`max-rounds`** (bereits gebaut): harte Obergrenze.

Jeder Abbruchgrund landet in der JSONL-History und im Summary — kein stiller Erfolg, kein Hang.

## Fehlerbehandlung

Alle bestehenden Garantien bleiben wirksam (P0-Requeue, task_id-Validierung, Adapter-Catch,
fail-closed-Verdikt). Zusätzlich:

- codex-Bau-Fehler → Abbruch mit `error_text` (kein Crash, JSONL-Spur).
- Reviewer-Adapter unbekannt / `run_claude`-Parsing leer → `status:error` → Abbruch.
- Reviewer ohne VERDICT-Marker → **`rejected`** (fail-closed, parse_verdict) — der Loop
  iteriert, akzeptiert NIE versehentlich.
- B-Timeout → sauberer Abbruch mit offenem task_id (liegt in der Lane).

## Test- & Regressionsstrategie (TDD)

**Test-Isolation (globale Regel §3):** `conftest.py` erzwingt bereits ein isoliertes
`DUAL_BRIDGE_ROOT` + Poison-Guard (Drive-Leak gefixt, `ff70df3`, snapshot-bewiesen). Die neue
Suite läuft darunter.

1. **Regressionsanker zuerst:** Ping-Pong-Modus (`increment`, `test_loop_driver.py` 72 Tests) +
   `test_stage1.py` + `test_hardening.py` bleiben unverändert grün. Der neue Modus ist additiv
   (`--mode`, Default = altes Verhalten).
2. **Neue Unit-Tests (Fake-Runner — P006/P009: Fake beweist nur Mechanik, nicht Vertragstreue):**
   - (a) accepted in Runde 1 → Loop endet sofort, Summary trägt `final_branch`/`final_commit`.
   - (b) rejected → A baut nach, `verdict_reason` fließt in den nächsten Bau-Auftrag.
   - (c) Stagnation Commit-Hash unverändert → früher Abbruch, korrekter Grund.
   - (d) Stagnation `verdict_reason` wiederholt → früher Abbruch.
   - (e) max-rounds ohne accepted → Abbruch „nicht akzeptiert".
   - (f) fail-closed: Reviewer ohne VERDICT-Marker → `rejected` (nicht versehentlich
     accepted / kein Abbruch).
   - (g) branch-Override: `run_codex_task` mit explizitem `branch` nutzt diesen statt
     `bridge/task-<id>`; ohne Override unverändert (Stage-1-Default).
3. **Live-Beweis (separater Schritt, NICHT in der Unit-Suite — P007):** ein echter codex-Bau +
   claude-Review über die Bridge, Ground-Truth gegengelesen (Branch-Inhalt byte-genau gegen
   Remote, echter VERDICT-Marker im Reviewer-Text, B-Device-Claim). Wie bei Stufe 1.

## Bewusst draußen (YAGNI)

Overnight-Scheduler · mehr als 2 Endpoints · parallele Loops · Reviewer-Eskalation an den
Menschen · **Auto-Merge des akzeptierten Branches** (der Mensch merged bewusst — globale Regeln
7/15) · konfigurierbare Builder/Reviewer-Rollen (fix verdrahtet). Das ist Stufe 3 / separater Scope.

## Erfolgskriterien

- [ ] `--mode build-review`: A=codex baut auf stabilem `bridge/loop-<id>`, B=claude reviewt
      (`kind:review`), `accepted` beendet den Loop erfolgreich.
- [ ] `rejected` iteriert mit den Reviewer-Gaps auf demselben Branch (codex sieht den
      Vorrunden-Stand, baut darauf auf).
- [ ] Drei Schutzschichten greifen nachweislich: Stagnation (Commit-Hash + verdict_reason),
      `round_timeout`, `max-rounds`.
- [ ] `run_codex_task` branch-Override ist additiv; Stage-1 + Ping-Pong-Modus regressionsfrei grün.
- [ ] Reviewer ohne Marker → `rejected` (fail-closed), nie versehentlich accepted.
- [ ] Live-Beweis erbracht (separater Schritt, Ground-Truth-verifiziert).

## Folge-Arbeit (nicht Teil dieser Spec)

- **Stufe 3:** freier Arbeits-Loop mit offenem Ziel + Owner-Eskalation; Overnight-Scheduler;
  evtl. orchestrated-bridge als Treiber-Heimat.
- **Wiki-Pflege:** Master-Plan `[[wiki/plans/2026-05-30-dual-bridge-master-plan]]` um den
  Bau↔Review-Loop ergänzen (beim Umsetzungs-Abschluss).
