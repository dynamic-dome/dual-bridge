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
from pathlib import Path
from typing import Optional

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


def run_claude(auftrag: str, fm: dict, workroot, claude_bin: Optional[str] = None,
               timeout: int = 600) -> RunnerResult:
    """Run one task via `claude -p`. Text only; never raises (spec contract)."""
    exe = claude_bin or os.environ.get("DUAL_BRIDGE_CLAUDE_BIN") or shutil.which("claude")
    if not exe:
        return RunnerResult(status="error",
                            error_text="claude nicht gefunden — installiert/im PATH?")
    cwd = str(workroot) if workroot is not None else None
    env = dict(os.environ)
    env["CLAUDE_CODE_DISABLE_HOOKS"] = "1"
    cmd = [exe, "-p", "--output-format", "json", auftrag]
    try:
        proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                              encoding="utf-8", stdin=subprocess.DEVNULL,
                              timeout=timeout, env=env)
    except subprocess.TimeoutExpired as exc:
        return RunnerResult(status="error", error_text=f"claude timeout nach {timeout}s",
                            stderr_excerpt=_tail(getattr(exc, "stderr", None)))
    except (FileNotFoundError, OSError) as exc:
        return RunnerResult(status="error",
                            error_text=f"claude nicht ausführbar ({exe}): {exc}")
    if proc.returncode != 0:
        return RunnerResult(status="error", error_text=f"claude exit {proc.returncode}",
                            stderr_excerpt=_tail(proc.stderr))
    antwort = parse_claude_output(proc.stdout)
    if not antwort:
        return RunnerResult(status="error", error_text="claude: leere Antwort",
                            stderr_excerpt=_tail(proc.stderr))
    return RunnerResult(status="done", antwort=antwort)


def _tail(text: Optional[str], limit: int = 2000) -> Optional[str]:
    if not text:
        return None
    return text[-limit:]


register_runner("claude", run_claude)
