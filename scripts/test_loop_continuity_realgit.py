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


def _fake_codex_self_commits(monkeypatch, line_holder):
    """Like _fake_codex_appends, but the fake codex ALSO commits its own change
    (git add + commit) before returning — exactly what real codex-cli 0.136 does
    under -s danger-full-access. The result: the workdir's working tree is CLEAN
    after codex runs, but HEAD is one commit ahead of origin/base. This is the
    seam that broke the live seed-02 round-2 review (2026-06-03): the adapter
    decided "no change" from `git status --porcelain` and returned commit=None,
    diff='' even though codex really had committed real work."""
    real_run = ca.subprocess.run

    def fake_run(cmd, **kw):
        exe = str(cmd[0]) if isinstance(cmd, (list, tuple)) and cmd else ""
        if not (exe.endswith("codex") or exe.endswith("codex.exe")):
            return real_run(cmd, **kw)
        cwd = kw.get("cwd")
        workdir = Path(cwd)
        f = workdir / "f.txt"
        f.write_text(f.read_text(encoding="utf-8") + line_holder[0] + "\n",
                     encoding="utf-8")
        # codex 0.136 self-commits → working tree clean afterwards.
        _git(workdir, "add", "-A")
        _git(workdir, "commit", "-m", "codex self-commit")
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


def test_codex_self_commit_is_seen_as_progress(monkeypatch, tmp_path):
    """Regression for the seed-02 round-2 empty-diff bug (2026-06-03).

    When codex commits its own change, `git status --porcelain` is clean, yet
    HEAD is ahead of origin/base. The adapter MUST report that commit + a
    non-empty diff (origin/base...HEAD) — not commit=None / diff='' ('keine
    Datei-Aenderung'). Otherwise the reviewer gets a leak-empty diff and the loop
    spuriously stagnates."""
    origin = _make_origin(tmp_path)
    workroot = tmp_path / "work"
    line = ["self-committed-line"]
    _fake_codex_self_commits(monkeypatch, line)

    r = ca.run_codex_task(auftrag="build", repo=origin, base_branch="main",
                          task_id="sc1", workroot=workroot,
                          branch="bridge/loop-SC", workdir_name="loop-SC")
    assert r.status == "done", r.error_text
    assert r.commit, "self-committed work reported as commit=None (Bug 2)"
    assert r.diff and "self-committed-line" in r.diff, \
        f"self-committed work produced an empty/short review diff (Bug 3): {r.diff!r}"

    # The self-committed commit MUST be pushed to origin/<branch>, otherwise the
    # next round's _git_clone_or_pull resets --hard to origin/<branch> and drops
    # the local-only commit → continuity breaks (Codex review MAJOR 2026-06-03).
    ls = _git(tmp_path, "ls-remote", "--heads", origin, "bridge/loop-SC")
    assert r.commit in ls.stdout or ls.stdout.strip(), \
        "self-committed branch was not pushed to origin (continuity risk)"
    # Stronger: the pushed branch tip must carry the self-committed line.
    probe = tmp_path / "probe"
    subprocess.run(["git", "clone", "--branch", "bridge/loop-SC", origin, str(probe)],
                   capture_output=True)
    assert "self-committed-line" in (probe / "f.txt").read_text(encoding="utf-8"), \
        "origin/bridge/loop-SC does not contain the self-committed work (not pushed)"


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
