<#
  register_overnight.ps1 - Dual-Bridge Overnight-Scheduler (lokaler Trigger, OPTIONAL).

  Registriert einen Scheduled Task, der einmal taeglich (Default 02:00)
  bridge_overnight.py startet und die Queue vordefinierter goal-loop-Seeds
  (Default docs/overnight/*.md) SERIELL abarbeitet. Am Ende wird EIN Morgen-Digest
  per Telegram gesendet (ueber bridge_notify). Eskalationen einzelner Seeds meldet
  ohnehin der separate DualBridgeEscalationNotifier-Task.

  SICHER: bridge_overnight.py ist read-mostly (schreibt nur state/_overnight/runs/),
  fail-soft je Seed (ein Fehler bricht den Batch nicht ab) und fail-closed bei
  Fehlkonfiguration (nicht-leere Queue ohne -Repo -> Exit 2, nichts gestartet).

  Voraussetzung:
  - TELEGRAM_TOKEN + TELEGRAM_CHAT_ID im Task-Kontext sichtbar (fuer den Digest).
  - Eine Queue docs/overnight/*.md mit goal-loop-Seeds (## Ziel / ## Done-Kriterien).
  - codex + claude wie beim manuellen goal-loop verfuegbar/eingeloggt.

  Erst NACH einem erfolgreichen Trockenlauf aktivieren:
      python bridge_overnight.py --dry-run --repo https://github.com/dynamic-dome/dual-bridge

  Aktivieren (taeglich 02:00):
      powershell -ExecutionPolicy Bypass -File register_overnight.ps1 -Repo https://github.com/dynamic-dome/dual-bridge

  Andere Uhrzeit / Queue / Runden:
      powershell -ExecutionPolicy Bypass -File register_overnight.ps1 -Repo <URL> -At 03:30 -Queue docs\overnight -MaxRounds 6

  ZWEI Timeout-Schranken (beide muessen passen, sonst greift die kleinste):
    -RoundTimeout  : wie lange loop_driver auf B's Ergebnis wartet (--round-timeout).
    -CodexTimeout  : wie lange `codex exec` selbst laufen darf, bevor es gekillt
                     wird (Env DUAL_BRIDGE_CODEX_TIMEOUT, codex_adapter Default 600).
                     Eine zu grosse Aufgabe stirbt sonst mit 'codex timeout nach 600s'
                     OBWOHL der Clone laengst lief (beobachtet 2026-06-06, DCO-Seed).
                     Default = RoundTimeout; wird im Task-Kontext per `cmd /c set`
                     gesetzt (setx in der aufrufenden Shell erreicht den Task NICHT).
      powershell -ExecutionPolicy Bypass -File register_overnight.ps1 -Repo <URL> -RoundTimeout 1800 -CodexTimeout 1800

  -WakeToRun: weckt den Rechner zur Laufzeit (sonst laeuft der Task erst beim naechsten Aufwachen).

  Deaktivieren:
      Unregister-ScheduledTask -TaskName "DualBridgeOvernight" -Confirm:$false
#>
param(
    [Parameter(Mandatory = $true)][string]$Repo,
    [string]$ScriptsDir = $PSScriptRoot,
    [string]$At = "02:00",
    [string]$Queue = "docs/overnight",
    [int]$MaxRounds = 4,
    [int]$RoundTimeout = 600,
    [int]$CodexTimeout = 0,
    [switch]$WakeToRun
)

# Default CodexTimeout to RoundTimeout so the inner (codex exec) and outer
# (loop_driver wait) limits stay aligned unless the caller overrides it.
if ($CodexTimeout -le 0) { $CodexTimeout = $RoundTimeout }

$ErrorActionPreference = "Stop"
$python = (Get-Command python).Source
$overnight = Join-Path $ScriptsDir "bridge_overnight.py"

if (-not (Test-Path $overnight)) {
    Write-Error "bridge_overnight.py nicht gefunden in $ScriptsDir"
    exit 1
}

# Repo-Wurzel = ein Verzeichnis ueber scripts/, damit der relative Queue-Pfad passt.
$repoRoot = Split-Path $ScriptsDir -Parent

# Set DUAL_BRIDGE_CODEX_TIMEOUT *inside the task process* via `cmd /c set && ...`
# (see register_jobpoll.ps1 for why a registering-shell setx is not enough).
$pyArgs = "`"$overnight`" --queue `"$Queue`" --repo `"$Repo`" " +
          "--max-rounds $MaxRounds --round-timeout $RoundTimeout"
$argLine = "/c set DUAL_BRIDGE_CODEX_TIMEOUT=$CodexTimeout && `"$python`" $pyArgs"

$action = New-ScheduledTaskAction -Execute "cmd.exe" `
    -Argument $argLine -WorkingDirectory $repoRoot

$trigger = New-ScheduledTaskTrigger -Daily -At $At

$settingsParams = @{
    AllowStartIfOnBatteries    = $true
    DontStopIfGoingOnBatteries = $true
    StartWhenAvailable         = $true
}
if ($WakeToRun) { $settingsParams["WakeToRun"] = $true }
$settings = New-ScheduledTaskSettingsSet @settingsParams

Register-ScheduledTask -TaskName "DualBridgeOvernight" `
    -Action $action -Trigger $trigger -Settings $settings `
    -Description "Arbeitet nachts ($At) die goal-loop-Queue '$Queue' ab und sendet einen Morgen-Digest per Telegram (read-mostly, fail-soft)." `
    -Force

Write-Host "Overnight-Scheduler registriert: DualBridgeOvernight (taeglich $At, Queue '$Queue', round-timeout ${RoundTimeout}s, codex-timeout ${CodexTimeout}s)."
Write-Host ""
Write-Host "WICHTIG: Vorher testen mit:  python bridge_overnight.py --dry-run --repo $Repo"
Write-Host "Deaktivieren: Unregister-ScheduledTask -TaskName 'DualBridgeOvernight' -Confirm:`$false"
