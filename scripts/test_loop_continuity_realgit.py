"""Cross-round continuity proof using a REAL local git repo (no fake_build).
This is the seam fake runners cannot exercise (P006/P009). Uses a local bare
'origin' so no network. conftest.py isolates DUAL_BRIDGE_ROOT."""
from __future__ import annotations

import subprocess
from pathlib import Path

import codex_adapter as ca


def _git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args],
                          capture_output=True, text=True, encoding="utf-8",
                          stdin=subprocess.DEVNULL)


def _make_origin(tmp_path) -> str:
    """Create a bare origin repo with one commit on main, return its path."""
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


def _fake_codex_appends(monkeypatch, line_holder):
    """Patch codex's subprocess so the codex binary call appends a line to
    f.txt in the workdir (a real file change → real commit) and writes an
    answer file.  Every other command (git clone/fetch/reset/commit/…) is
    delegated to the real subprocess.run so the git machinery stays genuine.
    Discrimination is on the binary name (cmd[0] ends with 'codex' or
    'codex.exe'), NOT on a positional token like cmd[1]=='exec', which would
    silently pass through a renamed or path-extended binary."""
    real_run = ca.subprocess.run  # captured BEFORE monkeypatch replaces it

    def fake_run(cmd, **kw):
        # Only intercept the codex binary; let every real git command run.
        exe = str(cmd[0]) if isinstance(cmd, (list, tuple)) and cmd else ""
        if not (exe.endswith("codex") or exe.endswith("codex.exe")):
            return real_run(cmd, **kw)
        cwd = kw.get("cwd")
        workdir = Path(cwd)
        f = workdir / "f.txt"
        f.write_text(f.read_text(encoding="utf-8") + line_holder[0] + "\n",
                     encoding="utf-8")
        class _P:
            returncode = 0
            stdout = "ok"
            stderr = ""
        for i, tok in enumerate(cmd):
            if tok == "-o":
                Path(cmd[i + 1]).write_text("done", encoding="utf-8")
        return _P()

    monkeypatch.setattr(ca.subprocess, "run", fake_run)
    monkeypatch.setattr(ca.shutil, "which", lambda _n: "C:/fake/codex.exe")


def test_round2_builds_on_round1_commit(monkeypatch, tmp_path):
    """Two real codex builds on the SAME stable workdir + loop branch: round 2
    must start from round 1's commit (f.txt keeps round-1's line), not base."""
    origin = _make_origin(tmp_path)
    workroot = tmp_path / "work"
    line = ["round1-line"]
    _fake_codex_appends(monkeypatch, line)

    r1 = ca.run_codex_task(auftrag="build", repo=origin, base_branch="main",
                           task_id="t1", workroot=workroot,
                           branch="bridge/loop-X", workdir_name="loop-X")
    assert r1.status == "done", r1.error_text
    assert r1.commit

    line[0] = "round2-line"
    r2 = ca.run_codex_task(auftrag="build more", repo=origin, base_branch="main",
                           task_id="t2", workroot=workroot,
                           branch="bridge/loop-X", workdir_name="loop-X")
    assert r2.status == "done", r2.error_text
    assert r2.commit and r2.commit != r1.commit

    workdir = workroot / "loop-X"
    content = (workdir / "f.txt").read_text(encoding="utf-8")
    assert "round1-line" in content, "round 2 lost round 1's work (continuity broken)"
    assert "round2-line" in content
