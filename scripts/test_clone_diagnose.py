"""Unit tests for _diagnose_clone_failure (auth-vs-missing-branch disambiguation).

Background: git reports a PRIVATE repo cloned anonymously as 'Remote branch main
not found in upstream origin' -- the branch is fine, the credential just was not
applied in the hardened worker context. Observed 2026-06-06: three queued
goal-loops escalated in a row with the misleading raw git wording because the
re-probe ALSO ran anonymously (rc=0, empty refs) and fell through to the raw
message. These tests pin the four diagnosis branches.

No real git network -- _run_git is monkeypatched. conftest.py isolates state."""
from __future__ import annotations

import subprocess

import codex_adapter as ca
from codex_adapter import _Cred


def _proc(rc: int, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=["git"], returncode=rc,
                                       stdout=stdout, stderr=stderr)


_MISSING = ("Cloning into '...'...\n"
            "fatal: Remote branch main not found in upstream origin")


def test_branch_visible_on_reprobe_reports_auth(monkeypatch):
    """ls-remote sees the branch -> clone's failure was auth/transient."""
    cred = _Cred(env={"GIT_ASKPASS": "x"})
    monkeypatch.setattr(ca, "_run_git",
                        lambda *a, **k: _proc(0, stdout="abc\trefs/heads/main"))
    msg = ca._diagnose_clone_failure("https://x/r", "main", _MISSING, cred)
    assert "AUTH, nicht fehlender Branch" in msg
    assert "main not found" in msg  # original git wording preserved as -- git:


def test_reprobe_unreachable_reports_remote_error(monkeypatch):
    """ls-remote itself fails -> remote unreachable / auth, not a missing branch."""
    cred = _Cred(env={"GIT_ASKPASS": "x"})
    monkeypatch.setattr(ca, "_run_git",
                        lambda *a, **k: _proc(2, stderr="fatal: could not read"))
    msg = ca._diagnose_clone_failure("https://x/r", "main", _MISSING, cred)
    assert "Remote nicht erreichbar" in msg
    assert "rc=2" in msg


def test_empty_reprobe_without_cred_reports_auth(monkeypatch):
    """The 2026-06-06 case: no credential resolved, so the re-probe runs
    anonymously and a PRIVATE repo legitimately shows 0 refs. Must be flagged
    AUTH, not parroted as a missing branch."""
    cred = _Cred(env={})  # _resolve_https_credential could not resolve a token
    monkeypatch.setattr(ca, "_run_git", lambda *a, **k: _proc(0, stdout=""))
    msg = ca._diagnose_clone_failure("https://x/r", "main", _MISSING, cred)
    assert "AUTH, nicht fehlender Branch" in msg
    assert "Keine Credential" in msg


def test_empty_reprobe_with_cred_reports_genuine_absence(monkeypatch):
    """A credential WAS resolved yet the branch is still invisible -> it really
    is absent (or the repo is empty). Do not cry auth in that case."""
    cred = _Cred(env={"GIT_ASKPASS": "x"})
    monkeypatch.setattr(ca, "_run_git", lambda *a, **k: _proc(0, stdout=""))
    msg = ca._diagnose_clone_failure("https://x/r", "main", _MISSING, cred)
    assert "AUTH" not in msg
    assert "nicht sichtbar trotz aufgeloester Credential" in msg


def test_unrelated_stderr_passes_through(monkeypatch):
    """A clone error that is NOT the 'not found in upstream' pattern is returned
    verbatim -- no re-probe, no misclassification."""
    # _run_git must not even be called here; make it explode if it is.
    monkeypatch.setattr(ca, "_run_git",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no reprobe")))
    other = "fatal: repository 'https://x/r' not found"
    msg = ca._diagnose_clone_failure("https://x/r", "main", other, _Cred(env={}))
    assert msg == f"git clone failed: {other}"


def test_no_token_ever_appears_in_message(monkeypatch):
    """The _Cred carrier holds paths, never the token -- but guard that the
    message never renders cred.env contents regardless."""
    cred = _Cred(env={"GIT_BRIDGE_CREDFILE": "/tmp/secret-store.store"})
    monkeypatch.setattr(ca, "_run_git", lambda *a, **k: _proc(0, stdout=""))
    msg = ca._diagnose_clone_failure("https://x/r", "main", _MISSING, cred)
    assert "secret-store" not in msg
    assert "CREDFILE" not in msg
