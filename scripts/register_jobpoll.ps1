<#
  register_jobpoll.ps1 - Dual-Bridge BUILDER-Knoten (Laptop B, HTTP-Job-Pull vom DCO).

  Registriert einen Scheduled Task, der job_poll.py im --watch-Modus haelt
  (job_poll.py --watch --interval N). Der Task startet einmal beim Anlegen und
  wird alle $IntervalMinutes erneut getriggert; faellt der Watch-Prozess je aus,
  hebt ihn der naechste Trigger wieder an.

  Dies ist der BUILDER-Knoten der Zwei-Knoten-Topologie: er pollt die DCO-
  Job-Queue per HTTP (GET /api/jobs/next), baut per codex (loop_driver --mode
  goal-loop) und meldet das Ergebnis zurueck (POST /api/jobs/<id>/result). Der
  REVIEWER-Knoten (handoff_poll.py, Drive-Datei-Bridge) laeuft separat auf dem
  anderen Geraet ueber register_watchdog.ps1.

  SICHER trotz blindem Start: job_poll.py haelt einen lokalen Singleton-Lock -
  ein zweiter Builder beendet sich sofort selbst. NIE doppelt geclaimt.

  KRITISCHE VORAUSSETZUNG (sonst pollt der Builder die Datei-Bridge statt den DCO):
    Der HTTP-Pull ist nur aktiv, wenn DUAL_BRIDGE_TRANSPORT=http gesetzt ist
    (Default 'file'!). Erforderliche persistente Env-Variablen (per setx, damit
    der Scheduled-Task-Kontext sie sieht - ein in-Session 'set' reicht NICHT):

        DUAL_BRIDGE_TRANSPORT = http
        DCO_BRIDGE_URL        = https://<host>/api    (MUSS auf /api enden, sonst 404)
        DCO_BRIDGE_TOKEN      = <BRIDGE_API_TOKEN des DCO>

    Beispiel (einmalig auf B, danach neue Shell/Reboot fuer Sichtbarkeit):
        setx DUAL_BRIDGE_TRANSPORT http
        setx DCO_BRIDGE_URL  "https://bot.dynamic-dome.com/api"
        setx DCO_BRIDGE_TOKEN "<token>"

  Dieses Skript prueft die drei Variablen VOR der Registrierung und bricht
  fail-closed ab (Exit 2), wenn etwas fehlt - es registriert keinen Task, der
  garantiert in die falsche Bridge laeuft. Mit -SkipEnvCheck ueberspringbar
  (z.B. wenn die Vars erst im Task-Kontext via einer wrapper-.cmd gesetzt werden).

  Erst NACH einem erfolgreichen Trockenlauf aktivieren:
      python job_poll.py --once

  Aktivieren (Default --interval 15s):
      powershell -ExecutionPolicy Bypass -File register_jobpoll.ps1
  Anderes Poll-Intervall (Sekunden) / Re-Trigger-Takt (Minuten) / Build-Limits:
      powershell -ExecutionPolicy Bypass -File register_jobpoll.ps1 -Interval 30 -IntervalMinutes 5 -MaxRounds 6 -RoundTimeout 1800

  ZWEI Timeout-Schranken (beide muessen passen, sonst greift die kleinste):
    -RoundTimeout  : wie lange loop_driver auf B's Ergebnis wartet (--round-timeout).
    -CodexTimeout  : wie lange `codex exec` selbst laufen darf, bevor es gekillt
                     wird (Env DUAL_BRIDGE_CODEX_TIMEOUT, codex_adapter Default 600).
                     Eine zu grosse Aufgabe stirbt sonst mit 'codex timeout nach 600s'
                     OBWOHL der Clone laengst lief (beobachtet 2026-06-06, DCO-Seed).
                     Default = RoundTimeout, damit beide Schranken konsistent sind;
                     wird im Task-Kontext per `cmd /c set` gesetzt (ein setx in der
                     aufrufenden Shell erreicht den Scheduled-Task-Prozess NICHT).
      powershell -ExecutionPolicy Bypass -File register_jobpoll.ps1 -RoundTimeout 1800 -CodexTimeout 1800

  Deaktivieren:
      Unregister-ScheduledTask -TaskName "DualBridgeJobPoll" -Confirm:$false
#>
param(
    [string]$ScriptsDir = $PSScriptRoot,
    [int]$Interval = 15,
    [int]$IntervalMinutes = 10,
    [int]$MaxRounds = 4,
    [int]$RoundTimeout = 600,
    [int]$CodexTimeout = 0,
    [switch]$SkipEnvCheck
)

# Default CodexTimeout to RoundTimeout so the inner (codex exec) and outer
# (loop_driver wait) limits stay aligned unless the caller overrides it.
if ($CodexTimeout -le 0) { $CodexTimeout = $RoundTimeout }

$ErrorActionPreference = "Stop"
$python = (Get-Command python).Source
$jobpoll = Join-Path $ScriptsDir "job_poll.py"

if (-not (Test-Path $jobpoll)) {
    Write-Error "job_poll.py nicht gefunden in $ScriptsDir"
    exit 1
}

# --- Fail-closed Env-Check: ohne HTTP-Transport pollt der Builder die ---------
# --- Datei-Bridge statt den DCO. Wir registrieren dann lieber NICHTS. ---------
if (-not $SkipEnvCheck) {
    $missing = @()
    if (("$env:DUAL_BRIDGE_TRANSPORT").ToLower() -ne "http") {
        $missing += "DUAL_BRIDGE_TRANSPORT (muss 'http' sein, ist: '$env:DUAL_BRIDGE_TRANSPORT')"
    }
    if (-not $env:DCO_BRIDGE_URL) {
        $missing += "DCO_BRIDGE_URL (z.B. https://bot.dynamic-dome.com/api)"
    } elseif (-not $env:DCO_BRIDGE_URL.TrimEnd('/').EndsWith('/api')) {
        $missing += "DCO_BRIDGE_URL endet nicht auf /api (ist: '$env:DCO_BRIDGE_URL') -> 404"
    }
    if (-not $env:DCO_BRIDGE_TOKEN) {
        $missing += "DCO_BRIDGE_TOKEN (BRIDGE_API_TOKEN des DCO)"
    }
    if ($missing.Count -gt 0) {
        Write-Host ""
        Write-Host "FAIL-CLOSED: HTTP-Job-Pull-Konfiguration unvollstaendig. Kein Task registriert." -ForegroundColor Red
        Write-Host "Fehlt / falsch:"
        $missing | ForEach-Object { Write-Host "  - $_" }
        Write-Host ""
        Write-Host "Setze die Variablen persistent (setx) und oeffne danach eine NEUE Shell:"
        Write-Host '    setx DUAL_BRIDGE_TRANSPORT http'
        Write-Host '    setx DCO_BRIDGE_URL  "https://bot.dynamic-dome.com/api"'
        Write-Host '    setx DCO_BRIDGE_TOKEN "<token>"'
        Write-Host ""
        Write-Host "Oder, wenn die Vars erst im Task-Kontext gesetzt werden: -SkipEnvCheck"
        exit 2
    }
    Write-Host "Env-Check OK: DUAL_BRIDGE_TRANSPORT=http, DCO_BRIDGE_URL=$env:DCO_BRIDGE_URL, DCO_BRIDGE_TOKEN gesetzt."
}

# Set DUAL_BRIDGE_CODEX_TIMEOUT *inside the task process* via `cmd /c set && ...`.
# A setx in the registering shell does NOT reach an already-scheduled task; only
# an env-var the task sets itself (or a persistent setx + a fresh task) is seen by
# the codex_adapter subprocess. cmd /c keeps it self-contained (no wrapper file).
$pyArgs = "`"$jobpoll`" --watch --interval $Interval " +
          "--max-rounds $MaxRounds --round-timeout $RoundTimeout"
$argLine = "/c set DUAL_BRIDGE_CODEX_TIMEOUT=$CodexTimeout && `"$python`" $pyArgs"

$action = New-ScheduledTaskAction -Execute "cmd.exe" `
    -Argument $argLine -WorkingDirectory $ScriptsDir

$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes)

$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -StartWhenAvailable

Register-ScheduledTask -TaskName "DualBridgeJobPoll" `
    -Action $action -Trigger $trigger -Settings $settings `
    -Description "Builder-Knoten: pollt die DCO-Job-Queue per HTTP alle ${Interval}s und baut per codex (Re-Trigger alle $IntervalMinutes min, Singleton-Lock gegen Doppelstart)." `
    -Force

Write-Host "Builder registriert: DualBridgeJobPoll (Re-Trigger alle $IntervalMinutes min, Poll alle ${Interval}s, max-rounds $MaxRounds, round-timeout ${RoundTimeout}s, codex-timeout ${CodexTimeout}s)."
Write-Host ""
Write-Host "WICHTIG: Vorher testen mit:  python job_poll.py --once"
Write-Host "Deaktivieren: Unregister-ScheduledTask -TaskName 'DualBridgeJobPoll' -Confirm:`$false"
