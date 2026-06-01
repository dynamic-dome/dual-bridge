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
