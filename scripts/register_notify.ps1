<#
  register_notify.ps1 - Dual-Bridge Eskalations-Notifier (lokaler Trigger, OPTIONAL).

  Registriert einen Scheduled Task, der periodisch bridge_notify.py startet und
  NEUE Eskalationen (state/ESCALATION-*.md) per Telegram meldet.

  SICHER trotz blindem Start: bridge_notify.py ist idempotent (Dedup ueber
  state/_notify/sent.json) und schreibt NICHTS in die Eskalations-Artefakte oder
  Lanes - ein erneuter Lauf pingt eine bereits gemeldete Eskalation nicht noch
  einmal. Analog zum Singleton-Lock-Schutz des Pollers.

  Voraussetzung: TELEGRAM_TOKEN + TELEGRAM_CHAT_ID muessen fuer den Task-Kontext
  sichtbar sein (System-/User-Env), sonst endet der Notifier mit rc=2 "nicht
  konfiguriert". Erst NACH einem erfolgreichen Trockenlauf aktivieren:
      python bridge_notify.py --dry-run

  Aktivieren (nur Eskalations-Alerts, alle 10 min):
      powershell -ExecutionPolicy Bypass -File register_notify.ps1

  Mit zusaetzlichem Tages-Digest (einmal taeglich 08:00):
      powershell -ExecutionPolicy Bypass -File register_notify.ps1 -Digest

  Deaktivieren:
      Unregister-ScheduledTask -TaskName "DualBridgeEscalationNotifier" -Confirm:$false
      Unregister-ScheduledTask -TaskName "DualBridgeDailyDigest" -Confirm:$false
#>
param(
    [string]$ScriptsDir = $PSScriptRoot,
    [int]$IntervalMinutes = 10,
    [switch]$Digest,
    [string]$DigestTime = "08:00"
)

$ErrorActionPreference = "Stop"
$python = (Get-Command python).Source
$notify = Join-Path $ScriptsDir "bridge_notify.py"

if (-not (Test-Path $notify)) {
    Write-Error "bridge_notify.py nicht gefunden in $ScriptsDir"
    exit 1
}

# --- Task 1: periodischer Eskalations-Alert ---------------------------------
$action = New-ScheduledTaskAction -Execute $python `
    -Argument "`"$notify`"" -WorkingDirectory $ScriptsDir

$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes)

$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -StartWhenAvailable

Register-ScheduledTask -TaskName "DualBridgeEscalationNotifier" `
    -Action $action -Trigger $trigger -Settings $settings `
    -Description "Meldet neue Dual-Bridge-Eskalationen alle $IntervalMinutes min per Telegram (idempotent ueber sent.json)." `
    -Force

Write-Host "Notifier registriert: DualBridgeEscalationNotifier (alle $IntervalMinutes min)."

# --- Task 2 (optional): taeglicher Status-Digest ----------------------------
if ($Digest) {
    $digestAction = New-ScheduledTaskAction -Execute $python `
        -Argument "`"$notify`" --digest" -WorkingDirectory $ScriptsDir
    $digestTrigger = New-ScheduledTaskTrigger -Daily -At $DigestTime
    Register-ScheduledTask -TaskName "DualBridgeDailyDigest" `
        -Action $digestAction -Trigger $digestTrigger -Settings $settings `
        -Description "Sendet einmal taeglich ($DigestTime) eine Dual-Bridge-Statuszusammenfassung per Telegram." `
        -Force
    Write-Host "Digest registriert: DualBridgeDailyDigest (taeglich $DigestTime)."
}

Write-Host ""
Write-Host "WICHTIG: Vorher testen mit:  python bridge_notify.py --dry-run"
Write-Host "Deaktivieren: Unregister-ScheduledTask -TaskName 'DualBridgeEscalationNotifier' -Confirm:`$false"
