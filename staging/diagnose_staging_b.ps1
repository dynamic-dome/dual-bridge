# =====================================================================
#  DIAGNOSE — Staging-DCO auf Laptop B
#  Prueft Schritt fuer Schritt und sagt im Klartext, was fehlt.
#  AUSFUEHREN AUF B (im Ordner, wo diese Datei + .env.staging liegen):
#    powershell -ExecutionPolicy Bypass -File diagnose_staging_b.ps1
#  Schickt KEINE Daten, startet NICHTS dauerhaft — nur Checks.
# =====================================================================

$ErrorActionPreference = 'Continue'
function Ok($m)   { Write-Host "[OK]   $m" -ForegroundColor Green }
function Bad($m)  { Write-Host "[FEHL] $m" -ForegroundColor Red }
function Info($m) { Write-Host "[INFO] $m" -ForegroundColor Cyan }

Write-Host "==================== STAGING-DIAGNOSE (Laptop B) ====================" -ForegroundColor Yellow
Info "Computer: $env:COMPUTERNAME"
Info "Dieser Ordner (PSScriptRoot): $PSScriptRoot"
Write-Host ""

# --- 1. Liegen die Skript-Dateien hier? -----------------------------
Write-Host "--- 1. Dateien im aktuellen Ordner ---"
foreach ($f in 'start_staging_dco.ps1','.env.staging','.env.staging.template') {
    $p = Join-Path $PSScriptRoot $f
    if (Test-Path $p) { Ok "$f vorhanden ($((Get-Item $p).Length) Bytes)" }
    else { Bad "$f FEHLT in diesem Ordner" }
}
Write-Host ""

# --- 2. .env.staging lesbar + vollstaendig? -------------------------
Write-Host "--- 2. .env.staging Inhalt (Secrets maskiert) ---"
$envFile = Join-Path $PSScriptRoot '.env.staging'
if (-not (Test-Path $envFile)) {
    Bad ".env.staging fehlt -> du musst .env.staging.template kopieren+ausfuellen."
} else {
    $required = 'DCO_DATA_DIR_OVERRIDE','DCO_AGENT_RUN_ROOT','TELEGRAM_TOKEN','TELEGRAM_CHAT_ID','WEBHOOK_SECRET','ADMIN_PIN'
    $found = @{}
    foreach ($line in Get-Content $envFile) {
        $t = $line.Trim()
        if ($t -eq '' -or $t.StartsWith('#')) { continue }
        $i = $t.IndexOf('='); if ($i -lt 1) { continue }
        $k = $t.Substring(0,$i).Trim(); $v = $t.Substring($i+1).Trim()
        $found[$k] = $v
    }
    foreach ($k in $required) {
        if (-not $found.ContainsKey($k) -or [string]::IsNullOrWhiteSpace($found[$k])) {
            Bad "$k fehlt oder ist leer"
        } elseif ($found[$k] -like '<*>') {
            Bad "$k ist noch ein Platzhalter: $($found[$k])"
        } else {
            $masked = if ($k -in 'TELEGRAM_TOKEN','WEBHOOK_SECRET','ADMIN_PIN') {
                '***' + $found[$k].Substring([Math]::Max(0,$found[$k].Length-4))
            } else { $found[$k] }
            Ok "$k = $masked"
        }
    }
    if ($found.ContainsKey('ADMIN_PIN') -and $found['ADMIN_PIN'].Length -lt 8) {
        Bad "ADMIN_PIN zu kurz ($($found['ADMIN_PIN'].Length) Zeichen, mind. 8)"
    }
    # Prod-Secret-Wiederverwendung warnen
    if ($found['WEBHOOK_SECRET'] -eq $found['ADMIN_PIN']) {
        Bad "WEBHOOK_SECRET == ADMIN_PIN -> config.py lehnt das ab. Verschiedene Werte!"
    }
}
Write-Host ""

# --- 3. DCO-Repo + venv da? -----------------------------------------
Write-Host "--- 3. DCO-Repo & venv ---"
$DcoRepo = 'C:\Users\domes\dynamic_central_orchestrator'
if (Test-Path $DcoRepo) { Ok "DCO-Repo: $DcoRepo" } else { Bad "DCO-Repo NICHT gefunden: $DcoRepo (Pfad auf B anders?)" }
$VenvPy = Join-Path $DcoRepo '.venv\Scripts\python.exe'
if (Test-Path $VenvPy) { Ok "venv-Python: $VenvPy" } else { Bad "venv FEHLT: $VenvPy -> venv anlegen / pip install" }
if (Test-Path (Join-Path $DcoRepo 'main.py')) { Ok "main.py vorhanden" } else { Bad "main.py fehlt im Repo" }
Write-Host ""

# --- 4. Ist uvicorn im venv installiert? ----------------------------
Write-Host "--- 4. uvicorn im venv ---"
if (Test-Path $VenvPy) {
    $u = & $VenvPy -c "import uvicorn, sys; print(uvicorn.__version__)" 2>&1
    if ($LASTEXITCODE -eq 0) { Ok "uvicorn $u" } else { Bad "uvicorn nicht importierbar: $u" }
} else { Info "uebersprungen (kein venv)" }
Write-Host ""

# --- 5. Port 8001 frei? Port 8000 (Prod) belegt? --------------------
Write-Host "--- 5. Ports ---"
$p8001 = Get-NetTCPConnection -LocalPort 8001 -State Listen -ErrorAction SilentlyContinue
if ($p8001) { Bad "Port 8001 schon belegt (PID $($p8001.OwningProcess -join ','))" } else { Ok "Port 8001 frei (Staging kann starten)" }
$p8000 = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
if ($p8000) { Info "Port 8000 belegt (vermutlich Prod-DCO laeuft) - gut" } else { Info "Port 8000 frei (Prod-DCO laeuft gerade nicht)" }
Write-Host ""

# --- 6. config.py Smoke: laedt es mit der Staging-env durch? ---------
Write-Host "--- 6. config.py Smoke-Test mit Staging-env (ohne Server zu starten) ---"
if ((Test-Path $VenvPy) -and (Test-Path $envFile) -and (Test-Path $DcoRepo)) {
    # env aus .env.staging als echte Prozess-Vars setzen (nur fuer diesen Test-Subprozess)
    foreach ($k in $found.Keys) { Set-Item -Path "Env:$k" -Value $found[$k] -ErrorAction SilentlyContinue }
    Push-Location $DcoRepo
    $out = & $VenvPy -c "import config; print('CONFIG_OK data=' + str(config.DATA_DIR))" 2>&1
    $code = $LASTEXITCODE
    Pop-Location
    if ($code -eq 0) { Ok "config.py laedt durch -> $out" }
    else { Bad "config.py crasht mit Staging-env:`n$out" }
} else { Info "uebersprungen (Voraussetzung fehlt)" }
Write-Host ""
Write-Host "==================== ENDE DIAGNOSE ====================" -ForegroundColor Yellow
Write-Host "Schick mir die ROTEN [FEHL]-Zeilen, dann weiss ich genau, was zu tun ist." -ForegroundColor Yellow
