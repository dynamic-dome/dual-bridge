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


def _make_origin(tmp_path, default_branch: str = "main") -> str:
    """Create a bare origin repo with one commit on default_branch, return path.

    default_branch='master' reproduces the real DCO repo, where the loop is still
    invoked with --base-branch main but origin only has master (2026-06-07)."""
    seed = tmp_path / "seed"
    seed.mkdir()
    subprocess.run(["git", "init", "-b", default_branch, str(seed)], check=True,
                   capture_output=True)
    _git(seed, "config", "user.email", "t@t.local")
    _git(seed, "config", "user.name", "t")
    (seed / "f.txt").write_text("base\n", encoding="utf-8")
    _git(seed, "add", "-A")
    _git(seed, "commit", "-m", "base")
    bare = tmp_path / "origin.git"
    subprocess.run(["git", "clone", "--bare", str(seed), str(bare)],
                   check=True, capture_output=True)
    # A bare clone's HEAD points at default_branch -> _remote_default_branch
    # resolves it, mirroring a real master-only remote.
    return str(bare)


def _fake_codex_appends(monkeypatch, line_holder):
    """Patch codex's subprocess so the codex binary call appends a line to
    f.txt in the workdir (a real file change → real commit) and writes an
    answer file.  Every other command (git clone/fetch/reset/commit/…) is
    delegated to the real subprocess.run so the git machinery stays genuine.
    Discrimination is on the binary name (cmd[0] ends with 'codex' or
    'codex.exe'), NOT on a positional token like cmd[1]=='exec', which would
    silently pass through a renamed or path-extended binary."""
    # Patch the codex-exec SEAM (_run_codex_exec), not subprocess.run: the adapter
    # now drives codex via subprocess.Popen + tree-kill (2026-06-09), so a
    # subprocess.run mock would no longer intercept it. _run_codex_exec is the
    # stable boundary — git keeps running for real, only the codex call is faked.
    def fake_exec(cmd, workdir, auftrag, timeout):
        workdir = Path(workdir)
        f = workdir / "f.txt"
        f.write_text(f.read_text(encoding="utf-8") + line_holder[0] + "\n",
                     encoding="utf-8")
        for i, tok in enumerate(cmd):
            if tok == "-o":
                Path(cmd[i + 1]).write_text("done", encoding="utf-8")
        return ca.subprocess.CompletedProcess(cmd, 0, "ok", "")

    monkeypatch.setattr(ca, "_run_codex_exec", fake_exec)
    monkeypatch.setattr(ca.shutil, "which", lambda _n: "C:/fake/codex.exe")


def _fake_codex_self_commits(monkeypatch, line_holder):
    """Like _fake_codex_appends, but the fake codex ALSO commits its own change
    (git add + commit) before returning — exactly what real codex-cli 0.136 does
    under -s danger-full-access. The result: the workdir's working tree is CLEAN
    after codex runs, but HEAD is one commit ahead of origin/base. This is the
    seam that broke the live seed-02 round-2 review (2026-06-03): the adapter
    decided "no change" from `git status --porcelain` and returned commit=None,
    diff='' even though codex really had committed real work."""
    # Patch the codex-exec seam (see _fake_codex_appends for why).
    def fake_exec(cmd, workdir, auftrag, timeout):
        workdir = Path(workdir)
        f = workdir / "f.txt"
        f.write_text(f.read_text(encoding="utf-8") + line_holder[0] + "\n",
                     encoding="utf-8")
        # codex 0.136 self-commits → working tree clean afterwards.
        _git(workdir, "add", "-A")
        _git(workdir, "commit", "-m", "codex self-commit")
        for i, tok in enumerate(cmd):
            if tok == "-o":
                Path(cmd[i + 1]).write_text("done", encoding="utf-8")
        return ca.subprocess.CompletedProcess(cmd, 0, "ok", "")

    monkeypatch.setattr(ca, "_run_codex_exec", fake_exec)
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


def test_merge_accepted_to_base_integrates_into_main(monkeypatch, tmp_path):
    """An accepted loop branch's work must land in base after merge, so the NEXT
    package's fresh clone of base sees it (cross-package accumulation, 2026-06-07
    reminders-v2). Real local git: build on a loop branch, merge into main, then
    assert origin/main carries the build and a fresh clone of main contains it."""
    origin = _make_origin(tmp_path)
    workroot = tmp_path / "wr"
    workroot.mkdir()
    line = ["paketA-line"]
    _fake_codex_appends(monkeypatch, line)

    # Build Paket A on its loop branch.
    rA = ca.run_codex_task(auftrag="build A", repo=origin, base_branch="main",
                           task_id="tA", workroot=workroot,
                           branch="bridge/loop-A", workdir_name="loop-A")
    assert rA.status == "done", rA.error_text

    # main has NOT seen it yet.
    probe = tmp_path / "probe-before"
    subprocess.run(["git", "clone", "-b", "main", origin, str(probe)],
                   check=True, capture_output=True)
    assert "paketA-line" not in (probe / "f.txt").read_text(encoding="utf-8")

    # Merge the accepted branch into main.
    new_head = ca.merge_accepted_to_base(
        repo=origin, branch="bridge/loop-A", base_branch="main",
        workdir=workroot / "loop-A")
    assert new_head, "merge returned no head"

    # A FRESH clone of main now carries Paket A — the next package would see it.
    probe2 = tmp_path / "probe-after"
    subprocess.run(["git", "clone", "-b", "main", origin, str(probe2)],
                   check=True, capture_output=True)
    assert "paketA-line" in (probe2 / "f.txt").read_text(encoding="utf-8"), \
        "accepted build did not accumulate into base after merge"


def test_merge_accepted_to_base_conflict_raises(monkeypatch, tmp_path):
    """A merge conflict must raise (fail-soft at the caller), NOT silently drop
    the integration. We make base diverge from the loop branch on the same line
    so git cannot auto-merge."""
    origin = _make_origin(tmp_path)
    workroot = tmp_path / "wr"
    workroot.mkdir()
    line = ["loop-change"]
    _fake_codex_appends(monkeypatch, line)
    rA = ca.run_codex_task(auftrag="build", repo=origin, base_branch="main",
                           task_id="tA", workroot=workroot,
                           branch="bridge/loop-A", workdir_name="loop-A")
    assert rA.status == "done", rA.error_text

    # Diverge main on the SAME file/line so the merge conflicts. f.txt currently
    # ends 'base\n'; the loop appended 'loop-change'. Rewrite base's f.txt fully.
    div = tmp_path / "div"
    subprocess.run(["git", "clone", "-b", "main", origin, str(div)],
                   check=True, capture_output=True)
    _git(div, "config", "user.email", "t@t.local")
    _git(div, "config", "user.name", "t")
    (div / "f.txt").write_text("totally-different\n", encoding="utf-8")
    _git(div, "add", "-A")
    _git(div, "commit", "-m", "diverge")
    _git(div, "push", "origin", "main")

    import pytest
    with pytest.raises(RuntimeError):
        ca.merge_accepted_to_base(repo=origin, branch="bridge/loop-A",
                                  base_branch="main", workdir=workroot / "loop-A")


def test_merge_accepted_resolves_base_on_master_repo(monkeypatch, tmp_path):
    """The merge must resolve main->master itself (like the build does), else a
    master-only repo dies with 'origin/main is not a commit' AFTER an accepted
    build — the merge silently fails and the next package never accumulates
    (observed live 2026-06-07, reminders Paket A loop ...d415). Build with
    --base-branch main against a MASTER-only origin, then merge: it must land on
    master, not raise."""
    origin = _make_origin(tmp_path, default_branch="master")
    workroot = tmp_path / "wr"
    workroot.mkdir()
    line = ["paketA-master"]
    _fake_codex_appends(monkeypatch, line)

    rA = ca.run_codex_task(auftrag="build A", repo=origin, base_branch="main",
                           task_id="tA", workroot=workroot,
                           branch="bridge/loop-A", workdir_name="loop-A")
    assert rA.status == "done", rA.error_text

    # Caller passes the unresolved 'main' (exactly what loop_driver does); the
    # merge must resolve it to master itself.
    new_head = ca.merge_accepted_to_base(
        repo=origin, branch="bridge/loop-A", base_branch="main",
        workdir=workroot / "loop-A")
    assert new_head, "merge returned no head on a master-only repo"

    probe = tmp_path / "probe"
    subprocess.run(["git", "clone", "-b", "master", origin, str(probe)],
                   check=True, capture_output=True)
    assert "paketA-master" in (probe / "f.txt").read_text(encoding="utf-8"), \
        "accepted build did not accumulate into master after merge"
