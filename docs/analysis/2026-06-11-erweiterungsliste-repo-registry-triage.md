# Triage: repo-registry.md + erweiterungsliste.md (2026-06-11)

> Konsolidierte Findings, Outcomes und weiteres Vorgehen zu den zwei User-Dokumenten
> `~/Downloads/repo-registry.md` und `~/Downloads/erweiterungsliste.md`.
> Methode: jeder Vorschlag ground-truth-geprüft gegen den realen Repo-/Code-Stand
> (Anti-Pattern „Reerfindung von Live-Code", vgl. Pulse-Triage 2026-06-06).

## 1. repo-registry.md — Verdikt: übernehmen mit 2 Korrekturen

Referenz-Dokument für den Perplexity-Space „skills plugins mcp". Faktencheck:
17/19 Einträge korrekt. **Keine Bridge-Tasks daraus** — reines Kontext-Dokument.

Korrekturen vor Verwendung:
1. **dual-bridge:** Status „Lane-Modell (Stage 2a)" ist veraltet → real **Stufe 3**
   (Goal-Loop + Owner-Eskalation, live bewiesen) + produktive DCO-Anbindung
   (`job_poll`, HTTP-Transport, Autoqueue mit Dep-Gating).
2. **pulse:** „Heartbeat/Pulse (ohne Beschreibung)" → real der Daily-Pulse-Hub /
   die Stack-Bridge mit substanzieller Triage-Historie.

## 2. erweiterungsliste.md — Triage aller 24 Punkte

Verdikt-Verteilung: **13 übernehmen · 4 umbauen/erweitern · 3 verwerfen · 4 vertagen.**

### Verworfen (mit Ground-Truth-Beleg)

| # | Vorschlag | Grund |
|---|---|---|
| 4.1 | Test-Suite für Handoff-Skripte | **Existiert bereits**: 360 Tests in 27 Dateien, davon 30 Treffer zu Path-Traversal/`_errors`-Quarantäne (`test_hardening.py`, `test_lanes.py`, `test_bridge_status.py`). Reerfindung von Live-Code. Sinnvoller Rest: gezielter Coverage-Lücken-Report. |
| 1.2 | Retry/Backoff für `_errors/` | Semantik-Fehler: `_errors/` quarantänt **invalide** Tasks (Traversal-/Injection-Schutz) — dort gibt es kein „transient". Transient/permanent-Klassifikation existiert als Muster bereits in `bridge_notify`. |
| 1.3 | Prioritäts-Feld im Task-Frontmatter | YAGNI: Reihenfolge bestimmt die DCO-Autoqueue (kleinste ID + Dep-Gate), nicht der Lane-Poll. Erst bei real beobachtetem Queue-Stau. |

### Übernommen → Welle 1 (heute als Bridge-Todos geseedet)

| Todo | Erw. | Inhalt | Repo |
|---|---|---|---|
| #7877 | 1.4 | Secrets-Pre-Send-Gate — **nachträglich aus der Bridge genommen und interaktiv gebaut** (siehe §3 Punkt 4: Gate-vs-Gate) | dual-bridge |
| #7878 | 3.4 | Gate-Linter für SKILL.md (`lint_gates.py:lint_all`, nutzt bestehenden Index-Parser) | skill-index |
| #7879 | 1.8 | Mutation-Tests (5 Mutationsklassen + Whitespace-Kontrolle gegen False-Positives) | bridge-replay |
| #7880 | 4.2 | README generieren (nur code-belegbare Claims) | ToDoDcO |
| #7881 | 4.2 | README generieren/nachziehen | pulse |
| #7882 | 4.2 | README fürs Tools-Lab (3 Submodules + Lab-Runner) | dual-bridge-tools-lab |

Korrektur an 4.2 gegenüber dem Original: **tool-usage-tracker gestrichen** — hat seit
2026-06-05 vollständige Doku (HOW-TO-USE, CAPABILITIES, CHANGELOG, …).

Recherche-Absicherung zu 1.4: Stand der Technik ist Regex+Entropie
(gitleaks: Regex + Entropie-Analyse; Yelp detect-secrets: base64 ≥ 4.5, hex ≥ 3.0
Bits/Zeichen). Entscheidung: kleiner Eigenbau nach diesem Muster statt neuer
Dependency (Repo ist bewusst stdlib-nah; Vorbild `safe_subprocess_env`-Denylist).

### Welle 2 (Bridge-fähig, nach Welle 1 seeden)

- **1.1 Lane-Health-Monitor** — als Ausbau von `bridge_status.py` + gehärtetem
  `bridge_notify`-Sendepfad, KEIN neues Skript-Silo.
- **2.2 Bridge-Ergebnis-Digest** — read-only auf `_processed/`, in vorhandene
  DCO-Digest-Integration einhängen.
- **4.5 E2E-Smoke als Cron** — täglicher echo-Roundtrip A→B→A; `register_*`-Familie,
  dry-run-Pflicht.
- **1.5 Bridge-Metriken** — Durchlaufzeit/Verdikt-Quote aus `_processed/`,
  Report lokal in `state/` (nicht auf den Drive schreiben).
- **1.7 bridge-replay als CI-Gate** — NUR mit Auflage: erst beweisen, dass die
  Suite auf dem ubuntu-Runner grün läuft (DCO-Lehre #7846: Windows-first-Suite
  → CI dauerrot → entfernt).

### Interaktive Design-Sessions (nicht bridge-fähig)

Reihenfolge-Empfehlung:
1. **2.5 Risk-Level-Mapping** (Bridge-`kind`/`adapter` → DCO-Risk-Levels; sicherheits-
   relevant, VOR 2.1; knüpft an `DUAL_BRIDGE_REPO_ALLOWLIST` + dangerous-deny-first an)
2. **2.1 Telegram `/bridge`-Command** — Korrektur: via `todos.add(tag=bridge)` statt
   Lane-Outbox direkt (Autoqueue liefert Dep-Gating/Cap/Journal gratis)
3. **1.6 Adapter-Gerüst extrahieren** — git-Klon/Commit/Push-Gerüst aus
   `codex_adapter.py` in gemeinsames Modul = Vorstufe für claude-Builder
   (offene Zukunftsoption, Memory `claude-adapter-is-review-only-no-build`)
   UND für jeden weiteren Adapter (gemini/ollama erst danach bewerten)
4. **3.2 Knowledge-Graph-Schema** (Perplexity-Skills als Knoten), Befüllung dann als Job
5. **4.3 Repo-Hygiene-Sweep** — Archiv-/Lösch-Entscheidungen nur mit Owner

### Vertagt

- **2.4 DCO_HANDOFF-Brücke** (orchestrated-bridge ist Walking Skeleton;
  Source-of-Truth-Frage + Doppelstruktur-Risiko zur jobs.db-Queue)
- **3.5 Skill-Sync Perplexity↔Claude** (eigener Spec-Zyklus)
- **3.6 mutation-engine an die Bridge** (Reifegrad unklar; erst nach 3.2)
- **3.3 Dubletten-Konsolidierung** — nur mit Owner-Gate pro Skill-Merge
  (Trigger-Phrasen-Semantik; text-only-Reviewer dafür zu schwach)

## 3. Constraints für Fremd-Repo-Bridge-Todos (heute gelernt)

1. **Keine `VORAUSSETZUNG:`-Ketten über Fremd-Repos:** `bridge_autoqueue.artifact_on_master`
   prüft im DCO-`_REPO_ROOT` gegen dessen origin/master. Ein ARTEFAKT in einem anderen
   Repo wird dort nie gefunden → Dauer-Block. Welle-1-Todos sind deshalb bewusst
   unabhängig. (Fix-Kandidat: repo-bewusster Dep-Check — eigener Slice, falls
   Fremd-Repo-Ketten gebraucht werden.)
2. Allowlist `https://github.com/dynamic-dome/*` deckt alle Ziel-Repos;
   `check_and_merge_in_repo` ist repo-parametrisiert, `main→master`-Auflösung
   vorhanden (`495966d`).
3. **DoD immer diff-prüfbar formulieren** (kein Browser/visuell für headless Worker) —
   Pattern P017; der Empty-State-Vorfall (#7863, Job bb3310326376) war genau diese Klasse.
4. **Gate-vs-Gate: Security-Tooling-Bau ist nicht bridge-fähig.** Der erste
   #7877-Lauf eskalierte in Runde 0 mit `dangerous_action`: Ein Secret-Scanner-Bau
   erzeugt zwangsläufig Secret-Regexe + Fake-Token-Fixtures im Diff, und der
   deny-first-Wächter des Goal-Loops (`loop_driver.DANGEROUS_PATTERNS`, Secret-
   Familie „armed everywhere") matcht genau diese. Konsequenz: Tasks, deren
   ARTEFAKT selbst Gefahr-Muster enthält (Security-Scanner, Wächter-Regeln,
   Destruktiv-SQL-Tooling), interaktiv bauen — nicht über die Bridge.
   #7877 wurde entsprechend umgetaggt und am 2026-06-11 interaktiv per TDD
   gebaut (`scripts/secret_gate.py` + `handoff_write`-Integration, 378 Tests grün).

## 4. Begleit-Ereignisse der Umsetzung (2026-06-11)

- Serie **#7863–#7870 komplett** (alle gemergt + artefakt-verifiziert); die nachge-
  schärfte Reihenfolge zahlte sich aus: die #7866-Merge-Härtung fing noch am selben
  Vormittag den Leerbau-Nachzügler von #7865 als Eskalation ab.
- **#7867 (Dep-Ping-Drossel)** manuell per TDD im DCO gebaut (`870582d`), da der
  Ping-Sturm akut war; Todo vor Autoqueue-Routing auf done gesetzt.
- Fehldiagnose dokumentiert: Windows-venv-Launcher-Ketten sind KEINE Doppel-Instanz
  (Memory `venv-launcher-is-not-a-duplicate-instance`); echter Stillstand kam vom
  Cockpit-Toggle-OFF (09:57).

## 5. Welle-1-Ergebnis (2026-06-11, abgeschlossen)

Alle 6 Todos erledigt. Ablauf-Erkenntnisse:

| Todo | Repo | Ergebnis |
|---|---|---|
| #7877 Secrets-Gate | dual-bridge | Gate-vs-Gate (§3.4) → interaktiv per TDD gebaut (`2e0d11c`) |
| #7878 Gate-Linter | skill-index | 1 Fehlschlag (leerer Build) → Retry baute, gemergt |
| #7879 Mutation-Tests | bridge-replay | 1 Fehlschlag (leerer Build, ~26 Min) → Retry baute, gemergt |
| #7880 README | ToDoDcO | 1. Anlauf, gemergt |
| #7881 README | pulse | 1. Anlauf, gemergt |
| #7882 README | tools-lab | 1. Anlauf, gemergt |

**Retry-Muster (neuer Befund):** Fremd-Repo-CODE-Tasks (Linter, Mutation-Tests)
eskalierten beide im ersten Anlauf mit `stagnation` Runde 0 = leerer Build (der
headless codex-Worker auf Laptop A produzierte keinen Diff), bauten aber im
automatischen Autoqueue-Retry sauber. DOKU-Tasks (READMEs) liefen alle im ersten
Anlauf durch. Konsequenz: Fremd-Repo-Code-Tasks brauchen Retry-Toleranz (1
Fehlschlag ist normal, nicht systematisch) — die Autoqueue-Selbstheilung + der
#7866-`empty_branch`-Guard fangen das zuverlässig auf, kein manueller Fix nötig.
Falls ein Code-Task >2 Anläufe braucht: Seed kleiner schneiden (zu groß für einen
headless-codex-Durchlauf), nicht endlos retrien.

## 6. Welle-2-Ergebnis (2026-06-11, abgeschlossen)

Von den 5 Welle-2-Punkten waren 3 sauber bridge-baubar; 2 sind Ops/interaktiv
(nicht blind seedbar):

| Todo | Erw. | Repo | Ergebnis |
|---|---|---|---|
| #7883 Bridge-Digest | 2.2 | DCO | 1. Anlauf accepted, aber Auto-Merge-Race → manuell gemergt (`1aa4bea`) |
| #7884 Lane-Health | 1.1 | dual-bridge | 1. Anlauf, auto-gemergt+verifiziert (`d9ac32b`) |
| #7885 Bridge-Metriken | 1.5 | dual-bridge | 1. Anlauf, auto-gemergt+verifiziert (`6005569`) |

**NICHT geseedet (bewusst, interaktiver Vorlauf nötig):**
- **4.5 E2E-Smoke-Cron** — `latency_probe.py` existiert bereits; der echo-Roundtrip
  braucht beide Endpunkte LIVE zum Testen + dry-run-pflichtige Scheduled-Task-
  Aktivierung. Kein headless-Build.
- **1.7 bridge-replay-CI** — Triage-Auflage „erst ubuntu-Grün beweisen" (Lehre
  #7846) kann ein headless-Worker nicht selbst erfüllen.

**Auto-Merge-Race (neuer Befund, wichtig):** `accepted`/`done=1` heißt NICHT
„auf master". Bei #7883 scheiterte der Auto-Merge fail-soft an einem
CHANGELOG-Konflikt, weil der idea-feeder-Loop parallel master bewegte (Race
zwischen Loop-Klon und Merge-Versuch). Der Build lag nur auf dem Loop-Branch;
das done-Flag stand trotzdem. NUR der G-pattern-005-Merge-Check (echtes
`git grep` auf origin/<base>) fing es. Konsequenz: Nach jedem `accepted` den
TATSÄCHLICHEN Merge verifizieren, nicht dem done-Flag trauen — besonders im
DCO-Repo (paralleler idea-feeder-Push). dual-bridge-Repo merged sauber (kein
Dauer-Loop). Manueller Merge = die dokumentierte fail-soft-Klausel
(„Branch manuell mergen"); digest.py merged automatisch, nur CHANGELOG
brauchte Handarbeit (CHANGELOG-Konflikt ist der Normalfall bei parallelen Bridge-Merges).

## 7. Nächste Schritte

1. repo-registry.md korrigieren: jetzt **3 Punkte** — dual-bridge (Stage 2a→Stufe 3),
   pulse (Beschreibung), UND ToDoDcO (ist kein ToDo-Tool, sondern Sandbox-Worktree
   `sandbox.py` + `ISSUES2FIX.md` — von der generierten README ground-truth belegt).
2. Interaktive Folge-Themen: 4.5 E2E-Smoke (Ops), 1.7 bridge-replay-CI (ubuntu zuerst),
   Design-Session 2.5 Risk-Mapping, 2.1 `/bridge`-Command, 1.6 Adapter-Gerüst.
3. Stichprobe Welle-1-READMEs: durchgeführt, alle 3 sauber + belegt (kein
   Halluzinations-Fund); ToDoDcO-README deckte sogar den registry-Fehler auf.
