"""Stage-1 ping-pong loop tests. Isoliert, kein echtes Drive (conftest.py setzt
DUAL_BRIDGE_ROOT auf tmp + re-registriert Runner)."""
from __future__ import annotations

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
