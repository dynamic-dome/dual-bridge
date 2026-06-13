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

import json
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
    _bb_cred = adapter_git._resolve_https_credential(repo)
    try:
        base_branch = adapter_git._resolve_base_branch(repo, base_branch, _bb_cred)
    finally:
        _bb_cred.cleanup()
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

    antwort = _real_text(parse_claude_output(proc.stdout))
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


def _tail(text: str | None, limit: int = 2000) -> str | None:
    if not text:
        return None
    return text[-limit:]


def _real_text(parsed: str) -> str:
    """Return parsed text only if it is genuine prose, not a JSON-fallback dump.

    parse_claude_output's last-resort fallback returns json.dumps(value) when no
    text field is found (e.g. an event list with an empty `result` string). For the
    builder, a bare JSON re-encoding is not a real answer — it means the model
    produced no text — so we treat it as empty to let the no-diff-no-text error
    gate fire correctly. A string that starts with '[' or '{' AND round-trips
    through json.loads without error is the fallback; anything else (real prose,
    even if it contains a brace) is kept as-is."""
    if not parsed:
        return ""
    s = parsed.strip()
    if s and s[0] in "[{":
        try:
            json.loads(s)
            # It decoded → it is a raw JSON re-encoding, not real prose. Discard.
            return ""
        except ValueError:
            pass  # partial / prose with braces → keep
    return parsed


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
