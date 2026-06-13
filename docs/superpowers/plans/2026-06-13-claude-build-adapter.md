# Claude-Build Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a building Claude adapter `claude-build` (capability=build) symmetric to the codex builder, sharing the git-finalize and process-tree-kill machinery, so Laptop B can build with claude (claude builds / codex reviews).

**Architecture:** Approach A — a new `claude_build.py` module mirrors `run_codex_task`, reusing `adapter_git`. The tree-kill/Popen-driver moves to a shared `subprocess_util.py`; the commit/push/self-commit finalize sequence moves to `adapter_git.finalize_build`. Both shared extractions are behavior-preserving for codex (its existing tests are the regression guard). The review-only `claude` adapter is untouched.

**Tech Stack:** Python 3.12, pure stdlib, pytest. Windows-first (codex/claude CLIs), Sharepoint file-bridge. Spec: `docs/superpowers/specs/2026-06-13-claude-build-adapter-design.md`.

**Working dir for all commands:** `cd C:/Users/domes/AI/dual-bridge` (tests run from `scripts/`). Expected baseline suite: green (Soll-Zahl in README/HOW-TO-USE; check before starting, `cd scripts && python -X utf8 -m pytest -q`).

---

## Task 1: Extract shared process-tree-kill into `subprocess_util.py`

Behavior-preserving extraction of `_kill_process_tree` + the Popen-driving timeout logic from `codex_adapter.py`. codex delegates; its tests prove no behavior change.

**Files:**
- Create: `scripts/subprocess_util.py`
- Create: `scripts/test_subprocess_util.py`
- Modify: `scripts/codex_adapter.py` (remove `_kill_process_tree` body + `_run_codex_exec` body, delegate to the new module)

- [ ] **Step 1: Write the shared module**

Create `scripts/subprocess_util.py`:

```python
"""Shared subprocess machinery for bridge builder adapters: whole-tree kill.

Both the codex and claude builders launch a CLI that spawns a process TREE
(python -> node -> <cli>.exe -> MCP children). A plain subprocess.run timeout
or Popen.kill only kills the DIRECT child, orphaning the real worker grandchild
which keeps holding the bridge worker slot open (live hang 2026-06-09: a goal-loop
ran ~50 min past its 600s timeout because an orphaned codex.exe kept working).
run_with_tree_kill drives Popen itself so a timeout kills the whole tree.
Pure stdlib.
"""
from __future__ import annotations

import os
import signal
import subprocess


def _kill_process_tree(pid: int) -> None:
    """Kill `pid` AND all of its descendants. Never raises.

    Windows: `taskkill /T /F /PID` walks the Win32 process snapshot. POSIX: kill
    the process GROUP (the child is started in its own session)."""
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(pid)],
                capture_output=True, stdin=subprocess.DEVNULL,
            )
        else:
            try:
                os.killpg(os.getpgid(pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                try:
                    os.kill(pid, signal.SIGKILL)
                except OSError:
                    pass
    except Exception:
        # Best-effort: a kill failure must never mask the timeout error itself.
        pass


def run_with_tree_kill(cmd, cwd, input_text, timeout, env=None):
    """Run `cmd`, feed `input_text` on stdin; on timeout kill the WHOLE tree then
    re-raise TimeoutExpired. Returns a CompletedProcess.

    errors="replace": codex/git/claude output on a German Windows console can
    carry non-utf8 (cp1252) bytes; a strict decode crashes Popen's reader thread.
    """
    popen_kwargs = dict(
        cwd=str(cwd), stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace", env=env,
    )
    if os.name != "nt":
        popen_kwargs["start_new_session"] = True  # own pgid for killpg
    proc = subprocess.Popen(cmd, **popen_kwargs)
    try:
        stdout, stderr = proc.communicate(input=input_text, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        _kill_process_tree(proc.pid)
        try:
            proc.communicate(timeout=10)  # reap, ignore post-kill trickle
        except Exception:
            pass
        raise exc
    return subprocess.CompletedProcess(cmd, proc.returncode, stdout, stderr)
```

- [ ] **Step 2: Write the failing test**

Create `scripts/test_subprocess_util.py`:

```python
import subprocess
import sys
import time

import pytest

import subprocess_util as su


def test_runs_and_captures_stdout(tmp_path):
    cmd = [sys.executable, "-c", "import sys; print(sys.stdin.read().strip())"]
    cp = su.run_with_tree_kill(cmd, tmp_path, "hallo", timeout=30)
    assert cp.returncode == 0
    assert cp.stdout.strip() == "hallo"


def test_timeout_raises_and_kills(tmp_path):
    # A child that sleeps far longer than the timeout must raise TimeoutExpired.
    cmd = [sys.executable, "-c", "import time; time.sleep(30)"]
    t0 = time.time()
    with pytest.raises(subprocess.TimeoutExpired):
        su.run_with_tree_kill(cmd, tmp_path, "", timeout=1)
    assert time.time() - t0 < 15  # killed promptly, not waited out


def test_kill_process_tree_never_raises_on_dead_pid():
    su._kill_process_tree(2_147_483_000)  # almost-certainly-absent PID; no raise
```

- [ ] **Step 3: Run test to verify it passes (module already written)**

Run: `cd scripts && python -X utf8 -m pytest test_subprocess_util.py -v`
Expected: 3 passed.

- [ ] **Step 4: Make codex delegate to the shared module**

In `scripts/codex_adapter.py`: DELETE the bodies of `_kill_process_tree` (currently ~lines 242–273) and `_run_codex_exec` (currently ~lines 277–310). Replace with a thin shim. Keep the `import os, shutil, signal, subprocess` block as-is except `signal` is no longer needed here (leave it; harmless). Add near the other imports:

```python
from subprocess_util import _kill_process_tree, run_with_tree_kill  # noqa: F401 — _kill_process_tree re-exported for back-compat
```

Replace `_run_codex_exec` with:

```python
def _run_codex_exec(cmd, workdir, auftrag, timeout):
    """Run `codex exec` with whole-tree kill on timeout (shared util). env =
    safe_subprocess_env() so codex inherits only the allowlisted environment."""
    return run_with_tree_kill(cmd, workdir, auftrag, timeout, env=safe_subprocess_env())
```

- [ ] **Step 5: Verify codex tests still green (regression guard = the extraction proof)**

Run: `cd scripts && python -X utf8 -m pytest test_codex_adapter.py test_loop_continuity_realgit.py test_build_review_loop.py test_goal_loop.py -v`
Expected: all pass.

If any test patches `codex_adapter._kill_process_tree` or `codex_adapter._run_codex_exec` and now fails: the patch target moved. Fix by patching `subprocess_util._kill_process_tree` instead, OR keep the timeout-path patch via `codex_adapter.run_with_tree_kill`. (Most codex tests use a fake codex binary, not internal-kill patches — verify with `grep -n "_kill_process_tree\|_run_codex_exec" test_*.py`.)

- [ ] **Step 6: Commit**

```bash
cd C:/Users/domes/AI/dual-bridge
git add scripts/subprocess_util.py scripts/test_subprocess_util.py scripts/codex_adapter.py
git commit -m "refactor: extract process-tree-kill into subprocess_util (shared by builders)"
```

---

## Task 2: Extract `finalize_build` into `adapter_git.py`

The "detect change (working-tree OR self-commit) → commit+push → diff" sequence (codex `run_codex_task` steps 6–7) becomes a shared, result-type-agnostic helper. codex calls it; behavior identical via a `no_change_note` parameter that preserves codex's exact wording.

**Files:**
- Modify: `scripts/adapter_git.py` (add `BuildOutcome` + `finalize_build` + a local `_tail`)
- Modify: `scripts/codex_adapter.py` (steps 6–7 of `run_codex_task` → one `finalize_build` call)
- Modify/Create: `scripts/test_adapter_git_shim.py` (add finalize_build cases) or a new `scripts/test_finalize_build.py`

- [ ] **Step 1: Write the failing test**

Create `scripts/test_finalize_build.py` (uses a real local git repo, mirroring `test_loop_continuity_realgit.py`'s git fixture — read that file for the `_init_repo`/clone helper and reuse it):

```python
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
    out = ag.finalize_build(work, "bridge/task-T1", "main", "T1", "bridge: task T1")
    assert out.status == "done"
    assert out.commit and out.branch == "bridge/task-T1"
    assert "new.py" in out.changed_files
    assert out.diff and "new.py" in out.diff


def test_no_change_returns_done_with_note(tmp_path):
    _, work = _make_origin_and_clone(tmp_path)
    out = ag.finalize_build(work, "bridge/task-T1", "main", "T1", "bridge: task T1",
                            no_change_note="claude gab nur Text, keine Datei-Aenderung")
    assert out.status == "done"
    assert out.branch is None and out.commit is None
    assert out.note == "claude gab nur Text, keine Datei-Aenderung"


def test_self_commit_is_detected_and_pushed(tmp_path):
    _, work = _make_origin_and_clone(tmp_path)
    (work / "self.py").write_text("y = 2\n", encoding="utf-8")
    _git(work, "add", "."); _git(work, "commit", "-m", "self-committed by agent")
    out = ag.finalize_build(work, "bridge/task-T1", "main", "T1", "bridge: task T1")
    assert out.status == "done"
    assert out.commit and "self.py" in out.diff
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd scripts && python -X utf8 -m pytest test_finalize_build.py -v`
Expected: FAIL with `AttributeError: module 'adapter_git' has no attribute 'finalize_build'`.

- [ ] **Step 3: Implement `finalize_build` + `BuildOutcome` in `adapter_git.py`**

Add near the top of `scripts/adapter_git.py` (after imports):

```python
from typing import NamedTuple


class BuildOutcome(NamedTuple):
    status: str                    # "done" | "error"
    branch: str | None
    commit: str | None
    changed_files: list
    diff: str | None
    error_text: str | None
    stderr_excerpt: str | None
    note: str | None


def _tail(text, limit: int = 2000):
    if not text:
        return None
    return text[-limit:]
```

Add at the end of `scripts/adapter_git.py`:

```python
def finalize_build(workdir, branch, base_branch, task_id, commit_msg,
                   no_change_note="nur Text, keine Datei-Aenderung") -> BuildOutcome:
    """Detect a builder's changes (uncommitted working-tree OR a self-commit that
    left HEAD ahead of base), commit+push when needed, and return the diff.

    Shared by the codex and claude builders. Never raises. The self-commit branch
    force-with-lease pushes the agent's own commit so the next round's
    clone_or_pull (reset --hard origin/<branch>) cannot drop it (continuity,
    Codex review MAJOR 2026-06-03).
    """
    changed = _git_status_porcelain(workdir)
    if not changed:
        ahead = _commits_ahead_of_base(workdir, base_branch)
        if ahead:
            diff = _git_diff(workdir, base_branch)
            changed_files = _changed_files_vs_base(workdir, base_branch)
            push = _run_git(workdir, "push", "--force-with-lease", "origin", branch)
            if push.returncode != 0:
                return BuildOutcome("error", branch, ahead[0], changed_files, diff,
                                    f"push fehlgeschlagen (lokaler Commit {ahead[0]} auf B)",
                                    _tail(push.stderr), None)
            return BuildOutcome("done", branch, ahead[0], changed_files, diff,
                                None, None, None)
        return BuildOutcome("done", None, None, [], None, None, None, no_change_note)
    try:
        commit = _git_commit_and_push(workdir, branch, commit_msg)
    except RuntimeError as exc:
        msg = str(exc)
        if msg.startswith("PUSH_FAILED::"):
            _, local_hash, stderr = msg.split("::", 2)
            return BuildOutcome("error", branch, local_hash, changed, None,
                                f"push fehlgeschlagen (lokaler Commit {local_hash} auf B)",
                                _tail(stderr), None)
        return BuildOutcome("error", branch, None, changed, None, msg, None, None)
    diff = _git_diff(workdir, base_branch)
    return BuildOutcome("done", branch, commit, changed, diff, None, None, None)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd scripts && python -X utf8 -m pytest test_finalize_build.py -v`
Expected: 3 passed.

- [ ] **Step 5: Make codex use `finalize_build` (steps 6–7 of `run_codex_task`)**

In `scripts/codex_adapter.py`, replace the block from `# 6. did codex change files?` through the final `return CodexResult(...)` of `run_codex_task` (currently ~lines 416–460) with:

```python
    # 6+7. detect change (working-tree OR self-commit), commit+push, diff —
    #      shared with the claude builder via adapter_git.finalize_build. The
    #      no_change_note preserves codex's exact wording (bit-identical output).
    outcome = adapter_git.finalize_build(
        workdir, branch, base_branch, task_id, f"bridge: task {task_id}",
        no_change_note="codex gab nur Text, keine Datei-Aenderung")
    return CodexResult(status=outcome.status, antwort=antwort, branch=outcome.branch,
                       commit=outcome.commit, changed_files=outcome.changed_files,
                       diff=outcome.diff, error_text=outcome.error_text,
                       stderr_excerpt=outcome.stderr_excerpt, note=outcome.note)
```

- [ ] **Step 6: Verify codex regression suite still green**

Run: `cd scripts && python -X utf8 -m pytest test_codex_adapter.py test_loop_continuity_realgit.py test_build_review_loop.py test_goal_loop.py -v`
Expected: all pass. If a test asserts the old codex no-change note string, it stays identical (we pass the codex wording) — no test change should be needed. If a push-failure-path test fails, compare the BuildOutcome→CodexResult mapping field-by-field against the old inline return.

- [ ] **Step 7: Commit**

```bash
cd C:/Users/domes/AI/dual-bridge
git add scripts/adapter_git.py scripts/codex_adapter.py scripts/test_finalize_build.py
git commit -m "refactor: extract finalize_build into adapter_git (shared commit/push/diff)"
```

---

## Task 3: The `claude_build.py` runner (mechanics, fake-CLI tests)

**Files:**
- Create: `scripts/claude_build.py`
- Create: `scripts/test_claude_build.py`

- [ ] **Step 1: Write the module**

Create `scripts/claude_build.py`:

```python
"""Claude builder adapter for the Dual-Laptop-Bridge — symmetric to codex.

Runs `claude -p` in AGENTIC BUILD mode (tools ON, multi-turn) inside a throwaway
clone and returns a RunnerResult with a git branch/commit/diff, exactly like the
codex builder. Git scaffolding shared via adapter_git; process-tree kill via
subprocess_util. The review-only `claude` adapter (claude_adapter.py) is a
SEPARATE adapter and is untouched — this registers `claude-build`. Pure stdlib.

Hardenings mirror the review adapter (P009) but flip tools ON and turns UP:
disableAllHooks (#1), bypassPermissions (#2, mandatory: with Bash on a permission
prompt would hang on closed stdin), prompt via stdin (#3 / P008), drop
ANTHROPIC_API_KEY → subscription (#4), parse/diff first then exit code (#5/P007 —
for a BUILDER the artifact is the git diff, not the text).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from bridge_common import config_value, safe_subprocess_env
from runners import RunnerResult, register_runner
from subprocess_util import run_with_tree_kill
import adapter_git
from claude_adapter import parse_claude_output  # reuse the P006-tolerant parser

try:  # pragma: no cover - environment dependent
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass


def _build_claude_cmd(claude_exe: str, max_turns: int) -> list[str]:
    """Agentic build invocation. Flags to VERIFY against the real binary at impl
    time (P006): --strict-mcp-config suppressing external MCP, and the exact
    --tools value list for this Claude Code version (see the spec's verification
    section)."""
    return [
        claude_exe, "-p",
        "--output-format", "json",
        "--settings", '{"disableAllHooks": true}',
        "--permission-mode", "bypassPermissions",
        "--max-turns", str(max_turns),
        "--tools", "Read,Write,Edit,Bash,Glob,Grep",
        "--strict-mcp-config",
    ]


def run_claude_build(auftrag, repo, base_branch, task_id, workroot,
                     claude_bin=None, timeout=600, branch=None,
                     workdir_name=None, max_turns=40) -> RunnerResult:
    """Run one build task end-to-end. Never raises (spec contract)."""
    allow = os.environ.get("DUAL_BRIDGE_REPO_ALLOWLIST", "").strip()
    if allow:
        import fnmatch
        patterns = [p.strip() for p in allow.split(",") if p.strip()]
        if not any(fnmatch.fnmatch(repo, pat) for pat in patterns):
            return RunnerResult(status="error",
                                error_text=f"repo nicht in allowlist abgelehnt: {repo}")

    branch = branch or f"bridge/task-{task_id}"
    claude_exe = (claude_bin or os.environ.get("DUAL_BRIDGE_CLAUDE_BIN")
                  or shutil.which("claude"))
    if not claude_exe:
        return RunnerResult(status="error",
                            error_text="claude nicht gefunden — auf B installiert/im PATH?")

    workdir = Path(workroot) / (workdir_name or task_id)
    # Resolve the real base branch every round (master/main, P007/continuity).
    _cred = adapter_git._resolve_https_credential(repo)
    try:
        base_branch = adapter_git._resolve_base_branch(repo, base_branch, _cred)
    finally:
        _cred.cleanup()
    try:
        adapter_git._git_clone_or_pull(repo, base_branch, workdir, prefer_branch=branch)
        adapter_git._git_checkout_branch(workdir, branch)
    except RuntimeError as exc:
        return RunnerResult(status="error", error_text=str(exc))

    cmd = _build_claude_cmd(claude_exe, max_turns)
    # Allowlist-only env drops ANTHROPIC_API_KEY/AUTH_TOKEN → subscription login
    # (P009#4 / reference_dco_brain_api_key_leak); deprecated hook flag kept for
    # older CLIs, the real disable is --settings disableAllHooks above.
    env = safe_subprocess_env({"CLAUDE_CODE_DISABLE_HOOKS": "1"})
    try:
        proc = run_with_tree_kill(cmd, workdir, auftrag, timeout, env=env)
    except subprocess.TimeoutExpired as exc:
        return RunnerResult(status="error",
                            error_text=f"claude timeout nach {timeout}s",
                            stderr_excerpt=_tail(getattr(exc, "stderr", None)))
    except (FileNotFoundError, OSError) as exc:
        return RunnerResult(status="error",
                            error_text=f"claude nicht ausführbar ({claude_exe}): {exc}")

    antwort = parse_claude_output(proc.stdout) or ""
    # The DIFF is the artifact (P007), not the text. finalize_build handles the
    # working-tree AND self-commit paths.
    outcome = adapter_git.finalize_build(
        workdir, branch, base_branch, task_id, f"bridge: task {task_id}",
        no_change_note="claude gab nur Text, keine Datei-Aenderung")

    if outcome.status == "done" and outcome.branch is None and not antwort:
        # No diff AND no text → genuine failure; now the exit code matters.
        return RunnerResult(
            status="error",
            error_text=(f"claude exit {proc.returncode}: leere Antwort, kein Diff"
                        if proc.returncode else "claude: leere Antwort, kein Diff"),
            stderr_excerpt=_tail(proc.stderr))

    note = outcome.note
    if proc.returncode != 0 and outcome.status == "done":
        note = ((note + "; ") if note else "") + \
               f"claude exit {proc.returncode} (ignored: Build vorhanden)"
    return RunnerResult(
        status=outcome.status,
        antwort=antwort or "(claude: kein Text, Build via Diff)",
        branch=outcome.branch, commit=outcome.commit,
        changed_files=outcome.changed_files, diff=outcome.diff,
        error_text=outcome.error_text, stderr_excerpt=outcome.stderr_excerpt,
        note=note)


def _tail(text, limit: int = 2000):
    if not text:
        return None
    return text[-limit:]


def _claude_build_runner(auftrag, fm, workroot):
    task_id = fm.get("task_id")
    if not task_id:
        return RunnerResult(status="error", error_text="task ohne task_id")
    wr = Path(workroot) if workroot is not None else Path.home() / "dual-bridge-work"
    return run_claude_build(
        auftrag=auftrag, repo=fm.get("repo", ""),
        base_branch=fm.get("base_branch", "main"), task_id=task_id, workroot=wr,
        claude_bin=os.environ.get("DUAL_BRIDGE_CLAUDE_BIN") or None,
        timeout=config_value("claude_timeout", "DUAL_BRIDGE_CLAUDE_TIMEOUT", 600, cast=int),
        branch=fm.get("branch"), workdir_name=fm.get("workdir_name"),
        max_turns=config_value("claude_max_turns", "DUAL_BRIDGE_CLAUDE_MAX_TURNS", 40, cast=int),
    )


register_runner("claude-build", _claude_build_runner)
```

- [ ] **Step 2: Write the failing test (fake-claude CLI proves mechanics only — P006)**

Create `scripts/test_claude_build.py`. Reuse the real-git origin/clone helper pattern from `test_finalize_build.py` (copy `_git` + a `_make_origin` that creates a bare origin on main). The fake claude is a tiny python script invoked as the "binary"; it writes a file in its cwd (the workdir) and prints a JSON result, simulating an agentic build:

```python
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
    exits with exit_code. Returned as a [python, script] argv passed as claude_bin
    is not possible (claude_bin is one path), so we write a .py and invoke via a
    cmd/sh shim — simplest: write a python script and pass sys.executable through
    DUAL_BRIDGE_CLAUDE_BIN is also one path. Use a one-file launcher:"""
    script = tmp_path / "fake_claude.py"
    script.write_text(
        "import sys, json, pathlib\n"
        f"open({writes!r}, 'w').write({body!r})\n"
        f"print(json.dumps([{{'type':'result','result':{answer!r}}}]))\n"
        f"sys.exit({exit_code})\n",
        encoding="utf-8")
    # Launch via a shim: on POSIX a shebang; cross-platform we pass the python
    # interpreter as the bin and prepend the script through a wrapper .cmd/.sh.
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


def test_no_change_returns_done_with_note(tmp_path):
    origin = _make_origin(tmp_path)
    # fake writes README.md with the SAME content as base → no diff
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
    assert res.status == "done"  # diff present → exit code ignored (P007)
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
    res = cb.run_claude_build(
        auftrag="x", repo="https://github.com/ok/repo", base_branch="main",
        task_id="T6", workroot=tmp_path / "work",
        claude_bin=str(tmp_path / "nonexistent-claude"), timeout=60)
    assert res.status == "error"
```

Note on the fake bin: `run_claude_build` passes `claude_bin` straight to `run_with_tree_kill` as `cmd[0]`. On Windows a `.cmd` shim is directly executable by `subprocess`; on POSIX the `.sh` shebang. If `subprocess` cannot exec the `.cmd` directly in CI, fall back to setting `claude_bin=sys.executable` and prepend the script path — but the `.cmd`/`.sh` shim is the closest mirror of the real `claude.EXE`/`claude.CMD` and is preferred.

- [ ] **Step 3: Run tests to verify they fail, then pass**

Run: `cd scripts && python -X utf8 -m pytest test_claude_build.py -v`
Expected: with the module from Step 1 present, all 6 pass. If `test_claude_not_found_is_error` raises instead of returning error, ensure the `(FileNotFoundError, OSError)` except in `run_claude_build` wraps the `run_with_tree_kill` call (it does).

- [ ] **Step 4: Verify the adapter registered + whole suite green**

Run: `cd scripts && python -X utf8 -c "import claude_build, runners; print('claude-build' in runners.RUNNERS)"`
Expected: `True`.
Run: `cd scripts && python -X utf8 -m pytest -q`
Expected: green (baseline count + new tests).

- [ ] **Step 5: Commit**

```bash
cd C:/Users/domes/AI/dual-bridge
git add scripts/claude_build.py scripts/test_claude_build.py
git commit -m "feat: claude-build adapter (agentic build via claude -p, fake-CLI tested)"
```

---

## Task 4: Risk-policy entry + drift test

**Files:**
- Modify: `scripts/risk_policy.py:28-31` (the `ADAPTER_CAPABILITY` dict)
- Modify: `scripts/test_risk_policy.py` (or wherever the policy is tested — `grep -l ADAPTER_CAPABILITY test_*.py`)

- [ ] **Step 1: Write the failing test**

Add to the policy test file:

```python
def test_claude_build_is_a_builder():
    import risk_policy as rp
    assert rp.ADAPTER_CAPABILITY["claude-build"] == "build"
    # implement + claude-build is allowed (build == build)
    assert rp.check_task("implement", "claude-build", "add a function") is None
    # review + claude-build is a capability mismatch (R1)
    v = rp.check_task("review", "claude-build", "look at this")
    assert v is not None and v.rule == "level-mismatch"
    # the review-only `claude` adapter is unchanged (still read)
    assert rp.ADAPTER_CAPABILITY["claude"] == "read"
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd scripts && python -X utf8 -m pytest -k "claude_build_is_a_builder" -v`
Expected: FAIL with `KeyError: 'claude-build'`.

- [ ] **Step 3: Add the policy entry**

In `scripts/risk_policy.py`, change the `ADAPTER_CAPABILITY` dict to:

```python
ADAPTER_CAPABILITY = {
    "echo": "read", "claude": "read", "increment": "read",
    "codex": "build", "claude-build": "build",
}
```

- [ ] **Step 4: Run to verify pass + no drift-test regression**

Run: `cd scripts && python -X utf8 -m pytest test_risk_policy.py -v` (adjust filename if different)
Expected: pass, including any existing argparse-choices↔table drift test. If a drift test enumerates allowed `--adapter` choices, add `claude-build` to that argparse `choices=` list (search: `grep -rn "choices=" handoff_write.py loop_driver.py job_poll.py`).

- [ ] **Step 5: Commit**

```bash
cd C:/Users/domes/AI/dual-bridge
git add scripts/risk_policy.py scripts/test_risk_policy.py
git commit -m "feat: risk-policy registers claude-build as a builder (capability=build)"
```

---

## Task 5: Real-binary live proof (manual — P006/P007/P009)

The fake-CLI proves mechanics only. This task verifies the 4 real-binary unknowns and gets a true end-to-end build. **Manual, not a unit test.** Do it on Laptop B (DoMe-Dynamics, where `claude` is `claude.EXE`).

- [ ] **Step 1: Create a throwaway test repo**

Use any small private repo you control, or create one. Set an allowlist so nothing else can be touched:

```bash
export DUAL_BRIDGE_REPO_ALLOWLIST="https://github.com/<you>/<throwaway>*"
```

- [ ] **Step 2: Run a single real build via the runner**

```bash
cd C:/Users/domes/AI/dual-bridge/scripts
python -X utf8 -c "import claude_build, tempfile; from pathlib import Path; \
print(claude_build.run_claude_build( \
  auftrag='Create a file hello.py containing: print(\"hi\")', \
  repo='https://github.com/<you>/<throwaway>', base_branch='main', \
  task_id='live1', workroot=Path(tempfile.mkdtemp()), timeout=900))"
```

Expected: `RunnerResult(status='done', ..., branch='bridge/task-live1', commit=<hash>, ...)` and `hello.py` in the diff.

- [ ] **Step 3: Ground-truth verify (P007)**

```bash
git ls-remote https://github.com/<you>/<throwaway> "refs/heads/bridge/task-live1"
# fetch + show the file actually on the branch:
git fetch <throwaway> bridge/task-live1 && git show FETCH_HEAD:hello.py
```
Expected: the commit exists on the remote branch and `hello.py` has the exact content. **Do not trust the RunnerResult alone.**

- [ ] **Step 4: Verify the 4 unknowns; fix flags if needed**
  - (a) MCP suppressed: confirm no playwright/wiki/notebooklm startup in the run (fast start, no MCP errors). If `--strict-mcp-config` is the wrong flag for this Claude Code version, find the correct one (`claude -p --help | grep -i mcp`) and update `_build_claude_cmd`.
  - (b) `--tools` accepted: if claude rejects the `--tools Read,Write,...` syntax, get the correct form (`claude -p --help | grep -i tool`) and update `_build_claude_cmd`.
  - (c) self-commit vs working-tree: note which path fired (both are handled). If claude self-commits, `finalize_build`'s ahead-path must have pushed it — verify the remote has the commit.
  - (d) JSON shape: if `antwort` came back empty but a build happened, inspect raw stdout and extend `parse_claude_output` (in `claude_adapter.py`) for the observed event shape — the diff still made it `done`, so this is cosmetic but worth fixing.

- [ ] **Step 5: Negative control**

Re-run with an auftrag that asks for nothing buildable (e.g. "Do nothing, just say ok"). Expected: `status='done'`, `branch=None`, note "claude gab nur Text...". Confirms the no-change path is honest.

- [ ] **Step 6: Record the outcome**

If any flag changed in Steps 4: `git commit -am "fix(claude-build): real-binary flag corrections (MCP/tools)"`. Note the verified flags in the spec's verification section (turn `<MCP-Unterdrückung>` into the confirmed flag).

---

## Task 6: DCO miniapp preset (separate repo, surgical commit §7)

The DCO miniapp's compose mask only offers presets; a new adapter needs one. **This is in the DCO repo, not dual-bridge.**

**Files (in `C:/Users/domes/dynamic_central_orchestrator/`):**
- Modify: `miniapp/js/start.js` (`BRIDGE_PRESETS`)
- Modify: `miniapp/js/start.compose.test.js`
- Modify: `tests/test_miniapp_bridge_compose.py`

- [ ] **Step 1: Read the existing presets**

Run: `cd C:/Users/domes/dynamic_central_orchestrator && grep -n "BRIDGE_PRESETS" miniapp/js/start.js` and read the block. Mirror the existing `codex`/implement preset's shape for a new `claude-build` entry (kind=implement, adapter=claude-build).

- [ ] **Step 2: Add the preset + tests**

Add a `claude-build` preset analogous to the codex implement preset (same fields, `adapter: "claude-build"`, a sensible default `body`). Add a JS test in `start.compose.test.js` asserting the new preset exists and only emits R1-valid kind/adapter (implement+claude-build). Add a py case in `test_miniapp_bridge_compose.py` mirroring the existing codex-preset assertion.

- [ ] **Step 3: Run both suites**

Run: `cd C:/Users/domes/dynamic_central_orchestrator && node --test miniapp/js/start.compose.test.js && python -X utf8 -m pytest tests/test_miniapp_bridge_compose.py -q`
Expected: green.

- [ ] **Step 4: Surgical commit (§7 — only these files)**

```bash
cd C:/Users/domes/dynamic_central_orchestrator
git status --short
git add miniapp/js/start.js miniapp/js/start.compose.test.js tests/test_miniapp_bridge_compose.py
git status --short   # confirm no foreign drift staged
git commit -m "feat(bridge-compose): claude-build preset for the dual-bridge mask"
```

Note: a parallel session may be active in this repo (handoff L50) — snapshot `git status --short` first, never `git add -A`.

---

## Task 7: Documentation

**Files (in dual-bridge):**
- Modify: `README.md`, `HOW-TO-USE.md`, `docs/CHANGELOG.md`, `CLAUDE.md`

- [ ] **Step 1: Update the adapter lists**

In `CLAUDE.md` (Task-Initiierung adapter line) and `README.md`/`HOW-TO-USE.md`, add `claude-build` next to `codex`/`claude`/`echo`/`increment`: "`claude-build` (claude baut, committet Branch `bridge/task-<id>` — symmetrisch zu codex)". Document the new env vars `DUAL_BRIDGE_CLAUDE_TIMEOUT` (default 600) and `DUAL_BRIDGE_CLAUDE_MAX_TURNS` (default 40), and `DUAL_BRIDGE_CLAUDE_BIN`. Add a CHANGELOG entry. Update the expected pytest Soll-Zahl (baseline + new tests).

- [ ] **Step 2: Commit**

```bash
cd C:/Users/domes/AI/dual-bridge
git add README.md HOW-TO-USE.md docs/CHANGELOG.md CLAUDE.md
git commit -m "docs: claude-build adapter (usage, env vars, changelog, Soll-Zahl)"
```

---

## Done-Definition
- `claude-build` registered, fake-CLI tests green, whole dual-bridge suite green.
- codex regression suite bit-identical (Tasks 1+2 proof).
- Real-binary live proof passed with ground-truth verification (Task 5), flags confirmed.
- Risk-policy allows implement+claude-build, rejects review+claude-build.
- DCO miniapp offers the preset (separate repo commit).
- Docs + env vars + Soll-Zahl updated.
- A symmetric loop (claude builds on B, codex reviews on A) can be driven end-to-end.
