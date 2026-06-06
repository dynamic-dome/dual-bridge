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

    def fake_run_git(wd, *args, **kwargs):
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

    def fake_run_git(wd, *args, **kwargs):
        calls.append(args)
        class _CP:
            returncode = 0
            stdout = ""        # ls-remote returns empty → branch absent
            stderr = ""
        return _CP()

    monkeypatch.setattr(ca, "_run_git", fake_run_git)
    ca._git_clone_or_pull("repo", "main", workdir, prefer_branch="bridge/loop-new")
    assert ("reset", "--hard", "origin/main") in calls


def test_codex_runner_forwards_branch_from_fm(monkeypatch, tmp_path):
    """_codex_runner reads fm['branch'] and passes it to run_codex_task."""
    captured = {}

    def fake_task(**kw):
        captured.update(kw)
        from runners import RunnerResult
        return RunnerResult(status="done", antwort="ok")

    monkeypatch.setattr(ca, "run_codex_task", fake_task)
    fm = {"task_id": "t-7", "repo": "r", "base_branch": "main",
          "branch": "bridge/loop-zzz"}
    res = ca._codex_runner(auftrag="build it", fm=fm, workroot=tmp_path)
    assert res.status == "done"
    assert captured.get("branch") == "bridge/loop-zzz"


def test_codex_runner_branch_absent_is_none(monkeypatch, tmp_path):
    """No fm['branch'] → branch=None (legacy task-branch behaviour)."""
    captured = {}

    def fake_task(**kw):
        captured.update(kw)
        from runners import RunnerResult
        return RunnerResult(status="done", antwort="ok")

    monkeypatch.setattr(ca, "run_codex_task", fake_task)
    res = ca._codex_runner(auftrag="x", fm={"task_id": "t-8"}, workroot=tmp_path)
    assert captured.get("branch") is None


def test_run_codex_task_captures_diff(monkeypatch, tmp_path):
    """run_codex_task returns the build diff (git diff base..HEAD) on success."""
    monkeypatch.setattr(ca, "_git_clone_or_pull",
                        lambda r, b, w, **k: (w / ".git").mkdir(parents=True, exist_ok=True) or w)
    monkeypatch.setattr(ca, "_git_checkout_branch", lambda w, branch: None)
    monkeypatch.setattr(ca.shutil, "which", lambda _n: "C:/fake/codex.exe")

    class _Proc:
        returncode = 0
        stdout = "ok"
        stderr = ""
    monkeypatch.setattr(ca.subprocess, "run", lambda *a, **k: _Proc())
    monkeypatch.setattr(ca, "parse_codex_output", lambda _s: "answer")
    monkeypatch.setattr(ca, "_git_status_porcelain", lambda _w: ["scripts/runners.py"])
    monkeypatch.setattr(ca, "_git_commit_and_push", lambda w, b, m: "abc123")
    monkeypatch.setattr(ca, "_git_diff", lambda w, base: "--- a\n+++ b\n+new line\n")

    res = ca.run_codex_task(auftrag="x", repo="r", base_branch="main",
                            task_id="t-d", workroot=tmp_path, branch="bridge/loop-d")
    assert res.status == "done"
    assert res.diff == "--- a\n+++ b\n+new line\n"


# --- Auth-Pfad + klarere Clone-Fehler-Diagnose (Fix 2026-06-06: privates Repo
#     anonym gesehen -> irrefuehrendes 'branch not found' -> rc=3) ----------------

def test_https_credential_args_injects_helper(monkeypatch):
    """Fuer ein HTTPS-Remote loest _https_credential_args das Token im Parent auf
    und liefert einen ephemeren `-c credential.helper=...` (Token nie in env)."""
    class _Fill:
        returncode = 0
        stdout = "username=bob\npassword=ghp_secrettoken\n"
        stderr = ""
    monkeypatch.setattr(ca.subprocess, "run", lambda *a, **k: _Fill())

    args = ca._https_credential_args("https://github.com/owner/private-repo")
    assert args[:2] == ["-c", "credential.helper="]          # reset host chain
    assert any("credential.helper=" in a and "bob" in a for a in args)
    assert any("ghp_secrettoken" in a for a in args)


def test_https_credential_args_skips_local_and_ssh():
    """Lokale/SSH-Remotes brauchen keinen Helper -> []."""
    assert ca._https_credential_args("C:/tmp/origin.git") == []
    assert ca._https_credential_args("git@github.com:o/r.git") == []
    assert ca._https_credential_args("/home/x/origin") == []


def test_https_credential_args_empty_when_fill_fails(monkeypatch):
    """Wenn `git credential fill` nichts liefert, kein Helper (git nutzt seine
    eigene Kette und meldet den echten Fehler)."""
    class _Fill:
        returncode = 1
        stdout = ""
        stderr = "no credential"
    monkeypatch.setattr(ca.subprocess, "run", lambda *a, **k: _Fill())
    assert ca._https_credential_args("https://github.com/o/r") == []


def test_diagnose_clone_failure_flags_auth_when_branch_visible(monkeypatch):
    """'branch not found' + remote-sichtbarer Branch -> AUTH-Diagnose statt
    Parroting des irrefuehrenden git-Texts."""
    def fake_run_git(wd, *args, **kwargs):
        class _CP:
            returncode = 0
            stdout = "abc\trefs/heads/main\n"   # Branch IST remote sichtbar
            stderr = ""
        return _CP()
    monkeypatch.setattr(ca, "_run_git", fake_run_git)

    msg = ca._diagnose_clone_failure(
        "https://github.com/o/r", "main",
        "fatal: Remote branch main not found in upstream origin", cred=[])
    assert "AUTH" in msg
    assert "Auth/Token" in msg


def test_diagnose_clone_failure_passthrough_for_real_branch_miss(monkeypatch):
    """Branch wirklich nicht sichtbar -> git-Wortlaut bleibt erhalten."""
    def fake_run_git(wd, *args, **kwargs):
        class _CP:
            returncode = 0
            stdout = ""              # ls-remote leer -> Branch fehlt echt
            stderr = ""
        return _CP()
    monkeypatch.setattr(ca, "_run_git", fake_run_git)

    raw = "fatal: Remote branch nope not found in upstream origin"
    msg = ca._diagnose_clone_failure("https://github.com/o/r", "nope", raw, cred=[])
    assert "AUTH" not in msg
    assert raw in msg


def test_diagnose_clone_failure_passthrough_for_other_errors():
    """Andere Clone-Fehler (kein 'not found in upstream') unveraendert."""
    raw = "fatal: could not create work tree dir: Permission denied"
    msg = ca._diagnose_clone_failure("https://github.com/o/r", "main", raw, cred=[])
    assert msg == f"git clone failed: {raw}"
