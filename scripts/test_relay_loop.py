"""Relay-loop tests. Isoliert via conftest (tmp ROOT/STATE/LOCK, Endpoint A,
Runner re-registriert). Builder werden injiziert (build_runner_for) + b_tick-Hook,
kein echtes codex/claude."""
from __future__ import annotations

import importlib
import json
from pathlib import Path

import bridge_common as bc
import pytest


def test_parse_relay_seed_ziel_and_leitplanken():
    import loop_driver
    ziel, lp = loop_driver.parse_relay_seed(
        "## Ziel\nEine CLI-Toolsammlung.\n\n## Leitplanken\n- nur stdlib\n- [ ] mit Test\n")
    assert ziel == "Eine CLI-Toolsammlung."
    assert lp == ["nur stdlib", "mit Test"]


def test_parse_relay_seed_ziel_only():
    import loop_driver
    ziel, lp = loop_driver.parse_relay_seed("## Ziel\nFreie Richtung.\n")
    assert ziel == "Freie Richtung." and lp == []


def test_parse_relay_seed_missing_ziel_raises():
    import loop_driver
    with pytest.raises(ValueError):
        loop_driver.parse_relay_seed("## Leitplanken\n- x\n")


def test_other_builder_rotates_codex_and_claude():
    import loop_driver
    assert loop_driver._other_builder("codex") == "claude-build"
    assert loop_driver._other_builder("claude-build") == "codex"


def test_write_relay_review_task_fields_and_reviewer(tmp_path, monkeypatch):
    monkeypatch.setenv("DUAL_BRIDGE_ENDPOINT", "claude@laptop-a")
    monkeypatch.setenv("DUAL_BRIDGE_STATE", str(tmp_path))
    importlib.reload(bc)
    import loop_driver
    importlib.reload(loop_driver)
    tid = loop_driver.write_relay_review_task(
        "loop-r", 2, "Eine CLI-Toolsammlung.", ["nur stdlib"],
        "bridge/loop-r", "deadbeef", diff="--- a\n+++ b\n+x\n",
        reviewer="codex-review")
    doc = (bc.lane_outbox(bc.send_lane()) / f"task-{tid}.md").read_text(encoding="utf-8")
    fm, body = bc.parse_frontmatter(doc)
    assert fm["adapter"] == "codex-review"
    assert fm["kind"] == "review"
    # Body nennt Ziel + Leitplanken + die drei Marker, NICHT 'Done-Kriterien'.
    assert "Eine CLI-Toolsammlung." in body and "nur stdlib" in body
    assert "VERDICT: accepted" in body and "VERDICT: escalate" in body
    assert "Done-Kriterien" not in body
