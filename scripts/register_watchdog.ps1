<#
  register_watchdog.ps1 - Dual-Bridge Poller-Watchdog (Laptop B, OPTIONAL).

  Registriert einen Scheduled Task, der alle 10 Minuten den Poller startet.
  SICHER trotz blindem Start: handoff_poll.py haelt einen lokalen Singleton-Lock
  (acquire_singleton_lock) - ein zweiter Poller beendet sich sofort selbst.
  Damit kann NIE doppelt geclaimt / doppelt codex-aufgerufen werden.

  Erst NACH dem ersten erfolgreichen manuellen Roundtrip aktivieren.

  Aktivieren:    powershell -ExecutionPolicy Bypass -File register_watchdog.ps1
  Deaktivieren:  Unregister-ScheduledTask -TaskName "DualBridgePollerWatchdog" -Confirm:$false
#>
param(
    [string]$ScriptsDir = $PSScriptRoot,
    [int]$IntervalMinutes = 10
)

$ErrorActionPreference = "Stop"
$python = (Get-Command python).Source
$poller = Join-Path $ScriptsDir "handoff_poll.py"

if (-not (Test-Path $poller)) {
    Write-Error "handoff_poll.py nicht gefunden in $ScriptsDir"
    exit 1
}

$action = New-ScheduledTaskAction -Execute $python `
    -Argument "`"$poller`" --watch" -WorkingDirectory $ScriptsDir

$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes)

$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -StartWhenAvailable

Register-ScheduledTask -TaskName "DualBridgePollerWatchdog" `
    -Action $action -Trigger $trigger -Settings $settings `
    -Description "Startet den Dual-Bridge-Poller alle $IntervalMinutes min (Self-Guard verhindert Doppelstart)." `
    -Force

Write-Host "Watchdog registriert: DualBridgePollerWatchdog (alle $IntervalMinutes min)."
Write-Host "Deaktivieren: Unregister-ScheduledTask -TaskName 'DualBridgePollerWatchdog' -Confirm:`$false"
