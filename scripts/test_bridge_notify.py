"""Tests für den Eskalations-Notifier (bridge_notify.py).

Dual-runnable wie der Rest der Suite:
    python -m pytest scripts/test_bridge_notify.py
    python scripts/test_bridge_notify.py

Isoliert über DUAL_BRIDGE_STATE (tmp). Telegram wird NIE echt aufgerufen — der
Versand läuft über eine injizierte send_fn bzw. ein gepatchtes _post_telegram,
sodass kein Test je das Netz berührt. Der Notifier ist eine reine Push-Kante: er
liest ESCALATION-*.md, sendet, und merkt sich Gesendetes NUR in state/_notify/.
"""
from __future__ import annotations

import importlib
import json
import os
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path


def _fresh(endpoint: str = "claude@laptop-a") -> Path:
    root = Path(tempfile.mkdtemp(prefix="bridge-notify-"))
    os.environ["DUAL_BRIDGE_ROOT"] = str(root)
    os.environ["DUAL_BRIDGE_ENDPOINT"] = endpoint
    os.environ["DUAL_BRIDGE_STATE"] = str(root / "state")
    # Telegram per Default konfiguriert (Tests, die das Gegenteil wollen, löschen es).
    os.environ["TELEGRAM_TOKEN"] = "test-token"
    os.environ["TELEGRAM_CHAT_ID"] = "4242"
    # Override-Namen sauber halten, damit sie nicht aus einem früheren Test lecken.
    os.environ.pop("DUAL_BRIDGE_TG_TOKEN", None)
    os.environ.pop("DUAL_BRIDGE_TG_CHAT", None)
    return root


def _reload():
    import bridge_common as bc
    importlib.reload(bc)
    import bridge_status as bs
    importlib.reload(bs)
    import bridge_notify as bn
    importlib.reload(bn)
    return bc, bs, bn


def _write_escalation(bc, bs, *, loop_id: str, trigger: str = "max_rounds",
                      round_no: str = "3", question: str = "Soll ich X tun?") -> Path:
    bs.STATE_DIR.mkdir(parents=True, exist_ok=True)
    fm = {"loop_id": loop_id, "trigger": trigger, "round": round_no,
          "branch": f"bridge/{loop_id}", "commit": "abc123",
          "exit_reason": "escalation", "created": bc.now_iso()}
    body = (f"## Ziel (aus dem Seed)\nZiel\n\n"
            f"## Done-Kriterien\n- c\n\n"
            f"## Eskalations-Grund\nGrund\n\n"
            f"## Offene Frage an den Owner\n{question}\n\n"
            f"## Zwischenstand\nx\n")
    path = bs.STATE_DIR / f"ESCALATION-{loop_id}.md"
    bc.write_text_utf8(path, bc.build_document(fm, body))
    return path


class _Recorder:
    """Eine injizierbare send_fn, die Aufrufe protokolliert und optional bei
    bestimmten loop_ids einen Fehler wirft (Partial-Failure-Simulation)."""
    def __init__(self, fail_for: set | None = None):
        self.calls: list[str] = []          # gesendete Texte
        self.fail_for = fail_for or set()

    def __call__(self, text: str) -> None:
        # Welcher loop_id steckt in dieser Nachricht? (für gezieltes Fehlschlagen)
        for lid in self.fail_for:
            if lid in text:
                raise RuntimeError(f"simulierter Sendefehler für {lid}")
        self.calls.append(text)


def _snapshot(dirpath: Path) -> dict:
    out = {}
    if dirpath.exists():
        for p in sorted(dirpath.rglob("*")):
            if p.is_file():
                out[str(p.relative_to(dirpath))] = p.read_text(encoding="utf-8")
    return out


# --- (1) neue Eskalation -> ein Send + markiert -----------------------------
def test_new_escalation_triggers_send() -> None:
    _fresh()
    bc, bs, bn = _reload()
    _write_escalation(bc, bs, loop_id="loop-aaaa")
    rec = _Recorder()
    sent, failed = bn.notify_new_escalations(send_fn=rec)
    assert rec.calls and len(rec.calls) == 1, rec.calls
    # sent/failed/sent.json-Keys sind jetzt notify_key (loop_id+reason-Hash).
    assert len(sent) == 1 and sent[0].startswith("loop-aaaa:"), sent
    assert failed == [], failed
    saved = bn._load_sent()
    assert any(k.startswith("loop-aaaa:") for k in saved), saved
    print("  notify OK — neue Eskalation -> ein Send + in sent.json markiert")


# --- (2) bereits gesendet -> kein erneuter Send -----------------------------
def test_already_sent_escalation_is_not_resent() -> None:
    _fresh()
    bc, bs, bn = _reload()
    _write_escalation(bc, bs, loop_id="loop-aaaa")
    rec = _Recorder()
    bn.notify_new_escalations(send_fn=rec)      # erster Lauf
    rec2 = _Recorder()
    sent, failed = bn.notify_new_escalations(send_fn=rec2)  # zweiter Lauf
    assert rec2.calls == [], "bereits gemeldete Eskalation darf nicht erneut gehen"
    assert sent == [] and failed == []
    print("  notify OK — bereits gesendete Eskalation wird nicht erneut gepingt")


# --- (3) mehrere neue -> jede genau einmal ----------------------------------
def test_multiple_new_escalations_each_sent_once() -> None:
    _fresh()
    bc, bs, bn = _reload()
    for lid in ("loop-a", "loop-b", "loop-c"):
        _write_escalation(bc, bs, loop_id=lid)
    rec = _Recorder()
    sent, failed = bn.notify_new_escalations(send_fn=rec)
    assert len(rec.calls) == 3, rec.calls
    prefixes = {k.split(":")[0] for k in sent}
    assert prefixes == {"loop-a", "loop-b", "loop-c"}, sent
    saved_prefixes = {k.split(":")[0] for k in bn._load_sent()}
    assert saved_prefixes >= {"loop-a", "loop-b", "loop-c"}
    print("  notify OK — drei neue -> drei Sends, alle markiert")


# --- (4) Sendefehler markiert NICHTS ----------------------------------------
def test_send_failure_does_not_mark_sent() -> None:
    _fresh()
    bc, bs, bn = _reload()
    _write_escalation(bc, bs, loop_id="loop-aaaa")
    rec = _Recorder(fail_for={"loop-aaaa"})
    sent, failed = bn.notify_new_escalations(send_fn=rec)
    assert sent == [], sent
    assert len(failed) == 1 and failed[0].startswith("loop-aaaa:"), failed
    # Fehlschlag landet NICHT in sent.json (sondern als transient in attempts.json).
    assert not any(k.startswith("loop-aaaa:") for k in bn._load_sent()), "Fehlschlag darf nicht markieren"
    assert any(k.startswith("loop-aaaa:") for k in bn._load_attempts()), "transienter Fehler -> attempts.json"
    print("  notify OK — Sendefehler -> nicht sent.json, sondern attempts.json (Retry)")


# --- (5) Partial-Failure isoliert -------------------------------------------
def test_partial_failure_isolates() -> None:
    _fresh()
    bc, bs, bn = _reload()
    for lid in ("loop-a", "loop-b", "loop-c"):
        _write_escalation(bc, bs, loop_id=lid)
    rec = _Recorder(fail_for={"loop-b"})
    sent, failed = bn.notify_new_escalations(send_fn=rec)
    assert {k.split(":")[0] for k in sent} == {"loop-a", "loop-c"}, sent
    assert len(failed) == 1 and failed[0].startswith("loop-b:"), failed
    saved_prefixes = {k.split(":")[0] for k in bn._load_sent()}
    assert "loop-a" in saved_prefixes and "loop-c" in saved_prefixes and "loop-b" not in saved_prefixes, saved_prefixes
    print("  notify OK — ein Fehler isoliert, die anderen werden zugestellt")


# --- (6) nicht konfiguriert -> rc 2, nichts markiert ------------------------
def test_not_configured_returns_2_and_marks_nothing() -> None:
    _fresh()
    os.environ.pop("TELEGRAM_TOKEN", None)
    os.environ.pop("TELEGRAM_CHAT_ID", None)
    os.environ.pop("DUAL_BRIDGE_TG_TOKEN", None)
    os.environ.pop("DUAL_BRIDGE_TG_CHAT", None)
    bc, bs, bn = _reload()
    _write_escalation(bc, bs, loop_id="loop-aaaa")
    rc = bn.main([])
    assert rc == 2, rc
    assert bn._load_sent() == {} or "loop-aaaa" not in bn._load_sent()
    print("  notify OK — fehlende Konfig -> rc=2, kein Versand, kein Markieren")


# --- (7) --dry-run sendet/markiert nichts -----------------------------------
def test_dry_run_sends_nothing_marks_nothing() -> None:
    _fresh()
    bc, bs, bn = _reload()
    _write_escalation(bc, bs, loop_id="loop-aaaa")
    rec = _Recorder()
    sent, failed = bn.notify_new_escalations(send_fn=rec, dry_run=True)
    assert rec.calls == [], "dry-run darf nichts senden"
    assert "loop-aaaa" not in bn._load_sent(), "dry-run darf nichts markieren"
    assert sent == [] and failed == []
    print("  notify OK — --dry-run berührt weder Sender noch sent.json")


# --- (8) Nachrichtenformat enthält Schlüsselfelder --------------------------
def test_message_format_contains_key_fields() -> None:
    _fresh()
    bc, bs, bn = _reload()
    info = bs.EscalationInfo(loop_id="loop-xyz", trigger="stagnation",
                             round="2", branch="bridge/loop-xyz",
                             commit="dead99", created="2026-06-03T12:00:00")
    msg = bn.format_escalation_message(info, question="Brauchst du Y?")
    assert "loop-xyz" in msg
    assert "stagnation" in msg
    assert "2" in msg
    assert "Brauchst du Y?" in msg
    print("  notify OK — Nachricht enthält loop_id/trigger/round/Frage")


# --- (9) Markdown-Injection wird entschärft ---------------------------------
def test_message_escapes_markdown_injection() -> None:
    _fresh()
    bc, bs, bn = _reload()
    info = bs.EscalationInfo(loop_id="loop-evil", trigger="max_rounds",
                             round="1", branch="bridge/loop-evil",
                             commit="c0ffee", created="2026-06-03T12:00:00")
    nasty = "klick [hier](http://evil) *fett* _kursiv_ `code`"
    msg = bn.format_escalation_message(info, question=nasty)
    # Der vom Owner unkontrollierte Inhalt (die Frage) darf KEIN nacktes
    # Telegram-Markup mehr enthalten — jedes Spezialzeichen aus `nasty` muss in
    # der Nachricht escaped (mit vorangestelltem Backslash) auftauchen. Das
    # absichtliche Label-Markup des Notifiers (z.B. *Titel*) ist davon nicht
    # betroffen, daher prüfen wir gezielt die escapte Form des Inhalts.
    assert "\\[hier\\]" in msg, msg
    assert "\\*fett\\*" in msg, msg
    assert "\\_kursiv\\_" in msg, msg
    assert "\\`code\\`" in msg, msg
    # und das rohe, un-escapte Injektions-Muster darf NICHT vorkommen
    assert "*fett*" not in msg and "[hier]" not in msg, msg
    print("  notify OK — Markdown-Injection im Inhalt wird escaped")


# --- (10) --reconcile entfernt veraltete Einträge ---------------------------
def test_reconcile_drops_stale_entries() -> None:
    _fresh()
    bc, bs, bn = _reload()
    # sent.json mit einem loop_id, der gar nicht (mehr) offen ist
    bn._save_sent({"loop-stale": {"notified_at": "t"}})
    rec = _Recorder()
    removed = bn.reconcile()
    assert "loop-stale" in removed, removed
    assert "loop-stale" not in bn._load_sent()
    assert rec.calls == [], "reconcile sendet nichts"
    print("  notify OK — --reconcile entfernt veraltete sent.json-Einträge")


# --- (11) read-only auf ESCALATION-Baum -------------------------------------
def test_notifier_is_read_only_on_escalations() -> None:
    _fresh()
    bc, bs, bn = _reload()
    _write_escalation(bc, bs, loop_id="loop-a")
    _write_escalation(bc, bs, loop_id="loop-b")
    # Nur die ESCALATION-*.md selbst betrachten (state/_notify/ darf sich ändern).
    esc_before = {p.name: p.read_text(encoding="utf-8")
                  for p in bs.STATE_DIR.glob("ESCALATION-*.md")}
    rec = _Recorder()
    bn.notify_new_escalations(send_fn=rec)
    esc_after = {p.name: p.read_text(encoding="utf-8")
                 for p in bs.STATE_DIR.glob("ESCALATION-*.md")}
    assert esc_before == esc_after, "Notifier hat ESCALATION-Dateien verändert!"
    print("  notify OK — ESCALATION-*.md unverändert (schreibt nur in _notify/)")


# --- (12) Digest fasst zusammen, auch ohne Eskalation -----------------------
def test_digest_summarizes_without_escalation() -> None:
    _fresh()
    bc, bs, bn = _reload()
    # Eine offene Task, KEINE Eskalation
    bc.ensure_dirs()
    fm = {"created": bc.now_iso(), "schema_version": "2", "status": "open",
          "kind": "implement", "adapter": "codex",
          "task_id": "20260603-120000-000001-0-aaaa"}
    bc.write_text_utf8(
        bc.lane_outbox("A-to-B") / "task-20260603-120000-000001-0-aaaa.md",
        bc.build_document(fm, "## Auftrag\nx\n"))
    rec = _Recorder()
    n = bn.send_digest(send_fn=rec)
    assert n == 1 and len(rec.calls) == 1, rec.calls
    assert "1" in rec.calls[0]  # mind. die offene Task taucht in der Summary auf
    print("  notify OK — --digest sendet eine Zusammenfassung, auch ohne Eskalation")


# ===========================================================================
# HTTP-Härtung (Spec 2026-06-07): Fehlerklassifikation, Retry, Dedup
# ===========================================================================

class _MockTelegram:
    """Lokaler http.server, der ein scriptbares Ergebnis liefert. _post_telegram
    läuft mit echtem urllib dagegen (P006: echte HTTPError/URLError-Kette,
    kein gemockter Response)."""
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
    print("  notify OK — 4xx -> PERMANENT")


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
    print("  notify OK — 429 -> TRANSIENT + Retry-After")


def test_5xx_classified_transient() -> None:
    _fresh()
    bc, bs, bn = _reload()
    with _MockTelegram(status=503, body="oops") as mock:
        try:
            _post_to(bn, mock)
            assert False
        except bn.NotifySendError as exc:
            assert exc.category == "TRANSIENT"
    print("  notify OK — 5xx -> TRANSIENT")


def test_network_error_classified_transient() -> None:
    _fresh()
    bc, bs, bn = _reload()
    # Toter Port: nichts lauscht -> URLError -> TRANSIENT
    try:
        bn._post_telegram("hi", api_base="http://127.0.0.1:1/bot{token}/sendMessage")
        assert False
    except bn.NotifySendError as exc:
        assert exc.category == "TRANSIENT"
    print("  notify OK — Netzfehler -> TRANSIENT")


def test_200_ok_false_classified_permanent() -> None:
    _fresh()
    bc, bs, bn = _reload()
    with _MockTelegram(status=200,
                       body='{"ok": false, "description": "chat not found"}') as mock:
        try:
            _post_to(bn, mock)
            assert False
        except bn.NotifySendError as exc:
            assert exc.category == "PERMANENT"
    print("  notify OK — 200 ok:false -> PERMANENT")


def test_retry_after_http_date_parsed() -> None:
    _fresh()
    bc, bs, bn = _reload()
    from email.utils import format_datetime
    from datetime import datetime, timedelta, timezone
    future = format_datetime(datetime.now(timezone.utc) + timedelta(seconds=120))
    secs = bn._parse_retry_after(future)
    assert secs is not None and secs > 0
    print("  notify OK — Retry-After als HTTP-Datum geparst")


# --- HTTP-Härtung: Dedup-Key ------------------------------------------------
def test_notify_key_stable_for_same_reason() -> None:
    _fresh()
    bc, bs, bn = _reload()
    info = bs.EscalationInfo(loop_id="loop-x", trigger="stagnation", round="2")
    k1 = bn._notify_key(info)
    k2 = bn._notify_key(info)
    assert k1 == k2
    assert k1.startswith("loop-x:")
    print("  notify OK — notify_key stabil bei gleichem reason")


def test_notify_key_changes_with_reason() -> None:
    _fresh()
    bc, bs, bn = _reload()
    a = bs.EscalationInfo(loop_id="loop-x", trigger="stagnation", round="2")
    b = bs.EscalationInfo(loop_id="loop-x", trigger="max_rounds", round="4")
    assert bn._notify_key(a) != bn._notify_key(b)
    assert bn._notify_key(a).split(":")[0] == bn._notify_key(b).split(":")[0]
    print("  notify OK — notify_key ändert sich bei neuem reason, loop_id-Präfix bleibt")


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
    print("  notify OK — transient -> attempts.json, nicht sent.json")


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
    print("  notify OK — Retry nicht fällig -> kein Send")


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
    print("  notify OK — Retry fällig -> genau ein Versuch")


def test_transient_then_success_moves_to_sent() -> None:
    _fresh()
    bc, bs, bn = _reload()
    _write_escalation(bc, bs, loop_id="loop-t")
    bn.notify_new_escalations(send_fn=_FailSender(bn, "TRANSIENT", status=503))
    att = bn._load_attempts()
    key = next(iter(att))
    from datetime import datetime, timedelta
    att[key]["next_retry_at"] = (datetime.fromisoformat(bc.now_iso()) - timedelta(hours=1)).isoformat()
    bn._save_attempts(att)
    rec = _Recorder()
    sent, failed = bn.notify_new_escalations(send_fn=rec)
    assert sent and bn._load_attempts() == {}
    assert key in bn._load_sent()
    print("  notify OK — transient dann Erfolg -> wandert nach sent.json")


def test_permanent_failure_marks_failed() -> None:
    _fresh()
    bc, bs, bn = _reload()
    _write_escalation(bc, bs, loop_id="loop-p")
    sent, failed = bn.notify_new_escalations(send_fn=_FailSender(bn, "PERMANENT", status=401))
    att = bn._load_attempts()
    key = next(iter(att))
    assert att[key]["status"] == "permanent_failed"
    rec = _Recorder()
    s2, f2 = bn.notify_new_escalations(send_fn=rec)
    assert rec.calls == []
    print("  notify OK — permanent -> failed, kein Folgeversuch")


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
    print("  notify OK — MAX_TRANSIENT_ATTEMPTS -> permanent_failed")


def test_changed_reason_triggers_one_renotify() -> None:
    _fresh()
    bc, bs, bn = _reload()
    _write_escalation(bc, bs, loop_id="loop-r", trigger="stagnation", round_no="2")
    rec1 = _Recorder()
    bn.notify_new_escalations(send_fn=rec1)
    assert len(rec1.calls) == 1
    _write_escalation(bc, bs, loop_id="loop-r", trigger="max_rounds", round_no="4")
    rec2 = _Recorder()
    bn.notify_new_escalations(send_fn=rec2)
    assert len(rec2.calls) == 1   # genau eine Re-Notification
    rec3 = _Recorder()
    bn.notify_new_escalations(send_fn=rec3)
    assert rec3.calls == []
    print("  notify OK — geänderter reason -> genau eine Re-Notification")


# --- HTTP-Härtung: attempts.json + Backoff ----------------------------------
def test_attempts_roundtrip() -> None:
    _fresh()
    bc, bs, bn = _reload()
    bn._save_attempts({"k1": {"status": "transient_pending", "attempts": 1}})
    loaded = bn._load_attempts()
    assert loaded["k1"]["attempts"] == 1
    print("  notify OK — attempts.json roundtrip")


def test_load_attempts_defensive_when_missing() -> None:
    _fresh()
    bc, bs, bn = _reload()
    assert bn._load_attempts() == {}
    print("  notify OK — _load_attempts defensiv ({} bei fehlend)")


def test_next_retry_uses_retry_after_first() -> None:
    _fresh()
    bc, bs, bn = _reload()
    from datetime import datetime
    nxt = bn._compute_next_retry_at(attempts=1, retry_after=30)
    delta = (datetime.fromisoformat(nxt) - datetime.fromisoformat(bc.now_iso())).total_seconds()
    assert 25 <= delta <= 35  # ~30s, Retry-After gewinnt
    print("  notify OK — next_retry nutzt Retry-After zuerst")


def test_next_retry_exponential_without_header() -> None:
    _fresh()
    bc, bs, bn = _reload()
    from datetime import datetime
    nxt = bn._compute_next_retry_at(attempts=2, retry_after=None)
    delta = (datetime.fromisoformat(nxt) - datetime.fromisoformat(bc.now_iso())).total_seconds()
    # BACKOFF_BASE_SEC=60 * 2^(2-1) = 120
    assert 110 <= delta <= 130
    print("  notify OK — exp-Backoff ohne Header")


def test_retry_after_capped() -> None:
    _fresh()
    bc, bs, bn = _reload()
    from datetime import datetime
    nxt = bn._compute_next_retry_at(attempts=1, retry_after=999999)
    delta = (datetime.fromisoformat(nxt) - datetime.fromisoformat(bc.now_iso())).total_seconds()
    assert delta <= bn.RETRY_AFTER_CAP_SEC + 5
    print("  notify OK — absurder Retry-After gedeckelt")


def main() -> int:
    print("=== Eskalations-Notifier-Tests ===")
    tests = [
        test_new_escalation_triggers_send,
        test_already_sent_escalation_is_not_resent,
        test_multiple_new_escalations_each_sent_once,
        test_send_failure_does_not_mark_sent,
        test_partial_failure_isolates,
        test_not_configured_returns_2_and_marks_nothing,
        test_dry_run_sends_nothing_marks_nothing,
        test_message_format_contains_key_fields,
        test_message_escapes_markdown_injection,
        test_reconcile_drops_stale_entries,
        test_notifier_is_read_only_on_escalations,
        test_digest_summarizes_without_escalation,
        # HTTP-Härtung: Klassifikation
        test_4xx_classified_permanent,
        test_429_classified_transient_with_retry_after,
        test_5xx_classified_transient,
        test_network_error_classified_transient,
        test_200_ok_false_classified_permanent,
        test_retry_after_http_date_parsed,
        # HTTP-Härtung: Dedup-Key
        test_notify_key_stable_for_same_reason,
        test_notify_key_changes_with_reason,
        # HTTP-Härtung: attempts.json + Backoff
        test_attempts_roundtrip,
        test_load_attempts_defensive_when_missing,
        test_next_retry_uses_retry_after_first,
        test_next_retry_exponential_without_header,
        test_retry_after_capped,
        # HTTP-Härtung: Attempt-Lifecycle
        test_transient_failure_records_attempt_not_sent,
        test_retry_skipped_when_not_due,
        test_retry_attempted_when_due,
        test_transient_then_success_moves_to_sent,
        test_permanent_failure_marks_failed,
        test_max_attempts_becomes_permanent,
        test_changed_reason_triggers_one_renotify,
    ]
    failed = 0
    for t in tests:
        try:
            t()
        except AssertionError as exc:
            print(f"  FAIL {t.__name__}: {exc}"); failed += 1
        except Exception as exc:  # noqa: BLE001
            print(f"  ERROR {t.__name__}: {type(exc).__name__}: {exc}"); failed += 1
    print("=" * 48)
    print(f"{'FEHLER: '+str(failed) if failed else 'Alle'} {len(tests)-failed}/{len(tests)} ok")
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        import sys
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    raise SystemExit(main())
