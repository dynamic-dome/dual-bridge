"""Branch-override unit tests for run_codex_task (Stage-2b foundation).
No real codex/git network — we monkeypatch the git helpers and the codex call.
conftest.py isolates DUAL_BRIDGE_ROOT."""
from __future__ import annotations

import codex_adapter as ca


def test_run_codex_task_uses_branch_override(monkeypatch, tmp_path):
    """When branch= is given, that exact branch name is checked out."""
    used = {}

    def fake_clone(repo, base_branch, workdir, **kwargs):
        (workdir / ".git").mkdir(parents=True, exist_ok=True)
        return workdir

    def fake_checkout(workdir, branch):
        used["checkout_branch"] = branch

    class _Proc:
        returncode = 0
        stdout = "done"
        stderr = ""

    monkeypatch.setattr(ca, "_git_clone_or_pull", fake_clone)
    monkeypatch.setattr(ca, "_git_checkout_branch", fake_checkout)
    monkeypatch.setattr(ca.shutil, "which", lambda _n: "C:/fake/codex.exe")
    monkeypatch.setattr(ca.subprocess, "run", lambda *a, **k: _Proc())
    monkeypatch.setattr(ca, "parse_codex_output", lambda _s: "answer")
    monkeypatch.setattr(ca, "_git_status_porcelain", lambda _w: [])  # no changes → no commit

    res = ca.run_codex_task(
        auftrag="x", repo="r", base_branch="main", task_id="t-1",
        workroot=tmp_path, branch="bridge/loop-abc",
    )
    assert used.get("checkout_branch") == "bridge/loop-abc"
    assert res.status == "done"


def test_run_codex_task_defaults_to_task_branch(monkeypatch, tmp_path):
    """Without branch=, the legacy bridge/task-<id> name is used (Stage-1 unchanged)."""
    used = {}
    monkeypatch.setattr(ca, "_git_clone_or_pull",
                        lambda r, b, w, **kw: (w / ".git").mkdir(parents=True, exist_ok=True) or w)
    monkeypatch.setattr(ca, "_git_checkout_branch",
                        lambda w, branch: used.__setitem__("b", branch))
    monkeypatch.setattr(ca.shutil, "which", lambda _n: "C:/fake/codex.exe")

    class _Proc:
        returncode = 0
        stdout = "done"
        stderr = ""
    monkeypatch.setattr(ca.subprocess, "run", lambda *a, **k: _Proc())
    monkeypatch.setattr(ca, "parse_codex_output", lambda _s: "answer")
    monkeypatch.setattr(ca, "_git_status_porcelain", lambda _w: [])

    ca.run_codex_task(auftrag="x", repo="r", base_branch="main",
                      task_id="t-99", workroot=tmp_path)
    assert used.get("b") == "bridge/task-t-99"


def test_clone_or_pull_prefers_existing_remote_branch(monkeypatch, tmp_path):
    """If origin/<prefer_branch> exists, _git_clone_or_pull resets to it, not base."""
    workdir = tmp_path / "wd"
    (workdir / ".git").mkdir(parents=True)
    calls = []

    def fake_run_git(wd, *args):
        calls.append(args)
        class _CP:
            returncode = 0
            stdout = ""
            stderr = ""
        # `git ls-remote --heads origin <branch>` returns a non-empty line if it exists
        if args[:2] == ("ls-remote", "--heads"):
            _CP.stdout = "abc123\trefs/heads/bridge/loop-abc\n"
        return _CP()

    monkeypatch.setattr(ca, "_run_git", fake_run_git)
    ca._git_clone_or_pull("repo", "main", workdir, prefer_branch="bridge/loop-abc")

    # It must have reset to origin/bridge/loop-abc, not origin/main.
    assert ("reset", "--hard", "origin/bridge/loop-abc") in calls
    assert ("reset", "--hard", "origin/main") not in calls


def test_clone_or_pull_falls_back_to_base_when_branch_absent(monkeypatch, tmp_path):
    """If origin/<prefer_branch> does NOT exist, fall back to base_branch."""
    workdir = tmp_path / "wd"
    (workdir / ".git").mkdir(parents=True)
    calls = []

    def fake_run_git(wd, *args):
        calls.append(args)
        class _CP:
            returncode = 0
            stdout = ""        # ls-remote returns empty → branch absent
            stderr = ""
        return _CP()

    monkeypatch.setattr(ca, "_run_git", fake_run_git)
    ca._git_clone_or_pull("repo", "main", workdir, prefer_branch="bridge/loop-new")
    assert ("reset", "--hard", "origin/main") in calls
