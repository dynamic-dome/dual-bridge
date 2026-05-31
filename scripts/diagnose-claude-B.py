"""Phase-6 reviewer diagnosis — run ON LAPTOP B.

Reproduces the EXACT claude_adapter subprocess call and prints the full
truth: resolved binary, exit code, stdout, stderr. The bridge result only
showed 'claude exit 1' with an empty stderr excerpt — this script captures
what actually happened so we can fix the real cause (not guess).

Usage on B:
    cd C:\\Users\\domes\\AI\\dual-bridge\\scripts
    python diagnose-claude-B.py
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


print("=== CLAUDE REVIEWER DIAGNOSIS (Laptop B) ===\n")

# 1. How the adapter resolves the binary.
exe = os.environ.get("DUAL_BRIDGE_CLAUDE_BIN") or shutil.which("claude")
line("RESOLVED_CLAUDE", exe)
if exe:
    line("ENDS_WITH", os.path.splitext(exe)[1].lower())
    line("EXISTS", os.path.exists(exe))

prompt = ("Is running a force push on a throwaway test repo safe? Answer in one "
          "short sentence, then end with exactly one line: `VERDICT: accepted` "
          "or `VERDICT: rejected`.")

# 2. Variant A — EXACTLY what the adapter does today: [exe, -p, ...].
print("\n--- Variant A: subprocess.run([exe, '-p', '--output-format', 'json', "
      "'--settings', '{\"disableAllHooks\": true}', prompt]) ---")
env = dict(os.environ)
env["CLAUDE_CODE_DISABLE_HOOKS"] = "1"
cmd_a = [exe, "-p", "--output-format", "json",
         "--settings", '{"disableAllHooks": true}', prompt]
try:
    p = subprocess.run(cmd_a, capture_output=True, text=True, encoding="utf-8",
                       stdin=subprocess.DEVNULL, timeout=180, env=env)
    line("A_EXIT", p.returncode)
    line("A_STDOUT_LEN", len(p.stdout or ""))
    print("A_STDOUT (first 600):\n" + (p.stdout or "")[:600])
    print("A_STDERR (first 1500):\n" + (p.stderr or "")[:1500])
except Exception as exc:  # noqa: BLE001
    line("A_EXCEPTION", f"{type(exc).__name__}: {exc}")

# 3. Variant B — without --settings (was --settings the new breakage?).
print("\n--- Variant B: same but WITHOUT --settings ---")
cmd_b = [exe, "-p", "--output-format", "json", prompt]
try:
    p = subprocess.run(cmd_b, capture_output=True, text=True, encoding="utf-8",
                       stdin=subprocess.DEVNULL, timeout=180, env=env)
    line("B_EXIT", p.returncode)
    print("B_STDERR (first 1500):\n" + (p.stderr or "")[:1500])
except Exception as exc:  # noqa: BLE001
    line("B_EXCEPTION", f"{type(exc).__name__}: {exc}")

# 4. Variant C — resolve a .cmd/.exe instead of .ps1 (§10.2: spawn can't run .ps1
#    directly; npm ships claude.cmd next to claude.ps1).
print("\n--- Variant C: prefer claude.cmd/.exe over .ps1 ---")
alt = None
if exe:
    base = exe
    for suffix in (".ps1", ".bat"):
        if base.lower().endswith(suffix):
            base = base[: -len(suffix)]
            break
    for cand in (base + ".cmd", base + ".exe", base):
        if os.path.exists(cand):
            alt = cand
            break
line("ALT_BINARY", alt)
if alt and alt != exe:
    cmd_c = [alt, "-p", "--output-format", "json",
             "--settings", '{"disableAllHooks": true}', prompt]
    try:
        p = subprocess.run(cmd_c, capture_output=True, text=True, encoding="utf-8",
                           stdin=subprocess.DEVNULL, timeout=180, env=env)
        line("C_EXIT", p.returncode)
        line("C_STDOUT_LEN", len(p.stdout or ""))
        print("C_STDERR (first 1500):\n" + (p.stderr or "")[:1500])
    except Exception as exc:  # noqa: BLE001
        line("C_EXCEPTION", f"{type(exc).__name__}: {exc}")
else:
    print("(no distinct .cmd/.exe alternative found)")

print("\n=== ENDE — bitte die ganze Ausgabe an A zurueck ===")
