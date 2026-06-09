"""parse_codex_output parsing tests (QW1: NDJSON-fallback).

Same style as test_claude_adapter.py: plain asserts + a standalone main().
    python test_codex_adapter.py

Background (QW1, verified 2026-06-02): `codex exec --json` emits NDJSON --
several {..}\\n{..} lines. The old single raw_decode(text) path only sees the
FIRST event (thread.started) and drops the real answer in the last
item.completed / agent_message event. These tests pin the NDJSON path AND the
backward-compatible single-object / pretty-printed / plain-text paths.
"""
from __future__ import annotations

import importlib
import sys


def test_build_codex_cmd_uses_hang_safe_flags() -> None:
    """The seed-02 hang (2026-06-03) was root-caused to codex 0.136's Windows
    workspace-write sandbox: it blocks pytest tmp/.pytest_cache writes in %TEMP%,
    fails seeds whose criteria run tests at fixture setup, and sends codex into a
    %TEMP%-probing shell loop where the synchronous superpowers SessionStart hook
    deadlocks. The fix pins two flags. This test guards them against regression."""
    import codex_adapter as cx
    importlib.reload(cx)
    from pathlib import Path

    cmd = cx._build_codex_cmd("codex", Path("/wd"), Path("/wr/.codex-answer-x.txt"))

    # sandbox dropped (the actual hang fix) — never silently back to workspace-write
    assert "danger-full-access" in cmd, cmd
    assert "workspace-write" not in cmd, cmd
    # non-interactive approval policy so a write can never block on approval
    assert "-c" in cmd and 'approval_policy="never"' in cmd, cmd
    # invariants that must survive the refactor
    assert cmd[:2] == ["codex", "exec"], cmd
    assert "--skip-git-repo-check" in cmd, cmd
    assert cmd[-1] == "-", cmd                       # prompt via stdin (P008)
    assert "-o" in cmd, cmd
    print("  codex OK — _build_codex_cmd pins danger-full-access + approval=never")


def test_parse_ndjson_multi_event_returns_last_answer() -> None:
    """3-line NDJSON stream -> the answer from the final item.completed event,
    not "" (the old single raw_decode would only see thread.started)."""
    import codex_adapter as cx
    importlib.reload(cx)
    raw = (
        '{"type":"thread.started"}\n'
        '{"type":"item.started"}\n'
        '{"type":"item.completed","item":{"text":"DIE ANTWORT"}}\n'
    )
    assert cx.parse_codex_output(raw) == "DIE ANTWORT"
    print("  codex OK — multi-event NDJSON -> last item.completed answer")


def test_parse_ndjson_standard_codex_sequence_skips_turn_completed() -> None:
    """Real codex JSONL commonly ends with turn.completed after the message.
    The parser must skip that non-answer event and return the agent message."""
    import codex_adapter as cx
    importlib.reload(cx)
    raw = (
        '{"type":"thread.started","thread_id":"t"}\n'
        '{"type":"turn.started"}\n'
        '{"type":"item.completed","item":{"type":"agent_message","text":"PING"}}\n'
        '{"type":"turn.completed","usage":{"input_tokens":1}}\n'
    )
    assert cx.parse_codex_output(raw) == "PING"
    print("  codex OK — standard JSONL sequence skips trailing turn.completed")


def test_parse_single_json_object_unchanged() -> None:
    """A single JSON object stays backward-compatible (no NDJSON misread)."""
    import codex_adapter as cx
    importlib.reload(cx)
    assert cx.parse_codex_output('{"result":"ok"}') == "ok"
    print("  codex OK — single JSON object -> result text (unchanged)")


def test_parse_pretty_printed_single_json_with_newlines() -> None:
    """The critical user-fallback case: an INDENTED single JSON object with
    embedded newlines must NOT be misinterpreted as NDJSON. It decodes once
    (>1 event NOT reached) so the single raw_decode(text) path handles it."""
    import codex_adapter as cx
    importlib.reload(cx)
    raw = '{\n  "result": "x"\n}'
    assert cx.parse_codex_output(raw) == "x"
    print("  codex OK — pretty-printed single JSON w/ newlines -> not NDJSON")


def test_parse_plain_text_unchanged() -> None:
    """Plain text without a leading brace is returned verbatim."""
    import codex_adapter as cx
    importlib.reload(cx)
    assert cx.parse_codex_output("just a plain answer") == "just a plain answer"
    print("  codex OK — plain text -> unchanged")


def test_parse_ndjson_with_trailing_hook_noise() -> None:
    """NDJSON plus a trailing non-JSON hook line: the bad line does not decode
    (so it is not counted as an event) but the stream stays usable -- the real
    answer from the last item.completed is still returned."""
    import codex_adapter as cx
    importlib.reload(cx)
    raw = (
        '{"type":"thread.started"}\n'
        '{"type":"item.completed","item":{"text":"ROBUST"}}\n'
        'SessionEnd hook failed: not supported\n'
    )
    assert cx.parse_codex_output(raw) == "ROBUST"
    print("  codex OK — NDJSON + trailing hook noise -> still yields the answer")


def test_parse_ndjson_answer_before_trailing_metadata_event() -> None:
    """Codex-Verifier Q3b: a metadata event (turn.completed/usage) AFTER the
    answer must NOT shadow it. reversed(events) hits the metadata event first;
    it carries no real answer key, so it must be skipped -- not stringified via
    json.dumps and returned as if it were the answer."""
    import codex_adapter as cx
    importlib.reload(cx)
    raw = (
        '{"type":"thread.started"}\n'
        '{"type":"item.completed","item":{"text":"ECHTE ANTWORT"}}\n'
        '{"type":"turn.completed","usage":{"input_tokens":12,"output_tokens":34}}\n'
    )
    assert cx.parse_codex_output(raw) == "ECHTE ANTWORT"
    print("  codex OK — trailing metadata event does not shadow the real answer")


def test_parse_ndjson_trailing_error_event_with_message_does_not_shadow() -> None:
    """Codex-Verifier Q3b round 2: a trailing event that declares a non-answer
    type but carries a stray 'message' key (e.g. an error/status event) must NOT
    shadow the real item.completed answer that came before it."""
    import codex_adapter as cx
    importlib.reload(cx)
    raw = (
        '{"type":"item.completed","item":{"text":"DIE ANTWORT"}}\n'
        '{"type":"turn.failed","message":"some status note"}\n'
    )
    assert cx.parse_codex_output(raw) == "DIE ANTWORT"
    print("  codex OK — trailing typed status event w/ message does not shadow")


def test_parse_ndjson_unknown_answer_type_is_not_dropped() -> None:
    """Codex-Verifier Q3b round 3: an answer-bearing event with a type we did NOT
    foresee (e.g. message.output_text.delta) must still be mined for its answer,
    not silently dropped. The denylist only skips KNOWN metadata types."""
    import codex_adapter as cx
    importlib.reload(cx)
    raw = (
        '{"type":"thread.started"}\n'
        '{"type":"message.output_text.delta","text":"ZUKUNFTS-ANTWORT"}\n'
        '{"type":"turn.completed","usage":{"output_tokens":3}}\n'
    )
    assert cx.parse_codex_output(raw) == "ZUKUNFTS-ANTWORT"
    print("  codex OK — unbekannter Antwort-Typ wird nicht verworfen (Denylist)")


def test_parse_pretty_printed_json_array_not_misread_as_ndjson() -> None:
    """Codex-Verifier Q3a: a pretty-printed JSON ARRAY (each object on its own
    line) must be parsed as ONE value, not split into NDJSON events. The single
    raw_decode path returns the array's last answer-bearing item."""
    import codex_adapter as cx
    importlib.reload(cx)
    raw = '[\n  {"type":"a"},\n  {"result":"FROM ARRAY"}\n]'
    assert cx.parse_codex_output(raw) == "FROM ARRAY"
    print("  codex OK — pretty-printed JSON array -> single value, not NDJSON")


def test_parse_real_codex_0136_ndjson_sequence() -> None:
    """DCO #7729 / P006: pin the BYTE-EXACT event sequence emitted by a REAL
    `codex exec --json` run, not just a hand-guessed fixture.

    Captured 2026-06-03 from codex-cli 0.136.0 on Laptop A
    (`echo "Antworte mit genau dem Wort: PINGPONG" | codex exec --json
    --skip-git-repo-check -s read-only -`). The four real events are:
      thread.started -> turn.started -> item.completed(item.text) -> turn.completed(usage)
    The answer lives in item.completed's item.text; the trailing turn.completed
    (usage) must NOT shadow it. Verified live: parse_codex_output -> "PINGPONG".
    This test fails loudly if a future codex version drifts the schema (the -o
    answer.txt path masks this in production today, QW1)."""
    import codex_adapter as cx
    importlib.reload(cx)
    raw = (
        '{"thread_id":"019e8dbd-81bc-7702-87c9-3f0b1a9242c0","type":"thread.started"}\n'
        '{"type":"turn.started"}\n'
        '{"item":{"id":"item_0","text":"PINGPONG","type":"agent_message"},"type":"item.completed"}\n'
        '{"type":"turn.completed","usage":{"cached_input_tokens":0,"input_tokens":2500,'
        '"output_tokens":7,"reasoning_output_tokens":0}}\n'
    )
    assert cx.parse_codex_output(raw) == "PINGPONG"
    print("  codex OK — REAL codex-0.136 NDJSON sequence -> item.text answer")


def test_kill_process_tree_windows_uses_taskkill_tree() -> None:
    """On Windows, killing a timed-out codex MUST kill the WHOLE tree.

    The live hang (2026-06-09): a goal-loop's `codex exec` ran ~50 min past its
    600s timeout because subprocess.run(timeout=)'s kill hits only the direct
    child (the node launcher), while the real worker codex.exe is its GRANDCHILD
    and survives — holding the worker slot forever. _kill_process_tree must use
    `taskkill /T /F /PID <pid>` (Win32 snapshot walks the parent->child tree)
    rather than a single TerminateProcess, so node + codex.exe + the spawned MCP
    node/npx children all die together. This pins the /T (tree) + /F (force)."""
    import codex_adapter as cx
    importlib.reload(cx)

    calls = []

    def fake_run(cmd, *a, **k):
        calls.append(cmd)
        class _R:  # minimal CompletedProcess stand-in
            returncode = 0
        return _R()

    orig_run = cx.subprocess.run
    orig_name = cx.os.name
    try:
        cx.subprocess.run = fake_run
        cx.os.name = "nt"
        cx._kill_process_tree(4242)
    finally:
        cx.subprocess.run = orig_run
        cx.os.name = orig_name

    assert calls, "kill must invoke a subprocess (taskkill)"
    cmd = calls[-1]
    assert cmd[0].lower().startswith("taskkill"), cmd
    assert "/T" in cmd, f"missing tree flag /T: {cmd}"
    assert "/F" in cmd, f"missing force flag /F: {cmd}"
    assert "4242" in cmd, f"PID not passed to taskkill: {cmd}"
    print("  codex OK — _kill_process_tree uses taskkill /T /F on Windows")


def test_codex_timeout_kills_grandchild_process() -> None:
    """End-to-end proof: when `codex exec` exceeds its timeout, NO descendant
    survives. Uses a fake 'codex' that spawns a long-lived grandchild and then
    sleeps far past the (tiny) timeout. After run_codex_task returns the timeout
    error, the grandchild PID must be dead — proving the tree-kill, not just the
    direct child, fired. Guards the exact failure observed live 2026-06-09.

    Skipped on non-Windows only if psutil is unavailable for liveness checks;
    the kill itself is platform-generic (taskkill on nt, killpg elsewhere)."""
    import os
    import subprocess as sp
    import sys
    import tempfile
    import time
    from pathlib import Path

    import codex_adapter as cx
    importlib.reload(cx)

    # A fake codex: print our own PID, spawn a detached grandchild that sleeps
    # 120s, then sleep 120s ourselves so the parent codex outlives the timeout.
    # The grandchild writes its PID to a file so the test can check liveness.
    work = Path(tempfile.mkdtemp(prefix="killtree-"))
    pidfile = work / "grandchild.pid"
    gc_script = work / "gc.py"
    gc_script.write_text(
        "import os,sys,time\n"
        f"open(r'{pidfile}','w').write(str(os.getpid()))\n"
        "time.sleep(120)\n",
        encoding="utf-8",
    )
    fake_codex = work / "fakecodex.py"
    fake_codex.write_text(
        "import subprocess,sys,time,os\n"
        f"subprocess.Popen([sys.executable, r'{gc_script}'])\n"
        "time.sleep(120)\n",
        encoding="utf-8",
    )

    # run_codex_task expects a codex *executable*; we wrap python+script as the
    # codex_bin by writing a launcher. On Windows a .cmd, else an sh shebang.
    if os.name == "nt":
        launcher = work / "codex.cmd"
        launcher.write_text(
            f'@echo off\r\n"{sys.executable}" "{fake_codex}" %*\r\n', encoding="utf-8"
        )
    else:
        launcher = work / "codex"
        launcher.write_text(
            f'#!/bin/sh\nexec "{sys.executable}" "{fake_codex}" "$@"\n', encoding="utf-8"
        )
        os.chmod(launcher, 0o755)

    # Build a throwaway local git repo as the "remote" so the clone succeeds fast
    # and the run reaches the codex-exec step (where the timeout fires).
    remote = work / "remote.git"
    sp.run(["git", "init", "--bare", str(remote)], check=True,
           capture_output=True)
    seed = work / "seed"
    sp.run(["git", "init", str(seed)], check=True, capture_output=True)
    (seed / "x.txt").write_text("hi", encoding="utf-8")
    for args in (["add", "-A"], ["-c", "user.email=t@t", "-c", "user.name=t",
                                 "commit", "-m", "init"],
                 ["branch", "-M", "main"],
                 ["remote", "add", "origin", str(remote)],
                 ["push", "origin", "main"]):
        sp.run(["git", "-C", str(seed)] + args, check=True, capture_output=True)

    result = cx.run_codex_task(
        auftrag="irrelevant",
        repo=str(remote),
        base_branch="main",
        task_id="killtree-test",
        workroot=work / "wr",
        codex_bin=str(launcher),
        timeout=3,  # tiny: codex sleeps 120s -> guaranteed TimeoutExpired
    )

    assert result.status == "error", result
    assert "timeout" in (result.error_text or "").lower(), result.error_text

    # The grandchild must be dead. Give the OS a beat to reap.
    time.sleep(1.5)
    assert pidfile.exists(), "fake codex never spawned its grandchild"
    gc_pid = int(pidfile.read_text().strip())
    alive = _pid_alive(gc_pid)
    assert not alive, (
        f"grandchild PID {gc_pid} SURVIVED the codex timeout — tree-kill failed "
        "(this is exactly the 2026-06-09 slot-blocking hang)"
    )
    print("  codex OK — codex timeout kills the whole process tree (grandchild dead)")


def _pid_alive(pid: int) -> bool:
    """True if a process with this PID is currently running (best-effort, no deps)."""
    import os
    import subprocess as sp
    if os.name == "nt":
        out = sp.run(["tasklist", "/FI", f"PID eq {pid}"],
                     capture_output=True, text=True,
                     encoding="utf-8", errors="ignore")
        return str(pid) in (out.stdout or "")
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def main() -> int:
    print("=== QW1 Codex-Adapter NDJSON-Tests ===")
    tests = [
        test_build_codex_cmd_uses_hang_safe_flags,
        test_parse_ndjson_multi_event_returns_last_answer,
        test_parse_ndjson_standard_codex_sequence_skips_turn_completed,
        test_parse_single_json_object_unchanged,
        test_parse_pretty_printed_single_json_with_newlines,
        test_parse_plain_text_unchanged,
        test_parse_ndjson_with_trailing_hook_noise,
        test_parse_ndjson_answer_before_trailing_metadata_event,
        test_parse_ndjson_trailing_error_event_with_message_does_not_shadow,
        test_parse_ndjson_unknown_answer_type_is_not_dropped,
        test_parse_pretty_printed_json_array_not_misread_as_ndjson,
        test_parse_real_codex_0136_ndjson_sequence,
        test_kill_process_tree_windows_uses_taskkill_tree,
        test_codex_timeout_kills_grandchild_process,
    ]
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
