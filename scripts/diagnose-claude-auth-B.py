"""Phase-6 reviewer AUTH diagnosis — run ON LAPTOP B.

The reviewer ran end-to-end but answered 'Invalid API key'. This pins WHY:
- Is an ANTHROPIC_API_KEY inherited into the subprocess env (the DCO brain.py
  leak pattern: a stray/invalid key forces API billing/auth instead of the
  Claude subscription login)?
- Does `claude -p` work when that key is REMOVED from the env (i.e. is the
  subscription login present and sufficient)?

Read-only. Prints KEY=VALUE + the actual claude answers. Paste back to A.

Usage on B:
    cd C:\\Users\\domes\\AI\\dual-bridge\\scripts
    python diagnose-claude-auth-B.py
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass


def line(k, v):
    print(f"{k}={v}")


print("=== CLAUDE AUTH DIAGNOSIS (Laptop B) ===\n")

exe = os.environ.get("DUAL_BRIDGE_CLAUDE_BIN") or shutil.which("claude")
line("RESOLVED_CLAUDE", exe)

# 1. Is a key present in this environment?
key = os.environ.get("ANTHROPIC_API_KEY")
if key:
    line("ANTHROPIC_API_KEY_PRESENT", "YES")
    line("KEY_LEN", len(key))
    line("KEY_PREFIX", key[:7] + "...")
else:
    line("ANTHROPIC_API_KEY_PRESENT", "NO (good — subscription login should be used)")

prompt = "Reply with exactly the single word: PING"

# 2. claude AS THE ADAPTER CALLS IT (full inherited env) ---------------------
print("\n--- Test 1: claude -p with FULL inherited env (what the reviewer does) ---")
try:
    p = subprocess.run([exe, "-p", "--output-format", "json",
                        "--settings", '{"disableAllHooks": true}', prompt],
                       capture_output=True, text=True, encoding="utf-8",
                       stdin=subprocess.DEVNULL, timeout=120)
    line("T1_EXIT", p.returncode)
    print("T1_STDOUT (first 500):\n" + (p.stdout or "")[:500])
    print("T1_STDERR (first 800):\n" + (p.stderr or "")[:800])
except Exception as exc:  # noqa: BLE001
    line("T1_EXCEPTION", f"{type(exc).__name__}: {exc}")

# 3. claude WITHOUT a possibly-bad inherited key (force subscription) --------
print("\n--- Test 2: claude -p with ANTHROPIC_API_KEY REMOVED (force subscription login) ---")
env2 = dict(os.environ)
removed = env2.pop("ANTHROPIC_API_KEY", None)
line("REMOVED_KEY_FROM_ENV", "yes" if removed else "no key was set")
try:
    p = subprocess.run([exe, "-p", "--output-format", "json",
                        "--settings", '{"disableAllHooks": true}', prompt],
                       capture_output=True, text=True, encoding="utf-8",
                       stdin=subprocess.DEVNULL, timeout=120, env=env2)
    line("T2_EXIT", p.returncode)
    print("T2_STDOUT (first 500):\n" + (p.stdout or "")[:500])
    print("T2_STDERR (first 800):\n" + (p.stderr or "")[:800])
except Exception as exc:  # noqa: BLE001
    line("T2_EXCEPTION", f"{type(exc).__name__}: {exc}")

# 4. Where might the key come from? (do NOT print secrets, just sources) ------
print("\n--- Key sources (names only, no values) ---")
for var in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_API_KEY"):
    line(f"ENV_{var}", "set" if os.environ.get(var) else "unset")
# .env files near the bridge that might inject a key into a parent shell:
for cand in (".env", "../.env", os.path.expanduser("~/.env")):
    line(f"ENVFILE_{cand}", "exists" if os.path.exists(cand) else "absent")

print("\n=== ENDE — bitte die ganze Ausgabe an A zurueck ===")
print("Interpretation:")
print("  - T1 fail + T2 ok  -> a BAD inherited ANTHROPIC_API_KEY is the cause")
print("    (fix: unset it for the reviewer subprocess, like the DCO brain.py leak)")
print("  - T1 fail + T2 fail -> claude has NO valid auth on B")
print("    (fix: run `claude` interactively on B once and log in to the subscription)")
