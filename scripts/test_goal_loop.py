"""Goal-loop (Stage 3) unit tests. Fake runners only — fakes prove mechanics,
not contract (P006/P009). conftest.py isolates DUAL_BRIDGE_ROOT."""
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


# --- Task 1: parse_verdict escalate ---

def test_parse_verdict_escalate():
    from handoff_poll import parse_verdict
    v, _ = parse_verdict("some reasoning\nVERDICT: escalate")
    assert v == "escalate"


def test_parse_verdict_accepted_unchanged():
    from handoff_poll import parse_verdict
    assert parse_verdict("ok\nVERDICT: accepted")[0] == "accepted"


def test_parse_verdict_rejected_unchanged():
    from handoff_poll import parse_verdict
    assert parse_verdict("nope\nVERDICT: rejected")[0] == "rejected"


def test_parse_verdict_no_marker_fail_closed():
    from handoff_poll import parse_verdict
    assert parse_verdict("no marker here")[0] == "rejected"


def test_parse_verdict_unknown_token_fail_closed():
    from handoff_poll import parse_verdict
    # An unrecognised token must NOT become escalate — fail-closed to rejected.
    assert parse_verdict("x\nVERDICT: maybe")[0] == "rejected"


# --- Task 2: parse_seed ---

def test_parse_seed_splits_goal_and_criteria(monkeypatch, tmp_path):
    ld = _reload_as_a(monkeypatch, tmp_path)
    seed = (
        "## Ziel\n"
        "Add a greeting utility.\n\n"
        "## Done-Kriterien\n"
        "- [ ] function greet(name) returns 'Hello, <name>!'\n"
        "- [ ] has a docstring\n"
    )
    goal, criteria = ld.parse_seed(seed)
    assert goal == "Add a greeting utility."
    assert criteria == [
        "function greet(name) returns 'Hello, <name>!'",
        "has a docstring",
    ]


def test_parse_seed_missing_criteria_raises(monkeypatch, tmp_path):
    ld = _reload_as_a(monkeypatch, tmp_path)
    with __import__("pytest").raises(ValueError):
        ld.parse_seed("## Ziel\nonly a goal, no criteria block\n")


def test_parse_seed_empty_criteria_raises(monkeypatch, tmp_path):
    ld = _reload_as_a(monkeypatch, tmp_path)
    with __import__("pytest").raises(ValueError):
        ld.parse_seed("## Ziel\nG\n\n## Done-Kriterien\n")


# --- Task 3: write_goal_review_task ---

def test_write_goal_review_task_embeds_criteria_and_three_markers(
        monkeypatch, tmp_path):
    ld = _reload_as_a(monkeypatch, tmp_path)
    bc.ensure_dirs()
    task_id = ld.write_goal_review_task(
        loop_id="loop-x", round_no=0, goal="Add greet util",
        done_criteria=["greet(name) works", "has docstring"],
        loop_branch="bridge/loop-x", loop_commit="c1", diff="+def greet(): ...")
    lane = bc.send_lane()
    path = bc.lane_outbox(lane) / f"task-{task_id}.md"
    text = path.read_text(encoding="utf-8")
    assert "greet(name) works" in text
    assert "has docstring" in text
    assert "VERDICT: accepted" in text
    assert "VERDICT: rejected" in text
    assert "VERDICT: escalate" in text
    assert "+def greet(): ..." in text


# --- Task 4: scan_dangerous ---

def test_scan_dangerous_flags_force_push(monkeypatch, tmp_path):
    ld = _reload_as_a(monkeypatch, tmp_path)
    assert ld.scan_dangerous("git push --force origin main") is not None


def test_scan_dangerous_flags_drop_table(monkeypatch, tmp_path):
    ld = _reload_as_a(monkeypatch, tmp_path)
    assert ld.scan_dangerous("DROP TABLE users;") is not None


def test_scan_dangerous_flags_rm_rf(monkeypatch, tmp_path):
    ld = _reload_as_a(monkeypatch, tmp_path)
    assert ld.scan_dangerous("rm -rf /home/x") is not None


def test_scan_dangerous_flags_secret(monkeypatch, tmp_path):
    ld = _reload_as_a(monkeypatch, tmp_path)
    assert ld.scan_dangerous("token = 'sk-ant-abc123'") is not None


def test_scan_dangerous_clean_passes(monkeypatch, tmp_path):
    ld = _reload_as_a(monkeypatch, tmp_path)
    assert ld.scan_dangerous("def greet(name):\n    return f'Hi {name}'") is None
