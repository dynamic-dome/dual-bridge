import json
import subprocess
import sys
from pathlib import Path

import pytest

import claude_build as cb


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _make_origin(tmp_path):
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "--bare", "-b", "main", str(origin))
    seed = tmp_path / "seed"
    _git(tmp_path, "init", "-b", "main", str(seed))
    (seed / "README.md").write_text("base\n", encoding="utf-8")
    _git(seed, "add", ".")
    _git(seed, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "base")
    _git(seed, "remote", "add", "origin", str(origin))
    _git(seed, "push", "origin", "main")
    return str(origin)


def _fake_claude(tmp_path, *, writes="built.py", body="z = 3\n", exit_code=0,
                 answer="done building"):
    """A fake `claude` binary: writes a file in cwd, prints a JSON result event,
    exits with exit_code. Invoked via a .cmd (Windows) / .sh (POSIX) shim that
    forwards to the python interpreter — mirrors the real claude.EXE/.CMD."""
    script = tmp_path / "fake_claude.py"
    script.write_text(
        "import sys, json, pathlib\n"
        f"open({writes!r}, 'w').write({body!r})\n"
        f"print(json.dumps([{{'type':'result','result':{answer!r}}}]))\n"
        f"sys.exit({exit_code})\n",
        encoding="utf-8")
    if sys.platform == "win32":
        shim = tmp_path / "fake_claude.cmd"
        shim.write_text(f'@"{sys.executable}" "{script}" %*\n', encoding="utf-8")
    else:
        shim = tmp_path / "fake_claude.sh"
        shim.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n',
                        encoding="utf-8")
        shim.chmod(0o755)
    return str(shim)


def test_build_commits_and_returns_diff(tmp_path):
    origin = _make_origin(tmp_path)
    fake = _fake_claude(tmp_path, writes="built.py", body="z = 3\n")
    res = cb.run_claude_build(
        auftrag="add built.py", repo=origin, base_branch="main", task_id="T1",
        workroot=tmp_path / "work", claude_bin=fake, timeout=60)
    assert res.status == "done"
    assert res.commit and res.branch == "bridge/task-T1"
    assert "built.py" in res.diff
    assert res.antwort == "done building"


def test_build_rejects_non_bridge_branch_override(tmp_path):
    origin = _make_origin(tmp_path)
    fake = _fake_claude(tmp_path, writes="built.py", body="z = 4\n")
    res = cb.run_claude_build(
        auftrag="add built.py", repo=origin, base_branch="main", task_id="T-main",
        workroot=tmp_path / "work", claude_bin=fake, timeout=60, branch="main")
    assert res.status == "done"
    assert res.branch == "bridge/task-T-main"


def test_no_change_returns_done_with_note(tmp_path):
    origin = _make_origin(tmp_path)
    fake = _fake_claude(tmp_path, writes="README.md", body="base\n", answer="nichts zu tun")
    res = cb.run_claude_build(
        auftrag="noop", repo=origin, base_branch="main", task_id="T2",
        workroot=tmp_path / "work", claude_bin=fake, timeout=60)
    assert res.status == "done"
    assert res.branch is None
    assert "keine Datei-Aenderung" in (res.note or "")


def test_nonzero_exit_with_diff_is_done(tmp_path):
    origin = _make_origin(tmp_path)
    fake = _fake_claude(tmp_path, writes="built.py", body="z = 9\n", exit_code=1)
    res = cb.run_claude_build(
        auftrag="add built.py", repo=origin, base_branch="main", task_id="T3",
        workroot=tmp_path / "work", claude_bin=fake, timeout=60)
    assert res.status == "done"
    assert "built.py" in res.diff
    assert "exit 1" in (res.note or "")


def test_empty_answer_and_no_diff_is_error(tmp_path):
    origin = _make_origin(tmp_path)
    fake = _fake_claude(tmp_path, writes="README.md", body="base\n", exit_code=1, answer="")
    res = cb.run_claude_build(
        auftrag="noop", repo=origin, base_branch="main", task_id="T4",
        workroot=tmp_path / "work", claude_bin=fake, timeout=60)
    assert res.status == "error"


def test_repo_not_in_allowlist_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("DUAL_BRIDGE_REPO_ALLOWLIST", "https://github.com/ok/*")
    res = cb.run_claude_build(
        auftrag="x", repo="https://evil/repo", base_branch="main", task_id="T5",
        workroot=tmp_path / "work", claude_bin="claude", timeout=60)
    assert res.status == "error" and "allowlist" in res.error_text


def test_claude_not_found_is_error(tmp_path):
    origin = _make_origin(tmp_path)           # local bare repo → clone succeeds
    missing_bin = str(tmp_path / "nonexistent-claude")
    res = cb.run_claude_build(
        auftrag="x", repo=origin, base_branch="main",
        task_id="T6", workroot=tmp_path / "work",
        claude_bin=missing_bin, timeout=60)
    assert res.status == "error"
    assert "nicht ausführbar" in (res.error_text or "")


def test_claude_none_on_path_is_error(tmp_path, monkeypatch):
    monkeypatch.delenv("DUAL_BRIDGE_CLAUDE_BIN", raising=False)
    monkeypatch.setattr("shutil.which", lambda _: None)
    res = cb.run_claude_build(
        auftrag="x", repo="unused", base_branch="main",
        task_id="T6b", workroot=tmp_path / "work",
        claude_bin=None, timeout=60)
    assert res.status == "error"
    assert "nicht gefunden" in (res.error_text or "")


def test_timeout_is_error(tmp_path):
    origin = _make_origin(tmp_path)
    # a fake claude that sleeps longer than the timeout
    script = tmp_path / "slow_claude.py"
    script.write_text("import time, sys\ntime.sleep(30)\nsys.exit(0)\n", encoding="utf-8")
    import sys as _s
    if _s.platform == "win32":
        shim = tmp_path / "slow_claude.cmd"
        shim.write_text(f'@\"{_s.executable}\" \"{script}\" %*\n', encoding="utf-8")
    else:
        shim = tmp_path / "slow_claude.sh"
        shim.write_text(f'#!/bin/sh\nexec \"{_s.executable}\" \"{script}\" \"$@\"\n', encoding="utf-8")
        shim.chmod(0o755)
    res = cb.run_claude_build(
        auftrag="x", repo=origin, base_branch="main", task_id="T7",
        workroot=tmp_path / "work", claude_bin=str(shim), timeout=1)
    assert res.status == "error"
    assert "timeout" in (res.error_text or "").lower()


def test_real_text_suppresses_json_fallback():
    # parse_claude_output's json.dumps fallback (a bracketed string that decodes)
    assert cb._real_text('[{"type":"result","result":""}]') == ""
    assert cb._real_text('{"a": 1}') == ""
    # genuine prose is kept, even with a leading brace that is NOT valid json
    assert cb._real_text("done building") == "done building"
    assert cb._real_text("{not json} summary") == "{not json} summary"
    assert cb._real_text("") == ""


def test_registered_via_handoff_poll():
    # Runners self-register on import. The bridge poller must import claude_build
    # so adapter=claude-build actually resolves at runtime (not just in tests).
    import importlib
    import runners
    importlib.import_module("handoff_poll")
    assert "claude-build" in runners.RUNNERS


def test_registered_via_loop_driver():
    import importlib
    import runners
    importlib.import_module("loop_driver")
    assert "claude-build" in runners.RUNNERS


def test_goal_loop_routes_claude_build_to_its_builder():
    # goal-loop A-side builder selection: claude-build is a REAL git builder, so
    # the symmetric loop (claude baut / codex reviewt) must use it — not fall back
    # to the codex default (which is what `None` means).
    import importlib
    import runners
    ld = importlib.import_module("loop_driver")
    assert ld._goal_build_runner("claude-build") is runners.RUNNERS["claude-build"]
    assert ld._goal_build_runner("echo") is runners.RUNNERS["echo"]
    # the text-only 'claude' reviewer and codex keep the codex default (None)
    assert ld._goal_build_runner("claude") is None
    assert ld._goal_build_runner("codex") is None


def test_nonzero_exit_no_diff_is_error_even_with_text(tmp_path):
    # Codex-Verifier 2026-06-13: a failed claude run (exit!=0) that produced NO
    # build must be an error even if it printed text — the text is then an error
    # message, not a build, and must not masquerade as done.
    origin = _make_origin(tmp_path)
    fake = _fake_claude(tmp_path, writes="README.md", body="base\n", exit_code=1,
                        answer="Error: konnte den Task nicht umsetzen")
    res = cb.run_claude_build(
        auftrag="x", repo=origin, base_branch="main", task_id="T8",
        workroot=tmp_path / "work", claude_bin=fake, timeout=60)
    assert res.status == "error"
    assert "kein Diff/Build" in (res.error_text or "")
