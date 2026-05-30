# =====================================================================
#  Start DCO STAGING-Instanz auf Laptop B  (Idee 4 / Dual-Bridge)
#  ---------------------------------------------------------------
#  Startet eine zweite, voll isolierte DCO-Instanz NEBEN der Prod-
#  Instanz — an Tray-App + Single-Instance-Mutex vorbei:
#    - eigener Daten-Ordner   (DCO_DATA_DIR_OVERRIDE)
#    - eigener Bot-Token      (TELEGRAM_TOKEN)
#    - eigener Port 8001      (Prod = 8000, in tray.pyw hardcoded)
#
#  WARUM env-Vars statt nur .env.staging:
#    config.py ruft load_dotenv() OHNE Argument → es liest NUR die
#    Default-.env (= Prod-Secrets!). Daher setzen wir die Staging-
#    Werte als ECHTE Prozess-Umgebungsvariablen; python-dotenv
#    überschreibt vorhandene env-Vars per Default NICHT → Staging
#    gewinnt.
#
#  AUSFÜHREN AUF B:
#    1. .env.staging.template -> .env.staging kopieren + ausfüllen
#    2. Pfade unten ($DcoRepo, $EnvFile) prüfen
#    3.  powershell -ExecutionPolicy Bypass -File start_staging_dco.ps1
# =====================================================================

$ErrorActionPreference = 'Stop'

# --- Pfade auf B anpassen falls nötig --------------------------------
$DcoRepo = 'C:\Users\domes\dynamic_central_orchestrator'
$EnvFile = Join-Path $PSScriptRoot '.env.staging'
$Port    = 8001
$VenvPy  = Join-Path $DcoRepo '.venv\Scripts\python.exe'

# --- Vorbedingungen --------------------------------------------------
if (-not (Test-Path $EnvFile)) {
    throw "STOP: $EnvFile fehlt. Erst .env.staging.template kopieren + ausfuellen."
}
if (-not (Test-Path $VenvPy)) {
    throw "STOP: venv-Python nicht gefunden: $VenvPy"
}

# --- Port-Kollision pruefen (Prod laeuft auf 8000, Staging will 8001) -
$portBusy = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($portBusy) {
    throw "STOP: Port $Port ist bereits belegt. Andere Staging-Instanz laeuft? PID(s): $($portBusy.OwningProcess -join ', ')"
}

# --- .env.staging in echte Prozess-env-Vars laden -------------------
# Kommentare (#) und Leerzeilen ueberspringen; KEY=VALUE splitten.
Write-Host "Lade Staging-env aus $EnvFile ..." -ForegroundColor Cyan
$loaded = 0
foreach ($line in Get-Content $EnvFile) {
    $t = $line.Trim()
    if ($t -eq '' -or $t.StartsWith('#')) { continue }
    $idx = $t.IndexOf('=')
    if ($idx -lt 1) { continue }
    $key = $t.Substring(0, $idx).Trim()
    $val = $t.Substring($idx + 1).Trim()
    if ($val -like '<*>') {
        throw "STOP: $key ist noch ein Platzhalter ($val). .env.staging vollstaendig ausfuellen."
    }
    Set-Item -Path "Env:$key" -Value $val
    $loaded++
}
Write-Host "  $loaded Variablen gesetzt." -ForegroundColor Green

# --- Fail-fast: Pflicht-Keys vorhanden? (sonst kryptischer Crash) ----
# Verifier-Befund #5: fehlende Keys lösen sonst unverständliche Fehler aus.
$required = 'DCO_DATA_DIR_OVERRIDE','DCO_AGENT_RUN_ROOT','TELEGRAM_TOKEN','WEBHOOK_SECRET','ADMIN_PIN'
$missing = $required | Where-Object { [string]::IsNullOrWhiteSpace((Get-Item "Env:$_" -ErrorAction SilentlyContinue).Value) }
if ($missing) {
    throw "STOP: Pflicht-Keys fehlen oder leer in .env.staging: $($missing -join ', ')"
}
if ($env:ADMIN_PIN.Length -lt 8) {
    throw "STOP: ADMIN_PIN zu kurz ($($env:ADMIN_PIN.Length) < 8). config.py lehnt den Start sonst ab."
}

# --- Sanity: Staging zeigt NICHT auf Prod-Daten ---------------------
# Verifier-Befund #4b: auch absolute Prod-Pfade abfangen, nicht nur ./data.
$prodData = (Join-Path $DcoRepo 'data')
function Test-PointsAtProd($val) {
    if ([string]::IsNullOrWhiteSpace($val)) { return $true }
    if ($val -in @('./data','data','.\data')) { return $true }
    try {
        $resolved = [System.IO.Path]::GetFullPath((Join-Path $DcoRepo $val))
        if ($resolved.TrimEnd('\') -ieq $prodData.TrimEnd('\')) { return $true }
    } catch { }
    return $false
}
if (Test-PointsAtProd $env:DCO_DATA_DIR_OVERRIDE) {
    throw "STOP: DCO_DATA_DIR_OVERRIDE ('$($env:DCO_DATA_DIR_OVERRIDE)') zeigt auf Prod-data. Isolation verletzt."
}
$prodRuns = (Join-Path $prodData 'agent_runs')
try { $resolvedRuns = [System.IO.Path]::GetFullPath((Join-Path $DcoRepo $env:DCO_AGENT_RUN_ROOT)) } catch { $resolvedRuns = '' }
if ($resolvedRuns.TrimEnd('\') -ieq $prodRuns.TrimEnd('\')) {
    throw "STOP: DCO_AGENT_RUN_ROOT zeigt auf Prod-data/agent_runs. Isolation verletzt."
}
Write-Host "  Daten-Ordner (isoliert): $env:DCO_DATA_DIR_OVERRIDE" -ForegroundColor Green
Write-Host "  Agent-Runs (isoliert):   $env:DCO_AGENT_RUN_ROOT" -ForegroundColor Green
Write-Host "  Telegram-Token endet auf: ...$($env:TELEGRAM_TOKEN.Substring([Math]::Max(0,$env:TELEGRAM_TOKEN.Length-6)))" -ForegroundColor Green

# --- Start: direkter uvicorn auf Port 8001 (an Tray/Mutex vorbei) ---
Write-Host "Starte STAGING-DCO auf 127.0.0.1:$Port ..." -ForegroundColor Cyan
Push-Location $DcoRepo
try {
    & $VenvPy -m uvicorn main:app --host 127.0.0.1 --port $Port
}
finally {
    Pop-Location
}
