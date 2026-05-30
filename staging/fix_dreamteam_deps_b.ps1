# =====================================================================
#  FIX: dream-team-Dependencies ins DCO-venv nachinstallieren (Laptop B)
#  Grund: main.py -> mcp_servers/duett importiert dream_team, das
#  python-frontmatter + fastmcp braucht (nicht in DCO-requirements.txt).
#  Vorgesehener Weg laut dream-team/pyproject.toml: editable install.
#  AUSFUEHREN AUF B:
#    powershell -ExecutionPolicy Bypass -File fix_dreamteam_deps_b.ps1
# =====================================================================

$ErrorActionPreference = 'Stop'
function Ok($m)  { Write-Host "[OK]   $m" -ForegroundColor Green }
function Bad($m) { Write-Host "[FEHL] $m" -ForegroundColor Red }
function Step($m){ Write-Host "`n=== $m ===" -ForegroundColor Cyan }

$DcoRepo   = 'C:\Users\domes\dynamic_central_orchestrator'
$VenvPy    = Join-Path $DcoRepo '.venv\Scripts\python.exe'
$DreamTeam = 'C:\Users\domes\Desktop\Claude-Projekte\dream-team'

if (-not (Test-Path $VenvPy))    { Bad "venv-Python fehlt: $VenvPy"; exit 1 }
if (-not (Test-Path $DreamTeam)) { Bad "dream-team fehlt: $DreamTeam"; exit 1 }

# --- editable install von dream-team (zieht alle dream-team-Deps) ----
Step "dream-team editable install (zieht python-frontmatter, fastmcp, ...)"
& $VenvPy -m pip install -e $DreamTeam
if ($LASTEXITCODE -ne 0) {
    Bad "editable install fehlgeschlagen. Fallback: Einzelpakete direkt:"
    Bad "  $VenvPy -m pip install python-frontmatter fastmcp"
    exit 1
}
Ok "dream-team + Deps installiert"

# --- Import-Smoke: kommt main.py jetzt durch? -----------------------
Step "Import-Smoke (main importierbar?) — ohne Server zu starten"
Push-Location $DcoRepo
$env:DCO_DATA_DIR_OVERRIDE = './data_smoke_tmp'
$env:WEBHOOK_SECRET = 'smoke_dummy_secret_123'
$env:ADMIN_PIN = 'smoke_pin_1234'
$out = & $VenvPy -c "import importlib; importlib.import_module('main'); print('main OK')" 2>&1
$code = $LASTEXITCODE
Remove-Item Env:DCO_DATA_DIR_OVERRIDE, Env:WEBHOOK_SECRET, Env:ADMIN_PIN -ErrorAction SilentlyContinue
Pop-Location
if ($code -eq 0) {
    Ok "main.py importiert vollstaendig -> $out"
    Write-Host "`nJETZT: start_staging_dco.ps1 nochmal laufen lassen." -ForegroundColor Yellow
} else {
    Bad "main.py-Import crasht noch:`n$out"
    Write-Host "`n-> Schick mir die letzte 'ModuleNotFoundError'-Zeile, dann das naechste Paket." -ForegroundColor Yellow
}
