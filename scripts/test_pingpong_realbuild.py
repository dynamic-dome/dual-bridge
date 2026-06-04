"""Ping-pong loop with REAL git-building runners (codex), not the echo stub.

The ping-pong mode (run_loop) was written for the echo/increment test adapters,
which take a bare `fm={"payload": ...}` with no task_id/repo. The real codex
runner refuses such an fm ("task ohne task_id") and needs repo/branch/workdir to
build. This was a live-only gap: ping-pong had never run with a git builder
(found 2026-06-04 by a small cross-device live test, P012).

These tests pin the fix: in ping-pong, BOTH A's inline build and B's claimed
build must receive task_id + repo + a shared loop branch, so the built state
survives the A->B->A handoff exactly like the goal-loop's loop_branch does.

Setup mirrors test_loop_continuity_realgit: a local bare origin (no network) +
a fake codex binary that appends a line and self-commits. conftest isolates the
bridge root.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import os

import bridge_common as bc
import codex_adapter as ca
import handoff_poll as hp
import loop_driver as ld


def _b_polls_once():
    """Simulate B's poller in-process: B is a DIFFERENT endpoint identity, so it
    receives on the A-to-B lane (where A's task lands) and writes its result back
    there. In production B is a separate process; here we flip the endpoint env
    around a single poll, mirroring test_lanes' approach. A builds as the default
    claude@laptop-a; B builds as codex@laptop-b."""
    prev = os.environ.get("DUAL_BRIDGE_ENDPOINT")
    os.environ["DUAL_BRIDGE_ENDPOINT"] = "codex@laptop-b"
    try:
        hp.poll_once()
    finally:
        if prev is None:
            os.environ.pop("DUAL_BRIDGE_ENDPOINT", None)
        else:
            os.environ["DUAL_BRIDGE_ENDPOINT"] = prev


def _git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args],
                          capture_output=True, text=True, encoding="utf-8",
                          stdin=subprocess.DEVNULL)


def _make_origin(tmp_path) -> str:
    seed = tmp_path / "seed"
    seed.mkdir()
    subprocess.run(["git", "init", "-b", "main", str(seed)], check=True,
                   capture_output=True)
    _git(seed, "config", "user.email", "t@t.local")
    _git(seed, "config", "user.name", "t")
    (seed / "f.txt").write_text("base\n", encoding="utf-8")
    _git(seed, "add", "-A")
    _git(seed, "commit", "-m", "base")
    bare = tmp_path / "origin.git"
    subprocess.run(["git", "clone", "--bare", str(seed), str(bare)],
                   check=True, capture_output=True)
    return str(bare)


def _fake_codex_self_commits(monkeypatch, line_holder):
    """Fake codex: append the current line to f.txt and self-commit (codex 0.136
    under danger-full-access). Delegates every non-codex command to real git."""
    real_run = ca.subprocess.run

    def fake_run(cmd, **kw):
        exe = str(cmd[0]) if isinstance(cmd, (list, tuple)) and cmd else ""
        if not (exe.endswith("codex") or exe.endswith("codex.exe")):
            return real_run(cmd, **kw)
        workdir = Path(kw.get("cwd"))
        f = workdir / "f.txt"
        f.write_text(f.read_text(encoding="utf-8") + line_holder[0] + "\n",
                     encoding="utf-8")
        _git(workdir, "add", "-A")
        _git(workdir, "commit", "-m", f"codex {line_holder[0]}")
        class _P:
            returncode = 0
            stdout = "ok"
            stderr = ""
        for i, tok in enumerate(cmd):
            if tok == "-o":
                Path(cmd[i + 1]).write_text(f"built {line_holder[0]}", encoding="utf-8")
        return _P()

    monkeypatch.setattr(ca.subprocess, "run", fake_run)
    monkeypatch.setattr(ca.shutil, "which", lambda _n: "C:/fake/codex.exe")


def test_pingpong_codex_round0_gets_task_id_and_repo(monkeypatch, tmp_path):
    """RED before fix: run_loop calls the codex runner with fm={'payload':...},
    so codex returns 'task ohne task_id' and the loop aborts in round 0.

    After fix: A's inline build receives a task_id + repo + loop branch, builds a
    real commit, and the loop does NOT abort with a runner error."""
    origin = _make_origin(tmp_path)
    line = ["A-round0"]
    _fake_codex_self_commits(monkeypatch, line)

    # b_tick: let a real B worker claim+build the open task (B also uses codex).
    def b_tick(*_a, **_k):
        line[0] = "B-round0"
        _b_polls_once()

    summary = ld.run_loop(
        seed="build something", max_rounds=1, adapter="codex",
        round_timeout=30, interval=0.2, b_tick=b_tick,
        repo=origin, base_branch="main",
    )

    assert not summary["aborted"], summary["abort_reason"]
    assert "task ohne task_id" not in (summary["abort_reason"] or "")
    assert summary["rounds_done"] == 1, summary


def test_pingpong_b_builds_on_same_loop_branch(monkeypatch, tmp_path):
    """Continuity: A builds on bridge/<loop_id>, B claims and builds on the SAME
    loop branch (not base), so the origin loop branch tip carries BOTH lines."""
    origin = _make_origin(tmp_path)
    line = ["A-line"]
    _fake_codex_self_commits(monkeypatch, line)

    def b_tick(*_a, **_k):
        line[0] = "B-line"
        _b_polls_once()

    summary = ld.run_loop(
        seed="build", max_rounds=1, adapter="codex",
        round_timeout=30, interval=0.2, b_tick=b_tick,
        repo=origin, base_branch="main",
    )
    assert not summary["aborted"], summary["abort_reason"]

    loop_branch = f"bridge/{summary['loop_id']}"
    probe = tmp_path / "probe"
    clone = subprocess.run(
        ["git", "clone", "--branch", loop_branch, origin, str(probe)],
        capture_output=True, text=True,
    )
    assert clone.returncode == 0, f"loop branch not pushed: {clone.stderr}"
    content = (probe / "f.txt").read_text(encoding="utf-8")
    assert "A-line" in content, "A's build missing from origin loop branch"
    assert "B-line" in content, "B did not build on A's loop branch (continuity broken)"


def test_pingpong_echo_still_works_without_repo(monkeypatch, tmp_path):
    """Back-compat: the echo adapter (no repo, no git) must keep working — the
    fix must not require a repo for non-building adapters."""
    def b_tick(*_a, **_k):
        _b_polls_once()

    summary = ld.run_loop(
        seed="hello", max_rounds=2, adapter="echo",
        round_timeout=30, interval=0.2, b_tick=b_tick,
    )
    assert not summary["aborted"], summary["abort_reason"]
    assert summary["rounds_done"] == 2, summary
