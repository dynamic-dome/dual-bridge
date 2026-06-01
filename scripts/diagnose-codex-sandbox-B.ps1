# diagnose-codex-sandbox-B.ps1  (v2 — robust gegen den npm .ps1-Wrapper)
# Self-diagnosing check for the codex worker on Laptop B.
#
# Triggered by two live findings 2026-05-31:
#   (1) codex returned "windows sandbox: spawn setup refresh" under
#       -s workspace-write on the first real implement task, and
#   (2) codex is installed as codex.ps1 (npm pwsh wrapper) — Python subprocess
#       (the real adapter path) cannot launch a .ps1 directly (global rule 10.2).
#
# This script does NOT use `cmd /c` against the .ps1 (that was the v1 bug that
# dropped a stray codex.ps1 into the cwd). It inspects the npm bin dir, asks
# Python what it would launch, and probes codex via the .cmd shim + stdin.
#
# Run ONCE on B from the scripts/ dir:
#   powershell -ExecutionPolicy Bypass -File .\diagnose-codex-sandbox-B.ps1
# Then paste the full KEY=VALUE output back to A.

$ErrorActionPreference = "Continue"
function Emit($k, $v) { Write-Output "$k=$v" }

Write-Output "=== DIAGNOSE-CODEX-SANDBOX v2 (Laptop B / Worker) ==="
Write-Output ""

# --- 1. which codex variants exist? (npm drops .ps1 + .cmd + extensionless) -
$codexCmd = Get-Command codex -ErrorAction SilentlyContinue
if (-not $codexCmd) { Emit "CODEX_ON_PATH" "MISSING"; Emit "RESULT" "NOT-READY"; exit 1 }
Emit "CODEX_RESOLVED_BY_PATH" $codexCmd.Source
$binDir = Split-Path $codexCmd.Source -Parent
foreach ($ext in @(".cmd", ".ps1", ".exe", "")) {
    $cand = Join-Path $binDir ("codex" + $ext)
    $label = if ($ext -eq "") { "codex(noext)" } else { "codex$ext" }
    if (Test-Path $cand) { Emit "VARIANT_$label" "EXISTS" } else { Emit "VARIANT_$label" "-" }
}
$ver = (& codex --version 2>&1) -join " "
Emit "CODEX_VERSION" $ver

# --- 2. OS context ----------------------------------------------------------
$os = (Get-CimInstance Win32_OperatingSystem -ErrorAction SilentlyContinue)
if ($os) { Emit "OS_BUILD" "$($os.Caption) build $($os.BuildNumber)" }
Emit "WHOAMI" (whoami)

# --- 3. THE KEY CHECK: what does Python subprocess resolve + can it launch? --
# This is the real adapter path (codex_adapter.py: shutil.which + subprocess).
$pycode = @'
import shutil, subprocess, sys
which = shutil.which("codex")
print("PY_WHICH=" + (which or "NONE"))
if not which:
    sys.exit(0)
print("PY_WHICH_EXT=" + (which.rsplit(".",1)[-1] if "." in which else "noext"))
# Can subprocess actually start it? (.ps1 will raise; .cmd/.exe will run)
try:
    p = subprocess.run([which, "--version"], capture_output=True, text=True, timeout=30)
    out = (p.stdout or p.stderr or "").strip().splitlines()[:1]
    print("PY_SUBPROCESS_LAUNCH=OK (" + (out[0] if out else "no output") + ")")
except Exception as e:
    print("PY_SUBPROCESS_LAUNCH=FAIL (" + type(e).__name__ + ": " + str(e)[:80] + ")")
'@
$pyOut = ($pycode | python - 2>&1)
$pyOut | ForEach-Object { Write-Output $_ }

# --- 4. sandbox probe via the .CMD shim (NOT .ps1), prompt on stdin ---------
# Use codex.cmd explicitly so we never hit the .ps1 (which Python can't launch
# and which cmd-piping corrupts). Prompt piped on stdin like the fixed adapter.
$codexCmdShim = Join-Path $binDir "codex.cmd"
$work = Join-Path $env:TEMP ("codex-sbx-" + [Guid]::NewGuid().ToString("N").Substring(0,8))
New-Item -ItemType Directory -Path $work -Force | Out-Null

function Probe($mode) {
    if (-not (Test-Path $codexCmdShim)) { return "SKIP (no codex.cmd shim)" }
    $ans = Join-Path $env:TEMP ("ans-" + [Guid]::NewGuid().ToString("N").Substring(0,6) + ".txt")
    $err = Join-Path $env:TEMP ("err-" + [Guid]::NewGuid().ToString("N").Substring(0,6) + ".txt")
    # Pipe the prompt on stdin to the .cmd shim. & with a here-string via Write-Output.
    # --skip-git-repo-check: the probe workdir is a throwaway temp dir, NOT a git
    # repo, so codex 0.135 would otherwise refuse with "Not inside a trusted
    # directory" — which is a PROBE artefact, not a sandbox problem. The real
    # adapter clones a repo and passes this same flag (codex_adapter.py), so the
    # honest probe must pass it too.
    "Reply with exactly PONG and change no files." |
        & $codexCmdShim exec -C $work -s $mode --skip-git-repo-check -o $ans - 2> $err | Out-Null
    $code = $LASTEXITCODE
    $etxt = if (Test-Path $err) { (Get-Content $err -Raw -ErrorAction SilentlyContinue) } else { "" }
    Remove-Item $err -Force -ErrorAction SilentlyContinue
    if ($etxt -match "spawn setup refresh") { Remove-Item $ans -Force -ErrorAction SilentlyContinue; return "SANDBOX-REFRESH-ERROR" }
    if ($etxt -match "sandbox") { Remove-Item $ans -Force -ErrorAction SilentlyContinue; $t=($etxt.Trim() -replace '\s+',' '); return "SANDBOX-ERR: " + $t.Substring(0,[Math]::Min(110,$t.Length)) }
    if (Test-Path $ans) {
        $a = (Get-Content $ans -Raw -ErrorAction SilentlyContinue).Trim()
        Remove-Item $ans -Force -ErrorAction SilentlyContinue
        if ($a) { return "OK (" + $a.Substring(0,[Math]::Min(30,$a.Length)) + ")" }
    }
    $t = ($etxt.Trim() -replace '\s+',' ')
    return "EXIT $code :: " + $t.Substring(0,[Math]::Min(90,$t.Length))
}

Write-Output ""
Write-Output "--- Sandbox-Proben via codex.cmd (PONG-Prompt, Wegwerf-Workdir) ---"
Emit "PROBE_WORKSPACE_WRITE" (Probe "workspace-write")
Emit "PROBE_READ_ONLY"       (Probe "read-only")
Emit "PROBE_DANGER_FULL"     (Probe "danger-full-access")

Remove-Item $work -Recurse -Force -ErrorAction SilentlyContinue

Write-Output ""
Write-Output "Deutung:"
Write-Output "  - PY_WHICH endet auf .ps1 UND PY_SUBPROCESS_LAUNCH=FAIL -> der Adapter"
Write-Output "    erwischt den .ps1-Wrapper, den Python nicht starten kann. Fix im Adapter"
Write-Output "    (codex.cmd bevorzugen). [2026-06-01: auf B widerlegt, PY_WHICH=.CMD, LAUNCH=OK]"
Write-Output "  - PY_SUBPROCESS_LAUNCH=OK und alle PROBE_* OK -> codex ist gesund, der echte"
Write-Output "    Adapter-Pfad (klont Repo + --skip-git-repo-check) laeuft. KEIN B-Blocker mehr."
Write-Output "  - PROBE_* = SANDBOX-REFRESH-ERROR (spawn setup refresh) -> echtes codex-Sandbox-"
Write-Output "    Problem im write-Modus -> codex updaten / danger-full. (NICHT die Trusted-Dir-"
Write-Output "    Meldung — die war ein Probe-Artefakt vor dem --skip-git-repo-check-Fix.)"
Write-Output ""
Write-Output "=== ENDE DIAGNOSE v2 ==="
