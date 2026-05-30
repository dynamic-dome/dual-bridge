# =====================================================================
#  SETUP venv + Dependencies fuer DCO auf Laptop B
#  AUSFUEHREN AUF B:
#    powershell -ExecutionPolicy Bypass -File setup_venv_b.ps1
#  Legt .venv im DCO-Repo an, installiert requirements.txt voll,
#  prueft die externe dream-team-Pfad-Dependency. Idempotent.
# =====================================================================

$ErrorActionPreference = 'Stop'
function Ok($m)   { Write-Host "[OK]   $m" -ForegroundColor Green }
function Bad($m)  { Write-Host "[FEHL] $m" -ForegroundColor Red }
function Step($m) { Write-Host "`n=== $m ===" -ForegroundColor Cyan }

$DcoRepo = 'C:\Users\domes\dynamic_central_orchestrator'
if (-not (Test-Path $DcoRepo)) { Bad "DCO-Repo fehlt: $DcoRepo"; exit 1 }

# --- 1. Python finden -----------------------------------------------
Step "1. Python suchen"
$pyExe = $null
foreach ($cand in 'python','py') {
    try {
        $v = & $cand --version 2>&1
        if ($LASTEXITCODE -eq 0) { $pyExe = $cand; Ok "$cand -> $v"; break }
    } catch { }
}
if (-not $pyExe) {
    Bad "Kein Python gefunden (weder 'python' noch 'py')."
    Bad "-> Python 3.11+ installieren: https://www.python.org/downloads/  (Haken 'Add to PATH'!)"
    exit 1
}

# --- 2. venv anlegen -------------------------------------------------
Step "2. venv anlegen"
$venvDir = Join-Path $DcoRepo '.venv'
$venvPy  = Join-Path $venvDir 'Scripts\python.exe'
if (Test-Path $venvPy) {
    Ok "venv existiert bereits: $venvDir (ueberspringe Anlegen)"
} else {
    Push-Location $DcoRepo
    if ($pyExe -eq 'py') { & py -m venv .venv } else { & python -m venv .venv }
    Pop-Location
    if (Test-Path $venvPy) { Ok "venv angelegt: $venvDir" } else { Bad "venv-Anlegen fehlgeschlagen"; exit 1 }
}

# --- 3. pip upgrade --------------------------------------------------
Step "3. pip aktualisieren"
& $venvPy -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { Bad "pip-Upgrade fehlgeschlagen"; exit 1 }
Ok "pip aktuell"

# --- 4. requirements installieren (voll) ----------------------------
Step "4. requirements.txt installieren (kann mehrere Minuten dauern)"
$req = Join-Path $DcoRepo 'requirements.txt'
if (-not (Test-Path $req)) { Bad "requirements.txt fehlt"; exit 1 }
& $venvPy -m pip install -r $req
if ($LASTEXITCODE -ne 0) {
    Bad "pip install -r requirements.txt FEHLGESCHLAGEN."
    Bad "-> Schick mir die letzten roten Zeilen (oft: faster-whisper/piper-tts brauchen Build-Tools)."
    exit 1
}
Ok "Alle Dependencies installiert"

# --- 5. dream-team Pfad-Dependency pruefen --------------------------
Step "5. externe dream-team-Dependency (NICHT pip, via sys.path)"
$dreamTeam = 'C:\Users\domes\Desktop\Claude-Projekte\dream-team'
if (Test-Path $dreamTeam) {
    Ok "dream-team vorhanden: $dreamTeam"
} else {
    Bad "dream-team FEHLT auf B: $dreamTeam"
    Bad "-> config.py/main.py importiert das evtl. via _dream_team_path.py. Wenn der Smoke unten an einem"
    Bad "   dream-team-Import crasht, muss dieses Verzeichnis von A nach B kopiert/geklont werden."
}

# --- 6. Smoke: config.py + main importierbar? -----------------------
Step "6. Import-Smoke (ohne Server zu starten)"
Push-Location $DcoRepo
$envBak = $env:DCO_DATA_DIR_OVERRIDE
$env:DCO_DATA_DIR_OVERRIDE = './data_smoke_tmp'
$env:WEBHOOK_SECRET = 'smoke_dummy_secret_123'
$env:ADMIN_PIN = 'smoke_pin_123'
$out = & $venvPy -c "import config; print('config OK, DATA_DIR=' + str(config.DATA_DIR))" 2>&1
$code = $LASTEXITCODE
if ($envBak) { $env:DCO_DATA_DIR_OVERRIDE = $envBak } else { Remove-Item Env:DCO_DATA_DIR_OVERRIDE -ErrorAction SilentlyContinue }
Pop-Location
if ($code -eq 0) { Ok "config.py importiert -> $out" }
else { Bad "config.py-Import crasht:`n$out" }

Write-Host "`n=== FERTIG ===" -ForegroundColor Yellow
Write-Host "Wenn alles gruen: jetzt 'diagnose_staging_b.ps1' nochmal laufen lassen," -ForegroundColor Yellow
Write-Host "dann 'start_staging_dco.ps1'. Bei roten Zeilen: schick sie mir." -ForegroundColor Yellow
