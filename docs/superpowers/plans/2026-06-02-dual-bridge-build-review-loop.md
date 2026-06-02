# Dual-Bridge Stufe 2 — Bau↔Review-Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an asymmetric, self-correcting build↔review loop mode to `loop_driver.py`: A builds code with codex on a stable loop branch, B reviews with claude (`kind:review` → verdict); `accepted` ends the loop, `rejected` iterates the reviewer's gaps onto the same branch, with stagnation + round-timeout + max-rounds safety nets.

**Architecture:** Two small additive changes on the proven Stage-1/2a foundation. (1) `run_codex_task` gets an optional `branch` override so all rounds share one `bridge/loop-<id>` branch (round 2+ checks out `origin/<branch>` so codex sees its own prior work). (2) `loop_driver.py` gets a `--mode {ping-pong, build-review}` switch and a new `run_build_review_loop` function that drives the codex-build / claude-review rounds. The existing `run_loop` (ping-pong) is untouched; the new mode is a separate function. Tests use fake runners (no real CLIs — fakes prove mechanics only, P006/P009).

**Tech Stack:** Python 3 stdlib only, pytest, git CLI. Windows-first (PowerShell + Bash). Drive-synced lanes via `bridge_common`.

---

## Background the implementing engineer needs

This repo is a two-laptop bridge: Laptop A and Laptop B exchange task/result Markdown files (with YAML frontmatter) through a Google-Drive-synced folder. Pure stdlib over the filesystem. Everything runs on Windows.

**Key existing pieces you will touch or call (verified against the code):**

- `scripts/runners.py` — `RunnerResult` dataclass (fields: `status`, `antwort`, `branch`, `commit`, `changed_files`, `error_text`, `stderr_excerpt`, `note`, `verdict`, `verdict_reason`). `RUNNERS` dict; `register_runner(name, fn)`. Runner signature is `(auftrag: str, fm: dict, workroot) -> RunnerResult`.
- `scripts/codex_adapter.py`:
  - `run_codex_task(auftrag, repo, base_branch, task_id, workroot, codex_bin=None, timeout=600) -> RunnerResult` — clones, branches, runs `codex exec`, commits+pushes. Branch is currently hard-derived: `branch = f"bridge/task-{task_id}"` (line 165).
  - `_git_clone_or_pull(repo, base_branch, workdir) -> Path` — clones repo@base_branch, or if workdir exists fetches + `reset --hard origin/base_branch`.
  - `_git_checkout_branch(workdir, branch)` — `git checkout -B branch` (force, from current HEAD).
  - `_run_git(workdir, *args) -> CompletedProcess` — git helper, utf-8, `stdin=DEVNULL`.
  - `_codex_runner(auftrag, fm, workroot)` (line 289) — adapts `run_codex_task` to the runner signature, reading `repo`/`base_branch`/`task_id` from `fm`. Registered as `"codex"`.
- `scripts/loop_driver.py`:
  - `run_loop(seed, max_rounds, adapter, round_timeout, interval=5, b_tick=None) -> dict` — Stage-1 ping-pong loop (do NOT modify its body).
  - `write_round_task(loop_id, round_no, payload, adapter) -> task_id` — writes an open loop task into the send lane.
  - `wait_for_result(task_id, timeout, interval=5) -> dict | None` — polls the send lane inbox for `result-<task_id>.md`.
  - `append_state(loop_id, record)` — append-only JSONL history to `STATE_DIR / LOOP-<loop_id>.jsonl`.
  - `main(argv)` — argparse CLI.
- `scripts/handoff_poll.py`:
  - `parse_verdict(text) -> (verdict, reason)` — extracts `VERDICT: accepted|rejected`, **fail-closed** (no/unknown marker → `rejected`).
  - At lines 147-151: when `fm.get("kind") == "review"` and `result.status == "done"`, sets `result.verdict, result.verdict_reason = parse_verdict(result.antwort)`; the verdict is written into the result frontmatter.
- `scripts/bridge_common.py` — `send_lane()`, `lane_outbox(lane)`, `lane_inbox(lane)`, `this_endpoint()`, `make_task_id()`, `now_iso()`, `ensure_dirs()`, `write_text_utf8()`, `read_text_utf8()`, `parse_frontmatter()`, `build_document()`.

**Test conventions in this repo (follow exactly):**
- `conftest.py` already forces an isolated `DUAL_BRIDGE_ROOT` (tmp) + poison-guard. The drive-leak is fixed. Just write tests; they run isolated.
- A loop-driver test sets the endpoint and reloads: `monkeypatch.setenv("DUAL_BRIDGE_ENDPOINT", "claude@laptop-a")`, then `importlib.reload(bc); import loop_driver; importlib.reload(loop_driver)`, and `monkeypatch.setattr(loop_driver, "STATE_DIR", tmp_path)`.
- A `b_tick` callable simulates B's poll within a test (production B is a separate live poller, so `b_tick=None`).
- Run the full loop suite with: `cd C:/Users/domes/AI/dual-bridge/scripts && python -m pytest test_loop_driver.py -v`

**Regression anchors that MUST stay green throughout:** `test_loop_driver.py`, `test_stage1.py`, `test_hardening.py`, `test_gate_evidence.py`, `test_claude_adapter.py`.

---

## File Structure

- **Modify** `scripts/codex_adapter.py` — add `branch` override param to `run_codex_task`; teach `_git_clone_or_pull` to prefer an existing `origin/<branch>`; let `_codex_runner` pass `fm["branch"]` through. (Tasks 1-2)
- **Modify** `scripts/loop_driver.py` — add `run_build_review_loop`, helper `_build_review_round`, and the `--mode` CLI switch. (Tasks 3-7)
- **Test** `scripts/test_codex_branch_override.py` — new file for the branch-override unit tests. (Tasks 1-2)
- **Test** `scripts/test_build_review_loop.py` — new file for the loop-mode unit tests. (Tasks 3-7)

No other files change. `runners.py`, `handoff_poll.py`, `bridge_common.py` are reused as-is.

---

## Task 1: codex_adapter `run_codex_task` accepts a `branch` override

**Files:**
- Modify: `scripts/codex_adapter.py` (`run_codex_task` signature + branch line ~165, `_git_clone_or_pull` ~91-111)
- Test: `scripts/test_codex_branch_override.py` (create)

The current code always uses `branch = f"bridge/task-{task_id}"` and `_git_clone_or_pull` always resets to `origin/base_branch`. For the loop we need: (a) an explicit branch name, and (b) round 2+ to continue from the *existing* loop branch (not base), so codex sees its prior work.

- [ ] **Step 1: Write the failing test**

Add to `scripts/test_codex_branch_override.py`:

```python
"""Branch-override unit tests for run_codex_task (Stage-2b foundation).
No real codex/git network — we monkeypatch the git helpers and the codex call.
conftest.py isolates DUAL_BRIDGE_ROOT."""
from __future__ import annotations

from pathlib import Path

import codex_adapter as ca


def test_run_codex_task_uses_branch_override(monkeypatch, tmp_path):
    """When branch= is given, that branch name is used, not bridge/task-<id>."""
    used = {}

    def fake_clone(repo, base_branch, workdir):
        (workdir / ".git").mkdir(parents=True, exist_ok=True)
        return workdir

    def fake_checkout(workdir, branch):
        used["checkout_branch"] = branch

    def fake_run(cmd, **kw):  # codex exec is never really called
        raise AssertionError("codex should not run in this unit test")

    monkeypatch.setattr(ca, "_git_clone_or_pull", fake_clone)
    monkeypatch.setattr(ca, "_git_checkout_branch", fake_checkout)
    monkeypatch.setattr(ca.shutil, "which", lambda _n: None)  # force early 'no codex' exit

    res = ca.run_codex_task(
        auftrag="x", repo="r", base_branch="main", task_id="t-1",
        workroot=tmp_path, branch="bridge/loop-abc",
    )
    # We exit at the 'codex not found' guard AFTER branch is decided, so the
    # branch name is what we want to assert via the local variable. Instead we
    # assert through checkout, which runs before the codex guard.
    assert used.get("checkout_branch") == "bridge/loop-abc"
```

Note: `_git_checkout_branch` runs at step 3 of `run_codex_task` (before the codex-exec call at step 4), so forcing `shutil.which` to return `None` is too early. Re-order the assertion: instead make `shutil.which` return a path and stub the subprocess. Use this corrected test body:

```python
def test_run_codex_task_uses_branch_override(monkeypatch, tmp_path):
    """When branch= is given, that exact branch name is checked out."""
    used = {}

    def fake_clone(repo, base_branch, workdir):
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
                        lambda r, b, w: (w / ".git").mkdir(parents=True, exist_ok=True) or w)
    monkeypatch.setattr(ca, "_git_checkout_branch",
                        lambda w, branch: used.__setitem__("b", branch))
    monkeypatch.setattr(ca.shutil, "which", lambda _n: "C:/fake/codex.exe")

    class _Proc:
        returncode = 0; stdout = "done"; stderr = ""
    monkeypatch.setattr(ca.subprocess, "run", lambda *a, **k: _Proc())
    monkeypatch.setattr(ca, "parse_codex_output", lambda _s: "answer")
    monkeypatch.setattr(ca, "_git_status_porcelain", lambda _w: [])

    ca.run_codex_task(auftrag="x", repo="r", base_branch="main",
                      task_id="t-99", workroot=tmp_path)
    assert used.get("b") == "bridge/task-t-99"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd C:/Users/domes/AI/dual-bridge/scripts && python -m pytest test_codex_branch_override.py -v`
Expected: FAIL — `run_codex_task() got an unexpected keyword argument 'branch'`.

- [ ] **Step 3: Add the `branch` parameter**

In `scripts/codex_adapter.py`, change the `run_codex_task` signature (currently ends `..., timeout: int = 600,`) to add the new keyword:

```python
def run_codex_task(
    auftrag: str,
    repo: str,
    base_branch: str,
    task_id: str,
    workroot: Path,
    codex_bin: str | None = None,
    timeout: int = 600,
    branch: str | None = None,
) -> CodexResult:
```

Then replace the branch-derivation line (currently `branch = f"bridge/task-{task_id}"`) with:

```python
    branch = branch or f"bridge/task-{task_id}"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd C:/Users/domes/AI/dual-bridge/scripts && python -m pytest test_codex_branch_override.py -v`
Expected: PASS (both tests).

- [ ] **Step 5: Commit**

```bash
cd C:/Users/domes/AI/dual-bridge
git add scripts/codex_adapter.py scripts/test_codex_branch_override.py
git commit -m "feat(codex): run_codex_task accepts optional branch override

Default unchanged (bridge/task-<id>); loop mode passes bridge/loop-<id>.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: Round 2+ continues from the existing loop branch (not base)

**Files:**
- Modify: `scripts/codex_adapter.py` (`_git_clone_or_pull` ~91-111, and its call site in `run_codex_task` ~176)
- Test: `scripts/test_codex_branch_override.py` (append)

`_git_clone_or_pull` currently always checks out `base_branch` and resets to `origin/base_branch`. When a loop branch already exists on the remote, we must start from it so codex builds on its prior commit. We add a `prefer_branch` arg: if `origin/<prefer_branch>` exists, check it out and reset to it; otherwise fall back to base.

- [ ] **Step 1: Write the failing test**

Append to `scripts/test_codex_branch_override.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd C:/Users/domes/AI/dual-bridge/scripts && python -m pytest test_codex_branch_override.py -k clone_or_pull -v`
Expected: FAIL — `_git_clone_or_pull() got an unexpected keyword argument 'prefer_branch'`.

- [ ] **Step 3: Add `prefer_branch` to `_git_clone_or_pull`**

Replace the existing `_git_clone_or_pull` body's "workdir exists" branch. The full function becomes:

```python
def _git_clone_or_pull(repo: str, base_branch: str, workdir: Path,
                       prefer_branch: str | None = None) -> Path:
    """Clone repo@base_branch into workdir (fresh). If workdir exists, fetch and
    reset. When prefer_branch is given AND exists on origin, reset to it (so the
    loop continues its own prior work); otherwise reset to base_branch. Raises
    RuntimeError with stderr on failure."""
    workdir.parent.mkdir(parents=True, exist_ok=True)
    if (workdir / ".git").exists():
        fetch = _run_git(workdir, "fetch", "origin")
        if fetch.returncode != 0:
            raise RuntimeError(f"git fetch failed: {fetch.stderr.strip()}")
        target = base_branch
        if prefer_branch:
            ls = _run_git(workdir, "ls-remote", "--heads", "origin", prefer_branch)
            if ls.returncode == 0 and ls.stdout.strip():
                target = prefer_branch
        for args in (
            ("checkout", target),
            ("reset", "--hard", f"origin/{target}"),
        ):
            cp = _run_git(workdir, *args)
            if cp.returncode != 0:
                raise RuntimeError(f"git {args[0]} failed: {cp.stderr.strip()}")
        return workdir
    cp = _run_git(None, "clone", "--branch", base_branch, repo, str(workdir))
    if cp.returncode != 0:
        raise RuntimeError(f"git clone failed: {cp.stderr.strip()}")
    _run_git(workdir, "config", "user.email", "bridge@laptop-b.local")
    _run_git(workdir, "config", "user.name", "dual-bridge-worker")
    return workdir
```

Then update the call site in `run_codex_task` (currently `_git_clone_or_pull(repo, base_branch, workdir)`) to forward the loop branch:

```python
        _git_clone_or_pull(repo, base_branch, workdir, prefer_branch=branch)
```

(Place this AFTER the `branch = branch or f"bridge/task-{task_id}"` line so `branch` is resolved. For a fresh clone the prefer_branch is irrelevant — the subsequent `_git_checkout_branch(workdir, branch)` creates it from base via `checkout -B`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd C:/Users/domes/AI/dual-bridge/scripts && python -m pytest test_codex_branch_override.py -v`
Expected: PASS (all four tests).

- [ ] **Step 5: Run the regression anchors**

Run: `cd C:/Users/domes/AI/dual-bridge/scripts && python -m pytest test_stage1.py test_hardening.py test_loop_driver.py test_claude_adapter.py test_gate_evidence.py -q`
Expected: all PASS (Stage-1/2a regression intact).

- [ ] **Step 6: Commit**

```bash
cd C:/Users/domes/AI/dual-bridge
git add scripts/codex_adapter.py scripts/test_codex_branch_override.py
git commit -m "feat(codex): clone/pull continues from existing loop branch

Round 2+ resets to origin/<loop-branch> when present so codex builds on
its own prior commit; falls back to base when the branch is absent.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: `_codex_runner` passes `fm["branch"]` through

**Files:**
- Modify: `scripts/codex_adapter.py` (`_codex_runner` ~289-303)
- Test: `scripts/test_codex_branch_override.py` (append)

The loop drives A's build through the runner registry (`RUNNERS["codex"]`). To use the loop branch, the loop sets `fm["branch"]` and `_codex_runner` forwards it.

- [ ] **Step 1: Write the failing test**

Append to `scripts/test_codex_branch_override.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd C:/Users/domes/AI/dual-bridge/scripts && python -m pytest test_codex_branch_override.py -k codex_runner -v`
Expected: FAIL — `captured.get("branch")` is `None` for the first test (branch not forwarded yet).

- [ ] **Step 3: Forward the branch in `_codex_runner`**

In `_codex_runner`, add `branch=fm.get("branch")` to the `run_codex_task(...)` call:

```python
    return run_codex_task(
        auftrag=auftrag,
        repo=fm.get("repo", ""),
        base_branch=fm.get("base_branch", "main"),
        task_id=task_id,
        workroot=wr,
        codex_bin=os.environ.get("DUAL_BRIDGE_CODEX_BIN") or None,
        timeout=int(os.environ.get("DUAL_BRIDGE_CODEX_TIMEOUT", "600")),
        branch=fm.get("branch"),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd C:/Users/domes/AI/dual-bridge/scripts && python -m pytest test_codex_branch_override.py -v`
Expected: PASS (all six tests).

- [ ] **Step 5: Commit**

```bash
cd C:/Users/domes/AI/dual-bridge
git add scripts/codex_adapter.py scripts/test_codex_branch_override.py
git commit -m "feat(codex): _codex_runner forwards fm['branch'] to run_codex_task

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: `_build_review_round` — one build→review round (happy path)

**Files:**
- Modify: `scripts/loop_driver.py` (add `_build_review_round` near `run_loop`)
- Test: `scripts/test_build_review_loop.py` (create)

A single round: A builds via the codex runner (using fake runners in tests), A writes a `kind:review` task to B, waits for B's result, returns a structured round outcome. We isolate one round so the loop function (Task 5) stays simple.

The round helper takes the runners as injected callables so tests use fakes (no real codex/claude). It returns a dict: `{"status": "...", "verdict": ..., "verdict_reason": ..., "commit": ..., "task_id": ..., "abort_reason": ...}`.

- [ ] **Step 1: Write the failing test**

Create `scripts/test_build_review_loop.py`:

```python
"""Build↔review loop-mode unit tests (Stage-2b). Fake runners only — no real
codex/claude (fakes prove mechanics, not contract: P006/P009). conftest.py
isolates DUAL_BRIDGE_ROOT."""
from __future__ import annotations

import importlib

import bridge_common as bc


def _reload_as_a(monkeypatch, tmp_path):
    monkeypatch.setenv("DUAL_BRIDGE_ENDPOINT", "claude@laptop-a")
    importlib.reload(bc)
    import loop_driver
    importlib.reload(loop_driver)
    monkeypatch.setattr(loop_driver, "STATE_DIR", tmp_path)
    return loop_driver


def test_build_review_round_accepted(monkeypatch, tmp_path):
    """A builds (fake codex, new commit), B reviews (fake → accepted)."""
    ld = _reload_as_a(monkeypatch, tmp_path)
    from runners import RunnerResult

    def fake_build(auftrag, fm, workroot):
        return RunnerResult(status="done", antwort="built",
                            branch="bridge/loop-x", commit="c1",
                            changed_files=["a.py"])

    def fake_b_review(task_id):
        # Simulate B writing a review result with verdict accepted.
        lane = bc.send_lane()
        fm = {"created": bc.now_iso(), "from": "codex@laptop-b",
              "to": "claude@laptop-a", "status": "done", "task_id": task_id,
              "kind": "review", "verdict": "accepted", "verdict_reason": "lgtm"}
        bc.write_text_utf8(bc.lane_inbox(lane) / f"result-{task_id}.md",
                           bc.build_document(fm, "## Antwort\nVERDICT: accepted\n"))

    bc.ensure_dirs()
    out = ld._build_review_round(
        loop_id="loop-x", round_no=0, auftrag="build the thing",
        repo="r", base_branch="main", build_runner=fake_build,
        round_timeout=5, interval=1, b_tick=lambda tid: fake_b_review(tid))
    assert out["status"] == "done"
    assert out["verdict"] == "accepted"
    assert out["commit"] == "c1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd C:/Users/domes/AI/dual-bridge/scripts && python -m pytest test_build_review_loop.py -v`
Expected: FAIL — `module 'loop_driver' has no attribute '_build_review_round'`.

- [ ] **Step 3: Implement `_build_review_round`**

Add to `scripts/loop_driver.py` (after `write_round_task`, before `run_loop`):

```python
def write_review_task(loop_id: str, round_no: int, auftrag: str,
                      loop_branch: str, loop_commit: str) -> str:
    """Write an open kind:review task to B (claude reviewer). Mirrors the
    Stage-1 envelope but adds loop_branch/loop_commit and kind=review."""
    bc.ensure_dirs()
    me = bc.this_endpoint()
    lane = bc.send_lane()
    to = next((ep for ep, cfg in bc.ENDPOINTS.items()
               if lane in cfg["receives_on"]), "")
    task_id = bc.make_task_id()
    fm = {
        "created": bc.now_iso(), "schema_version": "2",
        "agent": me, "from": me, "to": to, "purpose": "handoff",
        "status": "open", "task_id": task_id, "kind": "review",
        "adapter": "claude",
        "loop_id": loop_id, "round": str(round_no),
        "loop_branch": loop_branch, "loop_commit": loop_commit,
        "payload": f"{loop_branch}@{loop_commit}",
        "claimed_by": "", "claimed_at": "",
    }
    body = (f"## Auftrag\n{auftrag}\n\n"
            f"Hol den Branch `{loop_branch}` (Commit `{loop_commit}`):\n"
            f"```\ngit fetch && git checkout {loop_branch}\n```\n"
            "Reviewe den Code. Antworte mit `VERDICT: accepted` oder "
            "`VERDICT: rejected` plus kurzer Begruendung.\n\n"
            "## Ergebnis\n<wird vom Reviewer gefuellt>\n")
    bc.write_text_utf8(bc.lane_outbox(lane) / f"task-{task_id}.md",
                       bc.build_document(fm, body))
    return task_id


def _build_review_round(loop_id, round_no, auftrag, repo, base_branch,
                        build_runner, round_timeout, interval=5, b_tick=None):
    """One build→review round. A builds via build_runner (codex), writes a
    kind:review task to B, waits for B's verdict. Returns an outcome dict.
    `b_tick(task_id)` is a test hook; in production B is a separate poller."""
    loop_branch = f"bridge/loop-{loop_id}"
    fm = {"task_id": bc.make_task_id(), "repo": repo,
          "base_branch": base_branch, "branch": loop_branch}
    try:
        a_res = build_runner(auftrag=auftrag, fm=fm, workroot=None)
    except Exception as exc:  # noqa: BLE001 — a runner must not crash the loop
        return {"status": "error", "abort_reason": f"A-build crash: {exc}",
                "verdict": None, "verdict_reason": None, "commit": None,
                "task_id": ""}
    if a_res.status != "done":
        return {"status": "error",
                "abort_reason": f"A-build error: {a_res.error_text}",
                "verdict": None, "verdict_reason": None, "commit": None,
                "task_id": ""}

    task_id = write_review_task(loop_id, round_no, auftrag,
                                loop_branch, a_res.commit or "")
    if b_tick is not None:
        b_tick(task_id)

    fm_result = wait_for_result(task_id, timeout=round_timeout, interval=interval)
    if fm_result is None:
        return {"status": "timeout", "abort_reason": f"timeout in round {round_no}",
                "verdict": None, "verdict_reason": None,
                "commit": a_res.commit, "task_id": task_id}
    if fm_result.get("status") == "error":
        return {"status": "error", "abort_reason": f"B error in round {round_no}",
                "verdict": None, "verdict_reason": None,
                "commit": a_res.commit, "task_id": task_id}
    return {"status": "done", "abort_reason": "",
            "verdict": fm_result.get("verdict"),
            "verdict_reason": fm_result.get("verdict_reason"),
            "commit": a_res.commit, "task_id": task_id}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd C:/Users/domes/AI/dual-bridge/scripts && python -m pytest test_build_review_loop.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd C:/Users/domes/AI/dual-bridge
git add scripts/loop_driver.py scripts/test_build_review_loop.py
git commit -m "feat(loop): _build_review_round + write_review_task (kind:review)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: `run_build_review_loop` — accepted ends, rejected iterates

**Files:**
- Modify: `scripts/loop_driver.py` (add `run_build_review_loop` after `_build_review_round`)
- Test: `scripts/test_build_review_loop.py` (append)

The driver loop: each round calls `_build_review_round`. `accepted` → success exit. `rejected` → the `verdict_reason` becomes the next round's `auftrag` (the gaps). Append a JSONL trace per round. Bounded by `max_rounds`.

- [ ] **Step 1: Write the failing tests**

Append to `scripts/test_build_review_loop.py`:

```python
def test_loop_accepted_round_one(monkeypatch, tmp_path):
    """accepted in round 0 → loop ends, success, final_commit set."""
    ld = _reload_as_a(monkeypatch, tmp_path)
    from runners import RunnerResult

    def fake_build(auftrag, fm, workroot):
        return RunnerResult(status="done", antwort="b", branch=fm["branch"],
                            commit="c1", changed_files=["a.py"])

    def b_accept(task_id):
        lane = bc.send_lane()
        fm = {"created": bc.now_iso(), "from": "codex@laptop-b",
              "to": "claude@laptop-a", "status": "done", "task_id": task_id,
              "kind": "review", "verdict": "accepted", "verdict_reason": "ok"}
        bc.write_text_utf8(bc.lane_inbox(lane) / f"result-{task_id}.md",
                           bc.build_document(fm, "VERDICT: accepted\n"))

    bc.ensure_dirs()
    summary = ld.run_build_review_loop(
        auftrag="build", repo="r", base_branch="main", max_rounds=5,
        round_timeout=5, interval=1, build_runner=fake_build, b_tick=b_accept)
    assert summary["accepted"] is True
    assert summary["aborted"] is False
    assert summary["rounds_done"] == 1
    assert summary["final_commit"] == "c1"


def test_loop_rejected_then_accepted(monkeypatch, tmp_path):
    """round 0 rejected → A rebuilds with the gaps as the new auftrag →
    round 1 accepted. The rejected reason must reach round 1's build."""
    ld = _reload_as_a(monkeypatch, tmp_path)
    from runners import RunnerResult

    seen_auftrags = []
    commits = iter(["c1", "c2"])

    def fake_build(auftrag, fm, workroot):
        seen_auftrags.append(auftrag)
        return RunnerResult(status="done", antwort="b", branch=fm["branch"],
                            commit=next(commits), changed_files=["a.py"])

    verdicts = iter([("rejected", "missing tests"), ("accepted", "ok now")])

    def b_tick(task_id):
        verdict, reason = next(verdicts)
        lane = bc.send_lane()
        fm = {"created": bc.now_iso(), "from": "codex@laptop-b",
              "to": "claude@laptop-a", "status": "done", "task_id": task_id,
              "kind": "review", "verdict": verdict, "verdict_reason": reason}
        bc.write_text_utf8(bc.lane_inbox(lane) / f"result-{task_id}.md",
                           bc.build_document(fm, f"VERDICT: {verdict}\n"))

    bc.ensure_dirs()
    summary = ld.run_build_review_loop(
        auftrag="build", repo="r", base_branch="main", max_rounds=5,
        round_timeout=5, interval=1, build_runner=fake_build, b_tick=b_tick)
    assert summary["accepted"] is True
    assert summary["rounds_done"] == 2
    # Round 1's auftrag must carry the round-0 rejection reason.
    assert "missing tests" in seen_auftrags[1]


def test_loop_max_rounds_without_accept(monkeypatch, tmp_path):
    """Always rejected, distinct reasons → stops at max_rounds, not accepted."""
    ld = _reload_as_a(monkeypatch, tmp_path)
    from runners import RunnerResult

    n = iter(range(100))
    def fake_build(auftrag, fm, workroot):
        return RunnerResult(status="done", antwort="b", branch=fm["branch"],
                            commit=f"c{next(n)}", changed_files=["a.py"])

    r = iter(range(100))
    def b_reject(task_id):
        lane = bc.send_lane()
        reason = f"still wrong {next(r)}"  # distinct each round → no stagnation
        fm = {"created": bc.now_iso(), "from": "codex@laptop-b",
              "to": "claude@laptop-a", "status": "done", "task_id": task_id,
              "kind": "review", "verdict": "rejected", "verdict_reason": reason}
        bc.write_text_utf8(bc.lane_inbox(lane) / f"result-{task_id}.md",
                           bc.build_document(fm, "VERDICT: rejected\n"))

    bc.ensure_dirs()
    summary = ld.run_build_review_loop(
        auftrag="build", repo="r", base_branch="main", max_rounds=2,
        round_timeout=5, interval=1, build_runner=fake_build, b_tick=b_reject)
    assert summary["accepted"] is False
    assert summary["aborted"] is True
    assert summary["rounds_done"] == 2
    assert "max-rounds" in summary["abort_reason"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd C:/Users/domes/AI/dual-bridge/scripts && python -m pytest test_build_review_loop.py -k loop_ -v`
Expected: FAIL — `module 'loop_driver' has no attribute 'run_build_review_loop'`.

- [ ] **Step 3: Implement `run_build_review_loop`**

Add to `scripts/loop_driver.py` after `_build_review_round`:

```python
def run_build_review_loop(auftrag, repo, base_branch, max_rounds,
                          round_timeout, interval=5, build_runner=None,
                          b_tick=None):
    """Asymmetric build↔review loop. A builds (codex) on a stable loop branch,
    B reviews (claude, kind:review → verdict). accepted ends; rejected feeds the
    reviewer's gaps into the next build. Bounded by max_rounds; stagnation guard
    added in the next task. `build_runner` defaults to the registered codex
    runner; tests inject a fake. Returns a summary dict."""
    if build_runner is None:
        build_runner = runners.RUNNERS["codex"]
    loop_id = _next_loop_id()
    current_auftrag = auftrag
    rounds_done = 0
    accepted = False
    aborted = False
    abort_reason = ""
    final_commit = ""
    open_task_id = ""

    for round_no in range(max_rounds):
        out = _build_review_round(
            loop_id=loop_id, round_no=round_no, auftrag=current_auftrag,
            repo=repo, base_branch=base_branch, build_runner=build_runner,
            round_timeout=round_timeout, interval=interval, b_tick=b_tick)
        append_state(loop_id, {"round": round_no, "side": "build-review",
                               "verdict": out.get("verdict"),
                               "verdict_reason": out.get("verdict_reason"),
                               "commit": out.get("commit"),
                               "task_id": out.get("task_id"),
                               "status": out["status"]})
        if out["status"] != "done":
            aborted, abort_reason = True, out["abort_reason"]
            open_task_id = out.get("task_id", "")
            break
        rounds_done += 1
        final_commit = out.get("commit") or final_commit
        if out["verdict"] == "accepted":
            accepted = True
            break
        # rejected → feed the gaps into the next build
        current_auftrag = (f"{auftrag}\n\nDer Reviewer hat abgelehnt. Behebe:\n"
                           f"{out.get('verdict_reason') or '(keine Begruendung)'}")
    else:
        aborted, abort_reason = True, "max-rounds erreicht, nicht akzeptiert"

    return {
        "loop_id": loop_id, "rounds_done": rounds_done, "accepted": accepted,
        "final_commit": final_commit, "aborted": aborted,
        "abort_reason": abort_reason, "open_task_id": open_task_id,
        "final_branch": f"bridge/loop-{loop_id}",
    }
```

Note on the `for/else`: the `else` runs only when the loop completes without `break`. Since both `accepted` and an abort `break`, the `else` fires exactly when all rounds ran and the last was `rejected` → max-rounds abort. Correct.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd C:/Users/domes/AI/dual-bridge/scripts && python -m pytest test_build_review_loop.py -v`
Expected: PASS (all loop tests).

- [ ] **Step 5: Commit**

```bash
cd C:/Users/domes/AI/dual-bridge
git add scripts/loop_driver.py scripts/test_build_review_loop.py
git commit -m "feat(loop): run_build_review_loop — accepted ends, rejected iterates

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: Stagnation guard (commit unchanged OR verdict_reason repeats) + fail-closed

**Files:**
- Modify: `scripts/loop_driver.py` (`run_build_review_loop` — add stagnation checks)
- Test: `scripts/test_build_review_loop.py` (append)

Two early-abort signals before max-rounds: (a) the build produced the same commit as the previous round (A changed nothing), (b) the reviewer's `verdict_reason` is identical to the previous round (B repeats itself). Also verify fail-closed: a missing verdict (None) is treated as rejected, never accepted.

- [ ] **Step 1: Write the failing tests**

Append to `scripts/test_build_review_loop.py`:

```python
def test_loop_aborts_on_unchanged_commit(monkeypatch, tmp_path):
    """Same commit hash two rounds running → early 'stagniert' abort."""
    ld = _reload_as_a(monkeypatch, tmp_path)
    from runners import RunnerResult

    def fake_build(auftrag, fm, workroot):
        return RunnerResult(status="done", antwort="b", branch=fm["branch"],
                            commit="SAME", changed_files=[])  # never changes

    def b_reject(task_id):
        lane = bc.send_lane()
        fm = {"created": bc.now_iso(), "from": "codex@laptop-b",
              "to": "claude@laptop-a", "status": "done", "task_id": task_id,
              "kind": "review", "verdict": "rejected", "verdict_reason": f"r{task_id[-2:]}"}
        bc.write_text_utf8(bc.lane_inbox(lane) / f"result-{task_id}.md",
                           bc.build_document(fm, "VERDICT: rejected\n"))

    bc.ensure_dirs()
    summary = ld.run_build_review_loop(
        auftrag="build", repo="r", base_branch="main", max_rounds=5,
        round_timeout=5, interval=1, build_runner=fake_build, b_tick=b_reject)
    assert summary["accepted"] is False
    assert summary["aborted"] is True
    assert "stagn" in summary["abort_reason"].lower()
    assert summary["rounds_done"] == 2  # round 0 built, round 1 same commit → abort


def test_loop_aborts_on_repeated_reason(monkeypatch, tmp_path):
    """Identical verdict_reason two rounds running → early 'stagniert' abort."""
    ld = _reload_as_a(monkeypatch, tmp_path)
    from runners import RunnerResult

    n = iter(range(100))
    def fake_build(auftrag, fm, workroot):
        return RunnerResult(status="done", antwort="b", branch=fm["branch"],
                            commit=f"c{next(n)}", changed_files=["a.py"])

    def b_reject_same(task_id):
        lane = bc.send_lane()
        fm = {"created": bc.now_iso(), "from": "codex@laptop-b",
              "to": "claude@laptop-a", "status": "done", "task_id": task_id,
              "kind": "review", "verdict": "rejected",
              "verdict_reason": "always the same"}
        bc.write_text_utf8(bc.lane_inbox(lane) / f"result-{task_id}.md",
                           bc.build_document(fm, "VERDICT: rejected\n"))

    bc.ensure_dirs()
    summary = ld.run_build_review_loop(
        auftrag="build", repo="r", base_branch="main", max_rounds=5,
        round_timeout=5, interval=1, build_runner=fake_build, b_tick=b_reject_same)
    assert summary["aborted"] is True
    assert "stagn" in summary["abort_reason"].lower()
    assert summary["rounds_done"] == 2


def test_loop_missing_verdict_is_not_accepted(monkeypatch, tmp_path):
    """A result with no verdict field (None) must NOT count as accepted."""
    ld = _reload_as_a(monkeypatch, tmp_path)
    from runners import RunnerResult

    n = iter(range(100))
    def fake_build(auftrag, fm, workroot):
        return RunnerResult(status="done", antwort="b", branch=fm["branch"],
                            commit=f"c{next(n)}", changed_files=["a.py"])

    def b_no_verdict(task_id):
        lane = bc.send_lane()
        fm = {"created": bc.now_iso(), "from": "codex@laptop-b",
              "to": "claude@laptop-a", "status": "done", "task_id": task_id,
              "kind": "review"}  # NO verdict key
        bc.write_text_utf8(bc.lane_inbox(lane) / f"result-{task_id}.md",
                           bc.build_document(fm, "no marker here\n"))

    bc.ensure_dirs()
    summary = ld.run_build_review_loop(
        auftrag="build", repo="r", base_branch="main", max_rounds=2,
        round_timeout=5, interval=1, build_runner=fake_build, b_tick=b_no_verdict)
    assert summary["accepted"] is False  # None verdict never accepts
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd C:/Users/domes/AI/dual-bridge/scripts && python -m pytest test_build_review_loop.py -k "stagn or unchanged or repeated or missing_verdict" -v`
Expected: FAIL — the stagnation tests fail (loop runs to max-rounds instead of aborting early). `test_loop_missing_verdict_is_not_accepted` may already pass (None != "accepted"), but keep it as a guard.

- [ ] **Step 3: Add the stagnation guard**

In `run_build_review_loop`, track the previous commit and reason. Add before the `for` loop:

```python
    prev_commit = None
    prev_reason = None
```

Inside the loop, AFTER `rounds_done += 1` and `final_commit = ...`, but BEFORE the `if out["verdict"] == "accepted":` check, insert:

```python
        if prev_commit is not None and out.get("commit") == prev_commit:
            aborted, abort_reason = True, "stagniert (kein neuer Commit)"
            break
        prev_commit = out.get("commit")
```

Then change the rejected branch (the code after the `accepted` check) to add the reason-repeat guard:

```python
        # rejected
        reason = out.get("verdict_reason")
        if prev_reason is not None and reason == prev_reason:
            aborted, abort_reason = True, "stagniert (Reviewer wiederholt sich)"
            break
        prev_reason = reason
        current_auftrag = (f"{auftrag}\n\nDer Reviewer hat abgelehnt. Behebe:\n"
                           f"{reason or '(keine Begruendung)'}")
```

(The `accepted` check stays `if out["verdict"] == "accepted": accepted = True; break` — `None` never equals `"accepted"`, so fail-closed holds.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd C:/Users/domes/AI/dual-bridge/scripts && python -m pytest test_build_review_loop.py -v`
Expected: PASS (all build-review tests).

- [ ] **Step 5: Commit**

```bash
cd C:/Users/domes/AI/dual-bridge
git add scripts/loop_driver.py scripts/test_build_review_loop.py
git commit -m "feat(loop): stagnation guard (unchanged commit / repeated reason)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 7: `--mode build-review` CLI wiring

**Files:**
- Modify: `scripts/loop_driver.py` (`main` argparse + dispatch ~183-227)
- Test: `scripts/test_build_review_loop.py` (append)

Add a `--mode {ping-pong, build-review}` flag (default `ping-pong`). For `build-review`, require `--repo`; `--seed` is reused as the initial build auftrag. The ping-pong path stays exactly as today.

- [ ] **Step 1: Write the failing test**

Append to `scripts/test_build_review_loop.py`:

```python
def test_main_build_review_requires_repo(monkeypatch, tmp_path, capsys):
    """--mode build-review without --repo exits non-zero with a clear message."""
    ld = _reload_as_a(monkeypatch, tmp_path)
    # Singleton lock would otherwise interfere; point it at tmp.
    monkeypatch.setattr(ld.bc, "default_lock_path",
                        lambda: tmp_path / "x.lock")
    rc = ld.main(["--mode", "build-review", "--max-rounds", "1",
                  "--seed", "build it"])
    assert rc != 0
    out = capsys.readouterr().out
    assert "repo" in out.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd C:/Users/domes/AI/dual-bridge/scripts && python -m pytest test_build_review_loop.py -k main_build_review -v`
Expected: FAIL — `--mode` is not a recognised argument (argparse SystemExit) or no repo guard.

- [ ] **Step 3: Wire the CLI**

In `loop_driver.main`, add these arguments (after the existing `--interval` arg):

```python
    parser.add_argument("--mode", default="ping-pong",
                        choices=["ping-pong", "build-review"],
                        help="ping-pong (Stage 1) or build-review (Stage 2b).")
    parser.add_argument("--repo", default="",
                        help="Repo URL/path to build in (build-review mode).")
    parser.add_argument("--base-branch", default="main",
                        help="Base branch to start the loop branch from.")
```

Then, after `args = parser.parse_args(argv)` and after acquiring the singleton lock, branch on the mode. Replace the existing single `summary = run_loop(...)` block with:

```python
    if args.mode == "build-review":
        if not args.repo:
            print("[A] --mode build-review braucht --repo.")
            return 2
        print(f"[A] Build-Review-Loop: repo={args.repo} "
              f"base={args.base_branch} max_rounds={args.max_rounds}")
        try:
            summary = run_build_review_loop(
                auftrag=args.seed, repo=args.repo, base_branch=args.base_branch,
                max_rounds=args.max_rounds, round_timeout=args.round_timeout,
                interval=args.interval, build_runner=None, b_tick=None)
        except KeyboardInterrupt:
            print("\n[A] Strg+C — Loop abgebrochen.")
            return 1
        print("=" * 60)
        print(f"[A] Build-Review-Loop {summary['loop_id']} fertig.")
        print(f"    Runden: {summary['rounds_done']}/{args.max_rounds}")
        print(f"    Akzeptiert: {summary['accepted']}")
        print(f"    Branch: {summary['final_branch']} @ {summary['final_commit']}")
        if summary["aborted"]:
            print(f"    ABGEBROCHEN: {summary['abort_reason']}")
            if summary["open_task_id"]:
                print(f"    Offener Task: {summary['open_task_id']}")
        print(f"    History: {STATE_DIR / ('LOOP-' + summary['loop_id'] + '.jsonl')}")
        print("=" * 60)
        return 0 if summary["accepted"] else 1

    try:
        summary = run_loop(seed=args.seed, max_rounds=args.max_rounds,
                           adapter=args.adapter,
                           round_timeout=args.round_timeout,
                           interval=args.interval, b_tick=None)
    except KeyboardInterrupt:
        print("\n[A] Strg+C -- Loop abgebrochen.")
        return 1
```

(Keep the rest of the existing ping-pong print block unchanged below this.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd C:/Users/domes/AI/dual-bridge/scripts && python -m pytest test_build_review_loop.py -v`
Expected: PASS.

- [ ] **Step 5: Full regression + new suite**

Run: `cd C:/Users/domes/AI/dual-bridge/scripts && python -m pytest -q`
Expected: ALL pass — existing suites (Stage-1/2a, hardening, gate-evidence, claude-adapter) plus the two new files. Confirm `test_loop_driver.py` (72 anchors) is fully green.

- [ ] **Step 6: Commit**

```bash
cd C:/Users/domes/AI/dual-bridge
git add scripts/loop_driver.py scripts/test_build_review_loop.py
git commit -m "feat(loop): --mode build-review CLI wiring

Default ping-pong unchanged; build-review needs --repo, reuses --seed as the
initial build auftrag. Returns 0 on accepted, 1 otherwise.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 8: Live proof (separate step — NOT a unit test, P007)

**Files:** none (operational verification, like Stage 1)

This is the Ground-Truth proof the spec requires. It runs real codex (build) and real claude (review) over the live bridge. Do NOT fold it into the pytest suite — it needs both laptops and real CLIs (P006/P009: fakes prove mechanics only).

- [ ] **Step 1: Pick a tiny, safe throwaway target**

Use a disposable repo or a scratch branch where a trivial change is reviewable (e.g. "add a one-line docstring to `scripts/runners.py`"). NOT a production repo (global rule 7/15 — no auto-merge, the human merges).

- [ ] **Step 2: Ensure B's claude reviewer is live**

On Laptop B: `handoff_poll.py --watch` running, `DUAL_BRIDGE_ENDPOINT=codex@laptop-b`, claude reachable (the 5 hardenings from P009 are already in `claude_adapter`).

- [ ] **Step 3: Run the loop on A**

```bash
cd C:/Users/domes/AI/dual-bridge/scripts
python loop_driver.py --mode build-review --repo <throwaway-repo> \
    --base-branch main --max-rounds 2 --seed "Add a one-line module docstring to runners.py" \
    --round-timeout 300
```

- [ ] **Step 4: Verify Ground-Truth (P007 — do NOT trust the exit code alone)**

- `git fetch && git show origin/bridge/loop-<id>:scripts/runners.py` → the docstring change is byte-real on the remote branch.
- The reviewer's result file in the lane `_processed/` ends with a real `VERDICT:` marker and a plausible reason (read it, don't just trust the parsed field).
- The result's `claimed_by` shows B's real device id (not a fake).
- The JSONL history (`state/LOOP-<id>.jsonl`) has one row per round with the verdict.

- [ ] **Step 5: Record the proof**

Write a short session note under `~/wiki/wiki/queries/YYYY-MM-DD-session-dual-bridge-build-review-loop.md` with the loop_id, branch/commit, verdict, device id, and round latency. Update the central handoff + status board at wrap-up.

---

## Task 9: Stable loop workdir (fix cross-round continuity — REAL git)

**Files:**
- Modify: `scripts/codex_adapter.py` (`run_codex_task` workdir derivation ~185; `_codex_runner` ~289)
- Modify: `scripts/loop_driver.py` (`_build_review_round` — pass a stable workroot)
- Test: `scripts/test_loop_continuity_realgit.py` (create — uses a REAL local git repo, no fake_build)

**Why:** The final holistic review found that `run_codex_task` derives `workdir = Path(workroot) / task_id`. Because every loop round mints a new `task_id`, every round gets a fresh non-existent workdir → `_git_clone_or_pull` always takes the clone-from-base path and the `prefer_branch` continuity path (Task 2) is never reached. codex rebuilds from base each round; only the reviewer's prompt text carries forward, not the prior code. The build-review unit tests missed this because they inject `fake_build`, which ignores `workroot`. This task fixes continuity and proves it with a REAL git repo.

**Design:** `run_codex_task` gets an optional `workdir_name: str | None = None` (default → `task_id`, so Stage-1 is unchanged). For loop tasks, the workdir name is derived from the loop branch so it is STABLE across rounds. The loop passes a real `workroot`. Round 2+ then finds the existing `.git`, enters the `prefer_branch` path, resets to `origin/<loop-branch>`, and codex builds on its prior commit. Note: the subsequent `_git_checkout_branch(workdir, branch)` does `checkout -B branch` from the now-correct HEAD (already `branch`@prior-commit), which is idempotent — no change to `_git_checkout_branch` needed.

- [ ] **Step 1: Write the failing REAL-git test**

Create `scripts/test_loop_continuity_realgit.py`:

```python
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
    """Patch codex's subprocess so 'codex' appends a line to f.txt in the
    workdir (a real file change → real commit), and writes an answer. Returns
    the changed-file so the commit/push path runs for real."""
    real_run = ca.subprocess.run

    def fake_run(cmd, **kw):
        # cmd is the codex exec invocation with -C <workdir>
        cwd = kw.get("cwd")
        workdir = Path(cwd)
        # append a unique line so each round makes a real, distinct change
        f = workdir / "f.txt"
        f.write_text(f.read_text(encoding="utf-8") + line_holder[0] + "\n",
                     encoding="utf-8")
        class _P:
            returncode = 0
            stdout = "ok"
            stderr = ""
        # write the -o answer file if requested
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

    # Round 1: fresh clone from main, build on the loop branch, push.
    r1 = ca.run_codex_task(auftrag="build", repo=origin, base_branch="main",
                           task_id="t1", workroot=workroot,
                           branch="bridge/loop-X", workdir_name="loop-X")
    assert r1.status == "done", r1.error_text
    assert r1.commit

    # Round 2: SAME workdir_name → existing .git → prefer_branch pulls the loop
    # branch → round 2 sees round 1's f.txt and adds to it.
    line[0] = "round2-line"
    r2 = ca.run_codex_task(auftrag="build more", repo=origin, base_branch="main",
                           task_id="t2", workroot=workroot,
                           branch="bridge/loop-X", workdir_name="loop-X")
    assert r2.status == "done", r2.error_text
    assert r2.commit and r2.commit != r1.commit

    # PROOF: the workdir's f.txt contains BOTH round lines → continuity holds.
    workdir = workroot / "loop-X"
    content = (workdir / "f.txt").read_text(encoding="utf-8")
    assert "round1-line" in content, "round 2 lost round 1's work (continuity broken)"
    assert "round2-line" in content
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd C:/Users/domes/AI/dual-bridge/scripts && python -m pytest test_loop_continuity_realgit.py -v`
Expected: FAIL — `run_codex_task() got an unexpected keyword argument 'workdir_name'`.

- [ ] **Step 3: Add `workdir_name` to `run_codex_task`**

In `run_codex_task`, add the parameter after `branch`:
```python
    branch: str | None = None,
    workdir_name: str | None = None,
```
Change the workdir derivation line `workdir = Path(workroot) / task_id` to:
```python
    workdir = Path(workroot) / (workdir_name or task_id)
```

- [ ] **Step 4: Forward it in `_codex_runner`**

In `_codex_runner`, pass a loop-stable name when the task carries a loop branch. After the existing `branch=fm.get("branch"),` line in the `run_codex_task(...)` call, add:
```python
        workdir_name=fm.get("workdir_name"),
```
And the loop will set `fm["workdir_name"]` (next step). For non-loop tasks `fm.get("workdir_name")` is `None` → defaults to `task_id` (Stage-1 unchanged).

- [ ] **Step 5: Make the loop pass a stable workroot + workdir_name**

In `scripts/loop_driver.py` `_build_review_round`, the `fm` dict (currently `{"task_id": ..., "repo": repo, "base_branch": base_branch, "branch": loop_branch}`) gains a stable workdir name, and the build call passes a real workroot derived from loop_id. Replace the build setup:
```python
    loop_branch = f"bridge/{loop_id}"
    fm = {"task_id": bc.make_task_id(), "repo": repo,
          "base_branch": base_branch, "branch": loop_branch,
          "workdir_name": loop_id}
    workroot = STATE_DIR / "work"
    try:
        a_res = build_runner(auftrag=auftrag, fm=fm, workroot=workroot)
```
(`STATE_DIR / "work"` is local, gitignored under `scripts/state/`. `workdir_name=loop_id` is stable across rounds, so round 2+ reuses `STATE_DIR/work/<loop_id>`.)

- [ ] **Step 6: Run the real-git test + full suite**

Run: `cd C:/Users/domes/AI/dual-bridge/scripts && python -m pytest test_loop_continuity_realgit.py -v`
Expected: PASS — both round lines present (continuity holds).
Run: `cd C:/Users/domes/AI/dual-bridge/scripts && python -m pytest -q`
Expected: ALL pass (Stage-1 + build-review unit tests + the new real-git test). The build-review fakes ignore `workroot`, so they stay green; Stage-1 codex path defaults `workdir_name` to `task_id`, unchanged.

- [ ] **Step 7: Commit**

```bash
cd C:/Users/domes/AI/dual-bridge
git add scripts/codex_adapter.py scripts/loop_driver.py scripts/test_loop_continuity_realgit.py
git commit -m "fix(loop): stable loop workdir so codex builds on its prior commit

run_codex_task derived workdir from task_id; each round had a new task_id, so
the prefer_branch continuity path was never reached and codex rebuilt from base.
Add workdir_name (default task_id → Stage-1 unchanged); the loop passes loop_id
as a stable name + a real workroot. Proven with a REAL local-git test that fakes
could not catch.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review (completed by plan author)

**Spec coverage:**
- Asymmetric loop (A=codex, B=claude) → Tasks 4-7. ✓
- Git-branch artifact, stable loop branch → Tasks 1-3 (branch override) + Task 4 (`bridge/loop-<id>`). ✓
- accepted ends / rejected iterates with gaps → Task 5. ✓
- Three safety layers: stagnation (commit + reason) → Task 6; round_timeout → reused in `_build_review_round` (Task 4) + tested via existing `wait_for_result`; max-rounds → Task 5. ✓
- fail-closed (no marker → rejected, never accepted) → Task 6 (`test_loop_missing_verdict_is_not_accepted`) + relies on existing `parse_verdict` in `handoff_poll`. ✓
- Stage-1 + ping-pong regression green → regression run in Task 2 step 5, Task 7 step 5. ✓
- Live proof, Ground-Truth → Task 8. ✓

**Placeholder scan:** No TBD/TODO; every code step shows full code; every command has expected output. Task 1 explicitly corrects an early-draft test body inline rather than leaving an ambiguous one. ✓

**Type/name consistency:** `run_codex_task(..., branch=)`, `_git_clone_or_pull(..., prefer_branch=)`, `_codex_runner` reads `fm["branch"]`, `write_review_task`, `_build_review_round`, `run_build_review_loop` — names used identically across tasks. Summary dict keys (`accepted`, `aborted`, `abort_reason`, `rounds_done`, `final_commit`, `final_branch`, `open_task_id`, `loop_id`) consistent between Task 5/6/7. ✓
