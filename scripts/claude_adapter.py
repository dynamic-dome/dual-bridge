"""Claude worker adapter for the Dual-Laptop-Bridge (Stage 2a).

Runs `claude -p` headless and returns a RunnerResult with TEXT only — no git
branch (that is codex-specific). Output parsing follows P006: strip a BOM,
raw_decode the first JSON value (ignoring trailing hook noise), pull the final
type:result event. CLAUDE_CODE_DISABLE_HOOKS=1 + stdin=DEVNULL at the source.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys

from runners import RunnerResult, register_runner

try:  # pragma: no cover - environment dependent
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass


def parse_claude_output(raw: str) -> str:
    """P006: BOM + event-stream + trailing hook noise tolerant. Returns "" if empty."""
    if raw is None:
        return ""
    text = raw.lstrip("﻿").strip()
    if not text:
        return ""
    if text[0] in "{[":
        try:
            value, _ = json.JSONDecoder().raw_decode(text)
        except ValueError:
            value = None
        if value is not None:
            return _answer_from_json(value).strip()
    return text


def _answer_from_json(value: object) -> str:
    if isinstance(value, list):
        for item in reversed(value):
            if isinstance(item, dict) and item.get("type") == "result":
                r = item.get("result")
                if isinstance(r, str) and r.strip():
                    return r
        for item in reversed(value):
            if isinstance(item, dict):
                for key in ("result", "message", "text", "content"):
                    v = item.get(key)
                    if isinstance(v, str) and v.strip():
                        return v
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, dict):
        for key in ("result", "answer", "message", "text", "content"):
            v = value.get(key)
            if isinstance(v, str) and v.strip():
                return v
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def run_claude(auftrag: str, fm: dict, workroot, claude_bin: str | None = None,
               timeout: int = 600) -> RunnerResult:
    """Run one task via `claude -p`. Text only; never raises (spec contract)."""
    exe = claude_bin or os.environ.get("DUAL_BRIDGE_CLAUDE_BIN") or shutil.which("claude")
    if not exe:
        return RunnerResult(status="error",
                            error_text="claude nicht gefunden — installiert/im PATH?")
    cwd = str(workroot) if workroot is not None else None
    env = dict(os.environ)
    # DCO brain.py leak pattern (verified live on B 2026-05-31): an inherited,
    # INVALID ANTHROPIC_API_KEY in the env takes precedence over the Claude
    # subscription login and makes `claude -p` answer "Invalid API key" (exit 1).
    # The reviewer must run on the SUBSCRIPTION, so drop any inherited key (and
    # the alternate auth-token var) from the subprocess env. Removing it forces
    # claude to use the local subscription login. Verified: key set -> Invalid;
    # key removed -> clean answer.
    env.pop("ANTHROPIC_API_KEY", None)
    env.pop("ANTHROPIC_AUTH_TOKEN", None)
    # CLAUDE_CODE_DISABLE_HOOKS=1 is DEPRECATED and no longer suppresses
    # prompt-based Stop/SessionEnd hooks in headless `-p` mode (verified live
    # 2026-05-31: the bridge reviewer crashed with exit 1 "Prompt stop hooks are
    # not yet supported outside REPL" because of a global wrap-up Stop hook).
    # Kept for older CLIs that still honour it, but the real fix is the
    # --settings override below.
    env["CLAUDE_CODE_DISABLE_HOOKS"] = "1"
    # Authoritative hook-disable for current Claude Code (v2.1+): an inline
    # settings override turns off ALL hooks for this headless run, so a
    # user-configured Stop/SessionEnd hook can never break the reviewer.
    # Anti-hang (verified live 2026-05-31): claude -p with tools enabled + a
    # review prompt naming a risky action (git push / rm -rf) HANGS forever — it
    # wants a tool-use permission and waits on stdin (DEVNULL) that never comes.
    # The reviewer only JUDGES (text), never acts, so:
    #   --tools ""                    -> no tools => nothing can prompt for a
    #                                    permission => cannot hang
    #   --permission-mode bypassPermissions -> defensive: never wait on a prompt
    #   --max-turns 1                 -> one turn, immediate exit
    # Prompt via STDIN, NOT a CLI arg (verified live 2026-05-31, global rule
    # §10.3): a long prompt with backticks/parens/newlines passed as an argument
    # is mangled/truncated by B's claude.CMD wrapper (cmd.exe quoting) — the
    # reviewer then "sees nothing". The SAME prompt works on A's claude.exe as an
    # arg but not B's .CMD. Piping it on stdin bypasses the cmd.exe layer
    # entirely, so the prompt arrives intact on every platform. (No trailing
    # prompt arg; claude -p reads the prompt from stdin.)
    cmd = [exe, "-p", "--output-format", "json",
           "--settings", '{"disableAllHooks": true}',
           "--tools", "",
           "--permission-mode", "bypassPermissions",
           "--max-turns", "1"]
    try:
        proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                              encoding="utf-8", input=auftrag,
                              timeout=timeout, env=env)
    except subprocess.TimeoutExpired as exc:
        return RunnerResult(status="error", error_text=f"claude timeout nach {timeout}s",
                            stderr_excerpt=_tail(getattr(exc, "stderr", None)))
    except (FileNotFoundError, OSError) as exc:
        return RunnerResult(status="error",
                            error_text=f"claude nicht ausführbar ({exe}): {exc}")
    # P007 (verified live 2026-05-31): with --settings disableAllHooks the
    # reviewer PRODUCES a full valid JSON result (verdict included) but STILL
    # exits 1 on this Claude build. The exit code lies; the answer is real. So
    # we PARSE FIRST and judge by the answer — a parseable answer means done,
    # regardless of the exit code. A nonzero exit is surfaced only as a note,
    # never discards real reviewer output.
    antwort = parse_claude_output(proc.stdout)
    if antwort:
        note = None
        if proc.returncode != 0:
            note = f"claude exit {proc.returncode} (ignored: valid answer parsed)"
        return RunnerResult(status="done", antwort=antwort, note=note)
    # No usable answer: now the exit code matters.
    if proc.returncode != 0:
        return RunnerResult(status="error", error_text=f"claude exit {proc.returncode}",
                            stderr_excerpt=_tail(proc.stderr))
    return RunnerResult(status="error", error_text="claude: leere Antwort",
                        stderr_excerpt=_tail(proc.stderr))


def _tail(text: str | None, limit: int = 2000) -> str | None:
    if not text:
        return None
    return text[-limit:]


register_runner("claude", run_claude)
