<#
  register_mirror.ps1 - b1 Ops-State-Mirror (Loop-Host -> Drive).

  Registriert einen Scheduled Task, der den read-only State-Mirror periodisch
  laufen laesst (bridge_mirror.py). Jeder Trigger ist EIN Lauf (kein --watch):
  er spiegelt LOOP-*.jsonl / ESCALATION-*.md / _overnight / _notify nach
  <bridge_root>/_ops-state-mirror/, damit die DCO-Ops-Konsole auf einem ANDEREN
  Knoten (DCO != Loop-Host) diesen State lesen kann.

  SICHER trotz blindem Start: bridge_mirror schreibt NUR in den Mirror, nie in
  den Source-State; ein Lauf ist idempotent (Copy-over + Prune aufgeloester
  Eintraege). Laeuft auf dem LOOP-HOST (praktisch Laptop A), wo loop_driver die
  LOOP-/ESCALATION-Dateien ablegt.

  Erst NACH einem gruenen Dry-Run aktivieren:
      python -X utf8 bridge_mirror.py --dry-run

  Aktivieren (Default: alle 5 min, Default-Pfade):
      powershell -ExecutionPolicy Bypass -File register_mirror.ps1
  Anderer Takt / explizite Pfade:
      powershell -ExecutionPolicy Bypass -File register_mirror.ps1 -IntervalMinutes 10 -Mirror "G:\...\_ops-state-mirror"
  Deaktivieren:
      Unregister-ScheduledTask -TaskName "DualBridgeOpsMirror" -Confirm:$false
#>
param(
    [string]$ScriptsDir = $PSScriptRoot,
    [int]$IntervalMinutes = 5,
    # Optionale Overrides; leer = Defaults aus bridge_mirror (DUAL_BRIDGE_STATE
    # bzw. scripts/state und <bridge_root>/_ops-state-mirror).
    [string]$State = "",
    [string]$Mirror = ""
)

$ErrorActionPreference = "Stop"
$python = (Get-Command python).Source
$mirror_py = Join-Path $ScriptsDir "bridge_mirror.py"

if (-not (Test-Path $mirror_py)) {
    Write-Error "bridge_mirror.py nicht gefunden in $ScriptsDir"
    exit 1
}

$argList = @("-X", "utf8", "`"$mirror_py`"")
if ($State)  { $argList += @("--state",  "`"$State`"") }
if ($Mirror) { $argList += @("--mirror", "`"$Mirror`"") }

$action = New-ScheduledTaskAction -Execute $python `
    -Argument ($argList -join " ") `
    -WorkingDirectory $ScriptsDir

$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes)

$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -StartWhenAvailable

Register-ScheduledTask -TaskName "DualBridgeOpsMirror" `
    -Action $action -Trigger $trigger -Settings $settings `
    -Description "Spiegelt A-seitigen Loop-State alle $IntervalMinutes min read-only auf den Drive (b1, fuer die DCO-Ops-Konsole)." `
    -Force

Write-Host "Ops-State-Mirror registriert: DualBridgeOpsMirror (alle $IntervalMinutes min)."
Write-Host "Deaktivieren: Unregister-ScheduledTask -TaskName 'DualBridgeOpsMirror' -Confirm:`$false"
