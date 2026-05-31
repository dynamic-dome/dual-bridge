# diagnose-codex-sandbox-B.ps1
# Self-diagnosing check for the codex sandbox on Laptop B (the WORKER).
# Triggered by a live failure 2026-05-31: codex returned
#   "windows sandbox: spawn setup refresh"
# when run with `-s workspace-write` during an implement task.
#
# Run ONCE on B. Prints KEY=VALUE lines so the orchestrator on A can read the
# whole state from a single paste-back. Read-only-ish: it runs codex against a
# THROWAWAY temp dir with a trivial prompt, writes nothing into the bridge or
# any real repo.
#
# Usage (on B):
#   powershell -ExecutionPolicy Bypass -File diagnose-codex-sandbox-B.ps1
#
# Paste the full output back to A.

$ErrorActionPreference = "Continue"
function Emit($k, $v) { Write-Output "$k=$v" }

Write-Output "=== DIAGNOSE-CODEX-SANDBOX (Laptop B / Worker) ==="
Write-Output ""

# --- 1. codex binary + version --------------------------------------------
$codexCmd = Get-Command codex -ErrorAction SilentlyContinue
if (-not $codexCmd) {
    Emit "CODEX_BIN" "MISSING (codex not on PATH)"
    Emit "RESULT" "NOT-READY"
    Write-Output "=== ENDE ==="
    exit 1
}
Emit "CODEX_BIN" "OK ($($codexCmd.Source))"
$ver = (& codex --version 2>&1) -join " "
Emit "CODEX_VERSION" $ver

# --- 2. OS / build context (sandbox is OS-version sensitive) ---------------
$os = (Get-CimInstance Win32_OperatingSystem -ErrorAction SilentlyContinue)
if ($os) { Emit "OS_BUILD" "$($os.Caption) build $($os.BuildNumber)" }
Emit "WHOAMI" (whoami)
# Admin? (codex windows sandbox can behave differently elevated)
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltinRole]::Administrator)
Emit "IS_ADMIN" $isAdmin

# --- 3. throwaway workdir for the probes -----------------------------------
$work = Join-Path $env:TEMP ("codex-sbx-" + [Guid]::NewGuid().ToString("N").Substring(0,8))
New-Item -ItemType Directory -Path $work -Force | Out-Null
$ansFile = Join-Path $env:TEMP ("codex-ans-" + [Guid]::NewGuid().ToString("N").Substring(0,8) + ".txt")
$prompt = "Reply with exactly the word PONG and change no files."

function Probe-Sandbox($mode) {
    # Runs codex exec in $mode against the throwaway workdir, prompt via stdin
    # (matches the adapter fix). Returns a short status string.
    if (Test-Path $ansFile) { Remove-Item $ansFile -Force -ErrorAction SilentlyContinue }
    $stderrFile = Join-Path $env:TEMP ("codex-err-" + [Guid]::NewGuid().ToString("N").Substring(0,6) + ".txt")
    try {
        $p = Start-Process -FilePath $codexCmd.Source `
            -ArgumentList @("exec", "-C", $work, "-s", $mode, "-o", $ansFile, "-") `
            -RedirectStandardInput "NUL" `
            -RedirectStandardError $stderrFile `
            -NoNewWindow -PassThru -Wait -ErrorAction Stop
        # NOTE: stdin via NUL means no prompt -> codex may wait; so instead we
        # feed the prompt through cmd piping below if this returns empty.
        $code = $p.ExitCode
    } catch {
        return "EXC: $($_.Exception.Message)"
    }
    $err = ""
    if (Test-Path $stderrFile) { $err = (Get-Content $stderrFile -Raw -ErrorAction SilentlyContinue) }
    Remove-Item $stderrFile -Force -ErrorAction SilentlyContinue
    if ($err -match "spawn setup refresh|sandbox") { return "SANDBOX-ERROR: $($err.Trim() -replace '\s+',' ')".Substring(0, [Math]::Min(160, "SANDBOX-ERROR: $err".Length)) }
    if ($code -ne 0) { return "EXIT $code :: $($err.Trim() -replace '\s+',' ')".Substring(0, [Math]::Min(160, 80)) }
    if (Test-Path $ansFile) {
        $ans = (Get-Content $ansFile -Raw -ErrorAction SilentlyContinue).Trim()
        return "OK (answer: $($ans.Substring(0,[Math]::Min(40,$ans.Length))))"
    }
    return "EMPTY (exit 0 but no answer file)"
}

# The probe above with NUL stdin won't deliver the prompt; use a cmd pipe so
# the prompt reaches codex on stdin exactly like the adapter does.
function Probe-SandboxPiped($mode) {
    if (Test-Path $ansFile) { Remove-Item $ansFile -Force -ErrorAction SilentlyContinue }
    $errFile = Join-Path $env:TEMP ("codex-err-" + [Guid]::NewGuid().ToString("N").Substring(0,6) + ".txt")
    $exe = $codexCmd.Source
    # echo prompt | codex exec -C work -s <mode> -o ans -
    $cmdline = "echo $prompt| `"$exe`" exec -C `"$work`" -s $mode -o `"$ansFile`" - 2> `"$errFile`""
    & cmd /c $cmdline | Out-Null
    $code = $LASTEXITCODE
    $err = ""
    if (Test-Path $errFile) { $err = (Get-Content $errFile -Raw -ErrorAction SilentlyContinue) }
    Remove-Item $errFile -Force -ErrorAction SilentlyContinue
    if ($err -match "spawn setup refresh") { return "SANDBOX-REFRESH-ERROR" }
    if ($err -match "sandbox") { $t = ($err.Trim() -replace '\s+',' '); return "SANDBOX-ERROR: " + $t.Substring(0,[Math]::Min(120,$t.Length)) }
    if (Test-Path $ansFile) {
        $ans = (Get-Content $ansFile -Raw -ErrorAction SilentlyContinue).Trim()
        if ($ans) { return "OK (answer: " + $ans.Substring(0,[Math]::Min(40,$ans.Length)) + ")" }
    }
    if ($code -ne 0) { $t = ($err.Trim() -replace '\s+',' '); return "EXIT $code :: " + $t.Substring(0,[Math]::Min(100,$t.Length)) }
    return "EMPTY (exit 0, no answer)"
}

# --- 4. probe the three sandbox modes --------------------------------------
Write-Output ""
Write-Output "--- Sandbox-Proben (trivialer PONG-Prompt, Wegwerf-Workdir) ---"
Emit "PROBE_WORKSPACE_WRITE" (Probe-SandboxPiped "workspace-write")
Emit "PROBE_READ_ONLY"       (Probe-SandboxPiped "read-only")
Emit "PROBE_DANGER_FULL"     (Probe-SandboxPiped "danger-full-access")

# --- 5. cleanup ------------------------------------------------------------
Remove-Item $work -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item $ansFile -Force -ErrorAction SilentlyContinue

Write-Output ""
Write-Output "Deutung:"
Write-Output "  - workspace-write SANDBOX-REFRESH-ERROR, read-only OK  -> Sandbox-Spawn-Bug nur"
Write-Output "    im write-Modus (codex-CLI/Windows-Sandbox-Problem). Workaround pruefen:"
Write-Output "    codex updaten (npm i -g @openai/codex@latest) ODER -s danger-full-access"
Write-Output "    (nur auf Wegwerf-Repos, Threat-Model)."
Write-Output "  - alle drei SANDBOX-ERROR -> codex-Sandbox grundsaetzlich kaputt auf B,"
Write-Output "    codex-Neuinstallation/Update noetig."
Write-Output "  - workspace-write OK -> Fehler war transient; Task einfach neu fahren."
Write-Output ""
Write-Output "=== ENDE DIAGNOSE ==="
