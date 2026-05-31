# gate-setup-check-B.ps1
# Self-diagnosing setup check for Laptop B as the GATE REVIEWER.
# Run ONCE on B before starting the poller. Prints KEY=VALUE lines so the
# orchestrator on A can read the state from a single paste-back.
#
# Usage (on B):
#   powershell -ExecutionPolicy Bypass -File gate-setup-check-B.ps1
#
# Does NOT start anything and does NOT write into the bridge. Read-only checks.

$ErrorActionPreference = "Continue"
$ok = $true

function Emit($k, $v) { Write-Output "$k=$v" }

Write-Output "=== GATE-SETUP-CHECK (Laptop B / Reviewer) ==="
Write-Output ""

# --- 1. Python -------------------------------------------------------------
$py = (Get-Command python -ErrorAction SilentlyContinue)
if ($py) {
    $pyver = (& python --version 2>&1)
    Emit "PYTHON" "OK ($pyver)"
} else {
    Emit "PYTHON" "MISSING"
    $ok = $false
}

# --- 2. claude CLI (the reviewer model) ------------------------------------
$claudeBin = $env:DUAL_BRIDGE_CLAUDE_BIN
if (-not $claudeBin) {
    $cc = (Get-Command claude -ErrorAction SilentlyContinue)
    if ($cc) { $claudeBin = $cc.Source }
}
if ($claudeBin -and (Test-Path $claudeBin)) {
    Emit "CLAUDE_BIN" "OK ($claudeBin)"
} else {
    Emit "CLAUDE_BIN" "MISSING (set DUAL_BRIDGE_CLAUDE_BIN or put claude in PATH)"
    $ok = $false
}

# --- 3. git ----------------------------------------------------------------
$git = (Get-Command git -ErrorAction SilentlyContinue)
if ($git) { Emit "GIT" "OK" } else { Emit "GIT" "MISSING"; $ok = $false }

# --- 4. Bridge root reachable (Google Drive mount) -------------------------
$root = $env:DUAL_BRIDGE_ROOT
if (-not $root) {
    $root = "G:\Meine Ablage\dynamic-AI\dynamic_sharepoint\00_INBOX\dual-bridge"
}
if (Test-Path $root) {
    Emit "BRIDGE_ROOT" "OK ($root)"
    # The A-to-B lane is where the gate review task arrives.
    $laneOutbox = Join-Path $root "lane-A-to-B\outbox"
    if (Test-Path $laneOutbox) {
        Emit "LANE_A_TO_B_OUTBOX" "OK"
    } else {
        Emit "LANE_A_TO_B_OUTBOX" "ABSENT (created on first ensure_dirs - not fatal)"
    }
} else {
    Emit "BRIDGE_ROOT" "UNREACHABLE ($root) - set DUAL_BRIDGE_ROOT if the Drive letter differs on B"
    $ok = $false
}

# --- 5. Endpoint identity --------------------------------------------------
$endpoint = $env:DUAL_BRIDGE_ENDPOINT
if ($endpoint -eq "codex@laptop-b") {
    Emit "ENDPOINT" "OK (codex@laptop-b)"
} elseif (-not $endpoint) {
    Emit "ENDPOINT" "UNSET - you MUST set: `$env:DUAL_BRIDGE_ENDPOINT='codex@laptop-b'  (else B defaults to A and won't poll the A-to-B lane)"
    $ok = $false
} else {
    Emit "ENDPOINT" "UNEXPECTED ($endpoint) - expected codex@laptop-b"
    $ok = $false
}

# --- 6. Scripts present + self-test ----------------------------------------
$scriptDir = $PSScriptRoot
$needed = @("handoff_poll.py","bridge_common.py","claude_adapter.py","runners.py")
$missing = @()
foreach ($f in $needed) {
    if (-not (Test-Path (Join-Path $scriptDir $f))) { $missing += $f }
}
if ($missing.Count -eq 0) {
    Emit "SCRIPTS" "OK"
} else {
    Emit "SCRIPTS" ("MISSING: " + ($missing -join ","))
    $ok = $false
}

# Phase-0 review verdict must be present in this checkout (gate needs it).
$pollText = ""
$pollPath = Join-Path $scriptDir "handoff_poll.py"
if (Test-Path $pollPath) { $pollText = Get-Content $pollPath -Raw }
if ($pollText -match "parse_verdict" -and $pollText -match "MIRROR_FIELDS") {
    Emit "PHASE0_REVIEW_VERDICT" "OK (parse_verdict + MIRROR_FIELDS present)"
} else {
    Emit "PHASE0_REVIEW_VERDICT" "MISSING - this checkout predates Phase 0. Run: git pull (need commit d99cc8b or later)"
    $ok = $false
}

# --- 7. Verdict line in the latest commit (informational) ------------------
Push-Location $scriptDir
try {
    $head = (& git log --oneline -1 2>$null)
    if ($head) { Emit "BRIDGE_HEAD" $head }
} catch { }
Pop-Location

Write-Output ""
if ($ok) {
    Emit "RESULT" "READY - alle Checks bestanden. Naechster Schritt: Poller starten (siehe PICKUP)."
} else {
    Emit "RESULT" "NOT-READY - mindestens ein Check oben failte. Fix + erneut laufen."
}
Write-Output "=== ENDE ==="
