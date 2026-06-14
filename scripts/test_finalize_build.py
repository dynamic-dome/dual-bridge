import subprocess
from pathlib import Path

import pytest

import adapter_git as ag


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True,
                   capture_output=True, text=True)


def _make_origin_and_clone(tmp_path):
    """A bare origin on 'main' + a working clone checked out on a task branch."""
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "--bare", "-b", "main", str(origin))
    seed = tmp_path / "seed"
    _git(tmp_path, "init", "-b", "main", str(seed))
    (seed / "README.md").write_text("base\n", encoding="utf-8")
    _git(seed, "add", "."); _git(seed, "-c", "user.email=t@t", "-c", "user.name=t",
                                  "commit", "-m", "base")
    _git(seed, "remote", "add", "origin", str(origin)); _git(seed, "push", "origin", "main")
    work = tmp_path / "work"
    _git(tmp_path, "clone", str(origin), str(work))
    _git(work, "config", "user.email", "t@t"); _git(work, "config", "user.name", "t")
    _git(work, "checkout", "-b", "bridge/task-T1")
    return origin, work


def test_working_tree_change_is_committed_and_pushed(tmp_path):
    _, work = _make_origin_and_clone(tmp_path)
    (work / "new.py").write_text("x = 1\n", encoding="utf-8")
    out = ag.finalize_build(work, "bridge/task-T1", "main", "bridge: task T1")
    assert out.status == "done"
    assert out.commit and out.branch == "bridge/task-T1"
    assert "new.py" in out.changed_files
    assert out.diff and "new.py" in out.diff


def test_no_change_returns_done_with_note(tmp_path):
    _, work = _make_origin_and_clone(tmp_path)
    out = ag.finalize_build(work, "bridge/task-T1", "main", "bridge: task T1",
                            no_change_note="claude gab nur Text, keine Datei-Aenderung")
    assert out.status == "done"
    assert out.branch is None and out.commit is None
    assert out.note == "claude gab nur Text, keine Datei-Aenderung"


def test_self_commit_is_detected_and_pushed(tmp_path):
    _, work = _make_origin_and_clone(tmp_path)
    (work / "self.py").write_text("y = 2\n", encoding="utf-8")
    _git(work, "add", "."); _git(work, "commit", "-m", "self-committed by agent")
    out = ag.finalize_build(work, "bridge/task-T1", "main", "bridge: task T1")
    assert out.status == "done"
    assert out.commit and "self.py" in out.diff


def test_git_diff_since_shows_only_increment(tmp_path):
    import subprocess
    import adapter_git
    wd = tmp_path / "repo"
    wd.mkdir()
    def git(*a):
        subprocess.run(["git", *a], cwd=wd, check=True,
                       capture_output=True, text=True)
    git("init", "-q")
    git("config", "user.email", "t@t")
    git("config", "user.name", "t")
    (wd / "a.txt").write_text("step1\n", encoding="utf-8")
    git("add", "."); git("commit", "-q", "-m", "s1")
    first = subprocess.run(["git", "rev-parse", "HEAD"], cwd=wd,
                           capture_output=True, text=True).stdout.strip()
    (wd / "b.txt").write_text("step2\n", encoding="utf-8")
    git("add", "."); git("commit", "-q", "-m", "s2")
    diff = adapter_git._git_diff_since(wd, first)
    assert "b.txt" in diff and "step2" in diff
    assert "a.txt" not in diff  # increment only, not the whole history
