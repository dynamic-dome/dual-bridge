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


def test_run_claude_nonzero_exit_with_valid_answer_is_done() -> None:
    """Live Phase-6 finding (P007): with --settings disableAllHooks the reviewer
    PRODUCES a full valid result (12 KB JSON, verdict included) but STILL exits
    1. The exit code lies; the answer is real. The adapter must NOT discard a
    parseable answer just because returncode != 0 — parse first, judge by the
    answer, surface the nonzero exit as a note (not a hard error)."""
    import claude_adapter as ca
    importlib.reload(ca)
    tmp = Path(tempfile.mkdtemp(prefix="claude-x1-"))
    fake = _write_fake_claude(tmp, answer="sieht ok aus\nVERDICT: accepted", exit_code=1)
    r = ca.run_claude(auftrag="review", fm={"task_id": "T1"}, workroot=tmp,
                      claude_bin=fake)
    assert r.status == "done", f"expected done despite exit 1, got {r.status}: {r.error_text}"
    assert "VERDICT: accepted" in r.antwort
    print("  claude OK — nonzero exit + valid answer -> done (P007: exit code lies)")


def test_run_claude_nonzero_exit_without_answer_is_error() -> None:
    """The flip side: a nonzero exit AND no parseable answer is a genuine error."""
    import claude_adapter as ca
    importlib.reload(ca)
    tmp = Path(tempfile.mkdtemp(prefix="claude-x1e-"))
    fake = _write_fake_claude(tmp, answer="", exit_code=1)  # no stdout, exit 1
    r = ca.run_claude(auftrag="review", fm={"task_id": "T1"}, workroot=tmp,
                      claude_bin=fake)
    assert r.status == "error", f"expected error, got {r.status}"
    assert "exit 1" in (r.error_text or "")
    print("  claude OK — nonzero exit + empty answer -> error")


def _write_argdump_claude(tmp: Path) -> tuple[str, Path, Path]:
    """A fake claude that dumps its argv, its ANTHROPIC_API_KEY env, AND its
    stdin to files, then emits a valid result. Lets us assert which flags the
    adapter passes, that no inherited API key reaches the subprocess, and that
    the prompt is delivered via stdin (not a CLI arg the cmd.exe wrapper mangles)."""
    bindir = tmp / "fakebin"; bindir.mkdir(parents=True, exist_ok=True)
    argfile = tmp / "argv.txt"
    envfile = tmp / "env_key.txt"
    stdinfile = tmp / "stdin.txt"
    py = bindir / "fake_claude.py"
    py.write_text(
        "import sys, os, json\n"
        "try:\n"
        "    sys.stdout.reconfigure(encoding='utf-8')\n"
        "    sys.stdin.reconfigure(encoding='utf-8')\n"
        "except Exception:\n"
        "    pass\n"
        f"open(r{str(argfile)!r}, 'w', encoding='utf-8').write('\\n'.join(sys.argv[1:]))\n"
        f"open(r{str(envfile)!r}, 'w', encoding='utf-8').write(os.environ.get('ANTHROPIC_API_KEY', '<UNSET>'))\n"
        f"open(r{str(stdinfile)!r}, 'w', encoding='utf-8').write(sys.stdin.read())\n"
        "sys.stdout.write('\\ufeff' + json.dumps([{'type':'result','result':'ok'}]) + '\\n')\n"
        "sys.exit(0)\n",
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
    return str(bindir / ("claude.cmd" if os.name == "nt" else "claude")), argfile, envfile


def test_run_claude_disables_hooks() -> None:
    """Live Phase-6 finding: a prompt-based Stop/SessionEnd hook in the user's
    global settings crashes `claude -p` with exit 1 ('Prompt stop hooks are not
    yet supported outside REPL'). CLAUDE_CODE_DISABLE_HOOKS is deprecated and no
    longer suppresses it. The adapter MUST pass --settings {"disableAllHooks":
    true} so the headless reviewer runs hook-free."""
    import json as _json
    import claude_adapter as ca
    importlib.reload(ca)
    tmp = Path(tempfile.mkdtemp(prefix="claude-hooks-"))
    fake, argfile, _ = _write_argdump_claude(tmp)
    r = ca.run_claude(auftrag="review", fm={"task_id": "T1"}, workroot=tmp,
                      claude_bin=fake)
    assert r.status == "done", f"expected done, got {r.status}: {r.error_text}"
    argv = argfile.read_text(encoding="utf-8").splitlines()
    assert "--settings" in argv, f"--settings missing from argv: {argv}"
    settings_val = argv[argv.index("--settings") + 1]
    assert _json.loads(settings_val).get("disableAllHooks") is True, settings_val
    print("  claude OK — passes --settings disableAllHooks (hook-disable hardening)")


def test_run_claude_sends_prompt_via_stdin_not_argv() -> None:
    """Live Phase-6 finding: a long prompt with backticks/parens/newlines passed
    as a CLI ARG gets mangled/truncated by B's claude.CMD wrapper (cmd.exe
    quoting, global rule §10.3) — the reviewer then 'sees nothing'. Verified: the
    SAME prompt works on A's claude.exe but not B's claude.CMD as an arg. Fix:
    deliver the prompt via STDIN so the cmd.exe layer never touches it."""
    import claude_adapter as ca
    importlib.reload(ca)
    tmp = Path(tempfile.mkdtemp(prefix="claude-stdin-"))
    fake, argfile, _ = _write_argdump_claude(tmp)
    stdinfile = tmp / "stdin.txt"
    tricky = ("Review `git push origin main` (force? no). End with one line:\n"
              "`VERDICT: accepted` or `VERDICT: rejected`.")
    r = ca.run_claude(auftrag=tricky, fm={"task_id": "T1"}, workroot=tmp,
                      claude_bin=fake)
    assert r.status == "done", f"expected done, got {r.status}: {r.error_text}"
    # The full prompt arrived via stdin, intact.
    seen_stdin = stdinfile.read_text(encoding="utf-8")
    assert tricky in seen_stdin, f"prompt not delivered via stdin: {seen_stdin!r}"
    # And it is NOT passed as a trailing argv item.
    argv = argfile.read_text(encoding="utf-8").splitlines()
    assert tricky not in argv, f"prompt leaked into argv: {argv}"
    print("  claude OK — prompt via stdin, not argv (cmd.exe quoting bypass)")


def test_run_claude_passes_anti_hang_flags() -> None:
    """Live Phase-6 finding: claude -p with tools enabled + a review prompt that
    names a risky action (git push / rm -rf) HANGS forever — claude wants a tool
    permission and waits on stdin (DEVNULL) that never answers. The reviewer only
    needs to JUDGE (text), never act, so the adapter must pass --tools "" +
    --permission-mode bypassPermissions + --max-turns 1 to guarantee it
    terminates regardless of prompt content."""
    import claude_adapter as ca
    importlib.reload(ca)
    tmp = Path(tempfile.mkdtemp(prefix="claude-hang-"))
    fake, argfile, _ = _write_argdump_claude(tmp)
    r = ca.run_claude(auftrag="review git push", fm={"task_id": "T1"}, workroot=tmp,
                      claude_bin=fake)
    assert r.status == "done", f"expected done, got {r.status}: {r.error_text}"
    argv = argfile.read_text(encoding="utf-8").splitlines()
    assert "--tools" in argv and argv[argv.index("--tools") + 1] == "", f"no empty --tools: {argv}"
    assert "--permission-mode" in argv, f"no --permission-mode: {argv}"
    assert argv[argv.index("--permission-mode") + 1] == "bypassPermissions", argv
    assert "--max-turns" in argv and argv[argv.index("--max-turns") + 1] == "1", f"no --max-turns 1: {argv}"
    print("  claude OK — passes --tools '' / bypassPermissions / --max-turns 1 (anti-hang)")


def test_run_claude_drops_inherited_api_key() -> None:
    """Live Phase-6 finding (DCO brain.py leak pattern): an inherited, INVALID
    ANTHROPIC_API_KEY in the env takes precedence over the subscription login and
    makes `claude -p` answer 'Invalid API key'. Verified on B: key set -> exit 1
    Invalid; key removed -> exit 0. The reviewer must run on the subscription, so
    the adapter MUST drop ANTHROPIC_API_KEY from the subprocess env."""
    import claude_adapter as ca
    importlib.reload(ca)
    tmp = Path(tempfile.mkdtemp(prefix="claude-key-"))
    fake, _, envfile = _write_argdump_claude(tmp)
    old = os.environ.get("ANTHROPIC_API_KEY")
    os.environ["ANTHROPIC_API_KEY"] = "sk-ant-INVALID-should-not-reach-subprocess"
    try:
        r = ca.run_claude(auftrag="review", fm={"task_id": "T1"}, workroot=tmp,
                          claude_bin=fake)
    finally:
        if old is None:
            os.environ.pop("ANTHROPIC_API_KEY", None)
        else:
            os.environ["ANTHROPIC_API_KEY"] = old
    assert r.status == "done", f"expected done, got {r.status}: {r.error_text}"
    seen = envfile.read_text(encoding="utf-8")
    assert seen == "<UNSET>", f"adapter leaked ANTHROPIC_API_KEY to subprocess: {seen!r}"
    print("  claude OK — drops inherited ANTHROPIC_API_KEY (subscription, not key)")


def main() -> int:
    print("=== Stage-2a Claude-Adapter-Tests ===")
    tests = [test_parse_event_stream_with_hook_noise, test_parse_empty_is_empty,
             test_run_claude_happy, test_run_claude_not_found,
             test_run_claude_disables_hooks,
             test_run_claude_sends_prompt_via_stdin_not_argv,
             test_run_claude_passes_anti_hang_flags,
             test_run_claude_drops_inherited_api_key,
             test_run_claude_nonzero_exit_with_valid_answer_is_done,
             test_run_claude_nonzero_exit_without_answer_is_error]
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
