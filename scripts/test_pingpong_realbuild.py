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
    # Patch the codex-exec seam (_run_codex_exec), not subprocess.run: the adapter
    # now drives codex via Popen + tree-kill (2026-06-09). git keeps running real.
    def fake_exec(cmd, workdir, auftrag, timeout):
        workdir = Path(workdir)
        f = workdir / "f.txt"
        f.write_text(f.read_text(encoding="utf-8") + line_holder[0] + "\n",
                     encoding="utf-8")
        _git(workdir, "add", "-A")
        _git(workdir, "commit", "-m", f"codex {line_holder[0]}")
        for i, tok in enumerate(cmd):
            if tok == "-o":
                Path(cmd[i + 1]).write_text(f"built {line_holder[0]}", encoding="utf-8")
        return ca.subprocess.CompletedProcess(cmd, 0, "ok", "")

    monkeypatch.setattr(ca, "_run_codex_exec", fake_exec)
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


def _fake_codex_builds_next_step(monkeypatch):
    """Fake codex that INTERPRETS the standing seed instead of appending a fixed
    line: it reads pingpong_chain.py, finds the highest existing step_<N>, and
    appends step_<N+1> in the seed's exact shape, then self-commits.

    This is the realistic builder behaviour the sharpened seed asks for. It only
    makes progress every round if the build *auftrag* actually reaches it each
    round — which is exactly what the round>=1 payload-passthrough bug breaks
    (after round 0 the builder receives the other side's prose answer, not the
    seed, so it can't know what to build)."""
    import re

    # Patch the codex-exec seam (_run_codex_exec): the adapter now drives codex via
    # Popen + tree-kill (2026-06-09). The auftrag arrives as a direct parameter
    # here (the real seam forwards it to codex via stdin, rule 10.8/P008).
    def fake_exec(cmd, workdir, auftrag, timeout):
        # Only build when the task text actually asks for a step_<N> chain. If the
        # auftrag is the other side's prose answer (the bug), build nothing — the
        # commit then carries no new step and the round produces no progress.
        auftrag = auftrag or ""
        workdir = Path(workdir)
        f = workdir / "pingpong_chain.py"
        existing = f.read_text(encoding="utf-8") if f.exists() else ""
        builds_chain = "step_" in auftrag and "pingpong_chain.py" in auftrag
        if builds_chain:
            nums = [int(n) for n in re.findall(r"def step_(\d+)\(", existing)]
            nxt = (max(nums) + 1) if nums else 1
            block = (f"def step_{nxt}() -> int:\n"
                     f'    """Ping-pong round {nxt}."""\n'
                     f"    return {nxt}\n")
            f.write_text(existing + ("\n" if existing else "") + block,
                         encoding="utf-8")
            _git(workdir, "add", "-A")
            _git(workdir, "commit", "-m", f"Add ping-pong step {nxt}")
        for i, tok in enumerate(cmd):
            if tok == "-o":
                Path(cmd[i + 1]).write_text(
                    f"built step (auftrag_had_chain={builds_chain})",
                    encoding="utf-8")
        return ca.subprocess.CompletedProcess(cmd, 0, "ok", "")

    monkeypatch.setattr(ca, "_run_codex_exec", fake_exec)
    monkeypatch.setattr(ca.shutil, "which", lambda _n: "C:/fake/codex.exe")


def test_pingpong_seed_auftrag_survives_round_1(monkeypatch, tmp_path):
    """Regression for the 2026-06-04 live finding: a 2-round ping-pong build must
    yield step_1 (A, round 0) AND step_2 (B, round 1) on the loop branch.

    The bug: run_loop feeds round N>=1 the *previous side's answer* as the new
    auftrag (payload = b_payload), so the standing build seed is lost after round
    0. The builder in round 1 receives prose ('Stand ist damit:') instead of the
    step_<N> instruction and builds nothing -> step_2 never appears.

    Fix target: for git-building adapters the standing seed auftrag is passed to
    every round; continuity of the work-so-far rides on the loop branch's file
    state, not on the prose payload."""
    origin = _make_origin(tmp_path)
    _fake_codex_builds_next_step(monkeypatch)

    def b_tick(*_a, **_k):
        _b_polls_once()

    seed = ("Append exactly ONE new function to pingpong_chain.py named "
            "step_<N> (next unused integer), shape def step_<N>() -> int with a "
            "docstring returning <N>. Do not change existing functions.")
    summary = ld.run_loop(
        seed=seed, max_rounds=2, adapter="codex",
        round_timeout=30, interval=0.2, b_tick=b_tick,
        repo=origin, base_branch="main",
    )
    assert not summary["aborted"], summary["abort_reason"]
    assert summary["rounds_done"] == 2, summary

    loop_branch = f"bridge/{summary['loop_id']}"
    probe = tmp_path / "probe2"
    clone = subprocess.run(
        ["git", "clone", "--branch", loop_branch, origin, str(probe)],
        capture_output=True, text=True,
    )
    assert clone.returncode == 0, f"loop branch not pushed: {clone.stderr}"
    content = (probe / "pingpong_chain.py").read_text(encoding="utf-8")
    assert "def step_1(" in content, "round 0 (A) build missing"
    assert "def step_2(" in content, (
        "round 1 (B) built nothing — standing seed auftrag was lost after "
        "round 0 (payload became the other side's prose answer)")


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
