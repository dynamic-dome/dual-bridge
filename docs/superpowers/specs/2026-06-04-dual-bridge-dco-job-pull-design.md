# Design-Spec: DCO-Job-Pull für dual-bridge (todos → jobs → Bridge)

- **Datum:** 2026-06-04
- **Status:** Entwurf (zur Freigabe)
- **Autor:** DoMe + Computer
- **Scope-Komponente:** DCO-seitig: `bridge_router.py` (neu), HTTP-Endpunkte in `api.py` (erweitert), `claim_next()` in `jobs.py` (neu). Bridge-seitig: `http` Quell-Treiber in `handoff_poll.py` (erweitert), `bridge_transport.py` (neu, Treiber-Abstraktion).
- **Baut auf:** DCO `jobs.py`/`todos.py`/`db.py`/`api.py`/`events.py`; dual-bridge `loop_driver.py`, `bridge_notify.py`, `bridge_common.py`, `handoff_poll.py`.
- **Verdichtet:** `2026-06-03-dual-bridge-http-job-pull-SKETCH.md` (Skizze, Abschnitt 9 gegen IST-Zustand).

---

## 1. Problem

Heute schreibt der Bridge-Producer Tasks als **Dateien** über Google Drive; die Worker
pollen Dateien und claimen per atomarem `os.rename`. Das funktioniert für N≈2, hat aber
Drive-Latenz und keine zentrale Sicht. Gleichzeitig existiert mit dem **DCO** bereits
eine SQLite-basierte Job-Maschinerie. Ziel: **eine Aufgabe in die DCO-todos schreiben →
sie wird automatisch zu einem Job → die Bridge zieht ihn per HTTP, baut lokal, meldet das
Ergebnis zurück → der Quell-Todo wird `done` und der Notifier sendet einen Digest.**

## 2. Zielbild

Der DCO **ist** der Broker (keine zweite Queue, keine zweite DB). Es entstehen nur zwei
kleine neue Teile:

1. ein **Router** `todos → jobs` (tag-getriggert), und
2. eine **HTTP-Pull-Oberfläche** über die bestehende `jobs`-Tabelle.

Der Bridge-Worker bleibt transport-agnostisch: er bekommt einen zweiten Quell-Treiber
(`http` neben `file`), gewählt per `DUAL_BRIDGE_TRANSPORT`. Die Run-/Publish-Logik
dahinter (loop_driver/Adapter, Exit-Mapping, ESCALATION-Artefakte) ist **identisch**.

## 3. Erkenntnisse aus dem echten DCO-Code (verifiziert)

| Baustein | IST-Zustand in den Quellen | Konsequenz für die Spec |
|---|---|---|
| **`jobs.transition_status(job_id, expected, status, …)`** | atomares `UPDATE … WHERE job_id=? AND status=?` (CAS), gibt `bool` zurück, `events.emit("job.<status>")` | **CAS ist da** — wird der Claim- und Result-Schritt. Kein neues Lock nötig. |
| **`jobs.create_job(chat_id, …, worker_type, idempotency_key, parent_job_id, trace_id)`** | vorhanden, Status default `queued` | Router ruft das direkt; `idempotency_key = "todo:<todo_id>"`. |
| **`jobs.create_job_if_active_below(…, max_active, active_statuses=(queued,running,waiting_approval))`** | vorhanden — Concurrency-Limit | Router nutzt es, um N parallele Bridge-Jobs zu deckeln. |
| **`claim_next()` / `dequeue()`** | **existiert NICHT** | **Neuer Helper** `claim_next(worker_type)` = „ältesten queued finden + CAS auf running". |
| **`jobs.recover_stale_jobs()`** | setzt beim Start hängende `queued/running` → `failed` (`STALE_STARTUP_RECOVERY`) | Crash-Recovery vorhanden; Lease-TTL baut darauf auf (Abschnitt 8). |
| **Felder** | `result_status`, `result_error_code`, `result_payload`, `worker_type` default `'chat'` | Bridge-Jobs nutzen `worker_type="dual-bridge"`; Result-Felder bilden Exit-Mapping ab. |
| **`todos.add(chat_id, text, parent_id)`** | setzt **immer** `DEFAULT_TAG='sonst'` — **ignoriert ein Tag-Argument** | Tag muss **nach** dem Insert gesetzt werden, ODER `add()` wird um `tag`-Param erweitert (Abschnitt 6.1). |
| **`todos.list_by_tag(chat_id, tag)`** | validiert gegen `VALID_TAGS`, wirft `ValueError` bei Unbekanntem | `"bridge"` muss in `VALID_TAGS` (config.py) aufgenommen werden. |
| **`db.py`** | thread-local SQLite + WAL + `wal_autocheckpoint=100`, `lazy_path()` | Router läuft in-Prozess in derselben DB/Transaktionswelt. Reicht für N≈2–5. |
| **`events.emit`** | Job-Statuswechsel feuern Events | Result-Hook (Todo-`done` + Notifier-Digest) hängt am `job.done`/`job.waiting_approval`-Event. |

## 4. Entscheidungen (zur Freigabe)

| Thema | Entscheidung (Vorschlag) |
|---|---|
| **Broker-Ort** | **In-Prozess im DCO** — eine DB, kein Sidecar. Router ist ein DCO-Modul. |
| **Trigger todo→job** | **Tag-basiert:** Todo mit `tag="bridge"` (neu in `VALID_TAGS`). Nur getaggte Todos werden Jobs. |
| **Text→Payload** | **Strukturierte erste Zeile** `repo=<URL> kind=<implement|review|increment|echo> adapter=<codex|claude|increment|echo>`, Rest des Textes = Auftrag. |
| **Claim** | Neuer `jobs.claim_next(worker_type)` auf Basis des bestehenden CAS. |
| **Result-Rückweg** | `POST /jobs/<id>/result` → `transition_status(running→done|waiting_approval|error)`; Event-Hook setzt Todo `done` + sendet Digest. |
| **Transport-Schalter Bridge** | `DUAL_BRIDGE_TRANSPORT=file|http` (Default `file`). HTTP ist additiv. |
| **Lebenszyklus Todo** | `accepted/error` → Todo automatisch `done`. `waiting_approval` (escalated) → Todo **bleibt offen**, Mensch entscheidet (fail-closed). |
| **Sicherheit** | Bind `127.0.0.1`/Tailnet, Bearer-Token je Worker, `repo`-Allowlist serverseitig (siehe Dossiers). |

## 5. Architektur

```
[Mensch/Agent]
   todos.add(chat_id, text)  +  tag="bridge"          (eine Zeile → die To-do)
        │  events: todo.created / tag gesetzt
        ▼
[bridge_router.py]  (DCO, in-Prozess)
   parse_seed_line(text) → {repo, kind, adapter, goal}
   jobs.create_job_if_active_below(
       worker_type="dual-bridge",
       idempotency_key=f"todo:{todo_id}",
       input_text=payload_json, max_active=N)        (todo → job, gedeckelt)
        │
        ▼
[jobs-Tabelle]  status=queued                         (bestehend, atomar)
        ▲                                   │
        │ GET /jobs/next?worker_type=…      │
        │  → jobs.claim_next() = CAS        │ POST /jobs/<id>/result {rc, payload}
        │    queued→running                 ▼
[api.py HTTP]  ←———————————————————→  [Bridge-Worker]
                                       handoff_poll  DUAL_BRIDGE_TRANSPORT=http
                                         → loop_driver/Adapter (lokal, wie heute)
                                         → rc 0/3/2/1
        │
        ▼ (transition_status running→done|waiting_approval|error)
[events.emit job.<status>]
        │
        ▼
[Result-Hook]  done/error → todos: markiere todo_id done
               + bridge_notify.send_*_digest()        (Kreis geschlossen)
```

### 5.1 Injizierbarer-Caller-Trick (gleiches Muster wie Notifier/Overnight)

Der Worker weiß **nicht**, woher der Job kam. `handoff_poll` bekommt eine
Treiber-Abstraktion `bridge_transport.Source` mit zwei Implementierungen:

- `FileSource` (heute: Drive-Dateien, `os.rename`-Claim),
- `HttpSource` (neu: `GET /jobs/next`, `POST /jobs/<id>/result`).

Run-/Publish-Logik dahinter ist identisch — exakt der `run_fn`/`send_fn`-Injektions-Trick,
nur eine Ebene höher (Quell-Treiber statt Runner).

## 6. Der Router `todos → jobs`

### 6.1 Tag setzen (DCO-Constraint)

`todos.add()` ignoriert heute ein Tag-Argument. Zwei freigabe-pflichtige Optionen:

- **A (minimal-invasiv):** Router macht `add()` + direktes `UPDATE todos SET tag='bridge'`.
- **B (sauberer):** `todos.add(chat_id, text, parent_id, tag=DEFAULT_TAG)` erweitern.

→ **Empfehlung B**, weil sonst zwei Schreibwege auf dieselbe Zeile entstehen. `"bridge"`
**muss** in `config.VALID_TAGS` ergänzt werden (sonst wirft `list_by_tag`).

### 6.2 Payload-Parsing (`parse_seed_line`)

```
erste Zeile:  repo=https://… kind=implement adapter=codex
rest:         <der eigentliche Goal-Text / Done-Kriterien>
```

- Fehlt `repo` oder ist nicht in der Allowlist → **kein Job**, Todo bekommt
  `result_error_code`-artige Notiz (bzw. Router-Log) + bleibt offen (fail-closed).
- `kind`/`adapter` defaulten auf `implement`/`codex` (dokumentiert).

### 6.3 Idempotenz & Deckelung

- `idempotency_key = "todo:<todo_id>"` → **pro Todo höchstens ein Job**.
- `create_job_if_active_below(max_active=N)` deckelt parallele Bridge-Jobs (N per Env,
  Default 2 = Lane-A/Lane-B-Äquivalent).
- Router ist **idempotent re-runnbar**: schon konvertierte Todos (Job existiert für den
  idempotency_key) werden übersprungen.

## 7. HTTP-Endpunkte (in `api.py`, FastAPI)

| Methode & Pfad | Zweck | DCO-Aufruf darunter |
|---|---|---|
| `GET /jobs/next?worker_type=dual-bridge` | nächsten Job claimen | `jobs.claim_next("dual-bridge")` → `200 {job}` oder `204` (leer) |
| `POST /jobs/<id>/result` | Ergebnis melden | `jobs.transition_status(running → done\|waiting_approval\|error, result_payload, result_status, result_error_code)` |
| `GET /jobs/<id>` | Status abfragen (Debug/Watch) | `jobs.get_job(id)` |

**`jobs.claim_next(worker_type)` (neuer Helper, der einzige neue Kern-Code im DCO):**

```python
def claim_next(worker_type: str) -> dict | None:
    """Ältesten queued-Job dieses worker_type atomar auf running setzen."""
    conn = _get_conn()
    row = conn.execute(
        f"SELECT {_JOB_COLUMNS} FROM jobs "
        "WHERE status='queued' AND worker_type=? "
        "ORDER BY created_at ASC LIMIT 1", (worker_type,)).fetchone()
    if row is None:
        return None
    job = dict(row)
    # CAS: nur wer hier gewinnt, bekommt den Job (Race-frei bei N Workern)
    if not transition_status(job["job_id"], "queued", "running"):
        return claim_next(worker_type)   # verloren → nächsten versuchen
    return job
```

→ Nutzt **ausschließlich** den bereits vorhandenen CAS. Kein neuer Lock-Mechanismus.

**Request/Response (fix):**

```
GET /jobs/next → 200
{ "job_id":"ab12…", "input_text":"repo=… kind=implement adapter=codex\n<goal>",
  "worker_type":"dual-bridge", "trace_id":"…" }

POST /jobs/<id>/result
{ "rc":0, "result_payload":{"branch":"bridge/loop-…","summary":"…"},
  "result_status":"accepted" }
→ 200 {"job_id":"ab12…","status":"done"}
```

## 8. Lease / Crash-Recovery

- **Lease-TTL:** Ein geclaimter (`running`) Job, der länger als `BRIDGE_LEASE_TTL`
  (Default 30 min) nicht per Result abgeschlossen wurde, gilt als verwaist.
- **Recovery:** Beim DCO-Start setzt `recover_stale_jobs()` hängende `queued/running`
  bereits auf `failed`. Für den **laufenden** Betrieb ergänzt ein periodischer Sweep
  (`requeue_stale(ttl)`): `running` mit `updated_at < now-ttl` → zurück auf `queued`
  (CAS `running→queued`), damit ein anderer Worker erneut claimen kann.
- **At-most-once-Garantie** bleibt durch den CAS: zwei Worker können denselben Job nie
  gleichzeitig auf `running` bringen.

## 9. Exit-Mapping (identisch zur restlichen Bridge)

`loop_driver`-Exit-Contract → `jobs`-Status (1:1 wie Overnight `_EXIT_OUTCOME`):

| `rc` | Bridge-Outcome | `jobs.status` | `result_status` | Todo-Folge |
|---|---|---|---|---|
| `0` | accepted | `done` | `accepted` | Todo → `done` |
| `3` | escalated | `waiting_approval` | `escalated` | Todo **bleibt offen** (Mensch) |
| `2` | config/resume | `error` | `error` | Todo bleibt offen + Fehlernotiz |
| `1` | sonstiger Fehler | `error` | `error` | Todo bleibt offen + Fehlernotiz |

## 10. Sicherheit (an die Dossiers angeschlossen)

Greift direkt `mcp-secure-exposure-dossier.md` / `mcp-remote-exposition-dossier.md`:

- **Kein offenes Internet by default:** Bind `127.0.0.1`/Tailnet; nach außen nur über
  denselben Cloudflare-Tunnel-Mechanismus wie Lane-B.
- **Auth:** Bearer-Token je Worker (kein anonymer Pull), Token via Env, **nie** im Job.
- **Keine Secrets im Payload** (Bridge-Regel 6). `repo`-Allowlist **serverseitig** im
  Router durchsetzen (heute `DUAL_BRIDGE_REPO_ALLOWLIST`).
- **Audit:** Jobs werden nie gelöscht, nur Status-Transitionen + `result_payload`
  (Bridge-Regel 7). DCO-Event-Bus protokolliert ohnehin jeden Wechsel.

## 11. Migrationspfad (nicht-disruptiv)

1. **`bridge_transport.Source`-Abstraktion** einziehen, `FileSource` = heutiges Verhalten
   (reines Refactoring, Tests müssen unverändert grün bleiben).
2. **DCO-Seite** bauen: `claim_next`, `bridge_router`, 3 Endpunkte — eigenständig testbar.
3. **`HttpSource`** in der Bridge ergänzen, gewählt per `DUAL_BRIDGE_TRANSPORT=http`.
4. **Schattenbetrieb:** ein Test-Seed über beide Wege, Ergebnisse vergleichen.
5. **Umschalten je Lane**, wenn HTTP stabil ist; Datei bleibt Fallback (Env zurückstellen).

## 12. CLI / Env

| Variable / Flag | Wirkung |
|---|---|
| `DUAL_BRIDGE_TRANSPORT=file\|http` | Quell-Treiber der Bridge (Default `file`). |
| `DCO_BRIDGE_URL` | Basis-URL des DCO-HTTP-API (z.B. `http://127.0.0.1:8787`). |
| `DCO_BRIDGE_TOKEN` | Bearer-Token des Workers. |
| `BRIDGE_MAX_ACTIVE` | Concurrency-Cap im Router (Default 2). |
| `BRIDGE_LEASE_TTL` | Lease-Timeout für `running`-Requeue (Default 1800 s). |
| `handoff_poll.py --transport http` | überschreibt die Env je Aufruf. |

## 13. Tests (TDD, dual-runnable, isoliert)

**DCO-seitig** (in der DCO-Test-Suite, gleiche `_fresh()`/`_reload()`-Konvention):

1. `claim_next` gibt bei leerer Queue `None`; bei einem queued-Job → genau dieser, Status `running`.
2. **Race:** zwei parallele `claim_next` auf einen Job → genau **einer** gewinnt (CAS), der andere `None`/nächster.
3. Router `parse_seed_line`: gültige erste Zeile → korrektes Payload; fehlendes/nicht-allowlisted `repo` → **kein Job**, Todo bleibt offen.
4. Router-**Idempotenz:** zweimaliger Lauf über denselben Todo → genau **ein** Job (idempotency_key).
5. `create_job_if_active_below`: bei `max_active` erreicht → **kein** neuer Job.
6. Result-Hook Exit-Mapping: `rc 0/3/2/1` → `done/waiting_approval/error/error`; Todo nur bei `done`/`error`-Pfad `done` bzw. offen gem. Tabelle 9.
7. Lease-Requeue: `running` älter als TTL → CAS `running→queued`; frischer `running` bleibt.
8. **Endpunkte:** `GET /jobs/next` ohne Token → `401`; mit Token + leerer Queue → `204`; mit Job → `200`+Claim. `POST /result` transitioniert korrekt.

**Bridge-seitig** (in `test_bridge_transport.py`, neu):

9. `FileSource` verhält sich nach dem Refactoring **identisch** (bestehende Transport-Tests bleiben grün — Regressionsschutz).
10. `HttpSource.next()` mappt `204`→„kein Job", `200`→Job; `result()` postet korrektes JSON (injizierter Fake-HTTP-Client, **kein** echtes Netz).
11. `DUAL_BRIDGE_TRANSPORT` wählt den richtigen Treiber; Default bleibt `file`.

**Akzeptanz:** volle DCO- **und** Bridge-Suite grün, Collection-Count steigt in beiden,
kein State-Leak, bestehende File-Transport-Tests unverändert grün (nicht-disruptiv beweisbar).

## 14. Bewusst NICHT in v1

- **Push statt Pull** (Long-Polling/SSE für Sofort-Zustellung) — Pull zuerst.
- **Mehr-Mandanten/`chat_id`-Routing** über simple Zuordnung hinaus.
- **GUI im DCO** zum Anlegen von Bridge-Todos — erst CLI/`todos.add`.
- **Ablösung des Dateitransports** — bleibt gleichberechtigter Fallback.
- **Verteiltes Hosting jenseits Tailnet/Tunnel** — lokal first.

---

### Anhang: Was neu gebaut wird vs. was schon da ist

| Neu (diese Spec) | Schon im DCO vorhanden |
|---|---|
| `jobs.claim_next(worker_type)` | `transition_status` (CAS), `create_job(_if_active_below)`, `get_job`, `recover_stale_jobs` |
| `bridge_router.py` (parse + create_job + Result-Hook) | `todos.add/list_by_tag`, Event-Bus `events.emit` |
| 3 HTTP-Endpunkte in `api.py` | FastAPI-App, Auth-Infrastruktur |
| `requeue_stale(ttl)`-Sweep | `recover_stale_jobs()` (Start-Recovery) |
| `bridge_transport.Source` + `HttpSource` (Bridge) | `FileSource`-Verhalten (heutiger `handoff_poll`) |
| `"bridge"` in `config.VALID_TAGS`, optional `todos.add(tag=…)` | `VALID_TAGS`, `DEFAULT_TAG` |
