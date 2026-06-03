# =====================================================================
#  Steuer-Skript fuer Laptop B: Staging-DCO (8001) + Tunnel dynamic-claude-b
#  Aufgerufen von tunnel-b-on/off/status.bat.
#
#  Hintergrund: A und B teilten sich frueher EINEN Tunnel
#  (dynamic-claude / bot.dynamic-dome.com) -> Load-Balancing-Kollision.
#  B hat jetzt einen EIGENEN Tunnel (dynamic-claude-b ->
#  bot-staging.dynamic-dome.com -> localhost:8001). A bleibt unberuehrt.
# =====================================================================
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('on', 'off', 'status')]
    [string]$Action
)

$ErrorActionPreference = 'Stop'

# --- Konfiguration ---------------------------------------------------
$Cloudflared  = "C:\Program Files\cloudflared\cloudflared.exe"
$TunnelName   = "dynamic-claude-b"
$ConfigB      = "C:\Users\domes\.cloudflared\config-b.yml"
$StagingStart = "C:\Users\domes\AI\dual-bridge\staging\start_staging_dco.ps1"
$Port         = 8001
$Hostname     = "bot-staging.dynamic-dome.com"
$TunnelLog    = "C:\Users\domes\AppData\Local\Temp\tunnel_b.log"
$DcoLog       = "C:\Users\domes\AppData\Local\Temp\staging_dco.log"

function Get-PortPid($p) {
    $c = Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue
    if ($c) { return ($c.OwningProcess | Select-Object -First 1) }
    return $null
}

function Invoke-Cloudflared {
    # Ruft cloudflared auf und faengt stderr (Versions-Warnung etc.) ab,
    # damit $ErrorActionPreference='Stop' nicht ueber harmlose WRN-Zeilen stolpert.
    param([string[]]$CfArgs)
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & $Cloudflared @CfArgs 2>$null
    } finally {
        $ErrorActionPreference = $prev
    }
}

function Get-TunnelBProcs {
    # cloudflared-Prozesse, die config-b.yml fahren (anhand CommandLine).
    Get-CimInstance Win32_Process -Filter "Name='cloudflared.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -and $_.CommandLine -match 'config-b\.yml' }
}

# =====================================================================
function Action-On {
    Write-Host "=== Tunnel-B + Staging-DCO STARTEN ===" -ForegroundColor Cyan

    # 1) Staging-DCO auf 8001
    $dcoPid = Get-PortPid $Port
    if ($dcoPid) {
        Write-Host ("  Staging-DCO laeuft bereits auf {0} (PID {1})" -f $Port, $dcoPid) -ForegroundColor Green
    } else {
        Write-Host "  Starte Staging-DCO ..." -ForegroundColor Cyan
        Remove-Item $DcoLog -ErrorAction SilentlyContinue
        Remove-Item "$DcoLog.err" -ErrorAction SilentlyContinue
        Start-Process powershell.exe `
            -ArgumentList "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$StagingStart`"" `
            -RedirectStandardOutput $DcoLog -RedirectStandardError "$DcoLog.err" `
            -WindowStyle Hidden | Out-Null
        # Auf Port warten (max ~25s)
        for ($i = 0; $i -lt 25; $i++) {
            Start-Sleep -Seconds 1
            if (Get-PortPid $Port) { break }
        }
        $dcoPid = Get-PortPid $Port
        if ($dcoPid) {
            Write-Host ("  Staging-DCO laeuft (PID {0})" -f $dcoPid) -ForegroundColor Green
        } else {
            Write-Host "  FEHLER: Staging-DCO nicht hochgekommen. Log:" -ForegroundColor Red
            if (Test-Path "$DcoLog.err") { Get-Content "$DcoLog.err" -Tail 12 }
            return
        }
    }

    # 2) Tunnel-B
    if (Get-TunnelBProcs) {
        Write-Host "  Tunnel-B laeuft bereits." -ForegroundColor Green
    } else {
        Write-Host "  Starte Tunnel-B ..." -ForegroundColor Cyan
        Remove-Item "$TunnelLog.err" -ErrorAction SilentlyContinue
        # Globale Flags (--config) MUESSEN vor 'tunnel run' stehen.
        Start-Process $Cloudflared `
            -ArgumentList "--config", "`"$ConfigB`"", "tunnel", "run", $TunnelName `
            -RedirectStandardOutput $TunnelLog -RedirectStandardError "$TunnelLog.err" `
            -WindowStyle Hidden | Out-Null
        Start-Sleep -Seconds 8
        if (Get-TunnelBProcs) {
            Write-Host "  Tunnel-B verbunden." -ForegroundColor Green
        } else {
            Write-Host "  FEHLER: Tunnel-B nicht gestartet. Log:" -ForegroundColor Red
            if (Test-Path "$TunnelLog.err") { Get-Content "$TunnelLog.err" -Tail 12 }
            return
        }
    }

    # 3) Extern-Check
    Start-Sleep -Seconds 2
    try {
        $r = Invoke-WebRequest -Uri ("https://{0}/health" -f $Hostname) -UseBasicParsing -TimeoutSec 15
        Write-Host ("  Extern OK: https://{0}/health -> HTTP {1}" -f $Hostname, $r.StatusCode) -ForegroundColor Green
    } catch {
        Write-Host ("  Extern noch nicht erreichbar (DNS/Propagation?): {0}" -f $_.Exception.Message) -ForegroundColor Yellow
    }
    Write-Host ""
    Write-Host ("FERTIG. Bot erreichbar unter https://{0}" -f $Hostname) -ForegroundColor Green
}

# =====================================================================
function Action-Off {
    Write-Host "=== Tunnel-B + Staging-DCO STOPPEN ===" -ForegroundColor Cyan

    # 1) Tunnel-B
    $tp = Get-TunnelBProcs
    if ($tp) {
        foreach ($proc in $tp) {
            Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue
            Write-Host ("  Tunnel-B gestoppt (PID {0})" -f $proc.ProcessId) -ForegroundColor Green
        }
    } else {
        Write-Host "  Tunnel-B lief nicht." -ForegroundColor Gray
    }

    # 2) Staging-DCO (Prozess auf Port 8001)
    $dcoPid = Get-PortPid $Port
    if ($dcoPid) {
        # uvicorn + ggf. Kind-Prozesse: erst den Listener, dann Aufraeumen
        Stop-Process -Id $dcoPid -Force -ErrorAction SilentlyContinue
        Write-Host ("  Staging-DCO gestoppt (PID {0})" -f $dcoPid) -ForegroundColor Green
    } else {
        Write-Host "  Staging-DCO lief nicht (Port 8001 frei)." -ForegroundColor Gray
    }
    Write-Host ""
    Write-Host "FERTIG. bot-staging.dynamic-dome.com ist offline." -ForegroundColor Green
}

# =====================================================================
function Action-Status {
    Write-Host "=== STATUS Laptop B ===" -ForegroundColor Cyan

    $dcoPid = Get-PortPid $Port
    if ($dcoPid) {
        Write-Host ("  Staging-DCO:  LAEUFT  (Port {0}, PID {1})" -f $Port, $dcoPid) -ForegroundColor Green
    } else {
        Write-Host ("  Staging-DCO:  aus     (Port {0} frei)" -f $Port) -ForegroundColor Yellow
    }

    $tp = @(Get-TunnelBProcs)
    if ($tp.Count -gt 0) {
        Write-Host ("  Tunnel-B:     LAEUFT  (PID {0})" -f ($tp.ProcessId -join ',')) -ForegroundColor Green
    } else {
        Write-Host "  Tunnel-B:     aus" -ForegroundColor Yellow
    }

    Write-Host ""
    Write-Host "  --- Cloudflare-Tunnel (beide) ---" -ForegroundColor Cyan
    Invoke-Cloudflared @('tunnel', 'list') | Select-String -Pattern "dynamic-claude" | ForEach-Object { Write-Host ("  " + $_.Line.Trim()) }

    Write-Host ""
    Write-Host "  --- Extern erreichbar? ---" -ForegroundColor Cyan
    try {
        $r = Invoke-WebRequest -Uri ("https://{0}/health" -f $Hostname) -UseBasicParsing -TimeoutSec 12
        Write-Host ("  https://{0}/health -> HTTP {1} {2}" -f $Hostname, $r.StatusCode, $r.Content) -ForegroundColor Green
    } catch {
        Write-Host ("  https://{0}/health -> nicht erreichbar" -f $Hostname) -ForegroundColor Yellow
    }
}

switch ($Action) {
    'on'     { Action-On }
    'off'    { Action-Off }
    'status' { Action-Status }
}
