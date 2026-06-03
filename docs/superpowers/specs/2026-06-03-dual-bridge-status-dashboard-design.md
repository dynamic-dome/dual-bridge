# Dual-Bridge — Status-Dashboard (Observability über beide Geräte)

*Datum: 2026-06-03*
*Autor: Perplexity Computer, nach Ground-Truth-Code-Verifikation des kompletten Repos*
*Projekt: Dual-Laptop-Bridge (`~/AI/dual-bridge`, Repo `dynamic-dome/dual-bridge`)*
*Status: Design — zur Umsetzung freigegeben nach User-Review*

## Kontext & Motivation

Die Bridge ist ein **dateibasiertes, verteiltes System über zwei Geräte** ohne zentralen
Server. Genau das ist die Stärke (kein Broker, kein Socket) — und die Achillesferse der
Bedienbarkeit: **Es gibt aktuell keinen einzigen Befehl, der den Gesamtzustand zeigt.** Wer
wissen will, was läuft, muss heute:

- mehrere Lane-Ordner im Drive (`lane-A-to-B/`, `lane-B-to-A/`, je `outbox/inbox/_processed/_errors/`)
  von Hand durchsehen,
- `state/LOOP-*.jsonl` einzeln öffnen, um Loop-Runden zu rekonstruieren,
- `state/ESCALATION-*.md` manuell finden, um zu sehen, ob ein Loop auf eine Owner-Entscheidung wartet,
- `docs/latency-baseline.md` / Latenz-Probes getrennt nachschlagen.

Das ist der typische Blindflug eines file-based Systems: der Zustand liegt **korrekt und
durable** vor (genau wie es das Design will), aber **verstreut**. Es fehlt die Lese-Linse.

### Leitprinzip (die Invariante)

**Das Dashboard ist eine reine Lese-Linse. Es claimt nie, schreibt nie in den Drive, mutiert
keinen Loop-State.** Es kann das System strukturell nicht kaputt machen — kein Claim-Race, kein
versehentliches Verschieben, kein Lock. Damit ist es gefahrlos auf BEIDEN Geräten parallel
laufbar, jederzeit, auch während Poller und Loop-Driver aktiv arbeiten.

Das passt zur Sicherheitsphilosophie des Repos (Manifest: Code lokal, kein Auto-Delete, keine
Secrets) und hält die Komponente testbar: ein read-only-Tool über einem temporären Lane-Baum.

## Ground-Truth: was bereits existiert (verifiziert am Code, nichts neu)

Das Dashboard erfindet **kein** neues Datenformat — es liest exakt die Artefakte, die das
System ohnehin schon schreibt:

- **Lanes** (`bridge_common.py`): `lane-A-to-B` / `lane-B-to-A`, je `outbox/ inbox/ _processed/ _errors/`.
  Helper `lane_outbox/lane_inbox/lane_processed/lane_errors` + `ENDPOINTS`-Dict liefern alle Pfade.
- **Task-Frontmatter** (`parse_frontmatter`): `status` (`open→claimed→done→consumed`), `task_id`,
  `kind`, `adapter`, `from`/`to`, `created`, `claimed_by`/`claimed_at`, optional `loop_id`/`round`,
  `verdict`/`verdict_reason`, `branch`/`commit`.
- **Claim-Marker im Dateinamen**: `task-<id>.claimed-<device>-<claimid>.md` (`_task_id_from_name`
  extrahiert die id; `claim_task` setzt den Marker).
- **Conflict-Copies**: Google-Drive-Artefakte `... (1).md` — überall per `_is_conflict_copy`
  (`"(" in name and ")" in name`) erkannt und übersprungen. Das Dashboard muss dieselbe Heuristik
  anwenden, sonst zählt es Geister-Tasks.
- **Result-Dateien**: `result-<id>.md` im `inbox/` der Sende-Lane; tragen `status`, optional
  `verdict`, `branch`/`commit`.
- **Loop-History** (`loop_driver.append_state`): `state/LOOP-<loop_id>.jsonl`, append-only, eine
  Zeile pro Runde mit `round`, `side`, `verdict`, `verdict_reason`, `commit`, `task_id`, `status`, `ts`.
- **Eskalationen**: `state/ESCALATION-<loop_id>.md` mit Frontmatter `trigger`, `round`, `branch`,
  `commit`, `exit_reason`, `created` (von `write_escalation`); beim Resume nach `state/_processed/`.
- **Singleton-Lock** (`default_lock_path`): lokale Lock-Datei (Poller bzw. `dual-bridge-loop.lock`),
  Inhalt `pid\ntimestamp`. `_pid_alive` sagt, ob ein Poller/Loop **gerade** läuft.
- **Latenz** (`latency_probe.py` / `docs/latency-baseline.md`): bestehende Roundtrip-Messung.

**Daraus folgt:** Das Dashboard ist ein *Aggregator über vorhandene Artefakte*. Kein neues
Schema, keine neue Schreibstelle, keine DB. Maximale Wiederverwendung von `bridge_common`.

## Architektur — additiv, kein Umbau

Neues, eigenständiges Script `scripts/bridge_status.py` + neue Testdatei
`scripts/test_bridge_status.py`. **Keine** Änderung an `bridge_common.py`, `handoff_*.py`,
`loop_driver.py`, `runners.py` oder den Adaptern. Die bestehenden 146 Tests bleiben unangetastet
grün; das Dashboard fügt nur neue dazu.

Das Script importiert `bridge_common as bc` und nutzt dessen Pfad-Helper + Parser, statt Pfade neu
zu hardcoden. So erbt es automatisch jede künftige Lane-/Endpoint-Änderung.

### Komponente 1 — Lane-Scanner (read-only Inventur)

Eine Funktion `scan_lane(lane: str) -> LaneStatus` liest **ohne zu mutieren** alle vier Unterordner
einer Lane und klassifiziert jede Datei:

| Bucket | Quelle | Bedeutung |
|---|---|---|
| `open` | `outbox/task-*.md` (kein `.claimed-`, keine Conflict-Copy) | wartet auf einen Empfänger |
| `claimed` | `outbox/task-*.claimed-*.md` | in Bearbeitung (Device aus dem Namen) |
| `results` | `inbox/result-*.md` | fertige Ergebnisse, noch nicht eingesammelt |
| `processed` | `_processed/*.md` | Archiv (Count genügt, keine Detail-Liste) |
| `errors` | `_errors/*.md` | quarantänte Tasks (invalide task_id) — **immer prominent** |
| `conflicts` | beliebige `... (N).md` | Drive-Sync-Konfliktkopien — Warnsignal |

Pro offenem/geclaimtem Task werden die Frontmatter-Felder gelesen (`task_id`, `kind`, `adapter`,
`from`/`to`, `created`, `claimed_by`, optional `loop_id`/`round`). Ein **Alters-Feld** (`age`,
abgeleitet aus `created` vs. jetzt) macht hängende Tasks sichtbar.

`scan_lane` muss `_is_conflict_copy` exakt wie der Rest des Codes anwenden und einen
**halbgeschriebenen Task** (Frontmatter parsebar, aber `task_id` fehlt — realer Drive-Sync-Fall,
siehe `wait_for_result`) als eigenen, nicht-fatalen Sonderfall führen, nie als gültigen Task zählen.

### Komponente 2 — Loop-Tracker (aktive & abgeschlossene Loops)

Eine Funktion `scan_loops(state_dir) -> list[LoopStatus]` aggregiert `state/LOOP-*.jsonl`:

- letzte Runde, `rounds_done`, letztes `verdict`, letzter `commit`, `final_branch` (`bridge/<loop_id>`),
- Endzustand abgeleitet: `accepted` / `escalated` / `running` / `aborted` (aus der letzten
  JSONL-Zeile + Existenz einer `ESCALATION-<loop_id>.md`),
- Querverweis auf eine offene Eskalation (Komponente 3).

JSONL wird **defensiv** gelesen (eine kaputte Zeile darf den Scan nicht abreißen — dieselbe
„never-crash"-Haltung wie der Poller). Append-only-Natur heißt: die **letzte** Zeile ist der
aktuelle Stand.

### Komponente 3 — Eskalations-Inbox (was auf den Owner wartet)

Eine Funktion `scan_escalations(state_dir) -> list[EscalationStatus]` liest `state/ESCALATION-*.md`
(nur das Verzeichnis, NICHT `state/_processed/` — letzteres ist erledigt). Pro Datei:
`loop_id`, `trigger`, `round`, `branch`, `commit`, `created`. Das ist die **Aktions-Liste des
Menschen**: „diese Loops hängen und brauchen eine Entscheidung". Im Dashboard ganz oben, weil es
das einzige ist, das aktiv Handlung erfordert.

### Komponente 4 — Liveness (laufen Poller/Loop-Driver gerade?)

Eine Funktion `scan_liveness() -> LivenessStatus` liest die lokalen Lock-Dateien
(`default_lock_path()` für den Poller, `...dual-bridge-loop.lock` für den Loop-Driver) und meldet
via `bc._pid_alive(pid)`, ob auf **diesem** Gerät ein Poller bzw. Loop-Driver aktiv ist (inkl.
PID + Startzeit aus der Lock-Datei).

**Ehrliche Grenze (P007):** Das sagt nur etwas über das **lokale** Gerät — die Lock-Datei liegt
bewusst lokal, nie im Drive (dieselbe F1-Lektion: local-atomic ≠ distributed). Über das andere
Gerät kann das Dashboard nur *indirekt* schließen (z.B. „Tasks werden geclaimt, also pollt drüben
jemand"). Das wird so benannt, nicht vorgetäuscht. Kein Heartbeat-File im Drive (YAGNI, würde die
„keine neue Schreibstelle"-Invariante brechen).

### Komponente 5 — Rendering (zwei Ausgabeformate)

Eine reine Render-Schicht, getrennt von den Scannern (Scanner liefern Dataclasses, Renderer
formatiert):

1. **`--format text`** (Default): kompakte, farb-freie Konsolen-Übersicht mit Ampel-Symbolen
   (ASCII-fallback-fähig wegen Windows-Codepage — UTF-8 ist über `ensure_utf8_runtime` gesichert,
   aber das Layout bleibt auch in reinem ASCII lesbar). Reihenfolge nach Dringlichkeit:
   `ESKALATIONEN (Owner-Aktion)` → `_errors/ (Quarantäne)` → `Aktive Loops` → `Offene/geclaimte
   Tasks pro Lane` → `Liveness` → `Zähler-Summary`.
2. **`--format json`**: dasselbe Modell als ein JSON-Objekt (`asdict` der Dataclasses) — maschinen-
   lesbar für die spätere Integration in DCO / einen Cron-Health-Check / das Heartbeat-Skill, ohne
   den Text-Output parsen zu müssen.

`--watch [--interval N]` rendert wiederholt (clear + redraw), analog zu `handoff_poll.py --watch`,
aber **rein lesend** — kein Lock nötig (mehrere Dashboards dürfen koexistieren).

### CLI (endpoint-relativ, identisch auf A und B)

```bash
cd ~/AI/dual-bridge/scripts
python bridge_status.py                 # Momentaufnahme, Text
python bridge_status.py --watch         # Live-View, alle 10s neu
python bridge_status.py --format json   # maschinenlesbar (DCO/Cron/Heartbeat)
python bridge_status.py --lane A-to-B   # nur eine Lane (Default: alle)
```

`DUAL_BRIDGE_ENDPOINT` / `DUAL_BRIDGE_ROOT` werden respektiert (über `bc`), damit dieselbe Sicht
auf beiden Geräten gilt. Default-Verhalten: alle bekannten Lanes scannen, nicht nur die des
aktuellen Endpoints — der Sinn eines Dashboards ist die **Gesamtsicht**.

## Testen

### Unit (`scripts/test_bridge_status.py`; gegen einen temporären Lane-Baum, kein echtes Drive)

Der bestehende `conftest.py`-Autouse-Fixture `_isolate_dual_bridge_state` (tmp_path,
`DUAL_BRIDGE_ROOT`-Override) wird wiederverwendet — kein echter Drive-Zugriff, deterministisch.

- (a) `scan_lane` zählt offene/geclaimte/result/processed/error-Dateien korrekt in einem
  präparierten Lane-Baum.
- (b) Conflict-Copies (`task-... (1).md`) werden NICHT als gültige Tasks gezählt, sondern als
  `conflicts` ausgewiesen (dieselbe `_is_conflict_copy`-Heuristik wie der Produktivcode).
- (c) Halbgeschriebener Task (Frontmatter ohne `task_id`) → eigener `incomplete`-Bucket, kein Crash,
  nie als gültiger Task gezählt.
- (d) `_errors/`-Inhalt wird separat und prominent gezählt (Quarantäne sichtbar).
- (e) `scan_loops` rekonstruiert aus einer mehrzeiligen `LOOP-<id>.jsonl` die letzte Runde +
  letztes Verdikt + Endzustand; eine kaputte JSONL-Zeile bricht den Scan NICHT ab.
- (f) Loop mit vorhandener `ESCALATION-<id>.md` → Endzustand `escalated`, Querverweis gesetzt.
- (g) `scan_escalations` liest nur `state/*.md`, NICHT `state/_processed/*.md` (erledigte zählen nicht).
- (h) `scan_liveness`: lebende PID in der Lock-Datei → `running`; tote/abwesende PID → `not running`
  (mit gemocktem `_pid_alive`, damit der Test plattformunabhängig läuft).
- (i) `--format json`: Output ist valides JSON und enthält die Top-Level-Keys
  (`escalations`, `errors`, `loops`, `lanes`, `liveness`, `summary`).
- (j) Render-Reihenfolge: Eskalationen + `_errors/` erscheinen VOR den normalen Lane-Tabellen
  (Dringlichkeit zuerst) — gegen den Text-Output assertet.
- (k) Leerer Bridge-Baum → sauberer „alles ruhig"-Output, kein Crash, Exit 0.
- Regression: das neue Modul importiert sauber neben den bestehenden; `pytest --co -q` zählt jetzt
  146 + N Tests (Exit-5-Trap), voller Lauf bleibt grün.

### Live-Smoke (separater Schritt, NICHT in der Unit-Suite — P007)

Auf A einen echten Stand erzeugen (eine offene Task + eine abgeschlossene + ggf. eine Eskalation
aus einem früheren Lauf), dann `python bridge_status.py` real laufen lassen und den Output
**byte-genau gegen die Drive-Ordner gegenlesen** (P007 — nicht dem Tool glauben, sondern die
Ordner manuell verifizieren). `--format json` einmal durch `python -m json.tool` schicken
(valides JSON beweisen).

## Erfolgskriterien

- [ ] `bridge_status.py` ist **read-only**: kein Test und kein Codepfad schreibt/verschiebt/claimt
      im Lane-Baum (durch einen Test bewiesen, der das Baum-Inventar vor/nach dem Scan vergleicht).
- [ ] Alle vier Lane-Unterordner werden korrekt klassifiziert; Conflict-Copies und halbgeschriebene
      Tasks werden nie als gültige Tasks gezählt.
- [ ] Aktive/abgeschlossene Loops werden aus `LOOP-*.jsonl` rekonstruiert; eine kaputte Zeile
      bricht nichts ab.
- [ ] Offene Eskalationen erscheinen als oberste, prominente „Owner-Aktion"-Liste; erledigte
      (`_processed/`) zählen nicht.
- [ ] Liveness meldet ehrlich nur den lokalen Stand (Lock + PID-Liveness), ohne Cross-Device zu
      faken.
- [ ] Zwei Formate: `text` (Default, ASCII-robust) und `json` (DCO/Cron/Heartbeat-tauglich);
      `--watch` rein lesend, ohne Lock.
- [ ] Die 146 bestehenden Tests bleiben grün; das Dashboard fügt nur neue dazu.

## Bewusst draußen (YAGNI)

- **Schreibende Aktionen** (Task abbrechen, Lane aufräumen, Eskalation auflösen) — das Dashboard
  ist Lese-Linse; Mutation bleibt bei den bestehenden Skripten. Eine spätere „bridge admin"-Schicht
  ist eigener Scope.
- **Cross-Device-Heartbeat-File im Drive** — bräche die „keine neue Schreibstelle"-Invariante und
  die F1-Lektion (local-atomic ≠ distributed). Indirekte Cross-Device-Hinweise (Claim-Aktivität)
  genügen.
- **Web-/GUI-Dashboard** — Konsole zuerst; ein späteres Web-View kann den `--format json`-Output
  konsumieren (Naht bewusst offen).
- **Latenz-Live-Messung** — das Dashboard *zeigt* eine vorhandene Baseline an, misst aber nicht
  selbst (`latency_probe.py` bleibt das Messwerkzeug).
- **History/Trend über die Zeit** — eine Momentaufnahme genügt; Trend-Aggregation kann der
  JSON-Output später in DCO/Heartbeat speisen.

## Folge-Arbeit (nicht Teil dieser Spec)

- **DCO-/Heartbeat-Integration**: der `--format json`-Output als Eingabe für einen periodischen
  Health-Check (z.B. dein `heartbeat`-Skill oder ein Cron, der bei offener Eskalation/`_errors/`
  benachrichtigt).
- **Notifikations-Naht**: bei einer neuen Eskalation oder einem hängenden Task pushen — baut auf
  dem JSON-Output + der Eskalations-Datei aus der Goal-Loop-Spec auf.
- **Optionales Web-View** auf Basis des JSON-Formats.
