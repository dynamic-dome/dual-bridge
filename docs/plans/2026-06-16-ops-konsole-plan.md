# Plan: Dual-Bridge Ops-Konsole (Hybrid) — Genehmigungsreif

> Erzeugt 2026-06-16 via ultracode-Workflow (12 Agenten: 4 Ground-Truth-Reader →
> 3 Design-Linsen → Synthese → 3 adversariale Reviewer → Finalisierung).
> **Read-only erstellt — noch KEINE Implementierung.** Phase 2 erst nach Freigabe.

## Entscheidungen (2026-06-16) + Konsequenzen

Vier Gabelungen vom User beantwortet. **Status: nur Plan, noch nicht gebaut.**

**A. DCO-Host ≠ Loop-Host (getrennt).** Das DCO/`/ops`-Backend läuft NICHT auf dem
Knoten, der `loop_driver` fährt und `state/LOOP-*.jsonl` + `ESCALATION-*.md` hält.
Konsequenzen (architektur-relevant):
- **Unverändert voll baubar (Drive-symmetrisch):** Lanes (`scan_lane`), Health,
  Metrics, Branches, Repos-Rollup, Risk-Policy/Check, Config-Read, Scheduler-Read.
- **Eskalations-/Approval-LISTE (#3/#8 „Heute"):** Quelle ist **`jobs.db`
  (`waiting_approval`)** auf dem DCO — NICHT `scan_escalations` aus lokalem state.
  Diese Liste funktioniert über die Topologie hinweg.
- **Detail-Views nur am Loop-Host (leer auf DCO):** `ESCALATION-*.md`-Volltext (für
  Resume-Kontext), `LOOP-*.jsonl`-History, `_overnight/runs/*.json`,
  `_notify/*.json`. → Zwei Wege, **Build-Phase-Entscheidung** (s. §9 Frage 6):
  (b1, empfohlen) der Loop-Host spiegelt diese read-only in einen Drive-Unterordner
  (`<bridge_root>/_ops-state-mirror/`, write-only vom Loop-Host, read-only vom DCO —
  bleibt „Sharepoint trägt nur Daten"); (b2) v1 ohne Detail, Herkunfts-Badge „liegt
  auf Laptop A". Leeren State NIE als „nichts offen" rendern.
- **`/ops/loops/{id}/resume` + `/ops/overnight/dry-run` NICHT DCO-lokal ausführbar**
  (kein state/Workdir am DCO-Knoten). → In dieser Topologie werden sie zu
  **vorbereiteten Copy-Befehlen für den Loop-Host** (gleiches Muster wie schtasks/
  Worker-Lifecycle), KEINE ausführenden DCO-Endpoints. Werden DCO und Loop-Host
  später ko-lokalisiert, können sie echte Endpoints werden.

**B. Exposure: nur 127.0.0.1 / LAN.** Auth-Baseline = Dashboard-Cookie + CSRF;
`_require_admin` (ADM) auf Cap/Allowlist/Config-Runtime/Merge-Check. `dash_auth`-Cookie
SameSite=Strict. Keine IP-Allowlist nötig (kein Tunnel).

**C. v1-Scope-Erweiterungen: Verbunden-Cross-Link + echter Worker-Heartbeat** (beide
kleine Worker-Änderungen), **kein** Pending-`promote`.
- **Verbunden-Cross-Link → in 2b:** `_real_run_fn` parst die `loop_id`-Zeile aus
  `loop_driver`-stdout ins Output-Dict (Job↔loop_id-Schlüssel). Macht die
  „Verbunden"-Leiste echt.
- **Echter Worker-Heartbeat → in 2b:** der B-Worker schreibt bei jedem `claim_next`
  `<bridge_root>/lane-B-to-A/_worker-heartbeat.json`. **Vorteil:** dadurch wird
  `/ops/worker/heartbeat` ein ECHTES Drive-Artefakt (statt nur abgeleitet) — sichtbar
  auch in der getrennten Topologie (A).
- **`promote` gestrichen:** Pending-Steuerung = nur `remove` + `drain`. Kein neuer
  `bridge_pending`-Helfer, Endpoint `/ops/pending/{id}/promote` entfällt.

**D. Nur Plan, noch nicht bauen.** Implementierung (Phase 2) bewusst aufgeschoben.
Reihenfolge bei Start bleibt 2a → 2b → 2c → 2d.

## STAND (2026-06-16) + NEXT-SESSION-AUFTRAG

### Was fertig & committet ist
- **Phase 2a (read-only Backend) — KOMPLETT.** 16 Endpoints `/api/ops/*` in
  `ops_router.py` (inkl. `/ops/jobs` als topologie-übergreifende Approval-Quelle,
  §A — in 2c nachgezogen). Commit DCO `434ecde` (+ `/ops/jobs` in `fe9e4e3`).
- **b1 Mirror-Writer + Worker-Extras — KOMPLETT.** dual-bridge `d70c741`.
- **Phase 2b FUNDAMENT — KOMPLETT.** `ops_audit.py` + `_auth_mut` + requeue-stale/
  pending-drain/-delete. Commit DCO `5a758a6`.
- **Phase 2b SCHWERGEWICHTE — KOMPLETT (Commit DCO `fe9e4e3`).** `POST /ops/loops/start`
  (preset-only + eigenes `risk_policy.check_task`-422-Gate + repo-Form/Allowlist-
  Vorabprüfung), `POST /ops/jobs/{id}/cancel`, Toggles `autoqueue`/`finder`,
  `POST /ops/merge-check/{id}` (ADM), `POST /ops/config/runtime` (ADM, atomare
  validate-then-apply `os.environ`-Mutation, max_active-Klemmung, Fail-Open-Schutz,
  Vorher/Nachher-Audit-Diff). resume/overnight = Copy-Befehle (Topologie A, kein Endpoint).
- **Phase 2c (Desktop Control-Room `/ops`) — KOMPLETT (`fe9e4e3`).** `ops_route.py`
  (dash_auth-Cookie-Gate, Redirect→/dashboard) + `ops/{ops.html,ops.css,ops.js}`:
  5 Views (Heute/Lanes/Arbeit/Wissen/System), A↔B-Bottom-Strip, Confirm-Sheet,
  Copy-Command-Builder (resume/overnight, nie `--merge-on-accept`). Erbt miniapp
  `tokens.css`/`components.css`. `DASHBOARD_EXTRA_ORIGINS` (opt-in LAN-Origin).
- **Adversarialer Security-Review eingearbeitet (`fe9e4e3`):** 6 bestätigt, 5 gefixt —
  (1) ADM-Endpoints ziehen `_check_csrf` auf dem Cookie-Pfad nach (war asymmetrisch
  zu OD-M); (2) `DASHBOARD_EXTRA_ORIGINS` strikte `scheme://host[:port]`-Validierung;
  (3) `config/runtime` lehnt Host-Wildcard-Allowlist ab (Fail-Open-Footgun);
  (4) `/ops/jobs` redaktiert `goal`/`crash_reason`/`verdict`. **Won't-fix (F3):**
  case-sensitive `_check_csrf` in `api.py` — pre-existing, out-of-scope, kein realer
  Bypass (Browser-Origins ohne trailing slash, Allowlist normalisiert).
- **Tests grün:** volle DCO-Suite **2718 passed / 14 vorbestehende Baseline-Fails**
  (alle in unberührten Modulen); dual-bridge volle Suite **473 passed**;
  `ops.copy.test.js` (node) 8. DB-Isolation per Row-Count-Snapshot bewiesen
  (jobs.db/todos.db vor==nach).

### Etablierte Patterns (im next-session UNBEDINGT weiterführen)
- **Lazy-Import** der dual-bridge-Emitter im Endpoint (nie beim App-Load) via
  `_load(name)` + `DUAL_BRIDGE_SCRIPTS`. Auth via **Call-Zeit-Delegation** an
  `api._get_user_or_dashboard[_mutating]` (sonst greift der Test-Bypass nicht).
- **Audit:** jede mutierende Aktion ruft `ops_audit.record("<verb>", ...)` (redaktiert).
- **Test-Isolation:** Ops-Tests setzen `DUAL_BRIDGE_ROOT/STATE/OPS_MIRROR`→tmp;
  Audit/DBs über `DCO_DATA_DIR_OVERRIDE`→tmp (conftest). NIE gegen echtes Drive/DBs.
- **Security:** loop_id-Allowlist+Containment (Traversal), Repo-URL-Form+
  Allowlist-fail-closed+`--`-Separator (Injection), generische 502/503, Redaction.

### NÄCHSTE SCHRITTE (offen — 2b/2c sind erledigt)
1. **Manueller Browser-Smoke von `/ops`** (Frontend ist TDD-exempt, braucht Augen):
   `DASHBOARD_TOKEN` setzen → `/dashboard?token=<…>` (setzt `dash_auth`-Cookie) →
   `/ops` öffnen (127.0.0.1, nicht `localhost` — globale Regel §16). Prüfen:
   5 Views rendern, A↔B-Strip + LEDs, Confirm-Sheet bei destruktiven Aktionen,
   Risk-Vorschau im Composer, Copy-Commands (resume/overnight). Sample-Spotchecks
   gegen Markdown-/Pfad-/Secret-Artefakte (globale Regel §4 Pre-Deploy).
2. **Phase 2d (optional, zuletzt — nur wenn 2a–2c stabil):** minimale additive
   Miniapp-Ergänzung — Inline-Approval an der eskalierten Karte (→ `merge-check`) +
   Header-Reminder-Glocke mit Eskalations-Zahl. Keine neuen Tokens/Tabs (s. §2/§6).
3. **Codex-Verifier-Findings** (falls das Review welche liefert) einarbeiten.

Ground Truth (verifiziert, für 2d/Folgearbeit): `_require_admin`/`_check_csrf`/
`_is_dashboard_authed` (api.py 357/3344/2843), `route_or_buffer` (bridge_router.py 196),
`summarize_bridge_job` (432), `bridge_merge.check_and_merge` (545), Preset-Tabelle
`_PRESETS` (ops_router.py) == miniapp `BRIDGE_PRESETS` (start.js).

## Verifizierte Ground-Truth-Korrekturen (Reviewer gegen echten Code)

1. `risk_policy.check_task` hat **null** Aufrufe im DCO — fail-closed läuft nur auf dem **Worker** (`job_poll.process_item`), nicht im DCO-Routing.
2. `_max_active`/`_repo_allowlist`/`_default_repo` sind **Funktionen**, die `os.getenv` frisch lesen → Runtime-Override muss `os.environ` mutieren, nicht Modul-Attribute.
3. `_effective_input_text` übernimmt freie `kind`/`adapter`-Overrides ungeprüft → `/ops/loops/start` muss preset-only erzwingen.
4. `_escalation_path(loop_id)` baut roh `ESCALATION-{loop_id}.md`, `read_escalation` liest ohne Sanitizing → Path-Traversal real; `_TASK_ID_RE` als bestehender Boundary-Guard wiederverwenden.
5. `LoopStatus`/`EscalationInfo` tragen **kein** `repo`-Feld → Repo-Filter auf Loops nicht baubar aus aktuellen Emittern.
6. `bridge_pending` hat `remove`/`clear`, **kein** `promote` → promote wäre der einzige neue Helfer.

## 1. Gewähltes Frame + Begründung

**Control-Room-Skelett + Lifecycle-Navigation + Repo-als-Filter.** Persistentes Desktop-Grid mit dem **A↔B-Lane-Strip als immer sichtbarem Rückgrat** (Bottom-Strip), einer **Verb-Achse-Sidebar** (Heute / Lanes / Arbeit / Wissen / System), und **Repo als orthogonalem Filter-Chip** — nicht als oberste Achse.

**Warum:**
- Die Lane-Sicht (`bridge_status.scan_lane` → beide Lanes) ist die einzige symmetrisch geteilte, immer-aktuelle Drive-Quelle. Gehört ins Rückgrat, nicht in einen wegklickbaren Tab.
- Loop-Lifecycle ist der Arbeitskern, aber DCO steuert ihn nur indirekt (kein Hard-Kill, Start durchs Todo/Risk-Nadelöhr, Resume lokal) → ein Sidebar-Bereich „Arbeit", nicht die ganze Bühne, mit ehrlichen Wirkungs-Labels.
- Risk-Policy ist fail-closed/strukturell: kein kind/adapter erreicht `ops`. OPS-Verben laufen nur interaktiv am DCO-Prozess oder als read-only-Status + Copy-Befehl, nie als Bridge-Task.

Bewusst nachrangig: Capture-Funnel (Telegram-spezifisch), Modi-Umschalter (löst ein Mobil-Platzproblem, das die Konsole nicht hat).

## 2. Surface-Split: Miniapp (leicht) vs. Desktop-Konsole

| Fähigkeit | Miniapp (mobil, Telegram, ≤560px) | Ops-Konsole (Desktop, `/ops`) |
|---|---|---|
| Loop/Job starten | Preset-Quick-Start (`BRIDGE_PRESETS`, `start.js`) — unverändert | Composer-Werkstatt + Live-Risk-Vorschau, gleicher Backend-Weg, preset-only |
| Approval | Inline-Glance an der Karte (`.btn-approve`/`.btn-deny`) | Two-Pane + „Verbunden"-Kontext + `merge-check` |
| Monitoring | Status-Dot + Bridge-Chips | volle Lanes / Health / Metrics / Pipeline / Branches |
| Scheduled Tasks / Config-Setter / Pending-Reorder / Worker-Lifecycle | — **gar nicht** | **exklusiv** (System-Bereich) |

**Minimale Miniapp-Ergänzungen** (additiv, bestehende Tokens, keine neuen Tabs): (1) Inline-Approval an der eskalierten Karte → bestehendes `merge-check`; (2) Header-Reminder-Glocke mit Zahl offener Eskalationen. Phase 2d, nur wenn 2a–2c stabil.

## 3. Konsole: Navigation + Views (alle 14 Funktionen verortet)

**Layout:** 3-Zonen-Grid (Sidebar | Center Two-Pane | Right Dock) + immer sichtbarer A↔B-Bottom-Strip. Header: Omnibox (⌘K), ●A/●B-LED, 🔔-Meldungen, Risk-Badge, Live-Pause. Repo-Filter-Chip oben (kollabiert bei nur einem Repo).

| Bereich | Funktionen (mit Anker) |
|---|---|
| **Heute** | #3 offene Eskalationen · #8 Approval inline (`merge-check`) · #5 Pending-Backlog-Hinweis · fehlgeschlagene Jobs + lane-`_errors` |
| **Lanes** | #1 Lane-Status beide Lanes (`scan_lane`) · #2 Health-Band (`bridge_health`) + Metrik-Kachel (`bridge_metrics`) · Liveness-Dot je Endpoint |
| **Arbeit** | #3 Loop-History (Pipeline) · #4 Job-Detail · #6 Loop-Start (Composer) · #7 Resume/Cancel · #14 Pre-Start-Risk-Vorschau · Branch-Liste `bridge/loop-*` |
| **Wissen** | #2 Metrik-Historie · #11 Overnight-Logs · Notifier-Audit · Eskalations-Archiv |
| **System** | #5 Poller-Liveness + Flags · #9 Pending-Steuerung · #10 Worker-Heartbeat (abgeleitet) + Toggles · #11 Overnight Dry-Run · #12 Laufzeit-Config · #13 Scheduled-Tasks read-only + Copy · #14 Risk-Policy-Inspektor |

Deep-Links: `/ops#/arbeit/loop/<loop_id>`, `/ops#/lanes/B-to-A`, `/ops#/heute/escalation/<loop_id>`. „Verbunden"-Leiste vernetzt Job ↔ Branch ↔ ESCALATION ↔ Quell-Todo (Blocker-Fix §8: Schlüssel erst nachrüsten).

**Harte Trennungen:** #13 schtasks, #10 Worker-Start/Stop, #12 Cap/Allowlist, #11 Overnight-Scharfschalten = OPS → nie Bridge-Task. #8 Approval/merge-check behält die schärfere write-kritische Auth.

## 4. API-Vertrag (neue Endpoints, Router-Prefix `/api/ops/*`)

Auth: `OD`=`_get_user_or_dashboard` · `OD-M`=`_get_user_or_dashboard_mutating` (CSRF gratis) · `ADM`=`_require_admin`.

### 4a. Read-only Observability (importieren die Module direkt, KEIN Subprozess)

| Methode | Pfad | Auth | Backend-Aufruf |
|---|---|---|---|
| GET | `/api/ops/status?lane=&repo=` | OD | `bridge_status.build_report()→render_json` |
| GET | `/api/ops/health` | OD | `bridge_health.check_lane_health()` (HTTP 200 immer) |
| GET | `/api/ops/metrics?lane=` | OD | `bridge_metrics.compute_metrics()` |
| GET | `/api/ops/loops?state=` | OD | `bridge_status.scan_loops(STATE_DIR)` — kein `?repo=` |
| GET | `/api/ops/escalations` | OD | `bridge_status.scan_escalations(STATE_DIR)` |
| GET | `/api/ops/escalations/{loop_id}/source` | OD | Read `ESCALATION-<loop_id>.md` — loop_id-Allowlist-validiert |
| GET | `/api/ops/repos/rollup` | OD | `bridge/repos` + Lane/Jobs — kein per-Repo `last_verdict` |
| GET | `/api/ops/branches?repo=` | OD | `git ls-remote` als Arg-Liste, repo gegen `_repo_allowlist()`, `--`-Separator |
| GET | `/api/ops/overnight/runs?limit=` | OD | Read `state/_overnight/runs/*.json` |
| GET | `/api/ops/notify/state` | OD | Read `state/_notify/` |
| GET | `/api/ops/risk/policy` | OD | import `risk_policy`-Konstanten |
| GET | `/api/ops/risk/check?kind=&adapter=&seed=` | OD | `risk_policy.check_task()` (Vorschau, schreibt nichts) |
| GET | `/api/ops/scheduler/tasks` | OD | `schtasks /query` ohne User-Input, serverseitig auf `DualBridge*` gefiltert |
| GET | `/api/ops/worker/heartbeat` | OD | liest `lane-B-to-A/_worker-heartbeat.json` (echtes Drive-Artefakt, Worker-Änderung 2b); Fallback abgeleitet aus `jobs.updated_at` |
| GET | `/api/ops/config` | OD | wirksame Werte aus `os.getenv`/`config_value`; worker-only Vars als `null` |

### 4b. Write-Control (mutating; Ops läuft interaktiv am DCO, NIE über die Bridge)

| Methode | Pfad | Auth | Confirm+Audit | Backend-Aufruf |
|---|---|---|---|---|
| POST | `/api/ops/loops/start` | OD-M | Confirm + Audit | preset_key→{kind,adapter} serverseitig + eigenes `check_task`-422-Gate + `todos.add` + `route_or_buffer`. Body NUR `{repo,preset_key,auftrag}` |
| ~~POST~~ | `/api/ops/loops/{loop_id}/resume` | — | — | **In getrennter Topologie KEIN Endpoint** (braucht state/Workdir des Loop-Hosts) → Copy-Befehl `loop_driver.py --resume <loop_id>` für Laptop A, loop_id-Allowlist, **ohne** `--merge-on-accept`. Nur bei DCO=Loop-Host als echter OD-M-Endpoint. |
| POST | `/api/ops/jobs/{job_id}/cancel` | OD-M | Confirm + Audit | delegiert an `/jobs/{id}/cancel`; Label „nur DCO-DB, B-Build endet erst beim Timeout" |
| POST | `/api/ops/pending/drain` | OD-M | Audit | `bridge_router.drain_pending_once()` |
| DELETE | `/api/ops/pending/{todo_id}` | OD-M | Confirm + Audit | `bridge_pending.remove(todo_id)` |
| POST | `/api/ops/worker/requeue-stale` | OD-M | Audit | `jobs.requeue_stale(ttl,"dual-bridge")` |
| POST | `/api/ops/autoqueue` · `/finder` | OD-M | Audit | bestehende `/bridge/autoqueue` / `/finder` |
| POST | `/api/ops/merge-check/{job_id}` | **ADM** | Confirm + Audit | `bridge_merge.check_and_merge` (isoliertes Worktree) |
| POST | `/api/ops/config/runtime` | **ADM** | Confirm + Audit (Vorher/Nachher-Diff) | `os.environ`-Mutation; strikte Validierung; kein `.env`-Schreibpfad |
| ~~POST~~ | `/api/ops/overnight/dry-run` | — | — | **In getrennter Topologie KEIN Endpoint** (braucht Loop-Host) → Copy-Befehl `bridge_overnight.py --dry-run` für Laptop A, **ohne** `--merge-on-accept`. Nur bei DCO=Loop-Host als OD-M-Endpoint. |

**Bewusst KEIN Endpoint:** Scheduled-Task create/delete (`register_*.ps1`), `DUAL_BRIDGE_MERGE_ON_ACCEPT` setzen (worker-lokal), Worker-Start/Stop des B-Daemons → bleiben interaktiv/Copy-Befehl. **In dieser Topologie zusätzlich** (Entscheidung A): `resume` + `overnight/dry-run` → Copy-Befehl für den Loop-Host statt ausführender Endpoint. **Gestrichen** (Entscheidung C): `pending/.../promote`.

## 5. Dual-Endpoint-Datenmodell + ehrliche Gap-Liste

**Symmetrisch geteilt (Drive `bridge_root()`):** `scan_lane`, `check_lane_health`, `compute_metrics` → ein Konsolen-Backend deckt die komplette Lane-Sicht.

**Asymmetrisch — NUR lokaler `state/` (`DUAL_BRIDGE_STATE`), nicht Drive-synchron:** `LOOP-<id>.jsonl`, `ESCALATION-*.md`, `_overnight/runs/*.json`, `_notify/*.json` — nur wo `loop_driver` läuft (praktisch Laptop A).

**Streng maschinen-lokal:** Poller-Lock, Worker-Heartbeat (existiert heute nicht als Artefakt).

**Ehrliche Gaps:**
1. DCO-Host ≠ Loop-Host → Loops/Eskalationen/Overnight/Notify sind leer. Konsole rendert sie NICHT als „nichts offen", sondern mit **Herkunfts-Badge**.
2. Worker-Heartbeat: ab Entscheidung C ein **echtes** Drive-Artefakt (`lane-B-to-A/_worker-heartbeat.json`, vom Worker bei jedem `claim` geschrieben) — Label „letzter Claim vor N min"; Fallback `jobs.updated_at`, falls Artefakt fehlt.
3. Cancel hat kein Worker-Signal — nur Soft-Cancel (Hard-Kill von `loop_driver` auf B ist kein DCO-Kanal).
4. „Verbunden"-Cross-Link braucht erst den Job↔loop_id-Schlüssel (Worker-Änderung, §8).

`/ops`-Backend braucht korrekt gesetztes `DUAL_BRIDGE_ROOT` (Drive) UND `DUAL_BRIDGE_STATE` (lokal, auf den Loop-Host zeigend). `scan_loops`/`scan_escalations` sind nicht nullary — STATE_DIR explizit durchreichen.

## 6. Phasierter Plan 2a → 2d

**2a — Backend read-only Observability** (null Risiko, zuerst lauffähig)
Dateien: neu `dynamic_central_orchestrator/ops_router.py`; `main.py` (Router-Mount); `config.py` (`DUAL_BRIDGE_ROOT`/`STATE` sicherstellen). `dual-bridge/scripts/` per `sys.path` import-bar (heute kollisionsfrei). Zuerst lauffähig: `GET /api/ops/status` → Bottom-Strip + Lanes. Neue `/ops/*`-Routen vor `/jobs/{id}` kollisionsfrei registrieren.

**2b — Backend Write-Control** (Confirm/Audit, lokal)
Dateien: `ops_router.py` (POST/DELETE); neu `state/_ops/audit.jsonl`-Writer (mit Redaction); **zwei Worker-Änderungen (Entscheidung C):** `_real_run_fn` parst loop_id aus stdout (Verbunden-Cross-Link) + `job_poll` schreibt `lane-B-to-A/_worker-heartbeat.json` bei jedem `claim`. **Kein** `bridge_pending.promote`. Reihenfolge: Audit-Writer → idempotente Wrapper (drain, requeue-stale, toggles) → `pending/remove` → `config/runtime` (ADM) → Worker-Änderungen. **Kein** resume-/overnight-Subprozess (getrennte Topologie, Entscheidung A → Copy-Befehl im Frontend). Zuerst lauffähig: `POST /api/ops/pending/drain`.

**2c — Desktop-Konsole-Frontend**
Dateien: neu `ops/ops.html` + `ops/js/*` + `ops/css/ops.css`; Auslieferung via `dashboard_route.py`-Muster (Cookie-Gate, CSP-Nonce); `DASHBOARD_ALLOWED_ORIGINS` um `/ops`-Origin erweitern; erbt `tokens.css`+`components.css`. Zuerst lauffähig: read-only Bottom-Strip + Lanes.

**2d — minimale Miniapp-Ergänzung** (additiv, zuletzt)
Dateien: `miniapp/js/activity.js` (Inline-Approval), `miniapp/index.html`/`more.js` (Reminder-Glocke). Keine neuen Tokens/Tabs.

## 7. Guardrail- & Test-Compliance

- **Kein Ops-Verb über die Bridge.** OPS läuft interaktiv am DCO (lokaler Subprozess) ODER read-only+Copy. Auftragstext erreicht nie die Lanes.
- **Risk-Policy intakt am REALEN Ort.** `check_task` läuft auf dem Worker; `/ops/loops/start` gibt zusätzlich ein eigenes `check_task`-422-Vorab-Gate + preset-only-Body (Defense-in-Depth).
- **Observability schreibt nie.** Alle GET reichen `render_json`/`compute_*`/`check_*` durch; `schtasks /query`/`git ls-remote` read-only und arg-gehärtet.
- **Keine neuen kind/adapter.** Falls doch → harte Reihenfolge `risk_policy.py` → DCO-Miniapp-Preset (`start.js` + `start.compose.test.js` + `tests/test_miniapp_bridge_compose.py`) VOR Endpoint-/UI-Arbeit.
- **Audit-Redaction:** maskiert `user:pass@`, Bearer/`sk-`/`api_key`; kappt Seed-Text.
- **Test-DB/Drive-Isolation:** dual-bridge `conftest.py` lenkt `DUAL_BRIDGE_ROOT`/`STATE`/`LOCK` auf `tmp_path`; DCO `conftest.py` via `DCO_DATA_DIR_OVERRIDE` → lazy `_db_path()`. **Snapshot-Beweis** (Row-Count jobs.db/todos.db + Datei-Count Drive-`lane-*/`+`state/` vor/nach Suite).
- **Windows-Subprocess-Härtung (§10):** `shutil.which` absolut; Args als Liste; tree-kill bei Timeout; `git`/`schtasks` über `bridge_merge._git`-Muster (kein `shell=True`, `CREATE_NO_WINDOW`, stdin=DEVNULL).

## 8. Eingearbeitete Review-Findings

**Blocker:**
- **Path-Traversal `loop_id`:** jede `/ops`-Grenze validiert gegen `_TASK_ID_RE` + Allowlist real existierender loop_ids; Fehlschlag → 422.
- **Argument-Injection `git ls-remote`/`schtasks`:** repo gegen `_repo_allowlist()`; git als Arg-Liste mit `--`-Separator; `schtasks /query` ohne User-Input.
- **„Verbunden"-Schlüssel fehlt:** kleine Worker-Änderung — `_real_run_fn` parst die `loop_id`-Zeile aus stdout ins Output-Dict. Bis dahin „Verbunden"-Leiste für HTTP-Job-Pfad nicht baubar (Vorbedingung, kein Fundament).

**Major:**
- §H.2 Enforcement-Ort korrigiert (Worker, nicht DCO) → `/ops/loops/start` preset-only + eigenes 422-Gate.
- Freie kind/adapter-Overrides → `/ops/loops/start` öffnet overrides-Dict nicht für kind/adapter.
- Repo-Filter auf Loops entfällt (kein `repo`-Feld in `LoopStatus`); Filter nur auf Lanes/Metrics/Jobs.
- `config/runtime` mutiert `os.environ` (nicht Attribute); kein `.env`-Schreibpfad; `DASHBOARD_ALLOWED_ORIGINS` unverändert; `round_timeout`/`codex_timeout` worker-seitig → read-only.
- `config/runtime` Sicherheitsgrenze: leere/whitespace-Allowlist = fail-open → Setter lehnt leere/Shell-Metazeichen ab, klemmt `max_active`, ADM-Pflicht-Audit mit Diff.
- CSRF/SameSite: alle `/ops`-Mutationen nur POST/DELETE; `dash_auth`-Cookie SameSite=Strict.
- resume/overnight ohne `--merge-on-accept` (harte Invariante; einziger base-mutierender Pfad bleibt `/ops/merge-check`).
- merge-check-Auth → `_require_admin` statt initData-only (sonst 401 auf Cookie-Pfad).

**Minor:** Audit-Log-Redaction Pflicht; leere asymmetrische State-Views nicht grün rendern; `scan_loops`/`scan_escalations` STATE_DIR durchreichen; Hard-Kill bewusste Teilabdeckung; `sys.path`-Namens-Check bei künftigen gleichnamigen Modulen.

## 9. Fragen — Status

1. **DCO-Host = Loop-Host?** → **BEANTWORTET: nein, getrennt.** Siehe Entscheidung A.
2. **Exposure?** → **BEANTWORTET: nur 127.0.0.1/LAN.** Siehe Entscheidung B.
3. **Worker-Heartbeat echt?** → **BEANTWORTET: ja, echt (Drive-Artefakt).** Entscheidung C.
4. **Pending-`promote`?** → **BEANTWORTET: nein, gestrichen.** Entscheidung C.
5. **„Verbunden"-Cross-Link jetzt?** → **BEANTWORTET: ja, in 2b.** Entscheidung C.

**Offen für die Build-Phase (neu durch Entscheidung A):**
6. **Detail-Views (ESCALATION-Volltext, LOOP-History, Overnight, Notify): Drive-State-Mirror
   (b1) oder Badge-only (b2)?** Empfehlung b1 — der Loop-Host (Laptop A) spiegelt diese
   read-only nach `<bridge_root>/_ops-state-mirror/`, write-only von A, read-only vom DCO.
   Kleiner additiver Schreibpfad auf A; macht die Detail-Views über die Topologie sichtbar.
   Alternativ b2: v1 ohne Detail, nur Herkunfts-Badge. **Zu klären, bevor 2a die
   asymmetrischen Read-Endpoints implementiert.**
