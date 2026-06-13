"""Tests for the git-aware echo runner (Triage #7904 / L20).

Background: the DCO bridge runs every job as a goal-loop whose reviewer judges
the build DIFF against the done-criteria. The pure-text echo adapter produced an
EMPTY diff, so the smoke preset (echo·echo) could never be accepted — it always
escalated on max_rounds (live #7903, L20). Fix (Option A, user choice): when the
echo runner is invoked in a BUILDING context (fm carries a non-empty repo, i.e.
the goal-loop gave it a loop branch), it clones the loop branch and commits a
deterministic marker file so the diff is non-empty and the reviewer can accept
it against a marker done-criterion.

Without a repo the echo runner stays a pure text reflector (back-compat:
ping-pong / handoff echo) — that path is covered by test_lanes.test_run_echo.

Real local git only (no network, no GitHub): a bare "origin" repo in a tmp tree,
exactly the isolation live_mirror.py uses (global CLAUDE.md rule 3).
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

import runners

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None, reason="git not on PATH"
)


def _git(cwd, *args) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True, text=True, encoding="utf-8",
        stdin=subprocess.DEVNULL,
    )


def _make_origin(tmp: Path) -> str:
    """Bare origin repo with one commit on main — same shape as live_mirror."""
    seed = tmp / "seed"
    seed.mkdir()
    subprocess.run(["git", "init", "-b", "main", str(seed)], check=True,
                   capture_output=True)
    _git(seed, "config", "user.email", "t@t.local")
    _git(seed, "config", "user.name", "t")
    (seed / "f.txt").write_text("base\n", encoding="utf-8")
    _git(seed, "add", "-A")
    _git(seed, "commit", "-m", "base")
    bare = tmp / "origin.git"
    subprocess.run(["git", "clone", "--bare", str(seed), str(bare)],
                   check=True, capture_output=True)
    return str(bare)


def test_run_echo_text_only_without_repo():
    """Back-compat: no repo in fm -> pure text reflector, no commit, no diff."""
    r = runners.run_echo(auftrag="spiegel mich", fm={"task_id": "T1"},
                         workroot=None)
    assert r.status == "done"
    assert "spiegel mich" in r.antwort
    assert r.commit is None
    assert not r.diff


def test_run_echo_builds_marker_commit_with_repo(tmp_path):
    """Building context: a repo in fm -> clone loop branch, commit a marker,
    return a non-empty diff + commit so the reviewer can accept it."""
    origin = _make_origin(tmp_path)
    fm = {
        "task_id": "smoke-abc",
        "repo": origin,
        "base_branch": "main",
        "branch": "bridge/loop-SMOKE",
        "workdir_name": "loop-SMOKE",
    }
    r = runners.run_echo(auftrag="smoke", fm=fm, workroot=tmp_path / "work")

    assert r.status == "done", r.error_text
    assert r.commit, "marker build must produce a real commit"
    assert r.diff and "bridge-smoke" in r.diff
    assert "smoke-abc" in r.diff, "marker content must carry the task_id"
    assert any("bridge-smoke" in f for f in r.changed_files)

    # Continuity: the marker commit must be PUSHED to origin/<branch>, else the
    # next clone_or_pull resets it away (the codex-adapter MAJOR, L6).
    probe = tmp_path / "probe"
    clone = subprocess.run(
        ["git", "clone", "--branch", "bridge/loop-SMOKE", origin, str(probe)],
        capture_output=True, text=True,
    )
    assert clone.returncode == 0, clone.stderr
    marker = probe / "bridge-smoke.txt"
    assert marker.exists(), "marker file not pushed to origin/branch"
    assert "smoke-abc" in marker.read_text(encoding="utf-8")


def test_run_echo_marker_diff_nonempty_when_file_already_exists(tmp_path):
    """A second smoke against a base that ALREADY carries the marker must still
    produce a non-empty diff (the task_id changes) — otherwise the reviewer would
    see an empty diff and reject, the exact L20 failure we are fixing."""
    origin = _make_origin(tmp_path)
    # First smoke seeds bridge-smoke.txt onto the base via a merge into main.
    fm1 = {"task_id": "smoke-1", "repo": origin, "base_branch": "main",
           "branch": "bridge/loop-1", "workdir_name": "loop-1"}
    runners.run_echo(auftrag="smoke", fm=fm1, workroot=tmp_path / "work")
    # Merge loop-1 into the bare origin's main so the next clone sees the marker.
    merge_clone = tmp_path / "merge"
    subprocess.run(["git", "clone", origin, str(merge_clone)],
                   check=True, capture_output=True)
    _git(merge_clone, "config", "user.email", "t@t.local")
    _git(merge_clone, "config", "user.name", "t")
    _git(merge_clone, "fetch", "origin", "bridge/loop-1")
    _git(merge_clone, "merge", "--no-edit", "FETCH_HEAD")
    _git(merge_clone, "push", "origin", "main")

    # Second smoke with a DIFFERENT task_id on the (now marker-bearing) base.
    fm2 = {"task_id": "smoke-2", "repo": origin, "base_branch": "main",
           "branch": "bridge/loop-2", "workdir_name": "loop-2"}
    r2 = runners.run_echo(auftrag="smoke", fm=fm2, workroot=tmp_path / "work")
    assert r2.status == "done", r2.error_text
    assert r2.diff and "smoke-2" in r2.diff, "second smoke must still diff"


def test_goal_loop_routes_echo_adapter_to_echo_runner():
    """Wiring: goal-loop mode must pick the marker-building echo runner for
    adapter=='echo'. Before #7904 the goal-loop ALWAYS built via codex and
    ignored --adapter, so the echo runner never ran and the smoke could not be
    accepted (L20)."""
    import loop_driver as ld
    assert ld._goal_build_runner("echo") is runners.run_echo


def test_goal_loop_keeps_codex_default_for_other_adapters():
    """Regression guard: every non-echo adapter (incl. the 'increment' CLI
    default and unknown values) must keep run_goal_loop's codex default (None),
    so the historical goal-loop builder is unchanged — a non-building text runner
    must never silently become the builder."""
    import loop_driver as ld
    assert ld._goal_build_runner("codex") is None
    assert ld._goal_build_runner("increment") is None
    assert ld._goal_build_runner(None) is None
    assert ld._goal_build_runner("claude") is None
