param(
    [string]$GrafanaHome = 'C:\Program Files\GrafanaLabs\grafana\grafana-12.1.1',
    [switch]$AltPort,
    [switch]$Foreground,
    [switch]$Detach,
    [int]$StartupWaitSeconds = 15
)

$ErrorActionPreference = 'Stop'

Write-Host 'Starting Grafana with .env path variables...' -ForegroundColor Cyan

# Load .env (simple KEY=VALUE lines, skip comments)
$envFile = Join-Path (Get-Location) '.env'
if (-not (Test-Path $envFile)) {
    Write-Host "No .env found at $envFile" -ForegroundColor Yellow
} else {
    Get-Content $envFile | ForEach-Object {
        if ($_ -match '^[#\s]') { return }
        if ($_ -match '^(?<k>[A-Za-z0-9_]+)=(?<v>.*)$') {
            $k = $Matches.k; $v = $Matches.v
            # Only set Grafana related GF_ variables (avoid leaking secrets to child unnecessarily)
            if ($k -like 'GF_*') { $env:$k = $v }
        }
    }
}

if ($AltPort) { $env:GF_SERVER_HTTP_PORT = '3001' }

# Ensure data directories exist
foreach ($p in @($env:GF_PATHS_DATA, $env:GF_PATHS_LOGS, $env:GF_PATHS_PLUGINS)) {
    if ($p -and -not (Test-Path $p)) { New-Item -ItemType Directory -Path $p -Force | Out-Null }
}

$bin = Join-Path $GrafanaHome 'bin'
$exe = Join-Path $bin 'grafana-server.exe'
if (-not (Test-Path $exe)) { throw "grafana-server.exe not found at $exe" }

Write-Host "Using data path: $env:GF_PATHS_DATA" -ForegroundColor Green
if ($env:GF_SERVER_HTTP_PORT) { Write-Host "Port override: $env:GF_SERVER_HTTP_PORT" -ForegroundColor Green }
Write-Host "Provisioning path: $env:GF_PATHS_PROVISIONING" -ForegroundColor Green

if ($Foreground -and $Detach) {
    throw 'Specify only one of -Foreground or -Detach.'
}

$port = if ($env:GF_SERVER_HTTP_PORT) { $env:GF_SERVER_HTTP_PORT } else { '3000' }

if ($Foreground) {
    Write-Host 'Starting Grafana in foreground mode (Ctrl+C to stop)...' -ForegroundColor Yellow
    & $exe
    return
}

if ($Detach) {
    Write-Host 'Starting Grafana detached...' -ForegroundColor Yellow
    Start-Process -FilePath $exe -WorkingDirectory $bin | Out-Null
} else {
    Write-Host 'Starting Grafana (default detached mode)...' -ForegroundColor Yellow
    Start-Process -FilePath $exe -WorkingDirectory $bin | Out-Null
}

Write-Host "Waiting up to $StartupWaitSeconds s for Grafana to listen on port $port..." -ForegroundColor Cyan
for ($i=0; $i -lt $StartupWaitSeconds; $i++) {
    try {
        $tcp = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue
        if ($tcp) { break }
    } catch { }
    Start-Sleep -Seconds 1
}
if (-not (Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue)) {
    Write-Host 'Warning: Grafana not detected listening yet. Check logs.' -ForegroundColor Red
} else {
    Write-Host "Grafana appears up at http://localhost:$port" -ForegroundColor Green
}
