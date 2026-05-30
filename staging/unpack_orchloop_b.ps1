# =====================================================================
#  Entpackt orchestrated-loop-src.zip an die von agent_run erwartete
#  Stelle auf Laptop B und verifiziert src/ + Smoke-Vorbedingung.
#  AUSFUEHREN AUF B:
#    powershell -ExecutionPolicy Bypass -File unpack_orchloop_b.ps1
# =====================================================================
$ErrorActionPreference = 'Stop'
function Ok($m)  { Write-Host ('[OK]   ' + $m) -ForegroundColor Green }
function Bad($m) { Write-Host ('[FEHL] ' + $m) -ForegroundColor Red }

$zip    = 'G:\Meine Ablage\dynamic-AI\dynamic_sharepoint\00_INBOX\dual-bridge\_scripts-pickup\orchestrated-loop-src.zip'
$target = 'C:\Users\domes\AI\Agents\demos\orchestrated-loop'

if (-not (Test-Path $zip)) { Bad ('ZIP fehlt (Drive-Sync abwarten): ' + $zip); exit 1 }

# Zielordner anlegen (Parent-Kette)
New-Item -ItemType Directory -Path $target -Force | Out-Null

# Wenn schon Inhalt da ist: warnen, nicht blind ueberschreiben
$existing = Get-ChildItem -Path $target -Force -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host ('[INFO] Zielordner nicht leer (' + $existing.Count + ' Eintraege) - Dateien werden ueberschrieben/ergaenzt.') -ForegroundColor Cyan
}

Expand-Archive -Path $zip -DestinationPath $target -Force
Ok ('entpackt nach ' + $target)

# Verifikation: src/ + Kernmodul vorhanden?
$srcDir = Join-Path $target 'src'
$mainMod = Join-Path $target 'src\orchestrated_loop\__main__.py'
if (Test-Path $srcDir)  { Ok 'src/ vorhanden (agent_run-Vorbedingung erfuellt)' } else { Bad 'src/ FEHLT nach Entpacken' }
if (Test-Path $mainMod) { Ok 'src/orchestrated_loop/__main__.py vorhanden' } else { Bad '__main__.py fehlt' }

Write-Host ''
Write-Host '=== NAECHSTER SCHRITT ===' -ForegroundColor Yellow
Write-Host 'Jetzt smoke_staging_b.ps1 erneut laufen lassen - agent_smoke sollte durchlaufen.' -ForegroundColor Yellow
