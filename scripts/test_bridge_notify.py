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
    assert sent == ["loop-aaaa"], sent
    assert failed == [], failed
    saved = bn._load_sent()
    assert "loop-aaaa" in saved, saved
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
    assert set(sent) == {"loop-a", "loop-b", "loop-c"}, sent
    assert set(bn._load_sent()) >= {"loop-a", "loop-b", "loop-c"}
    print("  notify OK — drei neue -> drei Sends, alle markiert")


# --- (4) Sendefehler markiert NICHTS ----------------------------------------
def test_send_failure_does_not_mark_sent() -> None:
    _fresh()
    bc, bs, bn = _reload()
    _write_escalation(bc, bs, loop_id="loop-aaaa")
    rec = _Recorder(fail_for={"loop-aaaa"})
    sent, failed = bn.notify_new_escalations(send_fn=rec)
    assert sent == [], sent
    assert failed == ["loop-aaaa"], failed
    assert "loop-aaaa" not in bn._load_sent(), "Fehlschlag darf nicht markieren"
    print("  notify OK — Sendefehler -> nicht markiert, beim nächsten Lauf erneut")


# --- (5) Partial-Failure isoliert -------------------------------------------
def test_partial_failure_isolates() -> None:
    _fresh()
    bc, bs, bn = _reload()
    for lid in ("loop-a", "loop-b", "loop-c"):
        _write_escalation(bc, bs, loop_id=lid)
    rec = _Recorder(fail_for={"loop-b"})
    sent, failed = bn.notify_new_escalations(send_fn=rec)
    assert set(sent) == {"loop-a", "loop-c"}, sent
    assert failed == ["loop-b"], failed
    saved = bn._load_sent()
    assert "loop-a" in saved and "loop-c" in saved and "loop-b" not in saved, saved
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
