"""Codex worker adapter for the Dual-Laptop-Bridge (Stage 1).

Owns the real `codex exec` call plus the git clone/branch/commit/push dance.
Knows NOTHING about the bridge (no frontmatter, no Sharepoint paths) -- it takes
a task text + repo and returns a CodexResult. Pure stdlib.

Output parsing follows the L17/P006 lesson (BOM + event-stream + hook noise):
strip a BOM, raw_decode the first JSON value if present, else treat as plain
text. The exact real codex-exec format is verified in the live B run (L20).

codex exec flags (verified against codex-cli 0.133, `codex exec --help`):
  -C <dir>            explicit working root
  -s workspace-write  sandbox that may write inside the workspace
  -o <FILE>           final agent message written to that file (robust; avoids
                      the stdout BOM/event-stream/hook-noise problem entirely)
"""
from __future__ import annotations

import json
import sys

try:  # pragma: no cover - environment dependent
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass


def parse_codex_output(raw: str) -> str:
    """Extract the answer text from codex output, tolerant of BOM, a JSON value
    with trailing non-JSON noise, or plain text. Returns "" if empty."""
    if raw is None:
        return ""
    text = raw.lstrip("﻿").strip()
    if not text:
        return ""
    # Try JSON first (event-stream or single object); ignore trailing junk.
    if text[0] in "{[":
        try:
            value, _ = json.JSONDecoder().raw_decode(text)
        except ValueError:
            value = None
        if value is not None:
            return _answer_from_json(value).strip()
    return text


def _answer_from_json(value: object) -> str:
    """Pull a human answer out of a decoded JSON value. Tolerant of shapes we
    cannot yet pin down (verified against real codex in the B run): try common
    keys, then a final 'result'/'message' event in a list, else stringify."""
    if isinstance(value, dict):
        for key in ("answer", "result", "message", "text", "content", "output"):
            v = value.get(key)
            if isinstance(v, str) and v.strip():
                return v
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        for item in reversed(value):
            if isinstance(item, dict):
                for key in ("result", "message", "text", "content"):
                    v = item.get(key)
                    if isinstance(v, str) and v.strip():
                        return v
        return json.dumps(value, ensure_ascii=False)
    return str(value)


import os
import shutil
import subprocess
from pathlib import Path

from runners import RunnerResult, register_runner

CodexResult = RunnerResult  # back-compat alias; existing call sites unchanged


def _run_git(workdir: Path | None, *args: str) -> subprocess.CompletedProcess:
    """Run a git command, capturing output as utf-8. cwd=workdir if given."""
    cmd = ["git"]
    if workdir is not None:
        cmd += ["-C", str(workdir)]
    cmd += list(args)
    return subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8",
        stdin=subprocess.DEVNULL,
    )


def _git_clone_or_pull(repo: str, base_branch: str, workdir: Path) -> Path:
    """Clone repo@base_branch into workdir (fresh). If workdir exists, fetch+
    reset to origin/base_branch. Raises RuntimeError with stderr on failure."""
    workdir.parent.mkdir(parents=True, exist_ok=True)
    if (workdir / ".git").exists():
        for args in (
            ("fetch", "origin"),
            ("checkout", base_branch),
            ("reset", "--hard", f"origin/{base_branch}"),
        ):
            cp = _run_git(workdir, *args)
            if cp.returncode != 0:
                raise RuntimeError(f"git {args[0]} failed: {cp.stderr.strip()}")
        return workdir
    cp = _run_git(None, "clone", "--branch", base_branch, repo, str(workdir))
    if cp.returncode != 0:
        raise RuntimeError(f"git clone failed: {cp.stderr.strip()}")
    # Ensure a committer identity exists for later commits (CI-less machine).
    _run_git(workdir, "config", "user.email", "bridge@laptop-b.local")
    _run_git(workdir, "config", "user.name", "dual-bridge-worker")
    return workdir


def _git_checkout_branch(workdir: Path, branch: str) -> None:
    """Create/reset the task branch (force, so a repeated task_id is repairable)."""
    cp = _run_git(workdir, "checkout", "-B", branch)
    if cp.returncode != 0:
        raise RuntimeError(f"git checkout -B failed: {cp.stderr.strip()}")


def _git_status_porcelain(workdir: Path) -> list[str]:
    """Return list of changed paths (porcelain). Empty list = clean tree."""
    cp = _run_git(workdir, "status", "--porcelain")
    return [ln[3:].strip() for ln in cp.stdout.splitlines() if ln.strip()]


def _git_commit_and_push(workdir: Path, branch: str, message: str) -> str:
    """Add+commit all changes and push the branch (force-with-lease). Returns
    the commit hash. Raises RuntimeError(stderr) on commit/push failure, but the
    caller catches push failures separately to keep the answer."""
    add = _run_git(workdir, "add", "-A")
    if add.returncode != 0:
        raise RuntimeError(f"git add failed: {add.stderr.strip()}")
    commit = _run_git(workdir, "commit", "-m", message)
    if commit.returncode != 0:
        raise RuntimeError(f"git commit failed: {commit.stderr.strip()}")
    rev = _run_git(workdir, "rev-parse", "--short", "HEAD")
    commit_hash = rev.stdout.strip()
    push = _run_git(workdir, "push", "--force-with-lease", "origin", branch)
    if push.returncode != 0:
        raise RuntimeError(f"PUSH_FAILED::{commit_hash}::{push.stderr.strip()}")
    return commit_hash


def run_codex_task(
    auftrag: str,
    repo: str,
    base_branch: str,
    task_id: str,
    workroot: Path,
    codex_bin: str | None = None,
    timeout: int = 600,
) -> CodexResult:
    """Run one task end-to-end on Laptop B. Every path returns a CodexResult
    with status done|error -- never raises to the caller (spec section 5: no
    stuck, no silent failure)."""
    allow = os.environ.get("DUAL_BRIDGE_REPO_ALLOWLIST", "").strip()
    if allow:
        import fnmatch
        patterns = [p.strip() for p in allow.split(",") if p.strip()]
        if not any(fnmatch.fnmatch(repo, pat) for pat in patterns):
            return CodexResult(status="error",
                               error_text=f"repo nicht in allowlist abgelehnt: {repo}")

    branch = f"bridge/task-{task_id}"

    # 1. codex on PATH?
    codex_exe = codex_bin or shutil.which("codex")
    if not codex_exe:
        return CodexResult(status="error",
                           error_text="codex nicht gefunden -- auf B installiert/im PATH?")

    # 2. repo reachable?
    workdir = Path(workroot) / task_id
    try:
        _git_clone_or_pull(repo, base_branch, workdir)
    except RuntimeError as exc:
        return CodexResult(status="error", error_text=str(exc))

    # 3. task branch
    try:
        _git_checkout_branch(workdir, branch)
    except RuntimeError as exc:
        return CodexResult(status="error", error_text=str(exc))

    # 4. codex exec -- flags verified against codex-cli 0.133 (`codex exec --help`):
    #      -C <workdir>          explicit working root
    #      -s workspace-write    sandbox that may write inside the workspace
    #      -o <answer.txt>       final agent message written to a file (robust;
    #                            avoids the BOM/event-stream/hook-noise stdout
    #                            parsing problem of L17 entirely)
    #    stdin=DEVNULL -> Windows hang guard; prompt passed as the positional arg.
    #    The -o answer file lives OUTSIDE the workdir, so it can never be picked
    #    up by `git status` / committed (cleaner than relying on a post-unlink).
    answer_file = Path(workroot) / f".codex-answer-{task_id}.txt"
    cmd = [
        codex_exe, "exec",
        "-C", str(workdir),
        "-s", "workspace-write",
        "-o", str(answer_file),
        auftrag,
    ]
    try:
        proc = subprocess.run(
            cmd, cwd=str(workdir), capture_output=True, text=True,
            encoding="utf-8", stdin=subprocess.DEVNULL, timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        _safe_unlink(answer_file)
        return CodexResult(status="error",
                           error_text=f"codex timeout nach {timeout}s",
                           stderr_excerpt=_tail(getattr(exc, "stderr", None)))
    except (FileNotFoundError, OSError) as exc:
        # An explicit codex_bin that does not exist (or is not executable) must
        # not raise out of here — the spec guarantees a CodexResult on every path.
        _safe_unlink(answer_file)
        return CodexResult(status="error",
                           error_text=f"codex nicht ausführbar ({codex_exe}): {exc}")
    if proc.returncode != 0:
        _safe_unlink(answer_file)
        return CodexResult(status="error",
                           error_text=f"codex exit {proc.returncode}",
                           stderr_excerpt=_tail(proc.stderr))

    # 5. answer: prefer the -o file, fall back to parsing stdout (both robust).
    antwort = ""
    if answer_file.exists():
        antwort = parse_codex_output(answer_file.read_text(encoding="utf-8-sig"))
        _safe_unlink(answer_file)
    if not antwort:
        antwort = parse_codex_output(proc.stdout)
    if not antwort:
        return CodexResult(status="error", error_text="codex: leere Antwort",
                           stderr_excerpt=_tail(proc.stderr))

    # 6. did codex change files?
    changed = _git_status_porcelain(workdir)
    if not changed:
        return CodexResult(status="done", antwort=antwort, branch=None,
                           commit=None, changed_files=[],
                           note="codex gab nur Text, keine Datei-Aenderung")

    # 7. commit + push (keep answer even if push fails)
    try:
        commit = _git_commit_and_push(workdir, branch, f"bridge: task {task_id}")
    except RuntimeError as exc:
        msg = str(exc)
        if msg.startswith("PUSH_FAILED::"):
            _, local_hash, stderr = msg.split("::", 2)
            return CodexResult(status="error", antwort=antwort, branch=branch,
                               commit=local_hash, changed_files=changed,
                               error_text=f"push fehlgeschlagen (lokaler Commit {local_hash} auf B)",
                               stderr_excerpt=_tail(stderr))
        return CodexResult(status="error", antwort=antwort, branch=branch,
                           changed_files=changed, error_text=msg)
    return CodexResult(status="done", antwort=antwort, branch=branch,
                       commit=commit, changed_files=changed)


def _tail(text: str | None, limit: int = 2000) -> str | None:
    """Last `limit` chars of stderr, for an error excerpt."""
    if not text:
        return None
    return text[-limit:]


def _safe_unlink(path: Path) -> None:
    """Delete a file if present; never raise (best-effort cleanup)."""
    try:
        if path.exists():
            path.unlink()
    except OSError:
        pass


def _codex_runner(auftrag: str, fm: dict, workroot):
    """Adapt run_codex_task to the (auftrag, fm, workroot) runner signature."""
    from pathlib import Path as _P
    wr = _P(workroot) if workroot is not None else _P.home() / "dual-bridge-work"
    return run_codex_task(
        auftrag=auftrag,
        repo=fm.get("repo", ""),
        base_branch=fm.get("base_branch", "main"),
        task_id=fm["task_id"],
        workroot=wr,
        codex_bin=os.environ.get("DUAL_BRIDGE_CODEX_BIN") or None,
        timeout=int(os.environ.get("DUAL_BRIDGE_CODEX_TIMEOUT", "600")),
    )


register_runner("codex", _codex_runner)
