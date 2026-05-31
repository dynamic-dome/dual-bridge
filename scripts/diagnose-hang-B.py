"""Phase-6 reviewer HANG diagnosis — run ON LAPTOP B.

The reviewer subprocess hangs on certain review prompts (claimed but never
produces a result). Hypothesis: `claude -p` blocks on an interactive
permission prompt headless. This isolates the exact adapter call with a SHORT
60s timeout and a trivial prompt, then a realistic review prompt, so we see
which one hangs.

STOP the poller first (Strg+C) so it doesn't fight us for the bridge.

Usage on B:
    cd C:\\Users\\domes\\AI\\dual-bridge\\scripts
    python diagnose-hang-B.py
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass


def line(k, v):
    print(f"{k}={v}")


exe = os.environ.get("DUAL_BRIDGE_CLAUDE_BIN") or shutil.which("claude")
line("RESOLVED_CLAUDE", exe)

# Same env hardening the adapter now applies.
env = dict(os.environ)
env.pop("ANTHROPIC_API_KEY", None)
env.pop("ANTHROPIC_AUTH_TOKEN", None)
env["CLAUDE_CODE_DISABLE_HOOKS"] = "1"


def run(label, prompt, timeout):
    print(f"\n--- {label} (timeout {timeout}s) ---")
    cmd = [exe, "-p", "--output-format", "json",
           "--settings", '{"disableAllHooks": true}', prompt]
    t0 = time.time()
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                           stdin=subprocess.DEVNULL, timeout=timeout, env=env)
        dt = round(time.time() - t0, 1)
        line(f"{label}_EXIT", p.returncode)
        line(f"{label}_SECONDS", dt)
        line(f"{label}_STDOUT_LEN", len(p.stdout or ""))
        print(f"{label}_STDOUT (first 400):\n" + (p.stdout or "")[:400])
        if p.stderr:
            print(f"{label}_STDERR (first 600):\n" + p.stderr[:600])
    except subprocess.TimeoutExpired:
        dt = round(time.time() - t0, 1)
        line(f"{label}_RESULT", f"HANG/TIMEOUT after {dt}s")


print("=== REVIEWER HANG DIAGNOSIS (Laptop B) ===")

# Test 1: trivial prompt — does claude -p answer AT ALL within 60s?
run("T1_trivial", "Reply with exactly one word: PING", 60)

# Test 2: a review prompt that NAMES a risky action (the real gate shape).
# If T1 answers but T2 hangs, claude is blocking on a permission/confirmation
# for the action it is asked to reason about.
review = ("Adversarially review whether running `git push origin main` is safe. "
          "Answer in one sentence, then end with exactly one line: "
          "`VERDICT: accepted` or `VERDICT: rejected`. Do NOT run any command; "
          "only judge.")
run("T2_review", review, 90)

print("\n=== ENDE — bitte ganze Ausgabe an A ===")
print("Interpretation:")
print("  T1 ok + T2 ok    -> no hang; earlier hang was transient")
print("  T1 ok + T2 HANG  -> review prompt triggers an interactive block headless")
print("  T1 HANG          -> claude -p hangs even on a trivial prompt on B")
