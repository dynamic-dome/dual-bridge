"""Stage-1 ping-pong loop tests. Isoliert, kein echtes Drive (conftest.py setzt
DUAL_BRIDGE_ROOT auf tmp + re-registriert Runner)."""
from __future__ import annotations

import json
from pathlib import Path

import bridge_common as bc
import runners


def test_increment_runner_adds_one():
    runner = runners.RUNNERS["increment"]
    res = runner(auftrag="3", fm={"payload": "3"}, workroot=None)
    assert res.status == "done"
    assert res.antwort.strip() == "4"


def test_increment_runner_rejects_non_numeric():
    runner = runners.RUNNERS["increment"]
    res = runner(auftrag="abc", fm={"payload": "abc"}, workroot=None)
    assert res.status == "error"
    assert res.error_text  # nicht-leer, kein stiller Default


def _write_task(lane: str, fm_extra: dict, body_auftrag: str) -> str:
    """Helper: write an open task into lane outbox, return task_id."""
    bc.ensure_dirs()
    task_id = bc.make_task_id()
    fm = {
        "created": bc.now_iso(), "schema_version": "2",
        "agent": "claude@laptop-a", "from": "claude@laptop-a",
        "to": "codex@laptop-b", "purpose": "handoff", "status": "open",
        "task_id": task_id, "kind": "echo", "adapter": "increment",
        "claimed_by": "", "claimed_at": "",
    }
    fm.update(fm_extra)
    body = f"## Auftrag\n{body_auftrag}\n\n## Ergebnis\n<offen>\n"
    bc.write_text_utf8(bc.lane_outbox(lane) / f"task-{task_id}.md",
                       bc.build_document(fm, body))
    return task_id


def test_loop_id_and_round_are_mirrored(monkeypatch):
    """loop_id + round müssen vom Task-FM ins Result-FM gespiegelt werden."""
    monkeypatch.setenv("DUAL_BRIDGE_ENDPOINT", "codex@laptop-b")
    import importlib
    importlib.reload(bc)  # re-resolve endpoint
    import handoff_poll
    importlib.reload(handoff_poll)
    lane = "A-to-B"
    task_id = _write_task(lane, {"loop_id": "loop-xyz", "round": "2",
                                 "payload": "5"}, "5")
    handoff_poll.poll_once()
    result = bc.lane_inbox(lane) / f"result-{task_id}.md"
    assert result.exists()
    fm, _ = bc.parse_frontmatter(bc.read_text_utf8(result))
    assert fm.get("loop_id") == "loop-xyz"
    assert fm.get("round") == "2"


def test_loop_payload_is_runner_output(monkeypatch):
    """Result-FM payload muss der vom increment-Runner berechnete Wert sein."""
    monkeypatch.setenv("DUAL_BRIDGE_ENDPOINT", "codex@laptop-b")
    import importlib
    importlib.reload(bc)
    import handoff_poll
    importlib.reload(handoff_poll)
    lane = "A-to-B"
    task_id = _write_task(lane, {"loop_id": "loop-pay", "round": "0",
                                 "payload": "5"}, "5")
    handoff_poll.poll_once()
    result = bc.lane_inbox(lane) / f"result-{task_id}.md"
    assert result.exists()
    fm, _ = bc.parse_frontmatter(bc.read_text_utf8(result))
    assert fm.get("payload") == "6"   # 5 + 1


def test_non_loop_task_has_no_payload(monkeypatch):
    """Ein Task ohne loop_id bekommt KEIN payload-Feld ins Result (Bridge unberührt)."""
    monkeypatch.setenv("DUAL_BRIDGE_ENDPOINT", "codex@laptop-b")
    import importlib
    importlib.reload(bc)
    import handoff_poll
    importlib.reload(handoff_poll)
    lane = "A-to-B"
    task_id = _write_task(lane, {"adapter": "echo"}, "hallo")
    handoff_poll.poll_once()
    result = bc.lane_inbox(lane) / f"result-{task_id}.md"
    assert result.exists()
    fm, _ = bc.parse_frontmatter(bc.read_text_utf8(result))
    assert "payload" not in fm


def test_loop_task_with_runner_error_has_no_payload(monkeypatch):
    """Ein Loop-Task, dessen Runner fehlschlägt (status:error), bekommt KEIN payload."""
    monkeypatch.setenv("DUAL_BRIDGE_ENDPOINT", "codex@laptop-b")
    import importlib
    importlib.reload(bc)
    import handoff_poll
    importlib.reload(handoff_poll)
    lane = "A-to-B"
    # increment runner errors on a non-numeric payload
    task_id = _write_task(lane, {"loop_id": "loop-err", "round": "0",
                                 "payload": "abc"}, "abc")
    handoff_poll.poll_once()
    result = bc.lane_inbox(lane) / f"result-{task_id}.md"
    assert result.exists()
    fm, _ = bc.parse_frontmatter(bc.read_text_utf8(result))
    assert fm.get("status") == "error"
    assert "payload" not in fm


def test_driver_writes_loop_task(monkeypatch):
    """write_round_task schreibt einen Task mit korrektem Loop-Umschlag."""
    monkeypatch.setenv("DUAL_BRIDGE_ENDPOINT", "claude@laptop-a")
    import importlib
    importlib.reload(bc)
    import loop_driver
    importlib.reload(loop_driver)
    task_id = loop_driver.write_round_task(
        loop_id="loop-w", round_no=0, payload="7", adapter="increment")
    lane = bc.send_lane()  # A-to-B
    task = bc.lane_outbox(lane) / f"task-{task_id}.md"
    assert task.exists()
    fm, _ = bc.parse_frontmatter(bc.read_text_utf8(task))
    assert fm["loop_id"] == "loop-w"
    assert fm["round"] == "0"
    assert fm["payload"] == "7"
    assert fm["adapter"] == "increment"
    assert fm["status"] == "open"
    assert fm["task_id"] == task_id
    assert fm["from"] == "claude@laptop-a"
    assert fm["to"] == "codex@laptop-b"


def _write_result(lane: str, task_id: str, fm_extra: dict, status="done"):
    fm = {"created": bc.now_iso(), "agent": "codex@laptop-b",
          "from": "codex@laptop-b", "to": "claude@laptop-a",
          "purpose": "handoff", "status": status, "task_id": task_id,
          "kind": "echo", "adapter": "increment",
          "replies_to": f"task-{task_id}.md"}
    fm.update(fm_extra)
    bc.write_text_utf8(bc.lane_inbox(lane) / f"result-{task_id}.md",
                       bc.build_document(fm, "## Antwort\nok\n"))


def test_wait_for_result_returns_fm(monkeypatch):
    monkeypatch.setenv("DUAL_BRIDGE_ENDPOINT", "claude@laptop-a")
    import importlib
    importlib.reload(bc)
    import loop_driver
    importlib.reload(loop_driver)
    bc.ensure_dirs()
    lane = bc.send_lane()  # A-to-B — B writes results into the send lane's inbox
    tid = bc.make_task_id()
    _write_result(lane, tid, {"payload": "9"})
    fm = loop_driver.wait_for_result(tid, timeout=5, interval=1)
    assert fm is not None
    assert fm["payload"] == "9"
    assert not (bc.lane_inbox(lane) / f"result-{tid}.md").exists()
    assert (bc.lane_processed(lane) / f"result-{tid}.md").exists()


def test_wait_for_result_times_out(monkeypatch):
    monkeypatch.setenv("DUAL_BRIDGE_ENDPOINT", "claude@laptop-a")
    import importlib
    importlib.reload(bc)
    import loop_driver
    importlib.reload(loop_driver)
    bc.ensure_dirs()
    fm = loop_driver.wait_for_result("20260101-000000-000000-0-aaaa",
                                     timeout=2, interval=1)
    assert fm is None


def test_wait_for_result_ignores_conflict_copy(monkeypatch):
    monkeypatch.setenv("DUAL_BRIDGE_ENDPOINT", "claude@laptop-a")
    import importlib
    importlib.reload(bc)
    import loop_driver
    importlib.reload(loop_driver)
    bc.ensure_dirs()
    lane = bc.send_lane()  # A-to-B — B writes results into the send lane's inbox
    tid = bc.make_task_id()
    # A Google-Drive conflict copy of the result must be ignored.
    fm = {"created": bc.now_iso(), "from": "codex@laptop-b",
          "to": "claude@laptop-a", "status": "done", "task_id": tid,
          "payload": "9"}
    bc.write_text_utf8(bc.lane_inbox(lane) / f"result-{tid} (1).md",
                       bc.build_document(fm, "## Antwort\nok\n"))
    assert loop_driver.wait_for_result(tid, timeout=2, interval=1) is None


def test_wait_for_result_ignores_half_written(monkeypatch):
    """Eine halb-geschriebene Result-Datei (FM ohne task_id) ist KEIN Hit."""
    monkeypatch.setenv("DUAL_BRIDGE_ENDPOINT", "claude@laptop-a")
    import importlib
    importlib.reload(bc)
    import loop_driver
    importlib.reload(loop_driver)
    bc.ensure_dirs()
    lane = bc.send_lane()  # A-to-B — B writes results into the send lane's inbox
    tid = bc.make_task_id()
    # No closing fence / no task_id -> parse_frontmatter yields {} or no task_id.
    bc.write_text_utf8(bc.lane_inbox(lane) / f"result-{tid}.md",
                       "---\ncreated: x\n")  # truncated, no closing ---
    assert loop_driver.wait_for_result(tid, timeout=2, interval=1) is None


def test_append_state_writes_jsonl(tmp_path, monkeypatch):
    import importlib
    import loop_driver
    importlib.reload(loop_driver)
    monkeypatch.setattr(loop_driver, "STATE_DIR", tmp_path)
    loop_driver.append_state("loop-s", {"round": 0, "side": "B",
                                        "payload_in": "1", "payload_out": "2",
                                        "task_id": "t", "status": "done"})
    f = tmp_path / "LOOP-loop-s.jsonl"
    assert f.exists()
    line = json.loads(f.read_text(encoding="utf-8").strip())
    assert line["round"] == 0 and line["payload_out"] == "2"
    assert "ts" in line  # Zeitstempel wird ergaenzt


def _run_b_tick(task_id=None):
    """Simuliert B: ein Poll-Durchlauf, verarbeitet offene A->B-Tasks.
    Laeuft als B-Endpoint, danach Endpoint zurueck auf A.

    Nimmt task_id entgegen (Hook-Signatur seit loop_driver b_tick(task_id),
    Upstream 3fc99ea) — hier ungenutzt, da der Tick alle offenen Tasks pollt."""
    import importlib, os
    try:
        os.environ["DUAL_BRIDGE_ENDPOINT"] = "codex@laptop-b"
        importlib.reload(bc)
        import handoff_poll
        importlib.reload(handoff_poll)
        handoff_poll.poll_once()
    finally:
        os.environ["DUAL_BRIDGE_ENDPOINT"] = "claude@laptop-a"
        importlib.reload(bc)


def test_run_loop_max_rounds(tmp_path, monkeypatch):
    """3 Runden: A+B inkrementieren je Runde -> payload = seed + 2*rounds.
    jsonl hat genau `rounds` Zeilen."""
    monkeypatch.setenv("DUAL_BRIDGE_ENDPOINT", "claude@laptop-a")
    import importlib
    importlib.reload(bc)
    import loop_driver
    importlib.reload(loop_driver)
    monkeypatch.setattr(loop_driver, "STATE_DIR", tmp_path)
    summary = loop_driver.run_loop(
        seed="0", max_rounds=3, adapter="increment",
        round_timeout=5, interval=1, b_tick=_run_b_tick)
    assert summary["rounds_done"] == 3
    assert summary["final_payload"] == "6"   # 0 + 2*3
    assert summary["aborted"] is False
    jsonl = tmp_path / f"LOOP-{summary['loop_id']}.jsonl"
    assert len(jsonl.read_text(encoding="utf-8").strip().splitlines()) == 3


def test_run_loop_aborts_on_timeout(tmp_path, monkeypatch):
    """Kein B-Tick -> B-Result kommt nie -> sauberer Abbruch nach Timeout."""
    monkeypatch.setenv("DUAL_BRIDGE_ENDPOINT", "claude@laptop-a")
    import importlib
    importlib.reload(bc)
    import loop_driver
    importlib.reload(loop_driver)
    monkeypatch.setattr(loop_driver, "STATE_DIR", tmp_path)
    summary = loop_driver.run_loop(
        seed="0", max_rounds=3, adapter="increment",
        round_timeout=2, interval=1, b_tick=lambda task_id=None: None)
    assert summary["aborted"] is True
    assert summary["rounds_done"] == 0
    assert summary["open_task_id"]  # offener Task wird gemeldet
    import json as _json
    jsonl = tmp_path / f"LOOP-{summary['loop_id']}.jsonl"
    assert jsonl.exists()
    rows = [_json.loads(l) for l in jsonl.read_text(encoding="utf-8").strip().splitlines()]
    assert len(rows) == 1
    assert rows[0]["status"] == "timeout"
    assert rows[0]["task_id"] == summary["open_task_id"]


def test_run_loop_aborts_on_b_error(tmp_path, monkeypatch):
    """B liefert status:error -> fail-fast Abbruch, payload nicht verschleppt."""
    monkeypatch.setenv("DUAL_BRIDGE_ENDPOINT", "claude@laptop-a")
    import importlib
    importlib.reload(bc)
    import loop_driver
    importlib.reload(loop_driver)
    monkeypatch.setattr(loop_driver, "STATE_DIR", tmp_path)

    def _b_error_tick(task_id=None):
        """B claimt den offenen A->B-Task und schreibt ein error-Result.
        task_id wird per Hook-Vertrag übergeben (loop_driver b_tick(task_id))."""
        send = bc.send_lane()
        for task in bc.lane_outbox(send).glob("task-*.md"):
            if ".claimed-" in task.name:
                continue
            fm, _ = bc.parse_frontmatter(bc.read_text_utf8(task))
            tid = fm["task_id"]
            # B writes results into the lane inbox it polled (A-to-B/inbox/).
            # wait_for_result polls bc.send_lane() = A-to-B, so write there.
            result_lane = bc.send_lane()
            _write_result(result_lane, tid, {"loop_id": fm.get("loop_id", "")},
                          status="error")

    summary = loop_driver.run_loop(
        seed="0", max_rounds=3, adapter="increment",
        round_timeout=5, interval=1, b_tick=_b_error_tick)
    assert summary["aborted"] is True
    assert summary["rounds_done"] == 0
    assert "error" in summary["abort_reason"].lower()


def test_run_loop_a_error_leaves_jsonl_trace(tmp_path, monkeypatch):
    """Ein A-seitiger Runner-Fehler (non-numerischer seed) bricht ab UND
    hinterlaesst eine JSONL-Zeile (side:A, status:error) fuer die Post-Mortem."""
    monkeypatch.setenv("DUAL_BRIDGE_ENDPOINT", "claude@laptop-a")
    import importlib
    importlib.reload(bc)
    import loop_driver
    importlib.reload(loop_driver)
    monkeypatch.setattr(loop_driver, "STATE_DIR", tmp_path)
    summary = loop_driver.run_loop(
        seed="not-a-number", max_rounds=3, adapter="increment",
        round_timeout=2, interval=1, b_tick=lambda task_id=None: None)
    assert summary["aborted"] is True
    assert summary["rounds_done"] == 0
    jsonl = tmp_path / f"LOOP-{summary['loop_id']}.jsonl"
    assert jsonl.exists()
    import json as _json
    rows = [_json.loads(l) for l in jsonl.read_text(encoding="utf-8").strip().splitlines()]
    assert len(rows) == 1
    assert rows[0]["side"] == "A"
    assert rows[0]["status"] == "error"
