"""Codex review-only adapter for the Dual-Laptop-Bridge — symmetric to the
review-only `claude` adapter (claude_adapter.py).

Runs `codex exec` in READ-ONLY mode and returns a RunnerResult with TEXT only (a
verdict) — no git branch (that is the builder's job, codex_adapter.py). The diff
under review is embedded in the prompt by loop_driver.write_*_review_task, so the
reviewer needs no clone and writes nothing. Registers `codex-review`
(capability=read in risk_policy). Pure stdlib; reuses codex_adapter's
P006-tolerant output parser.

Hang-proofing (CLAUDE.md rule 10.10 — codex exec read-only sandbox + inherited
hooks deadlock): the builder needs danger-full-access (pytest writes %TEMP%), but
a review WRITES NOTHING, so we run with the read-only sandbox AND
approval_policy="never". "never" is the actual fix: with the default
escalate-to-user policy a read-only run that wants to probe for a writable dir
hangs on an approval that never comes; "never" makes it return immediately
instead. Prompt via stdin (P008/rule 10.8), allowlisted env (drops API keys),
tree-kill on timeout, parse-first-then-exit-code (P007).
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
from codex_adapter import parse_codex_output  # reuse the P006/L17-tolerant parser

try:  # pragma: no cover - environment dependent
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass


def _review_codex_cmd(codex_exe: str) -> list[str]:
    """`codex exec` argv for a read-only, no-write review (rationale in module
    docstring). Flags to VERIFY against the real binary in the Stage-A live-proof:
    that -s read-only + approval_policy="never" genuinely terminates on a no-write
    review instead of probing (the central rule-10.10 risk).

      exec                       non-interactive run
      -s read-only               no sandbox writes — a review writes nothing
      -c approval_policy="never" no approval-probing hang on a read-only run
      --skip-git-repo-check      runs in a throwaway cwd, not a trusted git tree
      -                          prompt via STDIN, not a CLI arg (P008/rule 10.8)
    """
    return [
        codex_exe, "exec",
        "-s", "read-only",
        "-c", 'approval_policy="never"',
        "--skip-git-repo-check",
        "-",
    ]


def run_codex_review(auftrag: str, fm: dict, workroot,
                     codex_bin: str | None = None,
                     timeout: int = 600) -> RunnerResult:
    """Run one review via `codex exec` read-only. Text only; never raises."""
    exe = (codex_bin or os.environ.get("DUAL_BRIDGE_CODEX_BIN")
           or shutil.which("codex"))
    if not exe:
        return RunnerResult(status="error",
                            error_text="codex nicht gefunden — installiert/im PATH?")
    cwd = Path(workroot) if workroot is not None else Path.home() / "dual-bridge-work"
    try:
        cwd.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    cmd = _review_codex_cmd(exe)
    env = safe_subprocess_env()
    try:
        proc = run_with_tree_kill(cmd, cwd, auftrag, timeout, env=env)
    except subprocess.TimeoutExpired as exc:
        return RunnerResult(status="error",
                            error_text=f"codex timeout nach {timeout}s",
                            stderr_excerpt=_tail(getattr(exc, "stderr", None)))
    except (FileNotFoundError, OSError) as exc:
        return RunnerResult(status="error",
                            error_text=f"codex nicht ausführbar ({exe}): {exc}")
    # P007: parse first; a valid verdict despite a nonzero exit is still real.
    antwort = parse_codex_output(proc.stdout)
    if antwort:
        note = None
        if proc.returncode != 0:
            note = f"codex exit {proc.returncode} (ignored: valid answer parsed)"
        return RunnerResult(status="done", antwort=antwort, note=note)
    if proc.returncode != 0:
        return RunnerResult(status="error", error_text=f"codex exit {proc.returncode}",
                            stderr_excerpt=_tail(proc.stderr))
    return RunnerResult(status="error", error_text="codex: leere Antwort",
                        stderr_excerpt=_tail(proc.stderr))


def _tail(text: str | None, limit: int = 2000) -> str | None:
    if not text:
        return None
    return text[-limit:]


def _codex_review_runner(auftrag: str, fm: dict, workroot):
    """Adapt run_codex_review to the (auftrag, fm, workroot) runner signature."""
    return run_codex_review(
        auftrag=auftrag, fm=fm, workroot=workroot,
        codex_bin=os.environ.get("DUAL_BRIDGE_CODEX_BIN") or None,
        timeout=config_value("codex_timeout", "DUAL_BRIDGE_CODEX_TIMEOUT", 600, cast=int),
    )


register_runner("codex-review", _codex_review_runner)
