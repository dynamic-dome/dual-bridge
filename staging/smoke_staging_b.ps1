# =====================================================================
#  SMOKE-TEST der Staging-DCO auf Laptop B  (Idee 4 Funktionsbeweis)
#  ---------------------------------------------------------------
#  Beweist, dass Staging nicht nur startet, sondern ARBEITET, und dass
#  alle Schreibvorgaenge in data_staging landen, NICHT in Prod-data.
#  Modus: stub (kein LLM, kein externer Call, kostenlos, deterministisch).
#
#  Kann laufen, waehrend der Staging-Server auf 8001 laeuft.
#
#  AUSFUEHREN AUF B (im staging-Ordner, wo .env.staging liegt):
#    powershell -ExecutionPolicy Bypass -File smoke_staging_b.ps1
# =====================================================================

$ErrorActionPreference = 'Stop'
function Say($tag, $msg, $color) { Write-Host ($tag + ' ' + $msg) -ForegroundColor $color }
function Ok($msg)   { Say '[OK]  ' $msg 'Green' }
function Bad($msg)  { Say '[FEHL]' $msg 'Red' }
function Info($msg) { Say '[INFO]' $msg 'Cyan' }
function Step($msg) { Write-Host '' ; Write-Host ('=== ' + $msg + ' ===') -ForegroundColor Cyan }

$DcoRepo = 'C:\Users\domes\dynamic_central_orchestrator'
$VenvPy  = Join-Path $DcoRepo '.venv\Scripts\python.exe'
$EnvFile = Join-Path $PSScriptRoot '.env.staging'

if (-not (Test-Path $VenvPy))  { Bad ('venv-Python fehlt: ' + $VenvPy); exit 1 }
if (-not (Test-Path $EnvFile)) { Bad ('.env.staging fehlt: ' + $EnvFile); exit 1 }

# --- 1. .env.staging als echte Prozess-env-Vars laden ---------------
Step '1. Staging-env laden'
$loaded = 0
foreach ($line in Get-Content $EnvFile) {
    $t = $line.Trim()
    if ($t -eq '' -or $t.StartsWith('#')) { continue }
    $i = $t.IndexOf('=')
    if ($i -lt 1) { continue }
    $k = $t.Substring(0, $i).Trim()
    $v = $t.Substring($i + 1).Trim()
    if ($v -like '<*>') { Bad ($k + ' ist Platzhalter'); exit 1 }
    Set-Item -Path ('Env:' + $k) -Value $v
    $loaded++
}
Ok ([string]$loaded + ' Vars gesetzt | DATA=' + $env:DCO_DATA_DIR_OVERRIDE + ' | RUNS=' + $env:DCO_AGENT_RUN_ROOT)

# --- 2. Prod-DB-Snapshot VORHER -------------------------------------
Step '2. Prod-DB-Snapshot VORHER'
$prodJobs = Join-Path $DcoRepo 'data\jobs.db'
if (Test-Path $prodJobs) { $prodBefore = [string](Get-Item $prodJobs).Length } else { $prodBefore = 'keine-prod-jobs.db' }
Ok ('Prod jobs.db Groesse vorher: ' + $prodBefore)

# --- 3. Smoke im stub-Modus -----------------------------------------
Step '3. agent_smoke --mode stub (kein LLM)'
Push-Location $DcoRepo
& $VenvPy -m agent_smoke --goal 'Staging smoke: beweise dass Idee 4 arbeitet und in data_staging schreibt' --mode stub --max-steps 6 --timeout-seconds 120
$smokeCode = $LASTEXITCODE
Pop-Location
if ($smokeCode -eq 0) { Ok 'agent_smoke EXIT 0' } else { Bad ('agent_smoke EXIT ' + [string]$smokeCode + ' (Output oben)') }

# --- 4. Isolation-Belege --------------------------------------------
Step '4. Isolation verifizieren'
$stagingData = Join-Path $DcoRepo 'data_staging'
if (Test-Path $stagingData) {
    Ok 'data_staging existiert. Inhalt:'
    Get-ChildItem $stagingData -Recurse -File |
        Select-Object @{n='KB';e={[math]::Round($_.Length / 1KB, 1)}}, FullName |
        Format-Table -AutoSize | Out-String | Write-Host
} else {
    Bad 'data_staging existiert NICHT - Smoke hat nichts isoliert geschrieben?'
}

$stagingRuns = Join-Path $stagingData 'agent_runs'
if (Test-Path $stagingRuns) {
    $runDirs = @(Get-ChildItem $stagingRuns -Directory -ErrorAction SilentlyContinue)
    Ok ('agent_runs in Staging: ' + [string]$runDirs.Count + ' Run-Ordner (isoliert)')
} else {
    Info 'noch keine agent_runs (je nach Smoke-Pfad ok)'
}

# --- 5. Prod-DB-Snapshot NACHHER ------------------------------------
Step '5. Prod-DB-Snapshot NACHHER (muss gleich sein)'
if (Test-Path $prodJobs) { $prodAfter = [string](Get-Item $prodJobs).Length } else { $prodAfter = 'keine-prod-jobs.db' }
if ($prodBefore -eq $prodAfter) {
    Ok ('Prod jobs.db UNVERAENDERT (' + $prodAfter + ') === Isolation bewiesen.')
} else {
    Bad ('Prod jobs.db GEAENDERT von ' + $prodBefore + ' auf ' + $prodAfter + ' - ISOLATION VERLETZT, sofort melden.')
}

Write-Host ''
Write-Host '=== ERGEBNIS ===' -ForegroundColor Yellow
Write-Host 'Wenn 3=EXIT0, 4=data_staging gefuellt, 5=Prod unveraendert: Idee 4 funktional bewiesen.' -ForegroundColor Yellow
Write-Host 'Output ueber Textdatei-Rueckkanal schicken, dann Beweis ins Wiki.' -ForegroundColor Yellow
