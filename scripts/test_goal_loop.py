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


# --- Task 5: write/read escalation ---

def test_write_and_read_escalation_roundtrip(monkeypatch, tmp_path):
    ld = _reload_as_a(monkeypatch, tmp_path)
    path = ld.write_escalation(
        loop_id="loop-x", trigger="reviewer_requested", round_no=2,
        branch="bridge/loop-x", commit="c2", goal="Add greet util",
        criteria_status=[("greet works", True), ("naming convention", False)],
        reason="Reviewer: naming convention is ambiguous",
        question="Which naming style: snake_case or camelCase?",
        progress="greet() exists on bridge/loop-x@c2")
    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert "trigger: reviewer_requested" in text
    assert "Which naming style" in text
    assert "- [x] greet works" in text
    assert "- [ ] naming convention" in text

    meta = ld.read_escalation("loop-x")
    assert meta["trigger"] == "reviewer_requested"
    assert meta["loop_id"] == "loop-x"
    assert meta["branch"] == "bridge/loop-x"


def test_read_escalation_missing_returns_none(monkeypatch, tmp_path):
    ld = _reload_as_a(monkeypatch, tmp_path)
    assert ld.read_escalation("does-not-exist") is None


# --- Task 6: run_goal_loop accepted ---

def _fake_build_factory(commit_seq):
    """Return a fake build_runner that yields commits from commit_seq in order."""
    from runners import RunnerResult
    calls = {"i": 0}

    def fake_build(auftrag, fm, workroot):
        i = calls["i"]
        calls["i"] += 1
        commit = commit_seq[min(i, len(commit_seq) - 1)]
        return RunnerResult(status="done", antwort="built", branch=fm["branch"],
                            commit=commit, changed_files=["greet.py"],
                            diff="+def greet(name): return f'Hi {name}'")
    return fake_build


def _b_verdict(verdict, reason="r"):
    """Return a b_tick that writes a review result with the given verdict."""
    def tick(task_id):
        lane = bc.send_lane()
        fm = {"created": bc.now_iso(), "from": "claude@laptop-b",
              "to": "claude@laptop-a", "status": "done", "task_id": task_id,
              "kind": "review", "verdict": verdict, "verdict_reason": reason}
        bc.write_text_utf8(bc.lane_inbox(lane) / f"result-{task_id}.md",
                           bc.build_document(fm, f"## Antwort\nVERDICT: {verdict}\n"))
    return tick


def test_goal_loop_accepted_round_one(monkeypatch, tmp_path):
    ld = _reload_as_a(monkeypatch, tmp_path)
    bc.ensure_dirs()
    summary = ld.run_goal_loop(
        goal="Add greet util", done_criteria=["greet works"],
        repo="r", base_branch="main", max_rounds=3, round_timeout=5,
        interval=1, build_runner=_fake_build_factory(["c1"]),
        b_tick=_b_verdict("accepted"))
    assert summary["accepted"] is True
    assert summary["escalated"] is False
    assert summary["final_commit"] == "c1"
    assert summary["final_branch"].startswith("bridge/loop-")


# --- Task 7: rejected iterates, escalate escalates ---

def test_goal_loop_rejected_then_accepted_iterates(monkeypatch, tmp_path):
    ld = _reload_as_a(monkeypatch, tmp_path)
    bc.ensure_dirs()
    verdicts = iter(["rejected", "accepted"])

    def b_seq(task_id):
        v = next(verdicts)
        lane = bc.send_lane()
        fm = {"created": bc.now_iso(), "from": "claude@laptop-b",
              "to": "claude@laptop-a", "status": "done", "task_id": task_id,
              "kind": "review", "verdict": v, "verdict_reason": f"reason-{v}"}
        bc.write_text_utf8(bc.lane_inbox(lane) / f"result-{task_id}.md",
                           bc.build_document(fm, f"## Antwort\nVERDICT: {v}\n"))

    summary = ld.run_goal_loop(
        goal="G", done_criteria=["c"], repo="r", base_branch="main",
        max_rounds=3, round_timeout=5, interval=1,
        build_runner=_fake_build_factory(["c1", "c2"]), b_tick=b_seq)
    assert summary["accepted"] is True
    assert summary["rounds_done"] == 2


def test_goal_loop_reviewer_escalate(monkeypatch, tmp_path):
    ld = _reload_as_a(monkeypatch, tmp_path)
    bc.ensure_dirs()
    summary = ld.run_goal_loop(
        goal="G", done_criteria=["ambiguous one"], repo="r", base_branch="main",
        max_rounds=3, round_timeout=5, interval=1,
        build_runner=_fake_build_factory(["c1"]),
        b_tick=_b_verdict("escalate", reason="criterion is ambiguous"))
    assert summary["escalated"] is True
    assert summary["escalation_trigger"] == "reviewer_requested"
    assert summary["accepted"] is False
    meta = ld.read_escalation(summary["loop_id"])
    assert meta["trigger"] == "reviewer_requested"


# --- Task 8: stagnation + max-rounds ---

def test_goal_loop_stagnation_same_commit(monkeypatch, tmp_path):
    ld = _reload_as_a(monkeypatch, tmp_path)
    bc.ensure_dirs()
    # Same commit twice + always rejected → stagnation on round 2.
    summary = ld.run_goal_loop(
        goal="G", done_criteria=["c"], repo="r", base_branch="main",
        max_rounds=5, round_timeout=5, interval=1,
        build_runner=_fake_build_factory(["c1", "c1"]),
        b_tick=_b_verdict("rejected", reason="nope"))
    assert summary["escalated"] is True
    assert summary["escalation_trigger"] == "stagnation"


def test_goal_loop_stagnation_repeated_reason(monkeypatch, tmp_path):
    ld = _reload_as_a(monkeypatch, tmp_path)
    bc.ensure_dirs()
    # New commit each round but identical reject reason → stagnation.
    summary = ld.run_goal_loop(
        goal="G", done_criteria=["c"], repo="r", base_branch="main",
        max_rounds=5, round_timeout=5, interval=1,
        build_runner=_fake_build_factory(["c1", "c2", "c3"]),
        b_tick=_b_verdict("rejected", reason="same gap"))
    assert summary["escalated"] is True
    assert summary["escalation_trigger"] == "stagnation"


def test_goal_loop_max_rounds(monkeypatch, tmp_path):
    ld = _reload_as_a(monkeypatch, tmp_path)
    bc.ensure_dirs()
    # Distinct commits + distinct reasons → never stagnates, hits max-rounds.
    reasons = iter(["r1", "r2"])

    def b_distinct(task_id):
        lane = bc.send_lane()
        fm = {"created": bc.now_iso(), "from": "claude@laptop-b",
              "to": "claude@laptop-a", "status": "done", "task_id": task_id,
              "kind": "review", "verdict": "rejected",
              "verdict_reason": next(reasons)}
        bc.write_text_utf8(bc.lane_inbox(lane) / f"result-{task_id}.md",
                           bc.build_document(fm, "## Antwort\nVERDICT: rejected\n"))

    summary = ld.run_goal_loop(
        goal="G", done_criteria=["c"], repo="r", base_branch="main",
        max_rounds=2, round_timeout=5, interval=1,
        build_runner=_fake_build_factory(["c1", "c2"]), b_tick=b_distinct)
    assert summary["escalated"] is True
    assert summary["escalation_trigger"] == "max_rounds"
