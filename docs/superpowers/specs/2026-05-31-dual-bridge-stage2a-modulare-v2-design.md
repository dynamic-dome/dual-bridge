# Dual-Bridge Stage 2a — Schlanke modulare v2 (Bidirektionalität + Adapter-Tausch)

*Datum: 2026-05-31*
*Autor: Claude (Opus 4.8), nach Multi-Perspektiven-Review + Codex-Verifier*
*Projekt: Dual-Laptop-Bridge*
*Status: Design — zur Umsetzung freigegeben nach User-Review*

## Kontext & Motivation

Stage 1 ist live vertrags-bewiesen: Laptop A schreibt einen Task, Laptop B pollt,
ruft echten `codex exec`, committet/pusht einen Branch, antwortet. Reine Python-Stdlib
über einen Google-Drive-synchronisierten SharePoint-Ordner.

Das Zielbild des Users ist **Umkehrbarkeit**: nicht nur A→B, sondern auch B→A, und nicht
nur Claude→Codex, sondern auch Codex→Claude — alles als **Konfiguration**, nicht als
Spezial-Code. Die aktuelle Struktur blockiert das an vier Stellen (alle am Code verifiziert):

- **Richtung in Ordnernamen verdrahtet** (`bridge_common.py:46-51` feste `outbox`/`inbox`).
- **`kind` mischt Fachabsicht + Modell** (`handoff_poll.py:29` — alle LLM-Kinds → Codex).
- **`process_one` ist Monolith** (claim+dispatch+run+render+publish in einer Funktion).
- **Kein Claude-Runner** — nur `codex_adapter.py` existiert.

Ein Multi-Perspektiven-Review (Architektur / Sicherheit / YAGNI / Bidirektionalität) plus
ein Codex-Verifier kamen übereinstimmend zu: **Codex' v2-Problemdiagnose ist korrekt, seine
4-Schichten-Therapie (TaskEnvelope/FileBridgeStore/Router-Registry/Transport-Abstraktion)
ist für ein 2-Laptop/1-Mensch-Setup überdosiert.** ~90 % des Zielbilds sind mit ~25 % der
Komplexität erreichbar. Diese Spec ist die abgerüstete Variante.

**Vorbedingung erfüllt:** Die Phase-0-Härtung (zwei Taskverlust-Bugs, task_id-Injection,
Adapter-Contract) ist behoben und committet (`acc8441`, `8be392e`), Codex-Verifier-gegengeprüft.
Test-Stand: `test_hardening.py` 10/10, `test_stage1.py` 17/17.

**Scope-Abgrenzung:** Diese Spec ist **Stage 2a** (das modulare Fundament). Der
Peer-Review-Loop (`kind: review`, B baut → A challenged → Owner) und der Overnight-Scheduler
sind **Stage 2b** und bauen auf diesem Fundament auf (eigene Spec).

## Architektur

### 1. Endpoint- & Lane-Modell

Richtung wird Konfiguration, nicht Code. Jeder Knoten ist ein **Endpoint** mit Namen
(`claude@laptop-a`, `codex@laptop-b`, …). Statt fester `outbox/`+`inbox/` gibt es
**richtungsgetrennte Lanes**:

```
dual-bridge/
  lane-A-to-B/   outbox/  inbox/  _processed/  _errors/
  lane-B-to-A/   outbox/  inbox/  _processed/  _errors/
```

- Ein Endpoint **sendet** in die `outbox/` seiner ausgehenden Lane, **empfängt** Antworten
  aus der `inbox/` derselben Lane.
- Der Poller eines Endpoints liest nur die `outbox/` der Lane(s), für die er **Empfänger** ist.
- **Folge (Kernentscheidung):** Zwei gleichzeitig aktive Poller (A *und* B) teilen sich
  niemals einen Claim-Pool. Die im Code dokumentierte Cross-Device-Claim-Race
  (`os.rename` ist nur lokal atomar, `bridge_common.py:171-181`) kann damit **strukturell
  nicht auftreten** — sie wird nicht verwaltet, sondern an der Wurzel entfernt.
- Der `to`-Filter (siehe §2) bleibt als Zusatzsicherung (Gürtel + Hosenträger), ist aber
  nicht mehr die einzige Verteidigung.

`bridge_common` ersetzt `outbox_dir()`/`inbox_dir()`/`processed_dir()`/`errors_dir()` durch
eine **endpoint-/lane-parametrierte Auflösung**. Die heutige A→B-Codex-Richtung wird dabei
zu *einer konfigurierten Lane* — kein Sonderfall, Stage 1 bleibt regressionsfrei.

### 2. Adapter-/Runner-Modell

**Frontmatter-Erweiterung** (additiv; Alt-Tasks bleiben gültig):

```yaml
schema_version: 2                  # NEU: einzelnes Feld, KEIN Migrations-Apparat
adapter: codex | claude | echo     # NEU: das Modell ("Womit"). Default echo, wenn fehlend.
kind:    implement | research | review | test   # bleibt: Fachabsicht ("Was")
from:    codex@laptop-b             # NEU: Absender-Endpoint
to:      claude@laptop-a            # NEU: Ziel-Endpoint (= Lane-Empfänger)
```

`adapter` ist explizit — **keine** versteckte Ableitung aus `kind`. Fehlt es (Stage-1-Alt-Task),
gilt Default `echo`.

**Runner-Schnittstelle** — schlanker Funktions-Vertrag, kein Klassen-Framework:

```python
def run(auftrag: str, fm: dict, workroot: Path) -> RunnerResult: ...
RUNNERS = {"echo": run_echo, "codex": run_codex, "claude": run_claude}
```

- **Ein** gemeinsames `RunnerResult`-Dataclass für alle Runner (status, antwort, optional
  branch/commit/changed_files, error_text, stderr_excerpt, note). Das heutige `CodexResult`
  wird darauf umgestellt/umbenannt.
- **Git-Publishing ist NICHT im Runner-Vertrag erzwungen.** Nur `run_codex` committet/pusht;
  `run_claude` und `run_echo` geben nur Text zurück. Das löst „ein Research-/Claude-Runner
  erbt ungewollt die Git-Pflicht".

**`process_one` zerlegt in `claim → route → run → publish`:**

- `route`: validiert `task_id` (bereits vorhanden), prüft `to`-Filter, wählt
  `RUNNERS[fm.get("adapter","echo")]`. Unbekannter Adapter → `status:error` (kein Crash).
- `run`: ruft den gewählten Runner.
- `publish`: schreibt das Result in die `inbox/` der Lane. Das heutige
  `_build_codex_result_body`-Rendering (`handoff_poll.py`) wandert zu `RunnerResult.to_markdown()`
  (raus aus dem Poller).

**Drei Runner:**

- `run_echo` — heutiges Stage-0-Echo, unverändert (Regressionsanker).
- `run_codex` — heutiges `codex_adapter.run_codex_task`, auf die gemeinsame Signatur gebracht.
  Inkl. **Repo-Allowlist**-Guard (`DUAL_BRIDGE_REPO_ALLOWLIST` env; Default leer = alle erlaubt,
  rückwärtskompatibel) gegen ungeprüfte Clone-URLs.
- `run_claude` — **neu**: echter `claude -p` headless. Output per **P006** robust geparst
  (BOM strippen, `json.JSONDecoder().raw_decode()` gegen Trailing-Hook-Müll, finales
  `type:result`-Event, `CLAUDE_CODE_DISABLE_HOOKS=1` im Subprozess-env). `stdin=DEVNULL`
  (Windows-Hang-Guard). **Kein erzwungener Git-Branch** — nur Text/Antwort zurück.

### 3. Bidirektionale CLI & Konfiguration

**Endpoint-Konfiguration** — eine explizite Quelle der Wahrheit pro Maschine:

```
DUAL_BRIDGE_ENDPOINT = "claude@laptop-a"   # wer bin ich (env-Var)
```

Die Endpoint→Lane-Zuordnung lebt als kleines `dict` in `bridge_common` (kein Config-File,
kein YAML-Parser — zwei Endpoints, ein Mensch). Daraus leitet sich ab: welche Lanes ich als
Empfänger polle, in welche Lane ich als Sender schreibe.

**CLI-Symmetrie** — dieselben Skripte, beide Richtungen:

- `handoff_write.py`: neue Args `--adapter` und `--to` (Default-`to` = Gegenstelle laut
  Endpoint-Tabelle). `--target`/`--repo`/`--base-branch` bleiben.
- `handoff_poll.py` + `handoff_collect.py`: **endpoint-relativ** statt fest „B pollt / A sammelt".
  Auf A *und* B identisch lauffähig; die Richtung bestimmt allein `DUAL_BRIDGE_ENDPOINT` +
  Lane-Zuordnung. „A→B umkehren zu B→A" wird reine Konfiguration.
- Die hartkodierten Strings `laptop-a-claude` / `laptop-b-worker`
  (`handoff_write.py:49`, `handoff_poll.py:51,99`) verschwinden zugunsten des Endpoint-Namens.

## Datenfluss (B→A-Beispiel, neu möglich)

1. Endpoint `codex@laptop-b` schreibt Task (`--to claude@laptop-a --adapter claude`) →
   `lane-B-to-A/outbox/task-<id>.md`.
2. Endpoint `claude@laptop-a` pollt `lane-B-to-A/outbox/` (er ist Empfänger), claimt,
   `route` → `run_claude` (`claude -p`), `publish` → `lane-B-to-A/inbox/result-<id>.md`.
3. `codex@laptop-b` sammelt aus `lane-B-to-A/inbox/`.

A→B-Codex (Stage 1) läuft identisch über `lane-A-to-B`, nur andere Endpoint-/Adapter-Config.

## Fehlerbehandlung

- Unbekannter `adapter` → `status:error` (kein Crash), Result mit klarer Meldung.
- `run_claude`-Parsing: leere/BOM-only Antwort → `status:error` (wie Codex-Pfad heute).
- Repo nicht in Allowlist → `status:error` vor jedem Clone.
- Alle Phase-0-Garantien bleiben: P0-Requeue, Sibling-Surrender-Cleanup, task_id-Validierung
  (inkl. Recovery-Pfad), Adapter-Catch — unverändert wirksam.

## Test- & Regressionsstrategie (TDD)

1. **Regressionsanker zuerst:** A→B-Codex als *eine konfigurierte Lane* unverändert grün.
   `test_stage1.py` 17/17 + `test_hardening.py` 10/10 laufen weiter (Endpoint-env in `_fresh_bridge`).
2. **Neue Unit-Tests:**
   - (a) Lane-Auflösung pro Endpoint.
   - (b) `to`-Filter überspringt Fremd-Lane-Tasks.
   - (c) Runner-Dispatch `echo`/`codex`/`claude` inkl. unbekannter Adapter → `status:error`.
   - (d) **B→A-Roundtrip** mit getauschter Endpoint-Config (Echo reicht als Beweis).
   - (e) `run_claude`-Parsing gegen P006-Müll-Shapes (Fake-CLI wie beim Codex-Fake).
3. **Live-Beweis (separater Schritt, NICHT in der Unit-Suite, P007):** echter `claude -p`
   auf einem Knoten, Ground-Truth-verifiziert.

## Bewusst draußen (YAGNI — aus der Multi-Perspektiven-Synthese)

`FileBridgeStore`-Klasse · `TaskRunner`-Interface-Hierarchie · Router/Registry-Framework ·
`schema_version`-Migrations-Maschinerie (nur das eine Feld, kein Apparat) · `conversation_id` ·
`trust.signed` · HTTP-Transport-Abstraktion · Overnight-Scheduler · der Review-Loop selbst
(= Stage 2b).

## Erfolgskriterien

- [ ] B→A funktioniert per Konfiguration, ohne neue Spezial-Skripte.
- [ ] Codex→Claude funktioniert: `run_claude` ist real lauffähig (Live-Beweis erbracht).
- [ ] `adapter` trennt Modell von `kind`-Fachabsicht; Runner-dict dispatcht darauf.
- [ ] Zwei gleichzeitige Poller (A+B) ohne Claim-Race (Lane-Trennung).
- [ ] Git-Publishing nur im Codex-Runner, nicht im Vertrag.
- [ ] Stage-1-Regression vollständig grün; Code-Kern bleibt < ~700 Zeilen.

## Folge-Arbeit (nicht Teil dieser Spec)

- **Wiki-TODOs umschreiben** (= „A" aus der Planung): `2026-05-30-dual-bridge-modulare-v2.md`
  von Envelope/Store/Runner-Klassen auf diesen abgerüsteten Scope umstellen;
  `2026-05-30-dual-bridge-haertung-vor-stage1.md` P0-Punkte als erledigt markieren
  (acc8441/8be392e). Erfolgt beim Plan-/Umsetzungs-Abschluss.
- **Stage 2b:** Peer-Review-Loop + Overnight-Scheduler.
