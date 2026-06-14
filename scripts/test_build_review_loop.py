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
    monkeypatch.setenv("DUAL_BRIDGE_STATE", str(tmp_path))
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


def test_loop_accepted_round_one(monkeypatch, tmp_path):
    """accepted in round 0 → loop ends, success, final_commit set."""
    ld = _reload_as_a(monkeypatch, tmp_path)
    from runners import RunnerResult

    def fake_build(auftrag, fm, workroot):
        return RunnerResult(status="done", antwort="b", branch=fm["branch"],
                            commit="c1", changed_files=["a.py"])

    def b_accept(task_id):
        lane = bc.send_lane()
        fm = {"created": bc.now_iso(), "from": "codex@laptop-b",
              "to": "claude@laptop-a", "status": "done", "task_id": task_id,
              "kind": "review", "verdict": "accepted", "verdict_reason": "ok"}
        bc.write_text_utf8(bc.lane_inbox(lane) / f"result-{task_id}.md",
                           bc.build_document(fm, "VERDICT: accepted\n"))

    bc.ensure_dirs()
    summary = ld.run_build_review_loop(
        auftrag="build", repo="r", base_branch="main", max_rounds=5,
        round_timeout=5, interval=1, build_runner=fake_build, b_tick=b_accept)
    assert summary["accepted"] is True
    assert summary["aborted"] is False
    assert summary["rounds_done"] == 1
    assert summary["final_commit"] == "c1"


def test_loop_rejected_then_accepted(monkeypatch, tmp_path):
    """round 0 rejected → A rebuilds with the gaps as the new auftrag →
    round 1 accepted. The rejected reason must reach round 1's build."""
    ld = _reload_as_a(monkeypatch, tmp_path)
    from runners import RunnerResult

    seen_auftrags = []
    commits = iter(["c1", "c2"])

    def fake_build(auftrag, fm, workroot):
        seen_auftrags.append(auftrag)
        return RunnerResult(status="done", antwort="b", branch=fm["branch"],
                            commit=next(commits), changed_files=["a.py"])

    verdicts = iter([("rejected", "missing tests"), ("accepted", "ok now")])

    def b_tick(task_id):
        verdict, reason = next(verdicts)
        lane = bc.send_lane()
        fm = {"created": bc.now_iso(), "from": "codex@laptop-b",
              "to": "claude@laptop-a", "status": "done", "task_id": task_id,
              "kind": "review", "verdict": verdict, "verdict_reason": reason}
        bc.write_text_utf8(bc.lane_inbox(lane) / f"result-{task_id}.md",
                           bc.build_document(fm, f"VERDICT: {verdict}\n"))

    bc.ensure_dirs()
    summary = ld.run_build_review_loop(
        auftrag="build", repo="r", base_branch="main", max_rounds=5,
        round_timeout=5, interval=1, build_runner=fake_build, b_tick=b_tick)
    assert summary["accepted"] is True
    assert summary["rounds_done"] == 2
    # Round 1's auftrag must carry the round-0 rejection reason.
    assert "missing tests" in seen_auftrags[1]


def test_loop_max_rounds_without_accept(monkeypatch, tmp_path):
    """Always rejected, distinct reasons → stops at max_rounds, not accepted."""
    ld = _reload_as_a(monkeypatch, tmp_path)
    from runners import RunnerResult

    n = iter(range(100))
    def fake_build(auftrag, fm, workroot):
        return RunnerResult(status="done", antwort="b", branch=fm["branch"],
                            commit=f"c{next(n)}", changed_files=["a.py"])

    r = iter(range(100))
    def b_reject(task_id):
        lane = bc.send_lane()
        reason = f"still wrong {next(r)}"  # distinct each round → no stagnation
        fm = {"created": bc.now_iso(), "from": "codex@laptop-b",
              "to": "claude@laptop-a", "status": "done", "task_id": task_id,
              "kind": "review", "verdict": "rejected", "verdict_reason": reason}
        bc.write_text_utf8(bc.lane_inbox(lane) / f"result-{task_id}.md",
                           bc.build_document(fm, "VERDICT: rejected\n"))

    bc.ensure_dirs()
    summary = ld.run_build_review_loop(
        auftrag="build", repo="r", base_branch="main", max_rounds=2,
        round_timeout=5, interval=1, build_runner=fake_build, b_tick=b_reject)
    assert summary["accepted"] is False
    assert summary["aborted"] is True
    assert summary["rounds_done"] == 2
    assert "max-rounds" in summary["abort_reason"]


def test_loop_aborts_on_unchanged_commit(monkeypatch, tmp_path):
    """Same commit hash two rounds running → early 'stagniert' abort."""
    ld = _reload_as_a(monkeypatch, tmp_path)
    from runners import RunnerResult

    def fake_build(auftrag, fm, workroot):
        return RunnerResult(status="done", antwort="b", branch=fm["branch"],
                            commit="SAME", changed_files=[])  # never changes

    def b_reject(task_id):
        lane = bc.send_lane()
        fm = {"created": bc.now_iso(), "from": "codex@laptop-b",
              "to": "claude@laptop-a", "status": "done", "task_id": task_id,
              "kind": "review", "verdict": "rejected", "verdict_reason": f"r{task_id[-2:]}"}
        bc.write_text_utf8(bc.lane_inbox(lane) / f"result-{task_id}.md",
                           bc.build_document(fm, "VERDICT: rejected\n"))

    bc.ensure_dirs()
    summary = ld.run_build_review_loop(
        auftrag="build", repo="r", base_branch="main", max_rounds=5,
        round_timeout=5, interval=1, build_runner=fake_build, b_tick=b_reject)
    assert summary["accepted"] is False
    assert summary["aborted"] is True
    assert "stagn" in summary["abort_reason"].lower()
    assert summary["rounds_done"] == 2  # round 0 built, round 1 same commit → abort


def test_loop_aborts_on_repeated_reason(monkeypatch, tmp_path):
    """Identical verdict_reason two rounds running → early 'stagniert' abort."""
    ld = _reload_as_a(monkeypatch, tmp_path)
    from runners import RunnerResult

    n = iter(range(100))
    def fake_build(auftrag, fm, workroot):
        return RunnerResult(status="done", antwort="b", branch=fm["branch"],
                            commit=f"c{next(n)}", changed_files=["a.py"])

    def b_reject_same(task_id):
        lane = bc.send_lane()
        fm = {"created": bc.now_iso(), "from": "codex@laptop-b",
              "to": "claude@laptop-a", "status": "done", "task_id": task_id,
              "kind": "review", "verdict": "rejected",
              "verdict_reason": "always the same"}
        bc.write_text_utf8(bc.lane_inbox(lane) / f"result-{task_id}.md",
                           bc.build_document(fm, "VERDICT: rejected\n"))

    bc.ensure_dirs()
    summary = ld.run_build_review_loop(
        auftrag="build", repo="r", base_branch="main", max_rounds=5,
        round_timeout=5, interval=1, build_runner=fake_build, b_tick=b_reject_same)
    assert summary["aborted"] is True
    assert "stagn" in summary["abort_reason"].lower()
    assert summary["rounds_done"] == 2


def test_loop_missing_verdict_is_not_accepted(monkeypatch, tmp_path):
    """A result with no verdict field (None) must NOT count as accepted."""
    ld = _reload_as_a(monkeypatch, tmp_path)
    from runners import RunnerResult

    n = iter(range(100))
    def fake_build(auftrag, fm, workroot):
        return RunnerResult(status="done", antwort="b", branch=fm["branch"],
                            commit=f"c{next(n)}", changed_files=["a.py"])

    def b_no_verdict(task_id):
        lane = bc.send_lane()
        fm = {"created": bc.now_iso(), "from": "codex@laptop-b",
              "to": "claude@laptop-a", "status": "done", "task_id": task_id,
              "kind": "review"}  # NO verdict key
        bc.write_text_utf8(bc.lane_inbox(lane) / f"result-{task_id}.md",
                           bc.build_document(fm, "no marker here\n"))

    bc.ensure_dirs()
    summary = ld.run_build_review_loop(
        auftrag="build", repo="r", base_branch="main", max_rounds=2,
        round_timeout=5, interval=1, build_runner=fake_build, b_tick=b_no_verdict)
    assert summary["accepted"] is False  # None verdict never accepts


def test_main_build_review_requires_repo(monkeypatch, tmp_path, capsys):
    """--mode build-review without --repo exits non-zero with a clear message."""
    ld = _reload_as_a(monkeypatch, tmp_path)
    # Singleton lock would otherwise interfere; point it at tmp.
    monkeypatch.setattr(ld.bc, "default_lock_path",
                        lambda: tmp_path / "x.lock")
    rc = ld.main(["--mode", "build-review", "--max-rounds", "1",
                  "--seed", "build it"])
    assert rc == 2  # usage error (missing --repo), distinct from 1 (not accepted)
    out = capsys.readouterr().out
    assert "repo" in out.lower()


def test_review_task_embeds_diff(monkeypatch, tmp_path):
    """write_review_task embeds the build diff in the task body (no 'fetch')."""
    ld = _reload_as_a(monkeypatch, tmp_path)
    bc.ensure_dirs()
    tid = ld.write_review_task(loop_id="loop-d", round_no=0, auftrag="do x",
                               loop_branch="bridge/loop-d", loop_commit="c1",
                               diff="--- a\n+++ b\n+added\n")
    lane = bc.send_lane()
    body = bc.read_text_utf8(bc.lane_outbox(lane) / f"task-{tid}.md")
    assert "+added" in body
    assert "```diff" in body
    assert "KEINE Tools" in body


def test_review_prompt_format_parses_as_accepted():
    """The format the review prompt now demands (reason line, then a bare
    'VERDICT: accepted' last line) must parse as accepted via parse_verdict.
    Closes the live-found seam: a single-line 'VERDICT: accepted - reason' did
    NOT parse (fail-closed to rejected). Regression guard for that bug."""
    import handoff_poll
    # Compliant format (separate marker line, bare token) → accepted.
    good = ("Der Diff ergaenzt einen Docstring wie verlangt, keine Code-Aenderung.\n"
            "VERDICT: accepted")
    assert handoff_poll.parse_verdict(good) == ("accepted", "")
    # The OLD anti-format (reason on the verdict line) does NOT parse → fail-closed.
    bad = "VERDICT: accepted — sieht gut aus"
    verdict, reason = handoff_poll.parse_verdict(bad)
    assert verdict == "rejected" and "unrecognised" in reason
