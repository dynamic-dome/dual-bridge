"""run_claude parsing tests (P006 shapes) against a fake claude CLI.
    python test_claude_adapter.py
"""
from __future__ import annotations

import importlib
import os
import sys
import tempfile
from pathlib import Path


def test_parse_event_stream_with_hook_noise() -> None:
    import claude_adapter as ca
    importlib.reload(ca)
    raw = ('﻿[{"type":"system"},'
           '{"type":"result","result":"die antwort"}]\n'
           'SessionEnd hook failed: not supported\n')
    assert ca.parse_claude_output(raw) == "die antwort"
    print("  claude OK — event-stream + BOM + trailing hook noise -> result text")


def test_parse_empty_is_empty() -> None:
    import claude_adapter as ca
    importlib.reload(ca)
    assert ca.parse_claude_output("﻿   \n") == ""
    print("  claude OK — whitespace/BOM-only -> empty")


def _write_fake_claude(tmp: Path, *, answer: str, exit_code: int = 0) -> str:
    bindir = tmp / "fakebin"; bindir.mkdir(parents=True, exist_ok=True)
    py = bindir / "fake_claude.py"
    py.write_text(
        "import sys, json\n"
        "try:\n"
        "    sys.stdout.reconfigure(encoding='utf-8')\n"
        "except Exception:\n"
        "    pass\n"
        f"ans = {answer!r}\n"
        f"code = {exit_code}\n"
        "if ans:\n"
        "    sys.stdout.write('\\ufeff' + json.dumps([{'type':'result','result':ans}]) + '\\n')\n"
        "    sys.stdout.write('Stop hook not supported\\n')\n"
        "sys.exit(code)\n",
        encoding="utf-8",
    )
    cmd = bindir / "claude.cmd"
    cmd.write_text(f'@echo off\r\npython "{py}" %*\r\n', encoding="utf-8")
    sh = bindir / "claude"
    sh.write_text(f'#!/bin/sh\nexec python "{py}" "$@"\n', encoding="utf-8")
    try:
        os.chmod(sh, 0o755)
    except OSError:
        pass
    return str(bindir / ("claude.cmd" if os.name == "nt" else "claude"))


def test_run_claude_happy() -> None:
    import claude_adapter as ca
    importlib.reload(ca)
    tmp = Path(tempfile.mkdtemp(prefix="claude-s2a-"))
    fake = _write_fake_claude(tmp, answer="erledigt")
    r = ca.run_claude(auftrag="tu was", fm={"task_id": "T1"}, workroot=tmp,
                      claude_bin=fake)
    assert r.status == "done" and "erledigt" in r.antwort
    assert r.branch is None, "claude runner darf KEINEN git-branch erzwingen"
    print("  claude OK — run_claude happy path, text only, no branch")


def test_run_claude_not_found() -> None:
    import claude_adapter as ca
    importlib.reload(ca)
    tmp = Path(tempfile.mkdtemp(prefix="claude-nf-"))
    missing = str(tmp / "no-such-claude.exe")
    r = ca.run_claude("x", {"task_id": "T1"}, tmp, claude_bin=missing)
    assert r.status == "error" and "claude" in (r.error_text or "").lower()
    print("  claude OK — missing binary -> status:error (no raise)")


def main() -> int:
    print("=== Stage-2a Claude-Adapter-Tests ===")
    tests = [test_parse_event_stream_with_hook_noise, test_parse_empty_is_empty,
             test_run_claude_happy, test_run_claude_not_found]
    failed = 0
    for t in tests:
        try:
            t()
        except AssertionError as exc:
            print(f"  FAIL {t.__name__}: {exc}"); failed += 1
        except Exception as exc:  # noqa: BLE001
            print(f"  ERROR {t.__name__}: {type(exc).__name__}: {exc}"); failed += 1
    print("=" * 48)
    print(f"{'FEHLER: '+str(failed) if failed else 'Alle'} {len(tests)-failed}/{len(tests)} ok")
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    raise SystemExit(main())
