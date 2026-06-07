# Notif HTTP-Härtung Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Härte die Telegram-Sende-Kante von `bridge_notify.py` zu einer betriebsfesten Kante: Fehlerklassifikation, cross-trigger Retry mit Retry-After, Dedup gegen Push-Sturm.

**Architecture:** Drei additive Schichten in `bridge_notify.py` — (1) `_post_telegram` wirft eine typisierte `NotifySendError(category, status, retry_after)`; (2) ein neuer Sidecar `state/_notify/attempts.json` hält Retry-State cross-trigger; (3) `notify_new_escalations` wird fälligkeits-gesteuert. Invariante gewahrt: schreibt nur in `state/_notify/`.

**Tech Stack:** Python 3.12 stdlib (`urllib`, `http.server`, `hashlib`, `json`), pytest. Kein neues Dependency.

**Spec:** `docs/superpowers/specs/2026-06-07-notif-http-hardening-design.md`

---

## File Structure

- **Modify:** `scripts/bridge_notify.py`
  - Neue Exception-Klasse `NotifySendError`
  - `_post_telegram` → klassifizierter Sender
  - Neue Helfer: `_classify_http_error`, `_parse_retry_after`, `_compute_next_retry_at`, `_notify_key`, `_reason_of`
  - Neuer Sidecar-Zugriff: `_attempts_path`, `_load_attempts`, `_save_attempts`
  - `notify_new_escalations` → fälligkeits-gesteuerter Kern
  - `reconcile` → räumt beide Sidecars
  - `main` → erweiterte rc=3-Logik
- **Modify:** `scripts/test_bridge_notify.py` — ~19 neue Tests + Mock-Server-Fixture
- **Modify:** `README.md` — kurzer Absatz Retry/Backoff-Verhalten (Task 6)

**Test-Idiome (bereits in `test_bridge_notify.py` vorhanden, wiederverwenden):**
- `_fresh(endpoint="claude@laptop-a")` — setzt tmp `DUAL_BRIDGE_ROOT/STATE` + Telegram-Env, gibt `root` zurück
- `_reload()` → `(bc, bs, bn)` (reloaded `bridge_common`, `bridge_status`, `bridge_notify`)
- `_write_escalation(bc, bs, *, loop_id, trigger="max_rounds", round_no="3", question=...)` → schreibt `ESCALATION-<loop_id>.md`
- `_Recorder(fail_for=set())` — injizierbare `send_fn`, protokolliert `.calls`
- `_snapshot(dirpath)` → `{relpath: content}` für Invarianten-Vergleich
- `bc.now_iso()` = lokale ISO ohne Mikrosekunden; vergleichbar via `datetime.fromisoformat`

---

## Task 1: Typisierte Fehlerklassifikation in `_post_telegram`

**Files:**
- Modify: `scripts/bridge_notify.py` (Exception + `_post_telegram` + `_classify_http_error` + `_parse_retry_after`)
- Test: `scripts/test_bridge_notify.py` (Mock-Server-Fixture + Klassifikations-Tests)

- [ ] **Step 1: Mock-Server-Helfer + erste Klassifikations-Tests schreiben (failing)**

Am Kopf von `test_bridge_notify.py` (nach den bestehenden Imports) ergänzen:

```python
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer


class _MockTelegram:
    """Lokaler http.server, der ein scriptbares Ergebnis liefert. _post_telegram
    läuft mit echtem urllib dagegen (P006: echte HTTPError/URLError-Kette)."""
    def __init__(self, status=200, body=None, headers=None):
        self.status = status
        self.body = body if body is not None else '{"ok": true}'
        self.headers = headers or {}
        self._srv = None
        self._thread = None

    def __enter__(self):
        outer = self

        class _H(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                self.rfile.read(length)
                self.send_response(outer.status)
                for k, v in outer.headers.items():
                    self.send_header(k, v)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(outer.body.encode("utf-8"))

            def log_message(self, *a):  # stumm
                pass

        self._srv = HTTPServer(("127.0.0.1", 0), _H)
        self._thread = threading.Thread(target=self._srv.serve_forever, daemon=True)
        self._thread.start()
        host, port = self._srv.server_address
        self.base_url = f"http://127.0.0.1:{port}"
        return self

    def __exit__(self, *a):
        self._srv.shutdown()
        self._srv.server_close()


def _post_to(bn, mock, text="hi"):
    """_post_telegram gegen den Mock laufen lassen (API-Base umgebogen)."""
    return bn._post_telegram(text, api_base=mock.base_url + "/bot{token}/sendMessage")


# --- HTTP-Härtung: Klassifikation -------------------------------------------
def test_4xx_classified_permanent() -> None:
    _fresh()
    bc, bs, bn = _reload()
    with _MockTelegram(status=401, body='{"ok": false}') as mock:
        try:
            _post_to(bn, mock)
            assert False, "sollte werfen"
        except bn.NotifySendError as exc:
            assert exc.category == "PERMANENT"
            assert exc.status == 401


def test_429_classified_transient_with_retry_after() -> None:
    _fresh()
    bc, bs, bn = _reload()
    with _MockTelegram(status=429, body='{"ok": false}',
                       headers={"Retry-After": "30"}) as mock:
        try:
            _post_to(bn, mock)
            assert False
        except bn.NotifySendError as exc:
            assert exc.category == "TRANSIENT"
            assert exc.retry_after == 30


def test_5xx_classified_transient() -> None:
    _fresh()
    bc, bs, bn = _reload()
    with _MockTelegram(status=503, body="oops") as mock:
        try:
            _post_to(bn, mock)
            assert False
        except bn.NotifySendError as exc:
            assert exc.category == "TRANSIENT"


def test_network_error_classified_transient() -> None:
    _fresh()
    bc, bs, bn = _reload()
    # Toter Port: nichts lauscht -> URLError -> TRANSIENT
    try:
        bn._post_telegram("hi", api_base="http://127.0.0.1:1/bot{token}/sendMessage")
        assert False
    except bn.NotifySendError as exc:
        assert exc.category == "TRANSIENT"


def test_200_ok_false_classified_permanent() -> None:
    _fresh()
    bc, bs, bn = _reload()
    with _MockTelegram(status=200, body='{"ok": false, "description": "chat not found"}') as mock:
        try:
            _post_to(bn, mock)
            assert False
        except bn.NotifySendError as exc:
            assert exc.category == "PERMANENT"


def test_retry_after_http_date_parsed() -> None:
    _fresh()
    bc, bs, bn = _reload()
    # HTTP-Datum statt Sekunden: _parse_retry_after liefert eine positive Sekundenzahl
    from email.utils import format_datetime
    from datetime import datetime, timedelta, timezone
    future = format_datetime(datetime.now(timezone.utc) + timedelta(seconds=120))
    secs = bn._parse_retry_after(future)
    assert secs is not None and secs > 0
```

- [ ] **Step 2: Tests laufen lassen, Fehlschlag bestätigen**

Run: `cd scripts && python -X utf8 -m pytest test_bridge_notify.py -k "classified or retry_after_http_date" -v`
Expected: FAIL — `AttributeError: module 'bridge_notify' has no attribute 'NotifySendError'`

- [ ] **Step 3: `NotifySendError` + Klassifikation + Retry-After-Parsing implementieren**

In `bridge_notify.py` nach den Konstanten (nach `_HTTP_TIMEOUT = 15`) ergänzen:

```python
import hashlib
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone


class NotifySendError(Exception):
    """Typisierter Sendefehler. category: 'PERMANENT' (Retry sinnlos) |
    'TRANSIENT' (später erneut). retry_after: Sekunden aus dem Header oder None."""
    def __init__(self, category: str, status: int | None,
                 retry_after: int | None, message: str):
        super().__init__(message)
        self.category = category
        self.status = status
        self.retry_after = retry_after


def _classify_http_status(status: int) -> str:
    """429 + 5xx = transient; übrige 4xx = permanent."""
    if status == 429 or status >= 500:
        return "TRANSIENT"
    if 400 <= status < 500:
        return "PERMANENT"
    return "TRANSIENT"  # unerwartet -> vorsichtig retrybar


def _parse_retry_after(value: str | None) -> int | None:
    """Retry-After als Sekunden-Integer ODER HTTP-Datum. None wenn unlesbar."""
    if not value:
        return None
    value = value.strip()
    if value.isdigit():
        return int(value)
    try:
        dt = parsedate_to_datetime(value)
        if dt is None:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        delta = int((dt - datetime.now(timezone.utc)).total_seconds())
        return delta if delta > 0 else 0
    except (TypeError, ValueError):
        return None
```

Dann `_post_telegram` ersetzen (Signatur um `api_base` erweitert, default = Produktiv-URL):

```python
def _post_telegram(text: str, api_base: str = "https://api.telegram.org/bot{token}/sendMessage") -> None:
    """Eine Nachricht an Telegram senden. Wirft NotifySendError mit Kategorie
    (PERMANENT/TRANSIENT) bei Fehler, damit der Aufrufer Retry vs. Aufgeben
    entscheiden kann. Erfolg = stille Rückkehr."""
    token, chat = _telegram_config()
    if not (token and chat):
        raise NotifySendError("PERMANENT", None, None,
                              "Telegram nicht konfiguriert (TELEGRAM_TOKEN/TELEGRAM_CHAT_ID).")
    url = api_base.format(token=token)
    payload = urllib.parse.urlencode({
        "chat_id": chat, "text": text, "parse_mode": "Markdown",
        "disable_web_page_preview": "true",
    }).encode("utf-8")
    req = urllib.request.Request(url, data=payload, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as resp:
            body = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        status = exc.code
        retry_after = _parse_retry_after(exc.headers.get("Retry-After")) if exc.headers else None
        cat = _classify_http_status(status)
        raise NotifySendError(cat, status, retry_after,
                              f"Telegram HTTP {status}") from exc
    except urllib.error.URLError as exc:
        raise NotifySendError("TRANSIENT", None, None,
                              f"Telegram nicht erreichbar: {exc}") from exc
    try:
        obj = json.loads(body)
    except ValueError as exc:
        raise NotifySendError("TRANSIENT", None, None,
                              f"Telegram-Antwort nicht parsebar: {body[:120]}") from exc
    if not obj.get("ok"):
        raise NotifySendError("PERMANENT", None, None,
                              f"Telegram-API lehnt ab: {body[:200]}")
```

- [ ] **Step 4: Tests laufen lassen, grün bestätigen**

Run: `cd scripts && python -X utf8 -m pytest test_bridge_notify.py -k "classified or retry_after_http_date" -v`
Expected: PASS (6 Tests)

- [ ] **Step 5: Volle Notify-Suite laufen lassen (Regression-Check der 12 Alt-Tests)**

Run: `cd scripts && python -X utf8 -m pytest test_bridge_notify.py -v`
Expected: PASS — die 12 alten Tests müssen grün bleiben. Falls ein Alt-Test `_post_telegram` direkt aufruft und nun `NotifySendError` statt `RuntimeError` erwartet: Erwartung im Alt-Test auf `bn.NotifySendError` anpassen (gleiche Stelle, nur Exception-Typ).

- [ ] **Step 6: Commit**

```bash
cd /c/Users/domes/AI/dual-bridge
git add scripts/bridge_notify.py scripts/test_bridge_notify.py
git commit -m "feat(notify): typisierte Fehlerklassifikation in _post_telegram

NotifySendError(category, status, retry_after); 4xx=PERMANENT, 429+5xx+Netz=TRANSIENT,
ok:false=PERMANENT. Retry-After parst Sekunden+HTTP-Datum. Test gegen echten http.server-Mock.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: Dedup-Key (`loop_id + reason`)

**Files:**
- Modify: `scripts/bridge_notify.py` (`_reason_of`, `_notify_key`)
- Test: `scripts/test_bridge_notify.py`

- [ ] **Step 1: Failing tests schreiben**

```python
# --- HTTP-Härtung: Dedup-Key ------------------------------------------------
def test_notify_key_stable_for_same_reason() -> None:
    _fresh()
    bc, bs, bn = _reload()
    info = bs.EscalationInfo(loop_id="loop-x", trigger="stagnation", round="2")
    k1 = bn._notify_key(info)
    k2 = bn._notify_key(info)
    assert k1 == k2
    assert k1.startswith("loop-x:")


def test_notify_key_changes_with_reason() -> None:
    _fresh()
    bc, bs, bn = _reload()
    a = bs.EscalationInfo(loop_id="loop-x", trigger="stagnation", round="2")
    b = bs.EscalationInfo(loop_id="loop-x", trigger="max_rounds", round="4")
    assert bn._notify_key(a) != bn._notify_key(b)
    assert bn._notify_key(a).split(":")[0] == bn._notify_key(b).split(":")[0]
```

- [ ] **Step 2: Fehlschlag bestätigen**

Run: `cd scripts && python -X utf8 -m pytest test_bridge_notify.py -k notify_key -v`
Expected: FAIL — `module 'bridge_notify' has no attribute '_notify_key'`

- [ ] **Step 3: Implementieren**

In `bridge_notify.py` ergänzen (nach `_parse_retry_after`):

```python
def _reason_of(info) -> str:
    """Stabiler Grund-String einer Eskalation, Basis des Dedup-Keys."""
    return f"{info.trigger or ''}|{info.round or ''}"


def _notify_key(info) -> str:
    """loop_id + Hash(reason). Gleiche Eskalation mit geändertem trigger/round
    -> neuer Key -> genau eine Re-Notification."""
    digest = hashlib.sha256(_reason_of(info).encode("utf-8")).hexdigest()[:12]
    return f"{info.loop_id}:{digest}"
```

- [ ] **Step 4: Grün bestätigen**

Run: `cd scripts && python -X utf8 -m pytest test_bridge_notify.py -k notify_key -v`
Expected: PASS (2 Tests)

- [ ] **Step 5: Commit**

```bash
cd /c/Users/domes/AI/dual-bridge
git add scripts/bridge_notify.py scripts/test_bridge_notify.py
git commit -m "feat(notify): Dedup-Key loop_id+reason-Hash gegen Push-Sturm

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: `attempts.json`-Sidecar + Backoff-Berechnung

**Files:**
- Modify: `scripts/bridge_notify.py` (Konstanten, `_attempts_path`, `_load_attempts`, `_save_attempts`, `_compute_next_retry_at`)
- Test: `scripts/test_bridge_notify.py`

- [ ] **Step 1: Failing tests schreiben**

```python
# --- HTTP-Härtung: attempts.json + Backoff ----------------------------------
def test_attempts_roundtrip() -> None:
    _fresh()
    bc, bs, bn = _reload()
    bn._save_attempts({"k1": {"status": "transient_pending", "attempts": 1}})
    loaded = bn._load_attempts()
    assert loaded["k1"]["attempts"] == 1


def test_load_attempts_defensive_when_missing() -> None:
    _fresh()
    bc, bs, bn = _reload()
    assert bn._load_attempts() == {}


def test_next_retry_uses_retry_after_first() -> None:
    _fresh()
    bc, bs, bn = _reload()
    from datetime import datetime
    nxt = bn._compute_next_retry_at(attempts=1, retry_after=30)
    delta = (datetime.fromisoformat(nxt) - datetime.fromisoformat(bc.now_iso())).total_seconds()
    assert 25 <= delta <= 35  # ~30s, Retry-After gewinnt


def test_next_retry_exponential_without_header() -> None:
    _fresh()
    bc, bs, bn = _reload()
    from datetime import datetime
    nxt = bn._compute_next_retry_at(attempts=2, retry_after=None)
    delta = (datetime.fromisoformat(nxt) - datetime.fromisoformat(bc.now_iso())).total_seconds()
    # BACKOFF_BASE_SEC=60 * 2^(2-1) = 120
    assert 110 <= delta <= 130


def test_retry_after_capped() -> None:
    _fresh()
    bc, bs, bn = _reload()
    from datetime import datetime
    nxt = bn._compute_next_retry_at(attempts=1, retry_after=999999)
    delta = (datetime.fromisoformat(nxt) - datetime.fromisoformat(bc.now_iso())).total_seconds()
    assert delta <= bn.RETRY_AFTER_CAP_SEC + 5
```

- [ ] **Step 2: Fehlschlag bestätigen**

Run: `cd scripts && python -X utf8 -m pytest test_bridge_notify.py -k "attempts or next_retry or retry_after_capped" -v`
Expected: FAIL — `_save_attempts` / `_compute_next_retry_at` fehlen

- [ ] **Step 3: Implementieren**

Konstanten nach `_HTTP_TIMEOUT = 15` ergänzen:

```python
ATTEMPTS_FILE_NAME = "attempts.json"
MAX_TRANSIENT_ATTEMPTS = 6
BACKOFF_BASE_SEC = 60
BACKOFF_CAP_SEC = 3600       # Deckel für eigenen exp-Backoff
RETRY_AFTER_CAP_SEC = 3600   # Deckel für Server-vorgegebenen Retry-After
```

Sidecar-Zugriff (analog zu `_sent_path`/`_load_sent`/`_save_sent`):

```python
def _attempts_path() -> Path:
    return _notify_dir() / ATTEMPTS_FILE_NAME


def _load_attempts() -> dict:
    path = _attempts_path()
    try:
        if not path.exists():
            return {}
        data = json.loads(bc.read_text_utf8(path))
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _save_attempts(data: dict) -> None:
    _notify_dir().mkdir(parents=True, exist_ok=True)
    bc.write_text_atomic(_attempts_path(), json.dumps(data, ensure_ascii=False, indent=2))


def _compute_next_retry_at(attempts: int, retry_after: int | None) -> str:
    """ISO-Zeitstempel des nächsten Retry. Retry-After zuerst (gedeckelt),
    sonst exp-Backoff (gedeckelt)."""
    from datetime import timedelta
    if retry_after is not None and retry_after >= 0:
        delay = min(retry_after, RETRY_AFTER_CAP_SEC)
    else:
        delay = min(BACKOFF_BASE_SEC * (2 ** max(0, attempts - 1)), BACKOFF_CAP_SEC)
    base = datetime.fromisoformat(bc.now_iso())
    return (base + timedelta(seconds=delay)).isoformat()
```

- [ ] **Step 4: Grün bestätigen**

Run: `cd scripts && python -X utf8 -m pytest test_bridge_notify.py -k "attempts or next_retry or retry_after_capped" -v`
Expected: PASS (5 Tests)

- [ ] **Step 5: Commit**

```bash
cd /c/Users/domes/AI/dual-bridge
git add scripts/bridge_notify.py scripts/test_bridge_notify.py
git commit -m "feat(notify): attempts.json-Sidecar + Retry-After-zuerst Backoff

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: Fälligkeits-gesteuerter Kern (`notify_new_escalations`)

**Files:**
- Modify: `scripts/bridge_notify.py` (`notify_new_escalations` neu)
- Test: `scripts/test_bridge_notify.py`

- [ ] **Step 1: Failing tests schreiben**

```python
# --- HTTP-Härtung: Attempt-Lifecycle ----------------------------------------
class _FailSender:
    """send_fn, die eine NotifySendError mit fixer Kategorie wirft."""
    def __init__(self, bn, category, status=None, retry_after=None):
        self.bn, self.category, self.status, self.retry_after = bn, category, status, retry_after
        self.calls = 0
    def __call__(self, text):
        self.calls += 1
        raise self.bn.NotifySendError(self.category, self.status, self.retry_after, "sim")


def test_transient_failure_records_attempt_not_sent() -> None:
    _fresh()
    bc, bs, bn = _reload()
    _write_escalation(bc, bs, loop_id="loop-t")
    sender = _FailSender(bn, "TRANSIENT", status=503)
    sent, failed = bn.notify_new_escalations(send_fn=sender)
    assert sent == [] and failed
    att = bn._load_attempts()
    key = next(iter(att))
    assert att[key]["status"] == "transient_pending"
    assert att[key]["attempts"] == 1
    assert "next_retry_at" in att[key]
    assert bn._load_sent() == {}


def test_retry_skipped_when_not_due() -> None:
    _fresh()
    bc, bs, bn = _reload()
    info = bs.EscalationInfo(loop_id="loop-t", trigger="max_rounds", round="3")
    _write_escalation(bc, bs, loop_id="loop-t")
    from datetime import datetime, timedelta
    future = (datetime.fromisoformat(bc.now_iso()) + timedelta(hours=1)).isoformat()
    bn._save_attempts({bn._notify_key(info): {
        "loop_id": "loop-t", "reason": bn._reason_of(info),
        "status": "transient_pending", "attempts": 1, "next_retry_at": future}})
    rec = _Recorder()
    sent, failed = bn.notify_new_escalations(send_fn=rec)
    assert rec.calls == [] and sent == [] and failed == []


def test_retry_attempted_when_due() -> None:
    _fresh()
    bc, bs, bn = _reload()
    info = bs.EscalationInfo(loop_id="loop-t", trigger="max_rounds", round="3")
    _write_escalation(bc, bs, loop_id="loop-t")
    from datetime import datetime, timedelta
    past = (datetime.fromisoformat(bc.now_iso()) - timedelta(hours=1)).isoformat()
    bn._save_attempts({bn._notify_key(info): {
        "loop_id": "loop-t", "reason": bn._reason_of(info),
        "status": "transient_pending", "attempts": 1, "next_retry_at": past}})
    rec = _Recorder()
    sent, failed = bn.notify_new_escalations(send_fn=rec)
    assert len(rec.calls) == 1 and sent


def test_transient_then_success_moves_to_sent() -> None:
    _fresh()
    bc, bs, bn = _reload()
    _write_escalation(bc, bs, loop_id="loop-t")
    bn.notify_new_escalations(send_fn=_FailSender(bn, "TRANSIENT", status=503))
    # next_retry_at künstlich in die Vergangenheit ziehen
    att = bn._load_attempts()
    key = next(iter(att))
    from datetime import datetime, timedelta
    att[key]["next_retry_at"] = (datetime.fromisoformat(bc.now_iso()) - timedelta(hours=1)).isoformat()
    bn._save_attempts(att)
    rec = _Recorder()
    sent, failed = bn.notify_new_escalations(send_fn=rec)
    assert sent and bn._load_attempts() == {}
    assert key in bn._load_sent()


def test_permanent_failure_marks_failed() -> None:
    _fresh()
    bc, bs, bn = _reload()
    _write_escalation(bc, bs, loop_id="loop-p")
    sent, failed = bn.notify_new_escalations(send_fn=_FailSender(bn, "PERMANENT", status=401))
    att = bn._load_attempts()
    key = next(iter(att))
    assert att[key]["status"] == "permanent_failed"
    # Folgelauf: kein weiterer Versuch
    rec = _Recorder()
    s2, f2 = bn.notify_new_escalations(send_fn=rec)
    assert rec.calls == []


def test_max_attempts_becomes_permanent() -> None:
    _fresh()
    bc, bs, bn = _reload()
    info = bs.EscalationInfo(loop_id="loop-m", trigger="max_rounds", round="3")
    _write_escalation(bc, bs, loop_id="loop-m")
    from datetime import datetime, timedelta
    past = (datetime.fromisoformat(bc.now_iso()) - timedelta(hours=1)).isoformat()
    bn._save_attempts({bn._notify_key(info): {
        "loop_id": "loop-m", "reason": bn._reason_of(info),
        "status": "transient_pending", "attempts": bn.MAX_TRANSIENT_ATTEMPTS,
        "next_retry_at": past}})
    bn.notify_new_escalations(send_fn=_FailSender(bn, "TRANSIENT", status=503))
    att = bn._load_attempts()
    assert att[bn._notify_key(info)]["status"] == "permanent_failed"


def test_changed_reason_triggers_one_renotify() -> None:
    _fresh()
    bc, bs, bn = _reload()
    # erst stagnation/2 erfolgreich
    _write_escalation(bc, bs, loop_id="loop-r", trigger="stagnation", round_no="2")
    rec1 = _Recorder()
    bn.notify_new_escalations(send_fn=rec1)
    assert len(rec1.calls) == 1
    # gleiche Eskalation verschärft -> max_rounds/4
    _write_escalation(bc, bs, loop_id="loop-r", trigger="max_rounds", round_no="4")
    rec2 = _Recorder()
    bn.notify_new_escalations(send_fn=rec2)
    assert len(rec2.calls) == 1   # genau eine Re-Notification
    # nochmal ohne Änderung -> kein Send
    rec3 = _Recorder()
    bn.notify_new_escalations(send_fn=rec3)
    assert rec3.calls == []


def test_partial_failure_isolates() -> None:
    _fresh()
    bc, bs, bn = _reload()
    _write_escalation(bc, bs, loop_id="loop-a")
    _write_escalation(bc, bs, loop_id="loop-b")
    _write_escalation(bc, bs, loop_id="loop-c")
    rec = _Recorder(fail_for={"loop-b"})
    sent, failed = bn.notify_new_escalations(send_fn=rec)
    # loop-b wirft generische RuntimeError (kein NotifySendError) -> als transient behandelt
    assert len(sent) == 2
    assert any("loop-b" in f for f in failed) or failed
```

> Hinweis für den Implementierer: `_Recorder` wirft bei `fail_for` eine generische `RuntimeError`. Der Kern muss daher **jede** Exception fangen; eine `RuntimeError` (kein `NotifySendError`) wird konservativ als `TRANSIENT` behandelt.

- [ ] **Step 2: Fehlschlag bestätigen**

Run: `cd scripts && python -X utf8 -m pytest test_bridge_notify.py -k "transient or retry_ or permanent or max_attempts or changed_reason or partial_failure" -v`
Expected: FAIL (Kern noch alt, kennt attempts.json nicht)

- [ ] **Step 3: `notify_new_escalations` ersetzen**

```python
def notify_new_escalations(send_fn=None, dry_run: bool = False,
                           mark: bool = True) -> tuple[list, list]:
    """Für jede fällige Eskalation genau einen Send-Versuch. Fälligkeitslogik:
    sent -> skip; permanent_failed -> skip; transient_pending & nicht fällig ->
    skip; transient_pending & fällig -> retry; sonst -> neu.

    Rückgabe: (sent_keys, failed_keys). at-least-once: transiente Fehler bleiben
    in attempts.json (retry beim nächsten fälligen Lauf); permanente kippen auf
    permanent_failed (kein Sturm). Schreibt NUR in state/_notify/."""
    send_fn = send_fn or _post_telegram
    escalations = bs.scan_escalations(bs.STATE_DIR)
    sent_map = _load_sent()
    attempts = _load_attempts()
    now = datetime.fromisoformat(bc.now_iso())

    sent: list[str] = []
    failed: list[str] = []

    for info in escalations:
        key = _notify_key(info)
        if key in sent_map:
            continue
        rec = attempts.get(key)
        if rec and rec.get("status") == "permanent_failed":
            continue
        if rec and rec.get("status") == "transient_pending":
            try:
                due = datetime.fromisoformat(rec.get("next_retry_at", bc.now_iso()))
            except ValueError:
                due = now
            if now < due:
                continue  # noch nicht fällig
            attempt_no = int(rec.get("attempts", 0)) + 1
        else:
            attempt_no = 1

        question = _extract_question(info.loop_id)
        msg = format_escalation_message(info, question)
        if dry_run:
            print(f"[dry-run] würde senden:\n{msg}\n")
            continue

        try:
            send_fn(msg)
        except NotifySendError as exc:
            failed.append(key)
            if exc.category == "PERMANENT" or attempt_no >= MAX_TRANSIENT_ATTEMPTS:
                attempts[key] = {"loop_id": info.loop_id, "reason": _reason_of(info),
                                 "status": "permanent_failed", "attempts": attempt_no,
                                 "last_error": str(exc)}
                print(f"[notify] PERMANENT gescheitert für {key}: {exc}")
            else:
                attempts[key] = {"loop_id": info.loop_id, "reason": _reason_of(info),
                                 "status": "transient_pending", "attempts": attempt_no,
                                 "next_retry_at": _compute_next_retry_at(attempt_no, exc.retry_after),
                                 "last_error": str(exc)}
                print(f"[notify] transient für {key} (Versuch {attempt_no}): {exc}")
            continue
        except Exception as exc:  # noqa: BLE001 — unbekannt -> konservativ transient
            failed.append(key)
            if attempt_no >= MAX_TRANSIENT_ATTEMPTS:
                attempts[key] = {"loop_id": info.loop_id, "reason": _reason_of(info),
                                 "status": "permanent_failed", "attempts": attempt_no,
                                 "last_error": str(exc)}
            else:
                attempts[key] = {"loop_id": info.loop_id, "reason": _reason_of(info),
                                 "status": "transient_pending", "attempts": attempt_no,
                                 "next_retry_at": _compute_next_retry_at(attempt_no, None),
                                 "last_error": str(exc)}
            print(f"[notify] Senden fehlgeschlagen für {key}: {exc}")
            continue

        # Erfolg
        sent.append(key)
        attempts.pop(key, None)
        sent_map[key] = {"loop_id": info.loop_id, "reason": _reason_of(info),
                         "notified_at": bc.now_iso()}

    if mark and not dry_run:
        _save_sent(sent_map)
        _save_attempts(attempts)

    return sent, failed
```

- [ ] **Step 4: Grün bestätigen**

Run: `cd scripts && python -X utf8 -m pytest test_bridge_notify.py -k "transient or retry_ or permanent or max_attempts or changed_reason or partial_failure" -v`
Expected: PASS

- [ ] **Step 5: Volle Notify-Suite (alte 12 + neue) grün**

Run: `cd scripts && python -X utf8 -m pytest test_bridge_notify.py -v`
Expected: PASS. Falls ein Alt-Test annahm, `sent.json`-Key sei `loop_id` (jetzt `notify_key`): Erwartung im Alt-Test auf `_notify_key(info)` umstellen bzw. auf „genau ein Eintrag" prüfen statt exaktem Key.

- [ ] **Step 6: Commit**

```bash
cd /c/Users/domes/AI/dual-bridge
git add scripts/bridge_notify.py scripts/test_bridge_notify.py
git commit -m "feat(notify): faelligkeits-gesteuerter Kern mit cross-trigger Retry

notify_new_escalations: sent/permanent_failed/transient-not-due/due/neu. Transiente
Fehler bleiben in attempts.json (Retry beim naechsten faelligen Lauf), permanente kippen
auf permanent_failed (kein Push-Sturm). Schreibt nur state/_notify/.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: `reconcile` räumt beide Sidecars + Invarianten/`--dry-run`-Tests + `main`-rc

**Files:**
- Modify: `scripts/bridge_notify.py` (`reconcile`, `main`)
- Test: `scripts/test_bridge_notify.py`

- [ ] **Step 1: Failing tests schreiben**

```python
# --- HTTP-Härtung: reconcile / Invariante / dry-run / rc -------------------
def test_reconcile_cleans_both_sidecars() -> None:
    _fresh()
    bc, bs, bn = _reload()
    # eine offene Eskalation + sent/attempts-Einträge für eine NICHT mehr offene
    _write_escalation(bc, bs, loop_id="loop-open")
    bn._save_sent({"loop-gone:abc": {"loop_id": "loop-gone"}})
    bn._save_attempts({"loop-gone:def": {"loop_id": "loop-gone", "status": "permanent_failed"}})
    removed = bn.reconcile()
    assert any("loop-gone" in r for r in removed)
    assert bn._load_sent() == {}
    assert bn._load_attempts() == {}


def test_notifier_still_read_only_on_escalations() -> None:
    _fresh()
    bc, bs, bn = _reload()
    _write_escalation(bc, bs, loop_id="loop-ro")
    esc_dir = bs.STATE_DIR
    before = _snapshot(esc_dir)
    before = {k: v for k, v in before.items() if k.startswith("ESCALATION-")}
    rec = _Recorder()
    bn.notify_new_escalations(send_fn=rec)
    after = _snapshot(esc_dir)
    after = {k: v for k, v in after.items() if k.startswith("ESCALATION-")}
    assert before == after  # ESCALATION-*.md unverändert


def test_dry_run_touches_no_sidecar() -> None:
    _fresh()
    bc, bs, bn = _reload()
    _write_escalation(bc, bs, loop_id="loop-d")
    bn.notify_new_escalations(dry_run=True)
    assert bn._load_sent() == {}
    assert bn._load_attempts() == {}


def test_main_rc3_on_permanent_failure() -> None:
    _fresh()
    bc, bs, bn = _reload()
    _write_escalation(bc, bs, loop_id="loop-rc")
    # _post_telegram durch einen PERMANENT-Werfer ersetzen
    def _boom(text, api_base=None):
        raise bn.NotifySendError("PERMANENT", 401, None, "bad token")
    bn._post_telegram = _boom  # type: ignore
    rc = bn.main([])
    assert rc == 3


def test_main_rc0_when_retry_not_due() -> None:
    _fresh()
    bc, bs, bn = _reload()
    info = bs.EscalationInfo(loop_id="loop-rc0", trigger="max_rounds", round="3")
    _write_escalation(bc, bs, loop_id="loop-rc0")
    from datetime import datetime, timedelta
    future = (datetime.fromisoformat(bc.now_iso()) + timedelta(hours=1)).isoformat()
    bn._save_attempts({bn._notify_key(info): {
        "loop_id": "loop-rc0", "reason": bn._reason_of(info),
        "status": "transient_pending", "attempts": 1, "next_retry_at": future}})
    rc = bn.main([])
    assert rc == 0   # nichts fällig -> kein Fehlversuch -> rc 0
```

- [ ] **Step 2: Fehlschlag bestätigen**

Run: `cd scripts && python -X utf8 -m pytest test_bridge_notify.py -k "reconcile_cleans or read_only or dry_run_touches or main_rc" -v`
Expected: FAIL (reconcile räumt nur sent.json; main-rc kennt failed-Liste noch nicht voll)

- [ ] **Step 3: `reconcile` + `main` anpassen**

`reconcile` ersetzen:

```python
def reconcile() -> list:
    """sent.json UND attempts.json gegen die offenen Eskalationen bereinigen:
    Einträge, deren loop_id nicht mehr offen ist, entfernen. Sendet nichts."""
    open_loops = {e.loop_id for e in bs.scan_escalations(bs.STATE_DIR)}
    removed: list[str] = []
    sent_map = _load_sent()
    for key in list(sent_map):
        if sent_map[key].get("loop_id") not in open_loops:
            sent_map.pop(key); removed.append(key)
    _save_sent(sent_map)
    attempts = _load_attempts()
    for key in list(attempts):
        if attempts[key].get("loop_id") not in open_loops:
            attempts.pop(key); removed.append(key)
    _save_attempts(attempts)
    return removed
```

In `main`: die `failed`-Liste führt schon zu rc=3 (bestehende Zeile `if failed: return 3`). Verifizieren, dass `notify_new_escalations` `failed` bei permanentem UND transientem Fehlversuch füllt (Task 4 tut das). Keine weitere main-Änderung nötig außer: sicherstellen, dass `--dry-run` weiterhin vor dem Konfig-Check durchläuft (bestehend). rc=0 bei „nichts fällig" ist automatisch (failed leer).

> Falls `test_main_rc3_on_permanent_failure` fehlschlägt, weil `main` `_is_configured()` prüft und mit Test-Token kurzschließt: Der Test setzt `TELEGRAM_TOKEN` via `_fresh()`, also ist `_is_configured()` True — der Pfad läuft in `notify_new_escalations`, wo der gepatchte `_boom` greift. Kein Sonderfall nötig.

- [ ] **Step 4: Grün bestätigen**

Run: `cd scripts && python -X utf8 -m pytest test_bridge_notify.py -k "reconcile_cleans or read_only or dry_run_touches or main_rc" -v`
Expected: PASS

- [ ] **Step 5: GANZE Suite grün (Regressionsbeweis)**

Run: `cd scripts && python -X utf8 -m pytest -q`
Expected: PASS — Soll war 307; jetzt 307 + neue Notify-Tests (~19), 0 Fehler. Bei roten Tests außerhalb von `test_bridge_notify.py`: prüfen ob sie vorbestehend rot sind (am Vor-HEAD), NICHT blind anpassen.

- [ ] **Step 6: Commit**

```bash
cd /c/Users/domes/AI/dual-bridge
git add scripts/bridge_notify.py scripts/test_bridge_notify.py
git commit -m "feat(notify): reconcile raeumt beide Sidecars + rc-Tests

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: README-Dokumentation

**Files:**
- Modify: `README.md` (Abschnitt zum Notifier)

- [ ] **Step 1: README-Abschnitt finden**

Run: `cd /c/Users/domes/AI/dual-bridge && grep -n "bridge_notify\|Notifier\|Eskalations-Notifier" README.md | head`
Expected: Zeilennummer des Notifier-Abschnitts.

- [ ] **Step 2: Absatz ergänzen** (unter dem Notifier-Abschnitt)

```markdown
**HTTP-Härtung der Sende-Kante:** Der Notifier klassifiziert Telegram-Fehler:
`4xx` (außer 429) und inhaltliche Ablehnung (`ok:false`) sind **permanent** —
keine Wiederholung, Eskalation wird als `permanent_failed` markiert (Sidecar
`state/_notify/attempts.json`), Exit-Code 3. `429`/`5xx`/Netzfehler sind
**transient** — der nächste Scheduled-Task-Lauf versucht es erneut, frühestens
ab `next_retry_at` (`Retry-After`-Header zuerst, sonst exponentielles Backoff,
max. `MAX_TRANSIENT_ATTEMPTS=6`). Dedup über `loop_id + reason` (trigger|round):
verschärft sich eine Eskalation, gibt es genau **eine** neue Benachrichtigung.
`--reconcile` räumt `sent.json` und `attempts.json`.
```

- [ ] **Step 3: Commit**

```bash
cd /c/Users/domes/AI/dual-bridge
git add README.md
git commit -m "docs(notify): Retry/Backoff/Dedup-Verhalten dokumentiert

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Live-Smoke (manuell, NACH allen Tasks — P007, NICHT in der Suite)

Mit echten Credentials (aus DCO `.env`):
```bash
cd /c/Users/domes/AI/dual-bridge/scripts
python bridge_notify.py --dry-run     # zeigt geplante Nachricht, sendet nichts
# dann gegen eine echte Test-Eskalation ein realer Lauf -> Telegram-Nachricht prüfen
```
Aufräumen: Test-Eskalation + `state/_notify/`-Testeinträge entfernen.

---

## Self-Review-Ergebnis (vom Plan-Autor)

- **Spec-Coverage:** Klassifikation→T1, Dedup-Key→T2, attempts.json+Backoff→T3, Fälligkeits-Kern+Lifecycle→T4, reconcile+Invariante+dry-run+rc→T5, Doku→T6. Alle 8 Erfolgskriterien abgedeckt. Live-Smoke als manueller Schritt (bewusst außerhalb Suite).
- **Platzhalter:** keine — jeder Code-Step zeigt vollständigen Code.
- **Typ-Konsistenz:** `NotifySendError(category, status, retry_after, message)` einheitlich; `_notify_key`/`_reason_of`/`_compute_next_retry_at`/`_load_attempts`/`_save_attempts`/`_attempts_path` über alle Tasks gleich benannt; `attempts`-Record-Felder (`loop_id, reason, status, attempts, next_retry_at, last_error`) konsistent.
- **Bekannte Migrations-Stelle:** `sent.json`-Key wechselt von `loop_id` zu `notify_key` — Alt-Tests, die den exakten Key prüfen, in T1/T4 Step 5 angepasst (auf `_notify_key`/„genau ein Eintrag").
