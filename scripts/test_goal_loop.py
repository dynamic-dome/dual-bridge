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


def _a_live_foreign_pid():
    """A currently-alive PID that is NOT this process, or None if none found.

    Used to simulate the recycled-but-live foreign lock holder from DCO #7728.
    bc._pid_alive is the same liveness oracle main() uses, so the chosen PID is
    guaranteed to read as 'live' for acquire_singleton_lock."""
    import os as _os
    for cand in (_os.getppid(), 4):  # parent process, then a low system pid
        if cand and cand != _os.getpid() and bc._pid_alive(cand):
            return cand
    if _os.name == "nt":
        import csv
        import io
        import subprocess
        try:
            out = subprocess.run(
                ["tasklist", "/NH", "/FO", "CSV"],
                capture_output=True, text=True, encoding="oem",
            ).stdout
        except OSError:
            return None
        for row in csv.reader(io.StringIO(out)):
            if len(row) > 1 and row[1].strip().isdigit():
                pid = int(row[1])
                if pid > 4 and pid != _os.getpid() and bc._pid_alive(pid):
                    return pid
    return None


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


# --- Task 4b: parametrised CRUD DELETE FROM must NOT escalate (False-Positive
# 2026-06-07: the reminders-v2 goal-loop escalated in round 0 because a legit
# `DELETE FROM reminders WHERE id = ?` CRUD method matched the bare DELETE-FROM
# guard. A row-targeted DELETE with a bound placeholder is the OPPOSITE of the
# destructive mass-delete the guard exists to stop). ---

def test_scan_dangerous_allows_parametrised_crud_delete(monkeypatch, tmp_path):
    ld = _reload_as_a(monkeypatch, tmp_path)
    # qmark, named and pyformat placeholders are all legitimate row-targeted CRUD.
    assert ld.scan_dangerous("DELETE FROM reminders WHERE id = ?") is None
    assert ld.scan_dangerous("DELETE FROM reminders WHERE id = :rid") is None
    assert ld.scan_dangerous("DELETE FROM reminders WHERE id = %s") is None


def test_scan_dangerous_allows_crud_delete_in_diff(monkeypatch, tmp_path):
    ld = _reload_as_a(monkeypatch, tmp_path)
    diff = (
        "+def delete(rid: int) -> None:\n"
        '+    _conn().execute("DELETE FROM reminders WHERE id = ?", (rid,))\n'
    )
    assert ld.scan_dangerous(diff) is None


def test_scan_dangerous_still_flags_mass_delete(monkeypatch, tmp_path):
    ld = _reload_as_a(monkeypatch, tmp_path)
    # No WHERE at all -> wipes the whole table. Still dangerous.
    assert ld.scan_dangerous("DELETE FROM users;") is not None
    assert ld.scan_dangerous("DELETE FROM users") is not None


def test_scan_dangerous_still_flags_unparametrised_where(monkeypatch, tmp_path):
    ld = _reload_as_a(monkeypatch, tmp_path)
    # A WHERE without a bound placeholder is not the safe CRUD shape; an always-
    # true / literal predicate can still wipe rows wholesale. Keep escalating.
    assert ld.scan_dangerous("DELETE FROM users WHERE 1=1") is not None


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


def test_reason_from_body_stops_at_foreign_heading(monkeypatch, tmp_path):
    """_reason_from_body must not bleed trailing boilerplate sections into the
    reason. RunnerResult.to_markdown appends '## Verdikt' / '## Artefakt (Git)'
    after '## Antwort'; when the reviewer prose has no own '## Begründung', the
    extractor must stop at the next FOREIGN '##' heading, not run to EOF
    (Codex review minor 2026-06-03)."""
    ld = _reload_as_a(monkeypatch, tmp_path)
    body = (
        "## Quelle\ntask_id x, geclaimt ...\n\n"
        "## Antwort\nDer echte Reviewer-Grund steht hier.\nZweite Zeile.\n\n"
        "## Verdikt\nverdict: escalate\nverdict_reason: foo\n\n"
        "## Artefakt (Git)\nBranch `b` auf dem Remote, Commit `c`.\n"
    )
    reason = ld._reason_from_body(body)
    assert "Der echte Reviewer-Grund steht hier." in reason
    assert "Zweite Zeile." in reason
    assert "## Verdikt" not in reason
    assert "verdict:" not in reason
    assert "Artefakt" not in reason
    assert "Branch" not in reason


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


def _b_verdict_body_only(verdict, body_reason):
    """A b_tick that mirrors the REAL handoff_poll result: parse_verdict leaves
    verdict_reason empty for a bare verdict, so the reviewer's reasoning lives
    ONLY in the document body (under '## Antwort'/'## Begründung'). The multi-line
    payload frontmatter collapses to the first heading line ('## Begründung') —
    exactly the known-MINOR data path."""
    def tick(task_id):
        lane = bc.send_lane()
        fm = {"created": bc.now_iso(), "from": "claude@laptop-b",
              "to": "claude@laptop-a", "status": "done", "task_id": task_id,
              "kind": "review", "verdict": verdict,
              # multi-line payload → parse_frontmatter keeps only line 1
              "payload": f"## Begründung\n\n{body_reason}"}
        body = f"## Antwort\n## Begründung\n\n{body_reason}\n\nVERDICT: {verdict}\n"
        bc.write_text_utf8(bc.lane_inbox(lane) / f"result-{task_id}.md",
                           bc.build_document(fm, body))
    return tick


def test_goal_loop_escalation_carries_real_body_reason(monkeypatch, tmp_path):
    """Known-MINOR fix (2026-06-03): the reviewer's real reason lives in the
    result BODY, not the truncated frontmatter payload ('## Begründung'). The
    escalation file must surface that real reason so the owner sees WHY, not a
    bare heading."""
    ld = _reload_as_a(monkeypatch, tmp_path)
    bc.ensure_dirs()
    real = "Kriterium 2 ist aus dem isolierten Docstring-Diff nicht belegbar."
    summary = ld.run_goal_loop(
        goal="G", done_criteria=["c"], repo="r", base_branch="main",
        max_rounds=3, round_timeout=5, interval=1,
        build_runner=_fake_build_factory(["c1"]),
        b_tick=_b_verdict_body_only("escalate", real))
    assert summary["escalated"] is True
    assert summary["escalation_trigger"] == "reviewer_requested"
    # The escalation reason lives in the file body under '## Eskalations-Grund'.
    esc_path = ld._escalation_path(summary["loop_id"])
    esc_text = bc.read_text_utf8(esc_path)
    assert real in esc_text, \
        f"escalation file lost the real reviewer reason:\n{esc_text}"
    # And it must NOT be the bare collapsed heading.
    assert "## Eskalations-Grund\n## Begründung" not in esc_text
    assert "Reviewer fordert Eskalation: ## Begründung" not in esc_text


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


def test_reason_carries_signal_classifies_boilerplate_vs_real(monkeypatch, tmp_path):
    """Unit-pin _reason_carries_signal: empty + ATX headings are no-signal;
    a real reason (even one starting with '#123', no space) carries signal."""
    ld = _reload_as_a(monkeypatch, tmp_path)
    # no signal
    assert ld._reason_carries_signal(None) is False
    assert ld._reason_carries_signal("") is False
    assert ld._reason_carries_signal("   ") is False
    assert ld._reason_carries_signal("## Begründung") is False
    assert ld._reason_carries_signal("# Heading") is False
    # signal
    assert ld._reason_carries_signal("Kriterium 2 nicht belegbar") is True
    assert ld._reason_carries_signal("#123 failing test still open") is True
    assert ld._reason_carries_signal("## Begründung\n\nDer echte Grund.") is True


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


def test_goal_loop_markdown_heading_reason_is_not_stagnation(monkeypatch, tmp_path):
    """Regression for the live seed-02 spurious stagnation (2026-06-03).

    parse_frontmatter returns only the FIRST line of a multi-line YAML payload,
    so a reviewer answer that starts with a '## Begründung' heading collapses to
    verdict_reason='## Begründung' EVERY round. A bare Markdown heading carries no
    differentiating signal — identical headings across rounds must NOT be read as
    a repeated reason. With distinct commits the loop should run to max_rounds,
    not escalate on stagnation after round 2."""
    ld = _reload_as_a(monkeypatch, tmp_path)
    bc.ensure_dirs()
    summary = ld.run_goal_loop(
        goal="G", done_criteria=["c"], repo="r", base_branch="main",
        max_rounds=2, round_timeout=5, interval=1,
        build_runner=_fake_build_factory(["c1", "c2"]),
        b_tick=_b_verdict("rejected", reason="## Begründung"))
    assert summary["escalated"] is True
    assert summary["escalation_trigger"] == "max_rounds", \
        f"bare heading reason spuriously stagnated: {summary['escalation_trigger']!r}"


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


# --- Task 9: dangerous-action ---

def test_goal_loop_dangerous_diff_escalates(monkeypatch, tmp_path):
    ld = _reload_as_a(monkeypatch, tmp_path)
    bc.ensure_dirs()
    from runners import RunnerResult

    def dangerous_build(auftrag, fm, workroot):
        return RunnerResult(status="done", antwort="built", branch=fm["branch"],
                            commit="c1", changed_files=["x.sql"],
                            diff="+DROP TABLE users;")

    # b_tick should never fire — escalation happens before review.
    fired = {"n": 0}

    def b_should_not_run(task_id):
        fired["n"] += 1

    summary = ld.run_goal_loop(
        goal="G", done_criteria=["c"], repo="r", base_branch="main",
        max_rounds=3, round_timeout=5, interval=1,
        build_runner=dangerous_build, b_tick=b_should_not_run)
    assert summary["escalated"] is True
    assert summary["escalation_trigger"] == "dangerous_action"
    assert fired["n"] == 0
    meta = ld.read_escalation(summary["loop_id"])
    assert meta["trigger"] == "dangerous_action"


# --- Task 10: CLI + resume validation ---

def test_main_goal_loop_requires_repo(monkeypatch, tmp_path, capsys):
    ld = _reload_as_a(monkeypatch, tmp_path)
    rc = ld.main(["--mode", "goal-loop", "--max-rounds", "2",
                  "--seed", "## Ziel\nG\n\n## Done-Kriterien\n- [ ] c\n"])
    assert rc == 2
    assert "repo" in capsys.readouterr().out.lower()


def test_main_goal_loop_lock_is_test_isolated(monkeypatch, tmp_path, capsys):
    """Regression DCO #7728: the singleton lock must be test-isolated.

    Before the conftest DUAL_BRIDGE_LOCK isolation, main() took a lock at a
    SHARED system-temp path (dual-bridge-loop.lock). A parallel/leftover run that
    held it with a recycled-but-live PID made acquire_singleton_lock() return
    False, so main() exited with rc=0 ("ein Loop laeuft bereits") instead of the
    expected rc=2 -> flaky.

    We plant a foreign LIVE-PID lock at the path the SHARED default WOULD resolve
    to, then assert main() still reaches the requires-repo check (rc=2) -- proving
    main() uses the isolated DUAL_BRIDGE_LOCK from conftest, not the shared path.

    NOTE (Codex-Verifier MAJOR 2026-06-03): we redirect tempfile.gettempdir() to a
    per-test tmp dir FIRST, so the planted "foreign holder" never touches the real
    machine-wide lock file -- a parallel real loop_driver poller is never clobbered
    (test-isolation discipline, global CLAUDE.md rule 3 applies to lock files too)."""
    import tempfile
    from pathlib import Path

    foreign_pid = _a_live_foreign_pid()
    if foreign_pid is None:
        import pytest
        pytest.skip("no foreign live PID available to simulate a lock holder")

    # Redirect the system temp dir to an isolated tmp BEFORE planting anything,
    # so the "shared default" path the test simulates is itself sandboxed.
    fake_tmp = tmp_path / "faketemp"
    fake_tmp.mkdir()
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(fake_tmp))

    ld = _reload_as_a(monkeypatch, tmp_path)
    # A FOREIGN live PID (not our own) is the holder that triggered #7728:
    # acquire_singleton_lock only takes over a lock held by os.getpid() or a dead
    # pid, so a foreign-live holder is what made the shared lock collide. Planted
    # at the (now-sandboxed) default path -- main() must NOT resolve there.
    shared_default_loop_lock = (
        Path(tempfile.gettempdir()) / "dual-bridge-poller.lock"
    ).with_name("dual-bridge-loop.lock")
    shared_default_loop_lock.write_text(f"{foreign_pid}\nstale\n", encoding="utf-8")
    try:
        rc = ld.main(["--mode", "goal-loop", "--max-rounds", "2",
                      "--seed", "## Ziel\nG\n\n## Done-Kriterien\n- [ ] c\n"])
        assert rc == 2, (
            "loop lock collided with the shared temp path -> not isolated"
        )
        assert "repo" in capsys.readouterr().out.lower()
    finally:
        shared_default_loop_lock.unlink(missing_ok=True)


def test_main_goal_loop_arg_validation_before_lock(monkeypatch, tmp_path, capsys):
    """Codex-Verifier MINOR 2026-06-03 (loop_driver.py order-of-ops): the --repo
    argument check must run BEFORE the singleton lock is acquired. Otherwise a
    user who forgot --repo while a real loop runs gets "Loop laeuft bereits"
    (rc 0) instead of the actionable "--repo" error (rc 2) -- a misleading,
    user-visible message. We hold the loop lock with a FOREIGN live PID at the
    isolated path main() uses, then call main() without --repo. The arg error
    (rc 2) must win over the lock conflict (rc 0)."""
    import tempfile
    from pathlib import Path

    foreign_pid = _a_live_foreign_pid()
    if foreign_pid is None:
        import pytest
        pytest.skip("no foreign live PID available to simulate a lock holder")

    ld = _reload_as_a(monkeypatch, tmp_path)
    # Hold the lock main() will try to take (the isolated DUAL_BRIDGE_LOCK path).
    held = bc.default_lock_path().with_name("dual-bridge-loop.lock")
    held.parent.mkdir(parents=True, exist_ok=True)
    held.write_text(f"{foreign_pid}\nheld-by-foreign\n", encoding="utf-8")

    rc = ld.main(["--mode", "goal-loop", "--max-rounds", "2",
                  "--seed", "## Ziel\nG\n\n## Done-Kriterien\n- [ ] c\n"])
    out = capsys.readouterr().out.lower()
    assert rc == 2, f"arg validation must precede lock acquisition (got rc={rc})"
    assert "repo" in out
    assert "laeuft bereits" not in out, (
        "lock conflict message leaked despite a missing required arg"
    )


def test_main_goal_loop_forwards_resolved_interval(monkeypatch, tmp_path):
    """Codex-Verifier L4 (2026-06-07): main() resolved args.interval via
    config_value but did NOT pass it into run_goal_loop -- so poll_interval from
    config.json/CLI was silently ignored in goal-loop mode (the Stage-3 main
    path), leaving run_goal_loop's hardcoded interval=5. We point config.json at
    a controlled file with poll_interval=2, call main() WITHOUT --interval, and
    assert the spy on run_goal_loop receives interval=2."""
    import json

    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"poll_interval": 2}), encoding="utf-8")
    monkeypatch.setenv("DUAL_BRIDGE_CONFIG", str(cfg))
    monkeypatch.delenv("DUAL_BRIDGE_POLL_INTERVAL", raising=False)

    ld = _reload_as_a(monkeypatch, tmp_path)

    captured = {}

    def _spy(**kwargs):
        captured.update(kwargs)
        return {
            "loop_id": "loop-x", "rounds_done": 0, "accepted": False,
            "escalated": False, "final_branch": "b", "final_commit": "c",
            "escalation_trigger": None,
        }

    monkeypatch.setattr(ld, "run_goal_loop", _spy)

    rc = ld.main(["--mode", "goal-loop", "--max-rounds", "2",
                  "--repo", "https://example.invalid/r.git",
                  "--seed", "## Ziel\nG\n\n## Done-Kriterien\n- [ ] c\n"])
    assert rc == 1  # not accepted -> rc 1 (spy returned accepted=False)
    assert captured.get("interval") == 2, (
        f"main() did not forward the resolved poll_interval to run_goal_loop "
        f"(got {captured.get('interval')!r}, expected 2)"
    )


def test_resume_max_rounds_allows_unchanged(monkeypatch, tmp_path):
    ld = _reload_as_a(monkeypatch, tmp_path)
    ld.write_escalation(
        loop_id="loop-r", trigger="max_rounds", round_no=1, branch="bridge/loop-r",
        commit="c1", goal="G", criteria_status=[("c", False)],
        reason="max", question="more?", progress="p")
    ok, _msg = ld.validate_resume("loop-r", new_seed_text=None)
    assert ok is True


def test_resume_other_trigger_requires_changed_seed(monkeypatch, tmp_path):
    ld = _reload_as_a(monkeypatch, tmp_path)
    ld.write_escalation(
        loop_id="loop-s", trigger="stagnation", round_no=1, branch="bridge/loop-s",
        commit="c1", goal="G", criteria_status=[("c", False)],
        reason="stuck", question="sharpen?", progress="p")
    ok, _msg = ld.validate_resume("loop-s", new_seed_text=None)
    assert ok is False
    ok2, _msg2 = ld.validate_resume(
        "loop-s", new_seed_text="## Ziel\nG2\n\n## Done-Kriterien\n- [ ] c2\n")
    assert ok2 is True


# --- Task 11: drift guard for mirrored dangerous patterns ---

def test_dangerous_patterns_cover_secret_marker(monkeypatch, tmp_path):
    """Our mirror MUST at least catch the sk-ant- secret marker that secret-sweep
    catches. This is the one pattern that overlaps by contract."""
    ld = _reload_as_a(monkeypatch, tmp_path)
    assert ld.scan_dangerous("sk-ant-deadbeef") is not None


def test_dangerous_patterns_drift_vs_secret_sweep(monkeypatch, tmp_path):
    """If orchestrated-bridge's gate_secret_sweep.py is reachable, every literal
    'sk-ant' / 'api_key' marker it relies on must also be covered by our mirror.
    Skips if the source repo isn't checked out on this machine."""
    import os
    import pytest
    ld = _reload_as_a(monkeypatch, tmp_path)
    candidates = [
        os.path.expanduser(
            "~/AI/Agents/demos/orchestrated-loop/src/orchestrated_loop/"
            "gate_secret_sweep.py"),
    ]
    src = next((p for p in candidates if os.path.exists(p)), None)
    if src is None:
        pytest.skip("orchestrated-bridge secret-sweep source not present")
    text = open(src, encoding="utf-8").read()
    for marker in ("sk-ant", "api_key"):
        if marker in text.lower():
            probe = {"sk-ant": "sk-ant-x", "api_key": "api_key = 'x'"}[marker]
            assert ld.scan_dangerous(probe) is not None, (
                f"mirror drifted: secret-sweep covers {marker!r} but our "
                f"DANGEROUS_PATTERNS does not")


def test_resume_missing_escalation_fails(monkeypatch, tmp_path):
    ld = _reload_as_a(monkeypatch, tmp_path)
    ok, _msg = ld.validate_resume("no-such-loop", new_seed_text=None)
    assert ok is False


# --- Review follow-ups (I-1, I-2) ---

def test_goal_loop_empty_reason_no_false_stagnation(monkeypatch, tmp_path):
    """I-2: in production parse_verdict returns ('rejected', '') for EVERY
    rejected verdict. Two rejected rounds with empty reason but DISTINCT commits
    must NOT trip the repeated-reason stagnation guard ('' == '' is not
    stagnation). Healthy progress (distinct commits) should keep iterating to
    max-rounds, not escalate as stagnation on round 2."""
    ld = _reload_as_a(monkeypatch, tmp_path)
    bc.ensure_dirs()

    def b_empty_reason(task_id):
        # Mirror production: rejected with empty verdict_reason.
        lane = bc.send_lane()
        fm = {"created": bc.now_iso(), "from": "claude@laptop-b",
              "to": "claude@laptop-a", "status": "done", "task_id": task_id,
              "kind": "review", "verdict": "rejected", "verdict_reason": ""}
        bc.write_text_utf8(bc.lane_inbox(lane) / f"result-{task_id}.md",
                           bc.build_document(fm, "## Antwort\nVERDICT: rejected\n"))

    summary = ld.run_goal_loop(
        goal="G", done_criteria=["c"], repo="r", base_branch="main",
        max_rounds=3, round_timeout=5, interval=1,
        build_runner=_fake_build_factory(["c1", "c2", "c3"]),
        b_tick=b_empty_reason)
    # Distinct commits + empty reasons → no stagnation; runs to max-rounds.
    assert summary["escalation_trigger"] == "max_rounds"
    assert summary["rounds_done"] == 3


def test_escalation_file_no_misleading_checkboxes(monkeypatch, tmp_path):
    """I-1: per-criterion status is not machine-captured from the reviewer, so
    the escalation file must NOT render checked '[x]' boxes that assert
    progress the loop never measured. It lists the criteria honestly instead."""
    ld = _reload_as_a(monkeypatch, tmp_path)
    path = ld.write_escalation(
        loop_id="loop-i1", trigger="stagnation", round_no=1,
        branch="bridge/loop-i1", commit="c1", goal="G",
        criteria_status=[("crit one", False), ("crit two", False)],
        reason="stuck", question="sharpen?", progress="p")
    text = path.read_text(encoding="utf-8")
    assert "crit one" in text and "crit two" in text
    # No checkbox claims either way — neither falsely-met nor checkbox theatre.
    assert "[x]" not in text


# --- Live-proof follow-up: escalate reason must reach the owner ---

def test_goal_loop_escalate_reason_falls_back_to_payload(monkeypatch, tmp_path):
    """Live-proof finding: parse_verdict returns ('escalate', '') — empty reason.
    The reviewer's real analysis lands in the result's `payload` field, not
    verdict_reason. The escalation file must surface that analysis, not
    '(kein Grund)'. The loop falls back to payload when verdict_reason is empty."""
    ld = _reload_as_a(monkeypatch, tmp_path)
    bc.ensure_dirs()
    analysis = ("Kriterium 1+2 erfuellt. Kriterium 3 ist mehrdeutig: keine "
                "Projekt-Referenz im Diff, nicht verifizierbar.")

    def b_escalate_with_payload(task_id):
        lane = bc.send_lane()
        fm = {"created": bc.now_iso(), "from": "claude@laptop-b",
              "to": "claude@laptop-a", "status": "done", "task_id": task_id,
              "kind": "review", "verdict": "escalate", "verdict_reason": "",
              "payload": analysis}
        bc.write_text_utf8(bc.lane_inbox(lane) / f"result-{task_id}.md",
                           bc.build_document(fm, f"## Antwort\n{analysis}\n"
                                                 "VERDICT: escalate\n"))

    summary = ld.run_goal_loop(
        goal="G", done_criteria=["c1", "c2", "ambiguous"], repo="r",
        base_branch="main", max_rounds=3, round_timeout=5, interval=1,
        build_runner=_fake_build_factory(["c1"]), b_tick=b_escalate_with_payload)
    assert summary["escalation_trigger"] == "reviewer_requested"
    meta = ld.read_escalation(summary["loop_id"])
    # The escalation FILE body must carry the reviewer's analysis.
    text = (ld._escalation_path(summary["loop_id"])).read_text(encoding="utf-8")
    assert "mehrdeutig" in text
    assert "(kein Grund)" not in text
