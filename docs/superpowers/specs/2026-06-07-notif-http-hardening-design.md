# Dual-Bridge — Notif HTTP-Härtung (Telegram-Sende-Kante)

*Erstellt: 2026-06-07 · Repo: `dynamic-dome/dual-bridge` · härtet `scripts/bridge_notify.py`*

## Kontext & Motivation

`bridge_notify.py` existiert und ist live bewiesen (Stufe-3-Eskalations-Notifier): Er
liest offene `state/ESCALATION-*.md`, schickt pro neuer Eskalation **eine** Telegram-
Nachricht und dedupt über `state/_notify/sent.json`. **Die Sende-Kante ist aber naiv:**
`_post_telegram` wirft bei *jedem* Fehler dieselbe generische `Exception` — ob 401
(falscher Token, hoffnungslos) oder 503 (Server kurz weg, retrybar). Es gibt keine
Fehlerklassifikation, kein `Retry-After`, kein Backoff und keinen Schutz gegen einen
Push-Sturm, wenn dieselbe Eskalation sich verschlimmert.

Dieser Slice macht aus der naiven eine **betriebsfeste** Sende-Kante. Quelle: Pulse-Triage
2026-06-06, **Outcome 03 (K1/K2/K3)** + **Outcome 06 (K8-Dedup)**.

### Leitprinzip (Invariante, unverändert aus der Stufe-3-Spec)

Der Notifier ist eine **Push-Kante über den Eskalations-Artefakten — er ändert den
Loop-/Bridge-Zustand NICHT.** Er liest `ESCALATION-*.md`, schickt Nachrichten und merkt
sich Zustand **ausschließlich** in seinem eigenen Sidecar `state/_notify/`. Er claimt
keine Tasks, verschiebt keine Eskalationen, schreibt nie in `ESCALATION-*.md` oder die
Lanes. Beliebig oft gefahrlos ausführbar.

### Bewusst draußen (YAGNI / Triage-Grenze)

- **Kein Pushover** — Transport bleibt Telegram; Pushover-vs-Telegram (Outcome 06 K8)
  ist eine spätere, separate Entscheidung. Der Transport ist hinter `_post_telegram`
  gekapselt, falls er je erweitert wird.
- **Kein SQLite-Ledger, kein `C:\AgentLoop\`-Apparat** — die Triage hat den
  Queue-Apparat ausdrücklich verworfen (Reerfindung von Live-Code). Der Retry-State ist
  ein schlanker JSON-Sidecar, kein Ledger.
- **Kein `provider`/`run_id` im Dedup-Key** — der Telegram-only-Slice braucht sie nicht.
- **Kein Reply-Handling, kein Multi-Channel, kein Daemon** — der Notifier bleibt ein
  kurzlebiger Ein-Schuss-Prozess; Retry läuft cross-trigger, kein `sleep()` im Lauf.

## Ground-Truth (verifiziert am Code 2026-06-07)

- **`_post_telegram(text)`** (`bridge_notify.py:103`) — POST an Telegram via `urllib`,
  wirft heute eine generische `RuntimeError`/`Exception` bei Config-/HTTP-/Netzfehler.
- **`notify_new_escalations(send_fn, dry_run, mark)`** (`:191`) — fängt jede Exception
  gleich (`:223`), markiert nicht-gesendet, verlässt sich auf „nächster Trigger".
- **`sent.json`** (`state/_notify/`, `_load_sent`/`_save_sent`) — heute Key = `loop_id`,
  Wert `{created, notified_at}`. Atomar via `bc.write_text_atomic`.
- **`bs.scan_escalations(STATE_DIR)`** liefert `EscalationInfo(loop_id, trigger, round,
  branch, commit, created)` aus dem `ESCALATION-*.md`-Frontmatter. `reason` für den
  Dedup-Hash wird aus `(trigger, round)` gebildet — beides vorhandene Felder, kein neues.
- **`bc.now_iso()`**, **`bc.parse_frontmatter`**, **`bc.read_text_utf8`** — vorhanden.
- **CLI:** `--dry-run` / `--digest` / `--reconcile`; Exit-Codes 0/2/3.

## Architektur — additiv, drei Schichten

### Schicht 1 — Klassifizierter Sender (`_post_telegram`)

Statt generischer Exception wirft die Sende-Funktion bei Fehlschlag eine typisierte
`NotifySendError(category, status, retry_after, message)`. Erfolg = stille Rückkehr (wie
heute). Klassifikation:

| urllib-Ergebnis | HTTP-Status | Kategorie | Begründung |
|---|---|---|---|
| `HTTPError` | 400, 401, 403, 404, übrige 4xx (außer 429) | `PERMANENT` | Falscher Token/Chat/Request — Retry hilft nie |
| `HTTPError` | 429 | `TRANSIENT` | Rate-Limit — `Retry-After` respektieren |
| `HTTPError` | 5xx (500/502/503/…) | `TRANSIENT` | Server kurz weg |
| `URLError` (DNS/Timeout/Conn-Refused) | — | `TRANSIENT` | Netz kurz weg |
| `200` aber `{"ok": false}` | — | `PERMANENT` | Telegram lehnt inhaltlich ab (z.B. „chat not found") |

`retry_after` wird aus dem `Retry-After`-Header gezogen (Sekunden-Integer **oder**
HTTP-Datum; unlesbar → `None`, exp-Backoff greift).

### Schicht 2 — Zwei Sidecar-Dateien (nur in `state/_notify/`)

**Dedup-Key:**
```
reason     = f"{trigger}|{round}"
notify_key = f"{loop_id}:{sha256(reason)[:12]}"
```
Gleicher `loop_id` mit geändertem `trigger`/`round` (= verschlimmert) → neuer
`notify_key` → genau eine Re-Notification. Unverändert → gleicher Key → kein Sturm.

**`sent.json`** — Endzustand „erfolgreich zugestellt". Key = `notify_key`:
```json
{ "loop-...-abc:9f3a1c2b": { "loop_id": "...", "reason": "stagnation|2",
                              "notified_at": "2026-06-07T..." } }
```

**`attempts.json`** (neu) — Übergangszustand „in Bearbeitung / gescheitert".
Key = `notify_key`:
```json
{ "loop-...-abc:9f3a1c2b": { "loop_id": "...", "reason": "stagnation|2",
    "status": "transient_pending" | "permanent_failed",
    "attempts": 2, "next_retry_at": "2026-06-07T...", "last_error": "503 ..." } }
```

Beide read-modify-write atomar via `bc.write_text_atomic`, defensiv `{}` bei fehlend/kaputt.

### Schicht 3 — Fälligkeits-gesteuerter Kern (`notify_new_escalations`)

Pro Lauf, pro offener Eskalation, in dieser Reihenfolge:

1. `notify_key` in `sent.json`? → **skip** (schon zugestellt)
2. in `attempts.json` mit `permanent_failed`? → **skip** (nie wieder)
3. in `attempts.json` mit `transient_pending`?
   - `now < next_retry_at`? → **skip** (noch nicht fällig)
   - sonst → **retry** (zählt als Versuch)
4. sonst → **neu** (erster Versuch)

Diese Reihenfolge löst die Retry×Dedup-Wechselwirkung: ein retry-pending Eintrag kann
nicht als „neu" durchrutschen (gleicher Key, solange `reason` gleich); ändert sich
`reason`, ist es bewusst eine neue Meldung.

Konsequenz für `permanent_failed`: Der Eintrag blockt nur seinen **eigenen**
`notify_key`. Verschlimmert sich dieselbe Eskalation (neuer `trigger`/`round` → neuer
Key), wird sie als frische Meldung neu versucht — ein permanent gescheiterter
Alt-Zustand verschluckt eine verschärfte Eskalation nicht.

**Übergänge bei einem Send-Versuch:**
```
[senden]
  ├─ Erfolg     → sent.json schreiben, Eintrag aus attempts.json entfernen
  ├─ TRANSIENT  → attempts.json: status=transient_pending, attempts+1,
  │               next_retry_at neu berechnet, last_error gesetzt
  └─ PERMANENT  → attempts.json: status=permanent_failed (Endzustand), laut loggen
```

`MAX_TRANSIENT_ATTEMPTS` erreicht → transient kippt zu `permanent_failed`.

### Backoff (`next_retry_at`, K1: Retry-After zuerst)

```
1. Retry-After vorhanden (429/503)?
   → next_retry_at = now + min(retry_after, RETRY_AFTER_CAP_SEC)
2. sonst exponentiell:
   → delay = min(BACKOFF_BASE_SEC * 2^(attempts-1), BACKOFF_CAP_SEC)
   → next_retry_at = now + delay
```
Kein `sleep()` im Lauf — `next_retry_at` ist nur ein Zeitstempel für den nächsten
Scheduled-Task-Lauf. Der Prozess bleibt kurzlebig.

### Parameter (Modul-Konstanten, später optional nach `config.json` ziehbar)

| Konstante | Default | Sinn |
|---|---|---|
| `MAX_TRANSIENT_ATTEMPTS` | 6 | Nach 6 vergeblichen transienten Versuchen → permanent_failed |
| `BACKOFF_BASE_SEC` | 60 | Erster exp-Backoff-Schritt |
| `BACKOFF_CAP_SEC` | 3600 | Deckel für den *eigenen* exp-Backoff (1 h) |
| `RETRY_AFTER_CAP_SEC` | 3600 | Deckel für den *Server-vorgegebenen* `Retry-After` |

Die beiden Caps haben denselben Default, aber **unterschiedliche Bedeutung** (eigener
Backoff vs. fremde Server-Vorgabe) — bewusst zwei Konstanten, nicht eine.

### Exit-Codes `main()` (erweitert, abwärtskompatibel)

| Code | Bedeutung |
|---|---|
| 0 | ok / nichts zu tun — inkl. „nur transient-pending, nichts fällig" |
| 2 | nicht konfiguriert (unverändert) |
| 3 | mind. ein realer Fehlversuch *in diesem Lauf* (transient gescheitert ODER neu permanent_failed) |

Wichtig: ein transient-pending allein (Retry liegt in der Zukunft, kein Versuch in
diesem Lauf) ist **kein** rc=3 — der Lauf hat nichts versucht. Das hält den
Scheduler-Alarm präzise.

### `--reconcile`

Räumt künftig **beide** Sidecars: Einträge, deren `loop_id` nicht mehr offen ist
(Eskalation abgearbeitet), fliegen aus `sent.json` **und** `attempts.json`.

## Testplan

### Test-Architektur — echter `http.server`-Mock (P006)

Fixture startet einen lokalen `http.server` im Daemon-Thread auf `127.0.0.1:0` (OS-Port).
Der Handler ist scriptbar (Test setzt Statuscode + Header + Body). `_post_telegram` läuft
mit **echtem urllib** dagegen → die reale HTTPError/URLError-Mapping-Schicht wird
getestet, kein Monkeypatch der HTTP-Ebene. Isolation über `DUAL_BRIDGE_STATE`=tmp
(bestehendes conftest-Muster); Mock bindet nur an Loopback, kein echter Egress.

### Neue Tests (`test_bridge_notify.py`, additiv zu den 12 bestehenden)

*Klassifikation (Mock-Server):*
1. `test_4xx_classified_permanent` — 401 → `PERMANENT`
2. `test_429_classified_transient_with_retry_after` — 429 + `Retry-After: 30` → `TRANSIENT`, retry_after==30
3. `test_5xx_classified_transient` — 503 → `TRANSIENT`
4. `test_network_error_classified_transient` — toter Port → `URLError` → `TRANSIENT`
5. `test_200_ok_false_classified_permanent` — 200 `{"ok":false}` → `PERMANENT`
6. `test_retry_after_http_date_parsed` — `Retry-After` als HTTP-Datum

*Orchestrierung (Attempt-Lifecycle):*
7. `test_transient_failure_records_attempt_not_sent` — 503 → attempts.json (transient_pending, attempts=1, next_retry_at), nicht in sent.json, rc=3
8. `test_retry_skipped_when_not_due` — next_retry_at in Zukunft → kein Send, rc=0
9. `test_retry_attempted_when_due` — next_retry_at in Vergangenheit → genau ein Versuch
10. `test_transient_then_success_moves_to_sent` — 503 dann 200 → wandert nach sent.json
11. `test_permanent_failure_marks_failed_rc3` — 401 → permanent_failed, rc=3, kein Folgeversuch
12. `test_max_attempts_becomes_permanent` — nach MAX_TRANSIENT_ATTEMPTS 503ern → permanent_failed
13. `test_retry_after_capped` — `Retry-After: 999999` → auf RETRY_AFTER_CAP_SEC gedeckelt

*Dedup-Key (reason):*
14. `test_same_reason_not_resent` — gleicher loop_id+reason in sent.json → kein Send
15. `test_changed_reason_triggers_one_renotify` — gleicher loop_id, neuer trigger/round → genau ein neuer Send

*Invariante & Kompatibilität:*
16. `test_notifier_still_read_only_on_escalations` — Snapshot ESCALATION-*.md vor/nach identisch
17. `test_reconcile_cleans_both_sidecars` — abgearbeitete Eskalation → aus beiden Sidecars entfernt
18. `test_partial_failure_isolates` — 3 Eskalationen, mittlere 503 → 2 sent, 1 attempts, rc=3
19. `test_dry_run_touches_no_sidecar` — `--dry-run` → weder sent.json noch attempts.json verändert

### Live-Smoke (separat, NICHT in der Suite — P007)

Mit echten `DUAL_BRIDGE_TG_TOKEN`/`_CHAT`: erst `--dry-run`, dann ein echter Lauf gegen
eine Test-Eskalation → reale Telegram-Nachricht. Bewusst außerhalb der Unit-Suite.

## Erfolgskriterien

- [ ] `_post_telegram` klassifiziert jeden Antwort-/Fehlerfall korrekt (PERMANENT vs TRANSIENT, inkl. `ok:false`).
- [ ] Transiente Fehler → cross-trigger Retry mit `Retry-After`-zuerst-Backoff; **kein** `sleep()` im Lauf.
- [ ] Permanente Fehler → `permanent_failed`, rc=3, laut geloggt, **kein** Push-Sturm.
- [ ] Re-Notify genau einmal bei geändertem `reason`; nie bei unverändertem.
- [ ] Notifier schreibt **ausschließlich** in `state/_notify/` (Snapshot-Test beweist Invariante).
- [ ] `--dry-run` berührt keinen Sidecar; `--reconcile` räumt beide.
- [ ] rc=3 nur bei realem Fehlversuch *in diesem Lauf*, nicht bei zukünftig-fälligem Retry.
- [ ] ~19 neue Tests grün; volle Suite (heute 307) ohne Regression.

## Folge-Arbeit (nicht Teil dieser Spec)

- **Transport-Wahl Pushover vs Telegram** (Outcome 06 K8) — eigene Entscheidung/Spec.
- **K4 Scheduled-Task-XML** (`MultipleInstances IgnoreNew` + `RandomDelay`) bei der
  Task-Registrierung — reine Ops-Config, separater Schritt.
- **Parameter nach `config.json`** ziehen, falls die Defaults justiert werden sollen.
