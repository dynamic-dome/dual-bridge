# Dual-Bridge Stufe 3 — Freier Arbeits-Loop mit Owner-Eskalation

*Datum: 2026-06-02*
*Autor: Claude (Opus 4.8), nach Brainstorming + Ground-Truth-Code-Verifikation*
*Projekt: Dual-Laptop-Bridge (`~/AI/dual-bridge`, Repo `dynamic-dome/dual-bridge`)*
*Status: Design — zur Umsetzung freigegeben nach User-Review*

## Kontext & Motivation

Stufe 2 ist live cross-device bewiesen: ein asymmetrischer Bau↔Review-Loop
(`loop_driver.py --mode build-review`). **A=codex baut** auf einem stabilen Loop-Branch,
**B=claude reviewt** den eingebetteten Diff-Text (`kind:review` → Verdikt, fail-closed
`parse_verdict`). `accepted` beendet den Loop, `rejected` lässt A auf demselben Branch
nachbauen. Drei Schutzschichten: Stagnation (Commit-Hash + verdict_reason), `round_timeout`,
`max-rounds`. Der Mensch merged den akzeptierten Branch bewusst (globale Regeln 7/15 — kein
Auto-Merge).

**Begriffsklärung:** "Stufe 3" ist in den Projektdokumenten doppelt belegt. Diese Spec meint
den **freien Arbeits-Loop mit offenem Ziel + Owner-Eskalation** (aus der Stufe-2-Spec-Folgearbeit
und dem zentralen Handoff), NICHT die "echte Verteilung / HTTP-Job-Pull" aus dem ursprünglichen
Master-Plan-Wortlaut (das bleibt späteres Infra-Projekt) und NICHT den Overnight-Scheduler
(orthogonaler Treiber, eigener Scope).

### Das Kern-Delta zu Stufe 2

| | Stufe 2 (`build-review`, fertig) | Stufe 3 (`goal-loop`, diese Spec) |
|---|---|---|
| **Ziel** | fixer Seed-Auftrag ("baue X") | offenes Ziel + Done-Kriterien ("fertig, wenn X, Y, Z") |
| **Reviewer-Frage** | "ist genau diese Änderung ok?" | "ist das Ziel *erreicht* (Diff gegen Done-Kriterien)?" |
| **Verdikte** | accepted / rejected | accepted / rejected / **escalate** |
| **Wenn es hakt** | rejected → iteriert blind bis max-rounds | **Owner-Eskalation**: Loop hält, schreibt Datei, Mensch entscheidet |

### Leitprinzip (die Invariante)

**Der Loop ist autonom *innerhalb fixer Grenzen* (der Seed-Done-Kriterien); der Mensch
*verschiebt die Grenzen* (über Eskalation + Neustart mit geschärftem Seed).** Die
Done-Kriterien ändern sich NIE im Loop selbst — nur durch den Menschen, an der Naht, wo er
ohnehin hinschaut. Kein lebendes State-File, das mitwachsen und das Fakes nicht prüfen könnten
(P006/P009). Wenn ein offenes Ziel ganz ohne Maßstab läuft, terminiert es selten oder driftet;
ein fixer, abhakbarer Maßstab pro Lauf hält es testbar und endlich.

## Ground-Truth: was bereits gebaut ist (verifiziert am Code, nichts neu)

- **`loop_driver.py`** trägt bereits `--mode build-review` neben dem Stage-1-Default; Modus-Auswahl
  ist additiv. `write_review_task` bettet `git diff base...HEAD` in den Review-Prompt ein
  (Stufe-2-Fix, tool-loser Reviewer) und verlangt den VERDICT-Marker in eigener letzter Zeile.
- **`parse_verdict`** (geteilter Gate-Code, NICHT neu): fail-closed — nur explizit
  `VERDICT: accepted` → accepted, sonst rejected.
- **`codex_adapter.run_codex_task`**: cloned/branched, `codex exec` (stdin-Prompt P008,
  `--skip-git-repo-check`, `-o` answer-file), commit+push; `branch=`/`workdir_name=`-Override
  (Stufe-2-Continuity-Fix: stabiler Loop-Workdir, codex baut auf der Vorrunde auf).
- **Drei Schutzschichten** im Loop (Stagnation / round_timeout / max-rounds) — bleiben erhalten,
  werden in Stufe 3 zu Eskalations-Auslösern statt stillen Abbrüchen umgeleitet.
- **secret-sweep-Pattern** existieren in orchestrated-bridge (`gate_secret_sweep.py`) als
  deny-first-Quelle für gefährliche Aktionen.

## Architektur — additiv, kein Umbau

Neuer Modus `--mode goal-loop` neben `build-review`. Alles bleibt in den bestehenden Dateien
(`loop_driver.py`, `bridge_common.py`/`parse_verdict`, `codex_adapter.py` praktisch unverändert).
`test_stage1.py`, `test_hardening.py`, `test_build_review_loop.py` bleiben unverändert grün.

### Komponente 1 — Strukturierter Seed

Der Seed ist eine Markdown-Datei mit zwei Blöcken (menschenschreibbar, von beiden Agenten lesbar):

```markdown
## Ziel
<das offene Ziel, in Prosa>

## Done-Kriterien
- [ ] Kriterium 1
- [ ] Kriterium 2
- [ ] Kriterium 3
```

`loop_driver` parst Seed → `goal` (str) + `done_criteria` (Liste). Beide Agenten bekommen
denselben Seed. Der Builder-Auftrag = Ziel + offene Kriterien + (ab Runde 2) die Reviewer-Gaps
der Vorrunde. Der Reviewer-Prompt prüft den kumulativen Diff (`git diff base...HEAD`) GEGEN die
Done-Kriterien.

### Komponente 2 — Drittes Verdikt `escalate`

`write_review_task` (goal-loop-Variante) verlangt einen von **drei** Markern in eigener letzter
Zeile: `VERDICT: accepted` / `VERDICT: rejected` / `VERDICT: escalate`. `parse_verdict` wird
**additiv** um `escalate` erweitert:

- `VERDICT: accepted` → accepted (alle Kriterien erfüllt, Loop endet erfolgreich)
- `VERDICT: escalate` → escalate (Reviewer fordert menschliche Entscheidung an)
- **alles andere / kein Marker → rejected** (fail-closed bleibt). Eskalation muss *explizit*
  sein — ein kaputter/markerloser Reviewer ruft NICHT fälschlich den Menschen, sondern führt
  zu rejected (und dann ggf. über Stagnation/max-rounds zur Eskalation, mit Kontext).

Der `parse_verdict`-Code ist mit dem orchestrated-bridge-Gate geteilt → additiv (neuer
Rückgabewert, alte Pfade unverändert) + Regressionstest, der accepted/rejected-Verhalten bindet.

### Komponente 3 — Vier Eskalations-Auslöser

Der Loop hält an und schreibt eine Eskalations-Datei bei:

1. **`reviewer_requested`** — Reviewer-Verdikt = `escalate` (neuer, expliziter Pfad).
2. **`stagnation`** — Commit-Hash unverändert ODER verdict_reason wiederholt sich (Stufe-2-
   Schutzschicht, jetzt Eskalation-mit-Kontext statt stiller Abbruch).
3. **`max_rounds`** — Runden-Limit erreicht ohne accepted (Stufe-2-Schutzschicht, jetzt Briefing
   an den Owner mit Zwischenstand + offenen Kriterien statt stillem Abbruch).
4. **`dangerous_action`** — lokaler deny-first-Check (siehe Komponente 5) findet ein riskantes
   Muster im Build-Auftrag oder erzeugten Diff.

### Komponente 4 — Eskalations-Datei + Resume

Bleibendes Protokoll, überlebt jede künftige Notifikations-Schicht. Datei
`ESCALATION-<loop-id>.md` (im Loop-State-Verzeichnis, danach Move nach `_processed/`, kein
Auto-Delete — Manifest-Regel 7):

```markdown
---
loop_id: goalloop-20260602-143000-abcd
trigger: reviewer_requested | stagnation | max_rounds | dangerous_action
round: 3
branch: bridge/loop-goalloop-...-abcd
commit: ffa06de
exit_reason: escalation
created: 2026-06-02T14:30:00
---

## Ziel (aus dem Seed)
<unverändert gespiegelt>

## Done-Kriterien — Stand
- [x] Kriterium 1 (vom Reviewer als erreicht markiert)
- [ ] Kriterium 3  ← hier hängt es

## Eskalations-Grund
<trigger-spezifisch: Reviewer-Text / "verdict_reason wiederholt seit Runde N" /
 "max-rounds N erreicht, Kriterium 3 offen" / geblockter Befehl + Pattern>

## Offene Frage an den Owner
<konkret: was der Mensch entscheiden muss>

## Zwischenstand
<was erreicht wurde, Branch/Commit zum Anschauen>
```

Der Loop beendet sich mit **Exit-Code ≠ 0** (Eskalation ist kein Erfolg).

**Resume durch den Owner** — `--resume <loop-id>` heißt: **gleicher Loop-Branch** (codex baut
auf dem Zwischenstand weiter, nutzt den Stufe-2-Continuity-Mechanismus, NICHT von base):

```
python loop_driver.py --mode goal-loop --resume goalloop-...-abcd --seed <geschärfter-seed.md>
```

**Resume-Validierung (vom `trigger` im Frontmatter gesteuert):**
- `trigger: max_rounds` → Resume **darf unverändert** weiterlaufen (man will nur mehr Laufzeit,
  das Ziel stimmt). `--seed` optional.
- **alle anderen Trigger** (`reviewer_requested`/`stagnation`/`dangerous_action`) → Resume
  **erzwingt einen geänderten Seed** (sonst rennt man garantiert in dieselbe Wand). Loop
  verweigert den Start, wenn der Seed-Inhalt unverändert ist.

Die alte `ESCALATION-...md` wandert beim Resume nach `_processed/`.

### Komponente 5 — Gefährliche Aktion: lokaler deny-first-Check (KEIN Cross-Device-Gate)

**Bewusste Architektur-Entscheidung:** Eine vollständige Gate-Integration (codex' Aktionen live
durch das Cross-Device-Gate) ist die **Latenz-Sackgasse**, die der Master-Plan am 2026-06-01
verworfen hat (30s-Hook vs. ~28s-Drive, synchron pro Tool-Call). Der Stufe-3-Builder ist codex
auf A (über `codex_adapter`), kein gehookter Claude-Code — der Gate-Hook feuert dort ohnehin nicht.

Stattdessen: der `loop_driver` führt einen **lokalen, synchronen Pre-/Post-Build-Check** auf den
Build-Auftrag + den erzeugten Diff durch — dieselbe deny-first-Logik wie secret-sweep (Regex auf
`push origin main`, `DROP TABLE`/`DELETE FROM`, `rm -rf`, Secret-Pattern `sk-ant-`/`api_key`).
Treffer → `trigger: dangerous_action`-Eskalation, kein Roundtrip, kein Hook.

- konsistent mit der secret-sweep-Philosophie (lokal, sofort, deny-first),
- **kein** synchroner Cross-Device-Review (nicht die Sackgasse),
- testbar mit Fakes (Regex auf bekannten Inputs),
- Naht zum echten Gate bleibt offen (später: Diff *asynchron* an einen Bridge-Reviewer).

Die Pattern-Liste wird **aus der bestehenden secret-sweep-Quelle wiederverwendet** (DRY, ein
Wartungspunkt). Falls der Import über Repo-Grenzen unsauber ist: Pattern-Liste spiegeln + Drift-Test
(wie beim Gate-Protokoll gemacht).

## Testen

### Unit (Fake-Runner — `test_goal_loop.py`; P006/P009: Fake beweist Mechanik, nicht Vertragstreue)
- (a) accepted in Runde N → Loop endet erfolgreich, Summary trägt `final_branch`/`final_commit`.
- (b) rejected → Builder baut nach, Reviewer-Gaps + offene Kriterien fließen in den nächsten Auftrag.
- (c) `escalate`-Verdikt → `ESCALATION-...md` geschrieben, Exit ≠ 0, `trigger: reviewer_requested`.
- (d) Stagnation (Commit-Hash unverändert / verdict_reason wiederholt) → Eskalation
  `trigger: stagnation`, korrekter Grund in der Datei.
- (e) max-rounds ohne accepted → Eskalation `trigger: max_rounds` (Briefing, nicht stiller Abbruch).
- (f) dangerous_action (riskantes Muster im Auftrag/Diff) → Eskalation `trigger: dangerous_action`,
  kein Roundtrip.
- (g) fail-closed: Reviewer ohne Marker → `rejected` (NICHT escalate, NICHT accepted).
- (h) Resume-Validierung: `max_rounds` darf unverändert resumen; andere Trigger verweigern den
  Start ohne geänderten Seed.
- (i) Seed-Parsing: Ziel + Done-Kriterien korrekt zerlegt; fehlerhafter Seed → klarer Fehler.
- Regression: `parse_verdict` accepted/rejected unverändert; Stage-1 + build-review-Modus grün.

### Live-Beweis (separater Schritt, NICHT in der Unit-Suite — P007)
**Beide Pfade in einem Lauf** (vollständigster Beweis): ein offenes Ziel gegen dual-bridge
selbst als Wegwerf-Ziel, mit 2-3 Done-Kriterien, von denen eines bewusst unterspezifiziert/
mehrdeutig ist. Erwartet: 1-2 Runden echter Fortschritt (Reviewer hakt Kriterien ab) → dann
Eskalation am offenen Kriterium. Ground-Truth-verifiziert: Branch-Inhalt byte-genau gegen Remote,
echter VERDICT-Marker im Reviewer-Text, B-Device-Claim, `ESCALATION-...md` real gegengelesen
(P007 — nicht Status glauben). Drive-Exposure unkritisch (Throwaway-Ziel).

## Erfolgskriterien

- [ ] `--mode goal-loop`: strukturierter Seed (Ziel + Done-Kriterien) wird geparst, beide Agenten
      sehen denselben Seed, Reviewer prüft Diff gegen die Kriterien.
- [ ] Drittes Verdikt `escalate` additiv in `parse_verdict`; accepted/rejected regressionsfrei,
      fail-closed (kein Marker → rejected).
- [ ] Alle vier Eskalations-Auslöser schreiben eine korrekte `ESCALATION-<loop-id>.md` + Exit ≠ 0.
- [ ] Resume: `max_rounds` unverändert erlaubt; andere Trigger erzwingen geänderten Seed; Resume
      baut auf dem Loop-Branch weiter (Continuity).
- [ ] Gefährliche Aktion via lokalem deny-first-Check (kein Cross-Device-Gate), Pattern aus
      secret-sweep wiederverwendet/gespiegelt + Drift-Test.
- [ ] Live-Beweis: ein Lauf, der Fortschritt UND Eskalation zeigt, Ground-Truth-verifiziert.

## Bewusst draußen (YAGNI)

- **Notifikations-Tool** (Telegram/DCO/Push) — der Owner sitzt an A und sieht die Datei sofort.
  Die Eskalations-Datei ist das bleibende Protokoll; Notifikation ist späterer Transport
  (gebraucht erst beim Overnight-Scheduler, wenn der Owner schläft). Naht bewusst offen gelassen.
- **Wartender/pausierender Loop-Prozess** (Antwort-Polling) — Resume-mit-Neustart ist crash-sicher
  und prozess-leicht; kein Loop hängt herum.
- **Lebendes GOAL-State-File** — Done-Kriterien wachsen nur über den bewussten Reseed-Resume
  (Eskalation → geschärfter Seed → Neustart), nicht über synchron gehaltenen Loop-State.
- **Synchrones Cross-Device-Gate** für gefährliche Aktionen — Latenz-Sackgasse (s.o.).
- **Auto-Merge** des akzeptierten Branches — Mensch merged bewusst (Regeln 7/15), wie Stufe 2.
- **Overnight-Scheduler, HTTP-Transport, >2 Endpoints, parallele Loops** — eigene Scopes/Stufen.

## Folge-Arbeit (nicht Teil dieser Spec)

- **Notifikations-Transport** + **Overnight-Scheduler**: bauen auf der Eskalations-Datei auf.
- **Asynchrones Bridge-Review** für gefährliche Aktionen (statt nur lokalem deny-first-Check).
- **Wiki-Pflege:** Master-Plan `[[wiki/plans/2026-05-30-dual-bridge-master-plan]]` um den
  goal-loop ergänzen (beim Umsetzungs-Abschluss); Begriffs-Doppelung "Stufe 3" dort klären.
