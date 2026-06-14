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


# ---------------------------------------------------------------------------
# Task 5: _relay_round
# ---------------------------------------------------------------------------

from runners import RunnerResult


def _reload_as_a(monkeypatch, tmp_path):
    monkeypatch.setenv("DUAL_BRIDGE_ENDPOINT", "claude@laptop-a")
    monkeypatch.setenv("DUAL_BRIDGE_STATE", str(tmp_path))
    importlib.reload(bc)
    import loop_driver
    importlib.reload(loop_driver)
    return loop_driver


def _fake_builder(commit, diff="--- a\n+++ b\n+x\n"):
    def run(auftrag, fm, workroot):
        return RunnerResult(status="done", antwort="gebaut", branch=fm.get("branch"),
                            commit=commit, diff=diff)
    return run


def _verdict_b_tick(ld, verdict):
    """Return a b_tick that answers the just-written review task with `verdict`."""
    def tick(task_id):
        lane = bc.send_lane()
        # The review task is in our OUTbox (A->B). Write B's result into A's inbox.
        fm = {"created": bc.now_iso(), "schema_version": "2",
              "task_id": task_id, "status": "done", "kind": "review",
              "verdict": verdict, "verdict_reason": f"reason-{verdict}"}
        body = f"## Antwort\nok\nVERDICT: {verdict}\n"
        bc.write_text_utf8(bc.lane_inbox(lane) / f"result-{task_id}.md",
                           bc.build_document(fm, body))
    return tick


def test_relay_round_accepted_returns_verdict_and_commit(tmp_path, monkeypatch):
    ld = _reload_as_a(monkeypatch, tmp_path)
    out = ld._relay_round(
        loop_id="loop-r", round_no=0, ziel="Z", leitplanken=[],
        builder_adapter="codex", reviewer="claude",
        build_runner=_fake_builder("c0"), prev_commit=None,
        repo="r", base_branch="main", round_timeout=2, interval=1,
        b_tick=_verdict_b_tick(ld, "accepted"))
    assert out["status"] == "done"
    assert out["verdict"] == "accepted"
    assert out["commit"] == "c0"
    assert out["saturated"] is False


def test_relay_round_empty_diff_is_saturation(tmp_path, monkeypatch):
    ld = _reload_as_a(monkeypatch, tmp_path)
    out = ld._relay_round(
        loop_id="loop-r", round_no=1, ziel="Z", leitplanken=[],
        builder_adapter="codex", reviewer="claude",
        build_runner=_fake_builder("c0", diff=""), prev_commit="c0",
        repo="r", base_branch="main", round_timeout=2, interval=1,
        b_tick=lambda tid: None)
    assert out["saturated"] is True
    assert out["status"] == "done"


# ---------------------------------------------------------------------------
# Task 6: run_relay_loop
# ---------------------------------------------------------------------------

def _seq_b_tick(ld, verdicts):
    """b_tick that answers each successive review task with the next verdict."""
    state = {"i": 0}
    def tick(task_id):
        v = verdicts[min(state["i"], len(verdicts) - 1)]
        state["i"] += 1
        lane = bc.send_lane()
        fm = {"created": bc.now_iso(), "schema_version": "2", "task_id": task_id,
              "status": "done", "kind": "review", "verdict": v,
              "verdict_reason": f"reason-{v}"}
        bc.write_text_utf8(bc.lane_inbox(lane) / f"result-{task_id}.md",
                           bc.build_document(fm, f"## Antwort\nx\nVERDICT: {v}\n"))
    return tick


def _runner_map(commits):
    """build_runner_for: each call returns the next commit id, alternating none."""
    state = {"i": 0}
    def for_adapter(adapter):
        def run(auftrag, fm, workroot):
            c = commits[min(state["i"], len(commits) - 1)]
            state["i"] += 1
            return RunnerResult(status="done", antwort="b", branch=fm.get("branch"),
                                commit=c, diff="" if c is None else f"+{c}\n")
        return run
    return for_adapter


def test_relay_loop_rotates_builder_on_accept(tmp_path, monkeypatch):
    ld = _reload_as_a(monkeypatch, tmp_path)
    seen = []
    def for_adapter(adapter):
        seen.append(adapter)
        def run(auftrag, fm, workroot):
            return RunnerResult(status="done", antwort="b", branch=fm.get("branch"),
                                commit=f"c{len(seen)}", diff=f"+{len(seen)}\n")
        return run
    summary = ld.run_relay_loop(
        ziel="Z", leitplanken=[], repo="r", base_branch="main", max_rounds=2,
        round_timeout=2, interval=1, start_adapter="codex",
        build_runner_for=for_adapter, b_tick=_seq_b_tick(ld, ["accepted", "accepted"]))
    # Round 0 builder=codex, round 1 builder=claude-build (rotated on accept).
    assert seen[0] == "codex" and seen[1] == "claude-build"
    assert summary["rounds_done"] == 2


def test_relay_loop_no_rotation_on_reject(tmp_path, monkeypatch):
    ld = _reload_as_a(monkeypatch, tmp_path)
    seen = []
    def for_adapter(adapter):
        seen.append(adapter)
        def run(auftrag, fm, workroot):
            return RunnerResult(status="done", antwort="b", branch=fm.get("branch"),
                                commit=f"c{len(seen)}", diff=f"+{len(seen)}\n")
        return run
    ld.run_relay_loop(
        ziel="Z", leitplanken=[], repo="r", base_branch="main", max_rounds=2,
        round_timeout=2, interval=1, start_adapter="codex",
        build_runner_for=for_adapter, b_tick=_seq_b_tick(ld, ["rejected", "accepted"]))
    # reject keeps the same builder for round 1.
    assert seen[0] == "codex" and seen[1] == "codex"


def test_relay_loop_saturation_clean_stop(tmp_path, monkeypatch):
    ld = _reload_as_a(monkeypatch, tmp_path)
    summary = ld.run_relay_loop(
        ziel="Z", leitplanken=[], repo="r", base_branch="main", max_rounds=5,
        round_timeout=2, interval=1, start_adapter="codex",
        build_runner_for=_runner_map([None]),  # empty diff round 0
        b_tick=lambda tid: None)
    assert summary["saturated"] is True
    assert summary["escalated"] is False
    assert summary["accepted"] is True  # saturation = clean success


def test_relay_loop_escalate_writes_escalation(tmp_path, monkeypatch):
    ld = _reload_as_a(monkeypatch, tmp_path)
    summary = ld.run_relay_loop(
        ziel="Z", leitplanken=[], repo="r", base_branch="main", max_rounds=3,
        round_timeout=2, interval=1, start_adapter="codex",
        build_runner_for=_runner_map(["c0", "c1"]),
        b_tick=_seq_b_tick(ld, ["escalate"]))
    assert summary["escalated"] is True
    assert summary["escalation_trigger"] == "reviewer_requested"
    assert ld._escalation_path(summary["loop_id"]).exists()


# ---------------------------------------------------------------------------
# Task 7: CLI --mode relay-loop
# ---------------------------------------------------------------------------

def test_cli_relay_loop_requires_repo(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("DUAL_BRIDGE_ENDPOINT", "claude@laptop-a")
    monkeypatch.setenv("DUAL_BRIDGE_STATE", str(tmp_path))
    importlib.reload(bc)
    import loop_driver
    importlib.reload(loop_driver)
    rc = loop_driver.main(["--mode", "relay-loop", "--max-rounds", "2",
                           "--seed", "## Ziel\nZ\n"])
    assert rc == 2  # missing --repo
    assert "repo" in capsys.readouterr().out.lower()


def test_relay_loop_max_rounds_stops(tmp_path, monkeypatch):
    """All rounds accepted but never saturates -> stop at max_rounds, clean (not
    escalated, not aborted). Coverage gap flagged by the final Verifier."""
    ld = _reload_as_a(monkeypatch, tmp_path)
    summary = ld.run_relay_loop(
        ziel="Z", leitplanken=[], repo="r", base_branch="main", max_rounds=2,
        round_timeout=2, interval=1, start_adapter="codex",
        build_runner_for=_runner_map(["c0", "c1", "c2"]),
        b_tick=_seq_b_tick(ld, ["accepted", "accepted", "accepted"]))
    assert summary["rounds_done"] == 2
    assert summary["escalated"] is False
    assert summary["aborted"] is False
    assert summary["saturated"] is False


def test_relay_loop_build_error_aborts_not_clean(tmp_path, monkeypatch):
    """A build/review error must mark the loop `aborted` (-> CLI exit 1), NOT a
    clean stop and NOT an escalation (Codex-Verifier MAJOR 2026-06-14)."""
    ld = _reload_as_a(monkeypatch, tmp_path)

    def for_adapter(adapter):
        def run(auftrag, fm, workroot):
            return RunnerResult(status="error", error_text="codex kaputt")
        return run

    summary = ld.run_relay_loop(
        ziel="Z", leitplanken=[], repo="r", base_branch="main", max_rounds=3,
        round_timeout=2, interval=1, start_adapter="codex",
        build_runner_for=for_adapter, b_tick=lambda tid: None)
    assert summary["aborted"] is True
    assert summary["abort_reason"]
    assert summary["escalated"] is False
    assert summary["accepted"] is False
