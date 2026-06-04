"""Tests für die Transport-Abstraktion (bridge_transport.py).

Dual-runnable wie der Rest der Suite:
    python -m pytest scripts/test_bridge_transport.py
    python scripts/test_bridge_transport.py

Die Transport-Schicht abstrahiert, WOHER ein Bridge-Job kommt:
  - FileSource  → die heutige Lane/Datei-Welt (claim via os.rename), gegen ein
    isoliertes tmp-Root getestet (kein echtes Drive, Poison-Guard greift).
  - HttpSource  → der DCO-Job-Pull (GET /jobs/next, POST /jobs/<id>/result),
    getestet über einen INJIZIERTEN Fake-HTTP-Client — niemals echtes Netz.

get_source() wählt den Treiber per DUAL_BRIDGE_TRANSPORT (Default 'file'). Der
WorkItem-Vertrag (job_id, input_text) ist für beide Quellen identisch, damit der
Worker transport-agnostisch bleibt (gleicher injizierbarer-Caller-Trick wie bei
run_fn/send_fn im Notifier/Overnight).
"""
from __future__ import annotations

import importlib
import os
import tempfile
from pathlib import Path


def _fresh(endpoint: str = "claude@laptop-a") -> Path:
    root = Path(tempfile.mkdtemp(prefix="bridge-transport-"))
    os.environ["DUAL_BRIDGE_ROOT"] = str(root)
    os.environ["DUAL_BRIDGE_ENDPOINT"] = endpoint
    os.environ["DUAL_BRIDGE_STATE"] = str(root / "state")
    os.environ["DUAL_BRIDGE_DEVICE"] = "testdev"
    os.environ.pop("DUAL_BRIDGE_TRANSPORT", None)
    os.environ.pop("DCO_BRIDGE_URL", None)
    os.environ.pop("DCO_BRIDGE_TOKEN", None)
    return root


def _reload():
    import bridge_common as bc
    importlib.reload(bc)
    import bridge_transport as bt
    importlib.reload(bt)
    return bc, bt


def _write_open_task(bc, lane: str, task_id: str, payload: str) -> Path:
    """Lege eine offene Task-Datei in die Outbox einer Lane (wie handoff_write)."""
    bc.ensure_dirs()
    outbox = bc.lane_outbox(lane)
    outbox.mkdir(parents=True, exist_ok=True)
    fm = {
        "task_id": task_id,
        "status": "open",
        "adapter": "echo",
        "kind": "echo",
        "claimed_by": "",
        "claimed_at": "",
    }
    p = outbox / f"task-{task_id}.md"
    p.write_text(bc.build_document(fm, payload), encoding="utf-8")
    return p


class _FakeHttpClient:
    """Injizierbarer HTTP-Client: (method, path, json, headers) -> (status, body).

    Protokolliert jeden Aufruf und liefert vorprogrammierte Antworten. Niemals
    echtes Netz. Antworten werden als Liste je Pfad-Präfix vorgehalten und der
    Reihe nach abgearbeitet (FIFO)."""

    def __init__(self, responses: dict[str, list[tuple[int, dict | None]]]):
        self._responses = {k: list(v) for k, v in responses.items()}
        self.calls: list[dict] = []

    def __call__(self, method, path, json=None, headers=None):
        self.calls.append(
            {"method": method, "path": path, "json": json, "headers": headers}
        )
        for prefix, queue in self._responses.items():
            if path.startswith(prefix) and queue:
                return queue.pop(0)
        return (204, None)


# ---------------------------------------------------------------------------
# FileSource — gegen die echte (isolierte) Lane/Datei-Welt
# ---------------------------------------------------------------------------

def test_filesource_claims_open_task_as_workitem():
    """FileSource.claim_next() findet eine offene Task, claimt sie atomar und
    gibt ein WorkItem mit job_id == task_id und input_text == Payload zurück."""
    _fresh("codex@laptop-b")              # B empfängt auf seinen receive-lanes
    bc, bt = _reload()
    lane = bc.receive_lanes()[0]
    _write_open_task(bc, lane, "abc12345", "repo=https://x kind=echo\nTu etwas")

    src = bt.FileSource()
    item = src.claim_next()

    assert item is not None
    assert item.job_id == "abc12345"
    assert "Tu etwas" in item.input_text
    # Nach dem Claim liegt KEINE offene task-<id>.md mehr da (atomar umbenannt).
    assert not (bc.lane_outbox(lane) / "task-abc12345.md").exists()


def test_filesource_empty_returns_none():
    """Leere Lanes → claim_next() liefert None (kein Fehler)."""
    _fresh("codex@laptop-b")
    bc, bt = _reload()
    bc.ensure_dirs()
    src = bt.FileSource()
    assert src.claim_next() is None


def test_filesource_publish_result_writes_inbox():
    """publish_result() legt ein result-<id>.md in die Inbox der Quell-Lane."""
    _fresh("codex@laptop-b")
    bc, bt = _reload()
    lane = bc.receive_lanes()[0]
    _write_open_task(bc, lane, "def67890", "repo=https://x kind=echo\nbau")

    src = bt.FileSource()
    item = src.claim_next()
    assert item is not None
    src.publish_result(item, rc=0, result_payload={"summary": "fertig"},
                        result_status="accepted")

    result = bc.lane_inbox(lane) / f"result-{item.job_id}.md"
    assert result.exists()
    assert "fertig" in bc.read_text_utf8(result)


# ---------------------------------------------------------------------------
# HttpSource — gegen einen injizierten Fake-HTTP-Client (kein Netz)
# ---------------------------------------------------------------------------

def test_httpsource_204_means_no_job():
    """GET /jobs/next → 204 ⇒ claim_next() liefert None."""
    _fresh()
    _, bt = _reload()
    client = _FakeHttpClient({"/jobs/next": [(204, None)]})
    src = bt.HttpSource(base_url="http://127.0.0.1:8787", token="t0k",
                        worker_type="dual-bridge", client=client)
    assert src.claim_next() is None
    assert client.calls[0]["method"] == "GET"
    assert client.calls[0]["path"].startswith("/jobs/next")


def test_httpsource_200_maps_to_workitem_with_auth():
    """GET /jobs/next → 200 ⇒ WorkItem; Bearer-Token wird mitgeschickt."""
    _fresh()
    _, bt = _reload()
    body = {"job_id": "job-7", "input_text": "repo=https://x kind=implement\nziel",
            "worker_type": "dual-bridge", "trace_id": "tr1"}
    client = _FakeHttpClient({"/jobs/next": [(200, body)]})
    src = bt.HttpSource(base_url="http://127.0.0.1:8787", token="t0k",
                        worker_type="dual-bridge", client=client)
    item = src.claim_next()
    assert item is not None
    assert item.job_id == "job-7"
    assert "ziel" in item.input_text
    # worker_type als Query mitgegeben, Bearer-Header gesetzt.
    assert "worker_type=dual-bridge" in client.calls[0]["path"]
    assert client.calls[0]["headers"]["Authorization"] == "Bearer t0k"


def test_httpsource_publish_result_posts_json():
    """publish_result() postet rc/result_payload/result_status nach
    /jobs/<id>/result mit Bearer-Token."""
    _fresh()
    _, bt = _reload()
    client = _FakeHttpClient({"/jobs/job-7/result": [(200, {"status": "done"})]})
    src = bt.HttpSource(base_url="http://127.0.0.1:8787", token="t0k",
                        worker_type="dual-bridge", client=client)
    item = bt.WorkItem(job_id="job-7", input_text="x", raw={})
    src.publish_result(item, rc=0, result_payload={"branch": "b1"},
                       result_status="accepted")
    call = client.calls[-1]
    assert call["method"] == "POST"
    assert call["path"] == "/jobs/job-7/result"
    assert call["json"]["rc"] == 0
    assert call["json"]["result_status"] == "accepted"
    assert call["json"]["result_payload"]["branch"] == "b1"
    assert call["headers"]["Authorization"] == "Bearer t0k"


# ---------------------------------------------------------------------------
# get_source() — Treiberwahl per Env
# ---------------------------------------------------------------------------

def test_get_source_default_is_file():
    """Ohne DUAL_BRIDGE_TRANSPORT ⇒ FileSource (rückwärtskompatibel)."""
    _fresh()
    _, bt = _reload()
    assert isinstance(bt.get_source(), bt.FileSource)


def test_get_source_http_when_env_set():
    """DUAL_BRIDGE_TRANSPORT=http ⇒ HttpSource (URL/Token aus Env)."""
    _fresh()
    os.environ["DUAL_BRIDGE_TRANSPORT"] = "http"
    os.environ["DCO_BRIDGE_URL"] = "http://127.0.0.1:8787"
    os.environ["DCO_BRIDGE_TOKEN"] = "envtok"
    _, bt = _reload()
    src = bt.get_source()
    assert isinstance(src, bt.HttpSource)
    assert src.base_url == "http://127.0.0.1:8787"
    assert src.token == "envtok"


def test_get_source_http_without_url_raises():
    """DUAL_BRIDGE_TRANSPORT=http ohne DCO_BRIDGE_URL ⇒ klarer Fehler
    (fail-closed: kein stiller Fallback auf Datei)."""
    _fresh()
    os.environ["DUAL_BRIDGE_TRANSPORT"] = "http"
    _, bt = _reload()
    raised = False
    try:
        bt.get_source()
    except (ValueError, RuntimeError):
        raised = True
    assert raised


def test_get_source_unknown_transport_raises():
    """Unbekannter Transport-Wert ⇒ Fehler statt stiller Default."""
    _fresh()
    os.environ["DUAL_BRIDGE_TRANSPORT"] = "carrier-pigeon"
    _, bt = _reload()
    raised = False
    try:
        bt.get_source()
    except (ValueError, RuntimeError):
        raised = True
    assert raised


# ---------------------------------------------------------------------------
# _urllib_client — der echte HTTP-Pfad (war ungetestet / pragma: no cover).
# Live-Bug 2026-06-04: (1) Cloudflare blockte den nackten Python-urllib-UA mit
# 403 "error code: 1010"; (2) der Client crashte mit JSONDecodeError, weil er
# json.loads() blind auf den text/plain-Fehlerbody warf. Beide nur live sichtbar.
# Wir testen ohne echtes Netz via monkeypatch auf urllib.request.urlopen.
# ---------------------------------------------------------------------------

class _FakeResp:
    def __init__(self, code: int, raw: bytes):
        self._code = code
        self._raw = raw
    def getcode(self):
        return self._code
    def read(self):
        return self._raw
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False


def test_urllib_client_non_json_body_does_not_crash():
    """200 mit nicht-JSON-Body -> body=None statt JSONDecodeError."""
    _fresh()
    _, bt = _reload()
    captured = {}
    def fake_urlopen(req, timeout=None):
        captured["req"] = req
        return _FakeResp(200, b"error code: 1010")   # text/plain, kein JSON
    bt.urllib.request.urlopen = fake_urlopen
    status, body = bt._urllib_client("GET", "http://x/api/jobs/next", None, {})
    assert status == 200
    assert body is None                                # kein Crash


def test_urllib_client_http_error_non_json_body_does_not_crash():
    """HTTPError (403) mit text/plain-Body -> (403, None) statt Crash."""
    import urllib.error
    _fresh()
    _, bt = _reload()
    def fake_urlopen(req, timeout=None):
        raise urllib.error.HTTPError(
            url="http://x", code=403, msg="Forbidden", hdrs=None,
            fp=__import__("io").BytesIO(b"error code: 1010"))
    bt.urllib.request.urlopen = fake_urlopen
    status, body = bt._urllib_client("GET", "http://x/api/jobs/next", None, {})
    assert status == 403
    assert body is None


def test_urllib_client_sets_user_agent_against_cloudflare():
    """Cloudflare 1010 blockt den nackten urllib-UA — der Client MUSS einen
    expliziten User-Agent setzen."""
    _fresh()
    _, bt = _reload()
    captured = {}
    def fake_urlopen(req, timeout=None):
        captured["req"] = req
        return _FakeResp(204, b"")
    bt.urllib.request.urlopen = fake_urlopen
    bt._urllib_client("GET", "http://x/api/jobs/next", None, {})
    req = captured["req"]
    ua = req.get_header("User-agent")                  # urllib title-cases keys
    assert ua, "kein User-Agent gesetzt"
    assert "python-urllib" not in ua.lower()           # nicht der Default-UA


def test_urllib_client_valid_json_still_parses():
    """Regression: gültiger 200-JSON-Body wird weiter korrekt geparst."""
    _fresh()
    _, bt = _reload()
    def fake_urlopen(req, timeout=None):
        return _FakeResp(200, b'{"job_id": "j1", "input_text": "x"}')
    bt.urllib.request.urlopen = fake_urlopen
    status, body = bt._urllib_client("GET", "http://x/api/jobs/next", None, {})
    assert status == 200
    assert body == {"job_id": "j1", "input_text": "x"}


if __name__ == "__main__":
    import sys
    import pytest
    sys.exit(pytest.main([__file__, "-q"]))
