<#
  watch_watchdog.ps1 - Eine Uebersicht ueber den DualBridgePollerWatchdog.

  Vereint drei Blicke:
    1. bridge_status.py            (read-only Live-Snapshot der Bridge)
    2. laufender Watch-Prozess?    (python ... handoff_poll.py --watch)
    3. Scheduled-Task-Historie     (LastRun / NextRun / LastResult)

  Schreibt nie. Reiner Lese-/Diagnose-Blick.

  Einmal:        powershell -ExecutionPolicy Bypass -File watch_watchdog.ps1
  Dauerschleife: powershell -ExecutionPolicy Bypass -File watch_watchdog.ps1 -Loop
                 (alle -Every Sekunden neu, Strg+C beendet)
#>
param(
    [switch]$Loop,
    [int]$Every = 15,
    [string]$ScriptsDir = $PSScriptRoot,
    # Lange loops-Liste standardmaessig ausblenden (Kopfzeile reicht); -Full zeigt alles.
    [switch]$Full
)

$ErrorActionPreference = "Continue"
$taskName = "DualBridgePollerWatchdog"

function Show-Overview {
    Clear-Host
    Write-Host "=== Dual-Bridge Watchdog-Uebersicht ===  $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" -ForegroundColor Cyan

    # --- 3. Scheduled-Task-Status ---
    Write-Host "`n[1] Scheduled Task" -ForegroundColor Yellow
    $task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if ($task) {
        $info = $task | Get-ScheduledTaskInfo
        $resultLabel = if ($info.LastTaskResult -eq 0) { "0 (OK)" } else { "$($info.LastTaskResult) (!)" }
        $resultColor = if ($info.LastTaskResult -eq 0) { "Green" } else { "Red" }
        Write-Host ("    State      : {0}" -f $task.State)
        Write-Host ("    LastRun    : {0}" -f $info.LastRunTime)
        Write-Host ("    NextRun    : {0}" -f $info.NextRunTime)
        Write-Host    "    LastResult : " -NoNewline
        Write-Host $resultLabel -ForegroundColor $resultColor
    } else {
        Write-Host "    NICHT REGISTRIERT" -ForegroundColor Red
    }

    # --- 2. Laufender Watch-Prozess? ---
    Write-Host "`n[2] Watch-Prozess (handoff_poll --watch)" -ForegroundColor Yellow
    $procs = Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like '*handoff_poll*' -and $_.CommandLine -like '*--watch*' }
    if ($procs) {
        foreach ($p in $procs) {
            Write-Host ("    LAEUFT  PID {0}" -f $p.ProcessId) -ForegroundColor Green
        }
        if (@($procs).Count -gt 1) {
            Write-Host ("    Hinweis: {0} Prozesse - Singleton-Lock sollte auf 1 reduzieren." -f @($procs).Count) -ForegroundColor Yellow
        }
    } else {
        Write-Host "    kein Watch-Prozess aktiv (naechster Task-Trigger startet ihn)" -ForegroundColor DarkYellow
    }

    # --- 1. Bridge-Live-Snapshot ---
    Write-Host "`n[3] bridge_status.py (read-only)" -ForegroundColor Yellow
    $statusScript = Join-Path $ScriptsDir "bridge_status.py"
    if (Test-Path -LiteralPath $statusScript) {
        $python = (Get-Command python -ErrorAction SilentlyContinue).Source
        if ($python) {
            $lines = & $python -X utf8 $statusScript 2>&1
            if (-not $Full) {
                # Den langen "--- loops ---"-Block einklappen: nur Kopfzeile + Zaehlung zeigen.
                $out = New-Object System.Collections.Generic.List[string]
                $inLoops = $false; $loopCount = 0
                foreach ($l in $lines) {
                    if ($l -match '^\s*---\s*loops\s*---') { $inLoops = $true; $out.Add($l); continue }
                    if ($inLoops) {
                        if ($l -match '^\s*---') { $inLoops = $false }   # naechster Block
                        elseif ($l -match 'loop-\d') { $loopCount++; continue }
                    }
                    $out.Add($l)
                }
                if ($loopCount -gt 0) {
                    $idx = $out.FindIndex({ param($x) $x -match '^\s*---\s*loops\s*---' })
                    if ($idx -ge 0) { $out.Insert($idx + 1, "      ($loopCount Loops ausgeblendet - -Full zeigt alle)") }
                }
                $lines = $out
            }
            $lines | ForEach-Object { Write-Host "    $_" }
        } else {
            Write-Host "    python nicht im PATH gefunden" -ForegroundColor Red
        }
    } else {
        Write-Host "    bridge_status.py nicht gefunden in $ScriptsDir" -ForegroundColor Red
    }
}

if ($Loop) {
    while ($true) {
        Show-Overview
        Write-Host "`n(Strg+C zum Beenden - aktualisiert alle $Every s)" -ForegroundColor DarkGray
        Start-Sleep -Seconds $Every
    }
} else {
    Show-Overview
}
