"""Shared subprocess machinery for bridge builder adapters: whole-tree kill.

Both the codex and claude builders launch a CLI that spawns a process TREE
(python -> node -> <cli>.exe -> MCP children). A plain subprocess.run timeout
or Popen.kill only kills the DIRECT child, orphaning the real worker grandchild
which keeps holding the bridge worker slot open (live hang 2026-06-09: a goal-loop
ran ~50 min past its 600s timeout because an orphaned codex.exe kept working).
run_with_tree_kill drives Popen itself so a timeout kills the whole tree.
Pure stdlib.
"""
from __future__ import annotations

import os
import signal
import subprocess

_NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def _kill_process_tree(pid: int) -> None:
    """Kill `pid` AND all of its descendants. Never raises.

    Windows: `taskkill /T /F /PID` walks the Win32 process snapshot. POSIX: kill
    the process GROUP (the child is started in its own session)."""
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(pid)],
                capture_output=True, stdin=subprocess.DEVNULL,
                creationflags=_NO_WINDOW,
            )
        else:
            try:
                os.killpg(os.getpgid(pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                try:
                    os.kill(pid, signal.SIGKILL)
                except OSError:
                    pass
    except Exception:
        # Best-effort: a kill failure must never mask the timeout error itself.
        pass


def run_with_tree_kill(cmd, cwd, input_text, timeout, env=None):
    """Run `cmd`, feed `input_text` on stdin; on timeout kill the WHOLE tree then
    re-raise TimeoutExpired. Returns a CompletedProcess.

    errors="replace": codex/git/claude output on a German Windows console can
    carry non-utf8 (cp1252) bytes; a strict decode crashes Popen's reader thread.
    """
    popen_kwargs = dict(
        cwd=str(cwd), stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace", env=env,
    )
    if os.name != "nt":
        popen_kwargs["start_new_session"] = True  # own pgid for killpg
    proc = subprocess.Popen(cmd, creationflags=_NO_WINDOW, **popen_kwargs)
    try:
        stdout, stderr = proc.communicate(input=input_text, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        _kill_process_tree(proc.pid)
        try:
            proc.communicate(timeout=10)  # reap, ignore post-kill trickle
        except Exception:
            pass
        raise exc
    return subprocess.CompletedProcess(cmd, proc.returncode, stdout, stderr)
