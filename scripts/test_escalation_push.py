"""Unit tests for push-branch-on-escalation.

Background: when a goal-loop escalates (exit 3), the loop branch holds finished,
often-mergeable code. The DCO-side 'Prüfen & Mergen' button fetches that branch
from origin to gate-check + merge it. That only works if the escalated branch is
actually pushed to origin — historically only the ACCEPTED path pushed (via
merge_accepted_to_base), so an escalated branch could live only locally on the
builder (observed 2026-06-07, reminders-D). This adds a best-effort push on the
escalation path, mirroring the accept-push credential handling.

Best-effort contract: a push failure must NOT raise — escalation must complete
regardless (the DCO button falls back to a 'branch not on origin' manual hint).

No real git network — _run_git is monkeypatched. conftest.py isolates state."""
from __future__ import annotations

import subprocess

import adapter_git as ag
from adapter_git import _Cred


def _proc(rc: int, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=["git"], returncode=rc,
                                       stdout=stdout, stderr=stderr)


def test_escalation_push_pushes_loop_branch(monkeypatch, tmp_path):
    """Happy path: pushes the loop branch to origin, returns True."""
    calls = []

    def fake_run_git(wd, *args, cred=None):
        calls.append(args)
        return _proc(0)

    monkeypatch.setattr(ag, "_run_git", fake_run_git)
    monkeypatch.setattr(ag, "_resolve_https_credential",
                        lambda repo: _Cred(env={}))

    ok = ag.push_branch_on_escalation(
        repo="https://github.com/x/y", branch="bridge/loop-A-0-aa", workdir=tmp_path)

    assert ok is True
    # The push targets origin with a <branch>:<branch> refspec
    assert any(a[0] == "push" and a[1] == "origin"
               and "bridge/loop-A-0-aa" in a[2] for a in calls), calls


def test_escalation_push_is_best_effort_on_failure(monkeypatch, tmp_path):
    """A push failure returns False, never raises (escalation must complete)."""
    def fake_run_git(wd, *args, cred=None):
        return _proc(1, stderr="remote rejected")

    monkeypatch.setattr(ag, "_run_git", fake_run_git)
    monkeypatch.setattr(ag, "_resolve_https_credential",
                        lambda repo: _Cred(env={}))

    ok = ag.push_branch_on_escalation(
        repo="https://github.com/x/y", branch="bridge/loop-A-0-aa", workdir=tmp_path)

    assert ok is False


def test_escalation_push_swallows_exceptions(monkeypatch, tmp_path):
    """Even an unexpected exception (e.g. credential resolution) returns False."""
    def boom(repo):
        raise RuntimeError("cred blew up")

    monkeypatch.setattr(ag, "_resolve_https_credential", boom)

    ok = ag.push_branch_on_escalation(
        repo="https://github.com/x/y", branch="bridge/loop-A-0-aa", workdir=tmp_path)

    assert ok is False
