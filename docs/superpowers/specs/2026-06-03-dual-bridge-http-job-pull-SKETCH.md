# Skizze: HTTP-Job-Pull als Transport für dual-bridge

- **Datum:** 2026-06-03
- **Status:** **SKIZZE / Vorentwurf** — bewusst noch keine Implementierung.
  Dient als Denkrahmen für „echte Verteilung" aus den Nächsten Schritten.
- **Autor:** DoMe + Computer
- **Verhältnis zum Bestand:** ersetzt NICHT den dateibasierten Transport, sondern
  ist eine **alternative Transport-Schicht** mit identischer Lane-/Claim-Semantik.

> Diese Datei ist absichtlich eine Skizze, kein abnehmbarer Bauplan. Sie hält die
> Idee, die Trade-offs und einen möglichen Schnitt fest, damit wir später ohne
> Anlauf in eine echte Design-Spec + TDD gehen können. Nichts hier ist final.

---

## 1. Worum es geht (in einem Satz)

Statt Tasks als `.md`-Dateien über Google-Drive zu synchronisieren, läuft ein
kleiner **HTTP-Job-Broker**; die Knoten **ziehen** sich Jobs per HTTP ab
(„Pull") — **mit demselben Claim-Mechanismus**, den der Dateitransport heute schon hat.

## 2. Warum überhaupt (Motivation)

Der heutige Dateitransport (zwei Lanes über Drive, atomarer Claim via `os.rename`,
`_processed`/`_errors`) funktioniert und ist race-frei. Seine Grenzen:

- **Latenz:** Drive-Sync braucht Sekunden bis Minuten; ein Task ist erst „da",
  wenn der Cloud-Client synchronisiert hat.
- **Skalierung:** sauber für A↔B (zwei feste Lanes), aber unhandlich für N Worker.
- **Zustellsicherheit:** hängt am Verhalten des Drive-Clients, nicht an einem
  Service, den wir kontrollieren.

HTTP-Job-Pull adressiert genau diese drei Punkte — **ohne** die bewährte Semantik
über Bord zu werfen.

## 3. Leitprinzip: gleiche Semantik, anderes Medium

Das ist der Kern. Was **gleich bleibt**:

| Konzept | Heute (Datei) | HTTP-Job-Pull |
|---|---|---|
| Richtungstrennung | zwei Lanes (`lane-A-to-B`/`lane-B-to-A`) | `lane`-Feld am Job; Pull filtert nach Lane |
| Atomarer Claim | `os.rename` → `task-<id>.claimed-<device>-<cid>.md` | serverseitige Transaktion: `open → claimed` |
| Race-Freiheit | getrennte Claim-Pools je Lane | DB-Transaktion: genau ein Worker gewinnt |
| Status-Lebenszyklus | `open → claimed → done → consumed` | identisch, als Spalte/Feld |
| Quarantäne | `_errors/` für invalide `task_id` | `status=error` + Grund, eigener Abruf |
| Crash-Requeue | geclaimter Task ohne Result wird requeued | Lease-Timeout → zurück auf `open` |
| Code lokal, Daten getrennt | Scripts lokal, Sharepoint nur Daten | Broker hält nur Daten, Runner bleiben lokal |

Was sich **ändert**: nur die Transport-/Speicherschicht. „Datei im Ordner" wird zu
„Zeile in einer Job-Tabelle hinter HTTP". Das ist exakt dasselbe Muster wie die
DCO-Readiness von Notifier/Scheduler: **die Kernlogik bleibt, nur der Caller wechselt.**

## 4. Grobe Architektur

```
                 ┌─────────────────────────────────────┐
                 │        bridge-broker (HTTP)          │
                 │  FastAPI + SQLite (jobs.db, WAL)     │
                 │  Lanes · Claim-Transaktion · Lease   │
                 └───────────────┬─────────────────────┘
        POST /jobs (enqueue)     │      GET /jobs/next?lane=…  (claim)
        GET  /jobs/<id>          │      POST /jobs/<id>/result
                 ▲               │               ▲
   handoff_write │               │               │ handoff_poll / handoff_collect
        (Producer)               ▼               (Worker auf A und B)
                       jobs.db (eine Quelle)
```

- **Ein Broker** ist die einzige Wahrheit über offene Jobs (statt verstreuter Dateien).
- **Worker pollen aktiv** (`GET /jobs/next`) — der Broker pusht nichts, er gibt beim
  Abruf atomar genau einen Job heraus und markiert ihn `claimed` (mit Lease).
- **Producer enqueuen** (`POST /jobs`) — das ist die HTTP-Variante von `handoff_write`.

## 5. Minimale HTTP-Oberfläche (Vorschlag)

| Methode | Pfad | Zweck | Datei-Äquivalent heute |
|---|---|---|---|
| `POST` | `/jobs` | Job einreihen (`lane`, `adapter`, `kind`, `repo`, `payload`) | `handoff_write.py` schreibt outbox |
| `GET` | `/jobs/next?lane=…&worker=…` | **atomar claimen** (genau einer gewinnt), Lease setzen | Poller claimt via `os.rename` |
| `POST` | `/jobs/<id>/result` | Result melden (`done`/`error` + Body) | Result-Datei in Gegen-Lane |
| `GET` | `/jobs/<id>` | Status/Result abfragen | `handoff_collect.py` liest inbox |
| `POST` | `/jobs/<id>/heartbeat` | Lease verlängern (lange Läufe) | — (neu, ersetzt „lebt noch?") |

Job-Schema spiegelt das heutige Frontmatter 1:1: `task_id`, `lane`, `adapter`
(`echo`/`codex`/`claude`), `kind`, `repo`, `payload`, `status`, `claimed_by`,
`claimed_at`, `result`. **Adapter/Runner-Vertrag bleibt unverändert** — der Broker
liefert nur den Job, ausgeführt wird weiter lokal mit demselben `RUNNERS`-Dispatch.

## 6. Der Claim — das Herzstück

Heute: `os.rename` ist die atomare Operation, die das Race entscheidet (Sibling-
Surrender räumt Verlierer auf). Im Broker übernimmt das eine **DB-Transaktion**:

```sql
-- vereinfacht: genau ein Worker bekommt den Job
UPDATE jobs SET status='claimed', claimed_by=:worker, claimed_at=:now,
                lease_until=:now_plus_ttl
WHERE id = (SELECT id FROM jobs
            WHERE status='open' AND lane=:lane
            ORDER BY created ASC LIMIT 1)
RETURNING *;
```

- **Genau einer gewinnt**, weil die Transaktion serialisiert (SQLite WAL +
  `BEGIN IMMEDIATE`). Kein Sibling-Surrender mehr nötig — das Problem existiert
  serverseitig gar nicht erst.
- **Lease/Requeue:** Ein Hintergrund-Sweep setzt Jobs mit `lease_until < now` und
  ohne Result zurück auf `open` — das ist das saubere Pendant zum heutigen
  „P0-Crash-Requeue".

## 7. Sicherheit (an deinen Stack angeschlossen)

Hier greifen direkt deine vorhandenen Dossiers
(`mcp-secure-exposure-dossier.md`, `mcp-remote-exposition-dossier.md`):

- **Kein offenes Internet by default.** Broker bindet auf `127.0.0.1` bzw. ins
  Tailnet/VPN; nach außen nur über denselben Cloudflare-Tunnel-Mechanismus, den
  Lane-B bereits nutzt.
- **Auth:** Bearer-Token je Worker (kein anonymer Pull). Tokens via Env, nie im Job.
- **Keine Secrets im Payload** (Regel 6 bleibt). `repo`-Allowlist serverseitig
  durchsetzen (heute `DUAL_BRIDGE_REPO_ALLOWLIST`).
- **Audit:** Jobs werden nie gelöscht, nur `status=consumed` + Archiv (Regel 7).

## 8. Migrationspfad (nicht-disruptiv)

1. **Broker neben dem Dateitransport** betreiben — Dateitransport bleibt Default.
2. **Adapter-Schicht im Worker:** `handoff_poll` bekommt einen zweiten „Quell-Treiber"
   (`file` | `http`), gewählt per Env (`DUAL_BRIDGE_TRANSPORT`). Die Run-/Publish-
   Logik dahinter ist identisch.
3. **Schattenbetrieb:** dieselben Jobs testweise über beide Wege, Ergebnisse vergleichen.
4. **Umschalten je Lane**, wenn HTTP stabil ist. Datei bleibt Fallback.

→ Damit ist es derselbe „injizierbare Caller"-Trick: der Worker weiß nicht, woher
der Job kam.

## 9. Anschluss an den DCO (gegen den echten IST-Zustand)

Wichtigste Erkenntnis nach Sichtung der realen DCO-Quellen: **Der DCO ist den
Broker schon fast** — wir müssen kein zweites Queue-System bauen, sondern nur
einen kleinen Übersetzungsschritt einziehen.

### 9.1 Was im DCO bereits existiert

- **`jobs`-Tabelle mit atomarem Claim.** `jobs.py` hat `create_job(chat_id, ...)`
  mit `worker_type`, `result_payload` und Status `queued/running/waiting_approval`.
  Der Claim läuft über `transition_status(job_id, expected_status, status, ...)`,
  intern ein `UPDATE jobs SET status=? ... WHERE job_id=? AND status=?` — also
  **exakt das Compare-and-Swap**, das diese Skizze für den Broker vorschlägt. Das
  „nur einer gewinnt das Rennen"-Problem ist im DCO bereits sauber gelöst.
- **`todos`-Tabelle ist eine menschliche To-do-Liste**, KEINE Job-Queue:
  `todos.py` mit `add(chat_id, text, parent_id)`, Feldern `todo_id, chat_id, text,
  done, tag (DEFAULT 'sonst'), parent_id, stale_level`. Tags aus `config.py`
  (`VALID_TAGS`, `DEFAULT_TAG="sonst"`).
- **Robuste Persistenz.** `db.py`: thread-local SQLite + WAL +
  `wal_autocheckpoint=100`, `lazy_path()`-Resolver (DATA_DIR wird frisch gelesen —
  Daten-Sicherheits-Invariante). Reicht für N≈2–5 Geräte locker.

→ Konsequenz: **Wir brauchen keinen separaten Broker-Service.** Die `jobs`-Tabelle
IST die Claim-fähige Queue aus Abschnitt 3–4. Was fehlt, ist (a) ein Mini-Router
`todos → jobs` und (b) ein HTTP-Pull-Endpunkt für die Bridge-Worker.

### 9.2 Der Wunschfluss (genau wie vom User beschrieben)

```
[Mensch/Agent]  todos.add(chat_id, text, tag="bridge")        ← eine Zeile in die To-do
      │
      ▼
[DCO-Router]    erkennt tag=="bridge" → create_job(            ← kleiner Übersetzer
                  worker_type="dual-bridge",
                  payload={repo, kind, adapter, text}, status="queued")
      │
      ▼
[jobs-Tabelle]  status=queued                                  ← schon da, atomar
      │   GET /jobs/next?worker_type=dual-bridge
      ▼   (transition_status queued→running = der Claim)
[Bridge-Worker] handoff_poll mit DUAL_BRIDGE_TRANSPORT=http     ← injizierbarer Caller
      │   führt loop_driver/Adapter aus (lokal, wie heute)
      ▼   POST /jobs/<id>/result {result_payload, rc}
[jobs-Tabelle]  status=running→done (oder waiting_approval/error)
      │
      ▼
[DCO-Router]    markiert den Quell-Todo done + Notifier-Digest  ← Kreis geschlossen
```

Der Bridge-Worker weiß weiterhin **nicht**, woher der Job kam — derselbe
„injizierbarer Caller"-Trick wie beim Dateitransport (Abschnitt 8). Nur der
Quell-Treiber wechselt von `file` auf `http`.

### 9.3 Die zwei kleinen neuen Teile

1. **Router/Übersetzer `todos → jobs`** (im DCO):
   - Trigger: ein Todo mit definiertem Tag (Vorschlag: `tag="bridge"`, erweitert
     `VALID_TAGS`). Tag-basiertes Routing hält es entkoppelt — nur getaggte Todos
     werden zu Jobs, der Rest bleibt reine menschliche Liste.
   - Mapping: Todo-`text` → Job-`payload`. Konvention im Text oder strukturiertes
     Feld (z. B. erste Zeile `repo=…  kind=implement  adapter=codex`, Rest = Auftrag).
   - Idempotenz: pro Todo höchstens ein Job (Job referenziert `todo_id`).
2. **HTTP-Pull-Oberfläche über die `jobs`-Tabelle:**
   - `GET /jobs/next?worker_type=dual-bridge` → `transition_status(queued→running)`
     als atomarer Claim (Code existiert, nur als Endpoint freilegen).
   - `POST /jobs/<id>/result` → `transition_status(running→done|waiting_approval|error)`,
     schreibt `result_payload`, triggert Notifier-Digest + Todo-`done`.
   - Bind auf `127.0.0.1`/Tailnet, Bearer-Token (Abschnitt 7), `repo`-Allowlist.

### 9.4 Warum das so gut passt

- **Eine DB statt zwei.** Kein zweites Queue-Schema, keine Sync-Probleme zwischen
  Broker und DCO — der Broker IST der DCO.
- **Exit-Mapping bleibt identisch.** loop_driver `0=accepted, 3=escalated,
  2/1=error` mappt direkt auf `done / waiting_approval / error` der `jobs`-Tabelle —
  dieselbe Semantik wie der Overnight-Scheduler heute (`_EXIT_OUTCOME`).
- **DCO-ready zahlt sich aus.** Notifier und Overnight-Scheduler sind bereits mit
  injizierbarem `run_fn`/`send_fn` gebaut; der Router muss nur `create_job` aufrufen
  und am Ende den Digest auslösen.

## 10. Offene Fragen (vor einer echten Spec zu klären)

- **Router-Ort:** als DCO-internes Modul (gleiche `db.py`/Transaktion) oder als
  schmaler Sidecar, der `jobs.create_job()` aufruft? (Tendenz: intern, eine DB.)
- **Tag-Konvention:** `tag="bridge"` neu in `VALID_TAGS`, oder eigener
  `worker_type`-Marker im Todo-Text? Wie wird `repo/kind/adapter` aus dem Text geparst
  (strukturierte erste Zeile vs. separate Felder)?
- **Todo↔Job-Lebenszyklus:** Wer markiert den Quell-Todo `done` — der Router beim
  Result-Callback, automatisch, oder erst nach Mensch-Bestätigung bei
  `waiting_approval`?
- **HTTP-Endpunkte am DCO:** kommen sie in dessen vorhandenes `api.py` (FastAPI) oder
  in einen separaten Bridge-Router-Mount? Auth-Token-Quelle (Env wie heute)?
- **Hosting:** rein lokal/Tailnet, oder über Tunnel auch von unterwegs erreichbar?
- **Push statt Pull später?** (Long-Polling/SSE für Sofort-Zustellung — Pull zuerst.)
- **Brauchen wir es jetzt?** Erst wenn Drive-Latenz/N>2 real wehtun. Sonst liegen lassen.

## 11. Bewusst NICHT in dieser Skizze

- Konkrete Endpoints-Signaturen final, Auth-Flow im Detail, DB-Schema-DDL.
- Tests (kommen erst in der echten Spec, dann TDD wie bei Notifier/Scheduler).
- Entscheidung Broker-im-DCO vs. standalone.

→ Nächster Schritt, **wenn** wir es angehen: diese Skizze zu einer echten
Design-Spec im `specs/`-Stil verdichten (Endpoints fix, DB-Schema, Sicherheits-
modell, Testliste), freigeben, dann TDD.
