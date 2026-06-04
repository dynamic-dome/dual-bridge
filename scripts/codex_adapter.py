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
    # NDJSON path (codex exec --json emits one JSON event per line). Parse each
    # non-empty line with raw_decode (BOM-tolerant) and collect what decodes.
    # ONLY treat the stream as NDJSON when >1 event actually decodes -- a single,
    # possibly pretty-printed JSON object that merely contains "\n" must NOT be
    # misread as NDJSON, so it falls through to the single raw_decode path below.
    if text[0] in "{[" and "\n" in text:
        events = []
        ndjson = True
        for line in text.splitlines():
            line = line.lstrip("﻿").strip()
            if not line:
                continue
            if line[0] not in "{[":
                continue  # trailing hook noise -> not an event, ignore
            try:
                value, end = json.JSONDecoder().raw_decode(line)
            except ValueError:
                continue  # undecodable line -> skip, do not abort the stream
            # A genuine NDJSON line is a COMPLETE JSON value: raw_decode must
            # consume essentially the whole line. If a line is only the partial
            # start of a value (e.g. "[" or "{" of a pretty-printed array/object
            # spanning lines), this is NOT NDJSON -> fall through to single path.
            if end < len(line.rstrip().rstrip(",")):
                ndjson = False
                break
            events.append(value)
        if ndjson and len(events) > 1:
            # Q3b: pick the last event that carries a REAL answer key. A trailing
            # metadata event (turn.completed/usage) has no answer -> must not be
            # stringified and returned as if it were the answer.
            for value in reversed(events):
                ans = _strict_answer_from_event(value)
                if ans:
                    return ans
            return ""
    # Single JSON value (event-stream array or single object); ignore trailing junk.
    if text[0] in "{[":
        try:
            value, _ = json.JSONDecoder().raw_decode(text)
        except ValueError:
            value = None
        if value is not None:
            return _answer_from_json(value).strip()
    return text


# Known NON-answer NDJSON event 'type' values (status / lifecycle / usage /
# error). We use a DENYLIST, not an allowlist (Codex-Verifier Q3b round 3): a
# closed answer-type allowlist would silently DROP a real answer carried by an
# event type we did not foresee (e.g. message.output_text.delta). Denylisting
# the known metadata types instead means an UNKNOWN type is still mined for an
# answer key -- fail toward preserving the answer, not losing it. Substring
# match catches the whole families (turn.*, thread.*, *.failed, error.*).
_NON_ANSWER_TYPE_SUBSTR = (
    "thread.started", "thread.", "turn.started", "turn.completed", "turn.failed",
    "turn.", "usage", "error", ".failed", ".aborted", ".cancelled", "rate_limit",
    "tool_call", "reasoning",
)


def _is_non_answer_type(etype: str) -> bool:
    low = etype.lower()
    return any(s in low for s in _NON_ANSWER_TYPE_SUBSTR)


def _strict_answer_from_event(value: object) -> str:
    """Answer text from ONE NDJSON event, or "" if it carries none.

    Unlike _answer_from_json this never falls back to json.dumps(value): a
    metadata-only event (turn.completed/usage/thread.started) must yield "" so
    the NDJSON selector skips it instead of mistaking its serialisation for the
    answer (Codex-Verifier Q3b).

    A declared metadata 'type' (denylisted family above) yields "" so a trailing
    status/error event cannot shadow the real answer. ANY other type -- known or
    not -- is mined for an answer key, so an unforeseen answer-bearing type is
    never silently dropped."""
    if not isinstance(value, dict):
        return ""
    etype = value.get("type")
    if isinstance(etype, str) and _is_non_answer_type(etype):
        return ""  # declared metadata/status/error event -> skip
    for key in ("answer", "result", "message", "text", "content", "output"):
        v = value.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    for key in ("item", "agent_message"):
        sub = value.get(key)
        if isinstance(sub, dict):
            for k in ("text", "result", "message", "content"):
                v = sub.get(k)
                if isinstance(v, str) and v.strip():
                    return v.strip()
        elif isinstance(sub, str) and sub.strip():
            return sub.strip()
    return ""


def _answer_from_json(value: object) -> str:
    """Pull a human answer out of a decoded JSON value. Tolerant of shapes we
    cannot yet pin down (verified against real codex in the B run): try common
    keys, then a final 'result'/'message' event in a list, else stringify."""
    if isinstance(value, dict):
        for key in ("answer", "result", "message", "text", "content", "output"):
            v = value.get(key)
            if isinstance(v, str) and v.strip():
                return v
        # NDJSON event shapes: codex item.completed wraps the answer in an
        # "item" sub-dict; an agent_message event carries it directly. Look one
        # level deeper before stringifying so the real answer is not lost.
        for key in ("item", "agent_message"):
            sub = value.get(key)
            if isinstance(sub, dict):
                for k in ("text", "result", "message", "content"):
                    v = sub.get(k)
                    if isinstance(v, str) and v.strip():
                        return v
            elif isinstance(sub, str) and sub.strip():
                return sub
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

from bridge_common import safe_subprocess_env
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
        stdin=subprocess.DEVNULL, env=safe_subprocess_env(),
    )


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
    # On a FRESH clone, prefer the loop branch if it already exists on origin, so
    # the OTHER side's prior work continues instead of restarting from base. This
    # is the ping-pong continuity seam: A built on bridge/<loop_id> and pushed it;
    # B's workdir is fresh, so without this it would clone base and silently drop
    # A's commit (the next builder's work must build ON the handoff, not beside
    # it). The fetch/reset branch above already honoured prefer_branch for an
    # existing workdir; this closes the same gap for the first clone.
    clone_branch = base_branch
    if prefer_branch:
        ls = _run_git(None, "ls-remote", "--heads", repo, prefer_branch)
        if ls.returncode == 0 and ls.stdout.strip():
            clone_branch = prefer_branch
    cp = _run_git(None, "clone", "--branch", clone_branch, repo, str(workdir))
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


def _commits_ahead_of_base(workdir: Path, base_branch: str) -> list[str]:
    """Short hashes of commits on HEAD not yet on origin/base (newest first).

    codex-cli 0.136 under -s danger-full-access may commit its OWN change, which
    leaves the working tree clean — so `git status --porcelain` says "nothing
    changed" while HEAD is genuinely ahead of origin/base. Detecting progress by
    porcelain status alone then drops a real, committed build (seed-02 round-2
    empty-diff bug, 2026-06-03). This counts the committed-but-unpushed work the
    porcelain check is blind to. Empty list = HEAD really is at origin/base."""
    cp = _run_git(workdir, "rev-list", f"origin/{base_branch}..HEAD")
    if cp.returncode != 0:
        return []
    return [ln.strip()[:7] for ln in cp.stdout.splitlines() if ln.strip()]


def _changed_files_vs_base(workdir: Path, base_branch: str) -> list[str]:
    """Files changed between origin/base and HEAD (for a self-committed build,
    where `git status --porcelain` is clean but commits carry the real change)."""
    cp = _run_git(workdir, "diff", "--name-only", f"origin/{base_branch}...HEAD")
    if cp.returncode != 0:
        return []
    return [ln.strip() for ln in cp.stdout.splitlines() if ln.strip()]


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


_DIFF_LIMIT = 60_000  # chars; over this we truncate the review payload honestly


def _git_diff(workdir: Path, base_branch: str) -> str:
    """Unified diff of the build vs base (origin/base...HEAD). Truncated to
    _DIFF_LIMIT with an explicit marker (never a silent cap)."""
    cp = _run_git(workdir, "diff", f"origin/{base_branch}...HEAD")
    text = cp.stdout or ""
    if len(text) > _DIFF_LIMIT:
        text = (text[:_DIFF_LIMIT]
                + f"\n\n[... Diff bei {_DIFF_LIMIT} Zeichen abgeschnitten "
                  f"(Gesamtlaenge {len(cp.stdout)}); Reviewer urteilt auf dem "
                  "gezeigten Ausschnitt ...]\n")
    return text


def _build_codex_cmd(codex_exe: str, workdir: Path, answer_file: Path) -> list[str]:
    """Assemble the `codex exec` argv for one non-interactive build.

    Flags verified against codex-cli 0.136 (`codex exec --help`):
      -C <workdir>            explicit working root
      -s danger-full-access   NO sandbox. Required, not a convenience: codex
                              0.136's Windows workspace-write sandbox blocks
                              pytest's tmp_path_factory / .pytest_cache writes
                              (they land in %TEMP%, outside the writable roots,
                              and --add-dir does not reliably whitelist %TEMP%
                              on Windows). A seed whose done-criteria run the
                              test suite then fails every test at fixture setup
                              with WinError 5, sends codex into an exploratory
                              %TEMP%-probing shell loop, and the synchronous
                              no-timeout superpowers SessionStart hook
                              (cmd->bash polyglot) deadlocks there -> the whole
                              python->node->codex.exe tree hangs past `timeout`.
                              Dropping the sandbox is safe HERE because the
                              workdir is itself a throwaway clone isolated from
                              the real repo, and the loop draws the real
                              boundary (allowlist + escalate-on-dangerous).
                              (Root-caused 2026-06-03, seed-02 hang.)
      -c approval_policy="never"
                              exec is non-interactive: with the default
                              escalate-to-user policy a write that needs
                              approval can never get it, so codex reports
                              "read-only / approvals disabled" and then probes
                              for a writable dir -> same hang path. "never"
                              makes failures return immediately instead.
      --skip-git-repo-check   the workdir is a freshly cloned+branched git repo
                              by construction; codex 0.135+ otherwise refuses on
                              a tree it doesn't recognise as trusted.
      -o <answer.txt>         final agent message to a file (robust; sidesteps
                              the BOM/event-stream/hook-noise stdout parsing of
                              L17). Lives OUTSIDE the workdir so `git status`
                              never picks it up.
      -                       prompt via STDIN, NOT as a CLI arg (rule 10.8 /
                              P008): a long prompt with backticks/parens/newlines
                              as an argument is mangled by B's codex.CMD wrapper
                              at the cmd.exe quoting layer.
    """
    return [
        codex_exe, "exec",
        "-C", str(workdir),
        "-s", "danger-full-access",
        "-c", 'approval_policy="never"',
        "--skip-git-repo-check",
        "-o", str(answer_file),
        "-",
    ]


def run_codex_task(
    auftrag: str,
    repo: str,
    base_branch: str,
    task_id: str,
    workroot: Path,
    codex_bin: str | None = None,
    timeout: int = 600,
    branch: str | None = None,
    workdir_name: str | None = None,
) -> CodexResult:
    """Run one task end-to-end on Laptop B. Every path returns a CodexResult
    with status done|error -- never raises to the caller (spec section 5: no
    stuck, no silent failure).

    workdir_name overrides the per-task working-dir name (default: task_id). The
    build-review loop passes a stable loop_id so all rounds share one workdir and
    round 2+ continues from the loop branch instead of re-cloning base.
    """
    allow = os.environ.get("DUAL_BRIDGE_REPO_ALLOWLIST", "").strip()
    if allow:
        import fnmatch
        patterns = [p.strip() for p in allow.split(",") if p.strip()]
        if not any(fnmatch.fnmatch(repo, pat) for pat in patterns):
            return CodexResult(status="error",
                               error_text=f"repo nicht in allowlist abgelehnt: {repo}")

    branch = branch or f"bridge/task-{task_id}"

    # 1. codex on PATH?
    codex_exe = codex_bin or shutil.which("codex")
    if not codex_exe:
        return CodexResult(status="error",
                           error_text="codex nicht gefunden -- auf B installiert/im PATH?")

    # 2. repo reachable?
    workdir = Path(workroot) / (workdir_name or task_id)
    try:
        _git_clone_or_pull(repo, base_branch, workdir, prefer_branch=branch)
    except RuntimeError as exc:
        return CodexResult(status="error", error_text=str(exc))

    # 3. task branch
    try:
        _git_checkout_branch(workdir, branch)
    except RuntimeError as exc:
        return CodexResult(status="error", error_text=str(exc))

    # 4. codex exec -- argv assembled by _build_codex_cmd (flags + rationale
    #    documented there; verified against codex-cli 0.136). The -o answer file
    #    lives OUTSIDE the workdir, so it can never be picked up by `git status`.
    answer_file = Path(workroot) / f".codex-answer-{task_id}.txt"
    cmd = _build_codex_cmd(codex_exe, workdir, answer_file)
    try:
        proc = subprocess.run(
            cmd, cwd=str(workdir), capture_output=True, text=True,
            encoding="utf-8", input=auftrag, timeout=timeout,
            env=safe_subprocess_env(),
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

    # 6. did codex change files? Two ways forward: an uncommitted working-tree
    #    change (we commit it), OR codex already self-committed (0.136 under
    #    danger-full-access) so the tree is clean but HEAD is ahead of base. Only
    #    when BOTH are empty did codex truly produce no change.
    changed = _git_status_porcelain(workdir)
    if not changed:
        ahead = _commits_ahead_of_base(workdir, base_branch)
        if ahead:
            # codex self-committed: surface its commit + diff as real progress
            # instead of dropping it as "no change" (seed-02 round-2 bug). The
            # commit is local-only — push it, or the next round's clone_or_pull
            # resets --hard to origin/<branch> and drops it (continuity break,
            # Codex review MAJOR 2026-06-03). On push failure keep the local hash
            # but flag it, mirroring the normal commit+push path below.
            diff = _git_diff(workdir, base_branch)
            changed_files = _changed_files_vs_base(workdir, base_branch)
            push = _run_git(workdir, "push", "--force-with-lease", "origin", branch)
            if push.returncode != 0:
                return CodexResult(status="error", antwort=antwort, branch=branch,
                                   commit=ahead[0], changed_files=changed_files,
                                   diff=diff,
                                   error_text=f"push fehlgeschlagen (lokaler Commit "
                                              f"{ahead[0]} auf B)",
                                   stderr_excerpt=_tail(push.stderr))
            return CodexResult(status="done", antwort=antwort, branch=branch,
                               commit=ahead[0], changed_files=changed_files,
                               diff=diff)
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
    diff = _git_diff(workdir, base_branch)
    return CodexResult(status="done", antwort=antwort, branch=branch,
                       commit=commit, changed_files=changed, diff=diff)


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
    task_id = fm.get("task_id")
    if not task_id:
        return RunnerResult(status="error", error_text="task ohne task_id")
    wr = Path(workroot) if workroot is not None else Path.home() / "dual-bridge-work"
    return run_codex_task(
        auftrag=auftrag,
        repo=fm.get("repo", ""),
        base_branch=fm.get("base_branch", "main"),
        task_id=task_id,
        workroot=wr,
        codex_bin=os.environ.get("DUAL_BRIDGE_CODEX_BIN") or None,
        timeout=int(os.environ.get("DUAL_BRIDGE_CODEX_TIMEOUT", "600")),
        branch=fm.get("branch"),
        workdir_name=fm.get("workdir_name"),
    )


register_runner("codex", _codex_runner)
