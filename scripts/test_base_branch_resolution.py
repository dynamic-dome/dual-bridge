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

import codex_adapter as ca
from codex_adapter import _Cred


def _proc(rc: int, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=["git"], returncode=rc,
                                       stdout=stdout, stderr=stderr)


_SYMREF = "ref: refs/heads/master\tHEAD\nf24543d\tHEAD\n"


def test_requested_branch_exists_is_kept(monkeypatch):
    """main exists on origin -> use it, never probe HEAD."""
    def fake(wd, *args, cred=None):
        assert args[:2] == ("ls-remote", "--heads")  # only the heads probe runs
        return _proc(0, stdout="abc\trefs/heads/main")
    monkeypatch.setattr(ca, "_run_git", fake)
    assert ca._resolve_base_branch("https://x/r", "main", _Cred(env={})) == "main"


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
    monkeypatch.setattr(ca, "_run_git", fake)
    assert ca._resolve_base_branch("https://x/r", "main", _Cred(env={})) == "master"
    assert ("ls-remote", "--symref") in calls


def test_probe_failure_keeps_requested_branch(monkeypatch):
    """ls-remote --heads errors (auth/transient) -> keep base, let clone surface
    the real error (do NOT silently switch branches on a failed probe)."""
    def fake(wd, *args, cred=None):
        return _proc(2, stderr="fatal: could not read Username")
    monkeypatch.setattr(ca, "_run_git", fake)
    assert ca._resolve_base_branch("https://x/r", "main", _Cred(env={})) == "main"


def test_default_unparseable_keeps_requested_branch(monkeypatch):
    """main absent AND HEAD symref unreadable -> keep base (let clone fail loudly
    rather than guess)."""
    def fake(wd, *args, cred=None):
        if args[:2] == ("ls-remote", "--heads"):
            return _proc(0, stdout="")
        return _proc(0, stdout="garbage without a ref line")
    monkeypatch.setattr(ca, "_run_git", fake)
    assert ca._resolve_base_branch("https://x/r", "main", _Cred(env={})) == "main"


def test_remote_default_branch_parses_trunk(monkeypatch):
    """_remote_default_branch parses an arbitrary default name (trunk)."""
    monkeypatch.setattr(ca, "_run_git",
                        lambda *a, **k: _proc(0, stdout="ref: refs/heads/trunk\tHEAD\n"))
    assert ca._remote_default_branch("https://x/r", _Cred(env={})) == "trunk"


def test_remote_default_branch_none_on_empty(monkeypatch):
    """No symref line (empty/private-anonymous) -> None."""
    monkeypatch.setattr(ca, "_run_git", lambda *a, **k: _proc(0, stdout=""))
    assert ca._remote_default_branch("https://x/r", _Cred(env={})) is None


def test_resolve_runs_only_on_fresh_workdir(monkeypatch, tmp_path):
    """run_codex_task must NOT re-probe the base branch when the workdir already
    has a .git (round 2+): base is already proven, a probe wastes a network call.
    We assert _resolve_base_branch is not called in that case."""
    workroot = tmp_path / "wr"
    existing = workroot / "loop-x"
    (existing / ".git").mkdir(parents=True)

    called = {"resolve": False}
    monkeypatch.setattr(ca, "_resolve_base_branch",
                        lambda *a, **k: called.__setitem__("resolve", True) or "main")
    monkeypatch.setattr(ca.shutil, "which", lambda _n: "C:/fake/codex.exe")
    monkeypatch.setattr(ca, "_git_clone_or_pull", lambda *a, **k: existing)
    monkeypatch.setattr(ca, "_git_checkout_branch", lambda *a, **k: None)
    monkeypatch.setattr(ca, "_git_status_porcelain", lambda _w: [])
    monkeypatch.setattr(ca.subprocess, "run",
                        lambda *a, **k: _proc(0, stdout="answer"))
    monkeypatch.setattr(ca, "parse_codex_output", lambda _s: "answer")

    ca.run_codex_task("auftrag", "https://x/r", "main", "tid",
                      workroot, workdir_name="loop-x")
    assert called["resolve"] is False
