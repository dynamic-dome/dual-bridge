"""Codex worker adapter for the Dual-Laptop-Bridge (Stage 1).

Owns the real `codex exec` call; the git clone/branch/commit/push scaffolding lives in adapter_git (extracted 2026-06-12) and is only orchestrated here and re-exported as a back-compat shim.
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

from bridge_common import config_value, safe_subprocess_env
from runners import RunnerResult, register_runner
from subprocess_util import _kill_process_tree, run_with_tree_kill  # noqa: F401 — _kill_process_tree re-exported for back-compat

import adapter_git
from adapter_git import (  # noqa: F401 — back-compat shim (Spec 2026-06-12): nur Re-Export, verbleibender Code nutzt diese Namen NICHT
    _ASKPASS_HELPER, _Cred, _DIFF_LIMIT, _changed_files_vs_base,
    _commits_ahead_of_base, _diagnose_clone_failure, _git_checkout_branch,
    _git_clone_or_pull, _git_commit_and_push, _git_diff, _git_status_porcelain,
    _remote_default_branch, _resolve_base_branch, _resolve_https_credential,
    _run_git, _write_askpass_wrapper, merge_accepted_to_base,
    push_branch_on_escalation,
)

CodexResult = RunnerResult  # back-compat alias; existing call sites unchanged


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


def _run_codex_exec(cmd: list[str], workdir: Path, auftrag: str,
                    timeout: int) -> subprocess.CompletedProcess:
    """Run `codex exec` with whole-tree kill on timeout (shared util). env =
    safe_subprocess_env() so codex inherits only the allowlisted environment."""
    return run_with_tree_kill(cmd, workdir, auftrag, timeout, env=safe_subprocess_env())


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
    # Resolve the real base branch BEFORE any git op: the loop defaults to 'main',
    # but a 'master'/'trunk' repo would otherwise fail every clone/rev-list/diff
    # (they all reference origin/<base_branch>). One credential resolve here; the
    # store file is ephemeral and cleaned up in the finally.
    #
    # This MUST run every round, not only on a fresh workdir. base_branch is a
    # per-call local the loop re-supplies as 'main' each round — it is NOT
    # persisted. Skipping the probe on an existing workdir (round 2+) therefore
    # left base_branch='main' on a master-only repo, so `git diff origin/main...
    # HEAD` died and the reviewer got an EMPTY diff -> rejected -> max_rounds
    # escalation, even though codex had built correctly (reminders-v2 Paket B,
    # loop ...4905, 2026-06-07). The redundant ls-remote per round is cheap
    # insurance against that silent continuity break.
    _bb_cred = adapter_git._resolve_https_credential(repo)
    try:
        base_branch = adapter_git._resolve_base_branch(repo, base_branch, _bb_cred)
    finally:
        _bb_cred.cleanup()
    try:
        adapter_git._git_clone_or_pull(repo, base_branch, workdir, prefer_branch=branch)
    except RuntimeError as exc:
        return CodexResult(status="error", error_text=str(exc))

    # 3. task branch
    try:
        adapter_git._git_checkout_branch(workdir, branch)
    except RuntimeError as exc:
        return CodexResult(status="error", error_text=str(exc))

    # 4. codex exec -- argv assembled by _build_codex_cmd (flags + rationale
    #    documented there; verified against codex-cli 0.136). The -o answer file
    #    lives OUTSIDE the workdir, so it can never be picked up by `git status`.
    answer_file = Path(workroot) / f".codex-answer-{task_id}.txt"
    cmd = _build_codex_cmd(codex_exe, workdir, answer_file)
    try:
        proc = _run_codex_exec(cmd, workdir, auftrag, timeout)
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
    changed = adapter_git._git_status_porcelain(workdir)
    if not changed:
        ahead = adapter_git._commits_ahead_of_base(workdir, base_branch)
        if ahead:
            # codex self-committed: surface its commit + diff as real progress
            # instead of dropping it as "no change" (seed-02 round-2 bug). The
            # commit is local-only — push it, or the next round's clone_or_pull
            # resets --hard to origin/<branch> and drops it (continuity break,
            # Codex review MAJOR 2026-06-03). On push failure keep the local hash
            # but flag it, mirroring the normal commit+push path below.
            diff = adapter_git._git_diff(workdir, base_branch)
            changed_files = adapter_git._changed_files_vs_base(workdir, base_branch)
            push = adapter_git._run_git(workdir, "push", "--force-with-lease", "origin", branch)
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
        commit = adapter_git._git_commit_and_push(workdir, branch, f"bridge: task {task_id}")
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
    diff = adapter_git._git_diff(workdir, base_branch)
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
        timeout=config_value(
            "codex_timeout", "DUAL_BRIDGE_CODEX_TIMEOUT", 600, cast=int),
        branch=fm.get("branch"),
        workdir_name=fm.get("workdir_name"),
    )


register_runner("codex", _codex_runner)
