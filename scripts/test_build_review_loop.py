"""Build↔review loop-mode unit tests (Stage-2b). Fake runners only — no real
codex/claude (fakes prove mechanics, not contract: P006/P009). conftest.py
isolates DUAL_BRIDGE_ROOT."""
from __future__ import annotations

import importlib

import bridge_common as bc


def _reload_as_a(monkeypatch, tmp_path):
    monkeypatch.setenv("DUAL_BRIDGE_ENDPOINT", "claude@laptop-a")
    importlib.reload(bc)
    import loop_driver
    importlib.reload(loop_driver)
    monkeypatch.setattr(loop_driver, "STATE_DIR", tmp_path)
    return loop_driver


def test_build_review_round_accepted(monkeypatch, tmp_path):
    """A builds (fake codex, new commit), B reviews (fake → accepted)."""
    ld = _reload_as_a(monkeypatch, tmp_path)
    from runners import RunnerResult

    def fake_build(auftrag, fm, workroot):
        return RunnerResult(status="done", antwort="built",
                            branch="bridge/loop-x", commit="c1",
                            changed_files=["a.py"])

    def fake_b_review(task_id):
        # Simulate B writing a review result with verdict accepted.
        lane = bc.send_lane()
        fm = {"created": bc.now_iso(), "from": "codex@laptop-b",
              "to": "claude@laptop-a", "status": "done", "task_id": task_id,
              "kind": "review", "verdict": "accepted", "verdict_reason": "lgtm"}
        bc.write_text_utf8(bc.lane_inbox(lane) / f"result-{task_id}.md",
                           bc.build_document(fm, "## Antwort\nVERDICT: accepted\n"))

    bc.ensure_dirs()
    out = ld._build_review_round(
        loop_id="loop-x", round_no=0, auftrag="build the thing",
        repo="r", base_branch="main", build_runner=fake_build,
        round_timeout=5, interval=1, b_tick=lambda tid: fake_b_review(tid))
    assert out["status"] == "done"
    assert out["verdict"] == "accepted"
    assert out["commit"] == "c1"
