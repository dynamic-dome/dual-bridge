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
