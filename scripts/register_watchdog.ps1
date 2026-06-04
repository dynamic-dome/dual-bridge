<#
  register_watchdog.ps1 - Dual-Bridge Poller-Watchdog (Laptop B, OPTIONAL).

  Registriert einen Scheduled Task, der den Reviewer-Poller im --watch-Modus
  haelt (handoff_poll.py --watch --interval N). Der Task startet einmal beim
  Anlegen und wird alle $IntervalMinutes erneut getriggert; faellt der Watch-
  Prozess je aus, hebt ihn der naechste Trigger wieder an.

  SICHER trotz blindem Start: handoff_poll.py haelt einen lokalen Singleton-Lock
  (acquire_singleton_lock) - ein zweiter Poller beendet sich sofort selbst.
  Damit kann NIE doppelt geclaimt / doppelt codex-aufgerufen werden.

  Dies ist der REVIEWER-Knoten der Zwei-Knoten-Topologie (liest die Drive-Datei-
  Bridge unter bridge_root(); braucht KEINE DCO-HTTP-Env). Der Builder-Knoten
  (job_poll.py, HTTP-Pull vom DCO) wird separat ueber register_jobpoll.ps1
  registriert.

  Erst NACH dem ersten erfolgreichen manuellen Roundtrip aktivieren.

  Aktivieren (Default --interval 15s):
      powershell -ExecutionPolicy Bypass -File register_watchdog.ps1
  Anderes Poll-Intervall (Sekunden) / anderer Re-Trigger-Takt (Minuten):
      powershell -ExecutionPolicy Bypass -File register_watchdog.ps1 -Interval 30 -IntervalMinutes 5
  Deaktivieren:  Unregister-ScheduledTask -TaskName "DualBridgePollerWatchdog" -Confirm:$false
#>
param(
    [string]$ScriptsDir = $PSScriptRoot,
    [int]$IntervalMinutes = 10,
    [int]$Interval = 15
)

$ErrorActionPreference = "Stop"
$python = (Get-Command python).Source
$poller = Join-Path $ScriptsDir "handoff_poll.py"

if (-not (Test-Path $poller)) {
    Write-Error "handoff_poll.py nicht gefunden in $ScriptsDir"
    exit 1
}

$action = New-ScheduledTaskAction -Execute $python `
    -Argument "`"$poller`" --watch --interval $Interval" -WorkingDirectory $ScriptsDir

$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes)

$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -StartWhenAvailable

Register-ScheduledTask -TaskName "DualBridgePollerWatchdog" `
    -Action $action -Trigger $trigger -Settings $settings `
    -Description "Startet den Dual-Bridge-Poller alle $IntervalMinutes min (Self-Guard verhindert Doppelstart)." `
    -Force

Write-Host "Watchdog registriert: DualBridgePollerWatchdog (Re-Trigger alle $IntervalMinutes min, Poll alle ${Interval}s)."
Write-Host "Deaktivieren: Unregister-ScheduledTask -TaskName 'DualBridgePollerWatchdog' -Confirm:`$false"
