"""Unit tests for default-branch auto-resolution (main vs master/trunk).

Background: the loop defaults base_branch to 'main', but repos like
dynamic-central-orchestrator still use 'master'. Cloning --branch main against a
master-only repo died with the misleading 'Remote branch main not found in
upstream origin' (observed 2026-06-06 -> rc=3). _resolve_base_branch probes the
requested branch and, only if genuinely absent, falls back to the remote HEAD's
real default via `git ls-remote --symref HEAD`.

No real git network -- _run_git is monkeypatched. conftest.py isolates state."""
from __future__ import annotations

import subprocess

import adapter_git as ag
import codex_adapter as ca
from adapter_git import _Cred


def _proc(rc: int, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=["git"], returncode=rc,
                                       stdout=stdout, stderr=stderr)


_SYMREF = "ref: refs/heads/master\tHEAD\nf24543d\tHEAD\n"


def test_requested_branch_exists_is_kept(monkeypatch):
    """main exists on origin -> use it, never probe HEAD."""
    def fake(wd, *args, cred=None):
        assert args[:2] == ("ls-remote", "--heads")  # only the heads probe runs
        return _proc(0, stdout="abc\trefs/heads/main")
    monkeypatch.setattr(ag, "_run_git", fake)
    assert ag._resolve_base_branch("https://x/r", "main", _Cred(env={})) == "main"


def test_absent_branch_falls_back_to_remote_default(monkeypatch):
    """main absent -> resolve to the remote HEAD default (master)."""
    calls = []
    def fake(wd, *args, cred=None):
        calls.append(args[:2])
        if args[:2] == ("ls-remote", "--heads"):
            return _proc(0, stdout="")            # main not present
        if args[:2] == ("ls-remote", "--symref"):
            return _proc(0, stdout=_SYMREF)       # HEAD -> master
        raise AssertionError(f"unexpected git call: {args}")
    monkeypatch.setattr(ag, "_run_git", fake)
    assert ag._resolve_base_branch("https://x/r", "main", _Cred(env={})) == "master"
    assert ("ls-remote", "--symref") in calls


def test_probe_failure_keeps_requested_branch(monkeypatch):
    """ls-remote --heads errors (auth/transient) -> keep base, let clone surface
    the real error (do NOT silently switch branches on a failed probe)."""
    def fake(wd, *args, cred=None):
        return _proc(2, stderr="fatal: could not read Username")
    monkeypatch.setattr(ag, "_run_git", fake)
    assert ag._resolve_base_branch("https://x/r", "main", _Cred(env={})) == "main"


def test_default_unparseable_keeps_requested_branch(monkeypatch):
    """main absent AND HEAD symref unreadable -> keep base (let clone fail loudly
    rather than guess)."""
    def fake(wd, *args, cred=None):
        if args[:2] == ("ls-remote", "--heads"):
            return _proc(0, stdout="")
        return _proc(0, stdout="garbage without a ref line")
    monkeypatch.setattr(ag, "_run_git", fake)
    assert ag._resolve_base_branch("https://x/r", "main", _Cred(env={})) == "main"


def test_remote_default_branch_parses_trunk(monkeypatch):
    """_remote_default_branch parses an arbitrary default name (trunk)."""
    monkeypatch.setattr(ag, "_run_git",
                        lambda *a, **k: _proc(0, stdout="ref: refs/heads/trunk\tHEAD\n"))
    assert ag._remote_default_branch("https://x/r", _Cred(env={})) == "trunk"


def test_remote_default_branch_none_on_empty(monkeypatch):
    """No symref line (empty/private-anonymous) -> None."""
    monkeypatch.setattr(ag, "_run_git", lambda *a, **k: _proc(0, stdout=""))
    assert ag._remote_default_branch("https://x/r", _Cred(env={})) is None


def test_resolve_runs_on_existing_workdir_too(monkeypatch, tmp_path):
    """run_codex_task MUST re-resolve the base branch on every round, including
    when the workdir already has a .git (round 2+).

    base_branch is a per-call local that the loop hands in as 'main' each round;
    it is NOT persisted across rounds. The earlier "skip the probe on an existing
    workdir" optimisation therefore left base_branch='main' in round 2+, so every
    `git diff origin/main...HEAD` died on a master-only repo and the reviewer got
    an EMPTY diff -> rejected -> max_rounds escalation, even though codex had
    built correctly (observed 2026-06-07, reminders-v2 Paket B, loop ...4905).
    The resolve must run every round so master/trunk repos diff correctly past
    round 0."""
    workroot = tmp_path / "wr"
    existing = workroot / "loop-x"
    (existing / ".git").mkdir(parents=True)

    called = {"resolve": False}
    monkeypatch.setattr(ag, "_resolve_base_branch",
                        lambda *a, **k: called.__setitem__("resolve", True) or "master")
    monkeypatch.setattr(ag, "_resolve_https_credential", lambda _r: _Cred(env={}))
    monkeypatch.setattr(ca.shutil, "which", lambda _n: "C:/fake/codex.exe")
    monkeypatch.setattr(ag, "_git_clone_or_pull", lambda *a, **k: existing)
    monkeypatch.setattr(ag, "_git_checkout_branch", lambda *a, **k: None)
    monkeypatch.setattr(ag, "_git_status_porcelain", lambda _w: [])
    monkeypatch.setattr(ca.subprocess, "run",
                        lambda *a, **k: _proc(0, stdout="answer"))
    monkeypatch.setattr(ca, "parse_codex_output", lambda _s: "answer")

    ca.run_codex_task("auftrag", "https://x/r", "main", "tid",
                      workroot, workdir_name="loop-x")
    assert called["resolve"] is True
