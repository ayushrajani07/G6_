param(
  [string]$GrafanaHome = 'C:\Program Files\GrafanaLabs\grafana\grafana-12.1.1',
  [switch]$Foreground,
  [switch]$AltPort
)

# Load .env from repo root (one level up from this scripts folder)
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$envFile = Join-Path (Split-Path $scriptRoot -Parent) ".env"
if (Test-Path $envFile) {
  Get-Content $envFile | ForEach-Object {
    if ($_ -match '^\s*#' -or $_ -match '^\s*$') { return }
    $name, $value = $_ -split '=', 2
    if ($name -and $value -ne $null) {
      [Environment]::SetEnvironmentVariable($name.Trim(), $value.Trim())
    }
  }
  Write-Host "Starting Grafana with .env path variables..." -ForegroundColor Cyan
} else {
  Write-Host "No .env found at $envFile" -ForegroundColor Yellow
}

# Compute paths
$grafanaExe = Join-Path (Join-Path $GrafanaHome 'bin') 'grafana-server.exe'
if (-not (Test-Path $grafanaExe)) {
  Write-Host "grafana-server.exe not found under $GrafanaHome" -ForegroundColor Red
  exit 1
}

# Honor AltPort via env
if ($AltPort) { [Environment]::SetEnvironmentVariable("GF_SERVER_HTTP_PORT","3001") }
if (-not $env:GF_SERVER_HTTP_PORT) { [Environment]::SetEnvironmentVariable("GF_SERVER_HTTP_PORT","3000") ; Write-Host "Port override: 3000" -ForegroundColor Gray }

# Ensure GF_PATHS_* present (fallback to GrafanaHome if not in .env)
# G6_ENHANCED_UI_MARKER: NEW fallback assignments (compatible with Windows PowerShell 5.1)
if (-not $env:GF_PATHS_HOME -or [string]::IsNullOrWhiteSpace($env:GF_PATHS_HOME)) {
  $env:GF_PATHS_HOME = $GrafanaHome
} [void]$null
if (-not $env:GF_PATHS_DATA -or [string]::IsNullOrWhiteSpace($env:GF_PATHS_DATA)) {
  $env:GF_PATHS_DATA = 'C:\GrafanaData\data'
} [void]$null
if (-not $env:GF_PATHS_LOGS -or [string]::IsNullOrWhiteSpace($env:GF_PATHS_LOGS)) {
  $env:GF_PATHS_LOGS = 'C:\GrafanaData\log'
} [void]$null
if (-not $env:GF_PATHS_PLUGINS -or [string]::IsNullOrWhiteSpace($env:GF_PATHS_PLUGINS)) {
  $env:GF_PATHS_PLUGINS = 'C:\GrafanaData\plugins'
} [void]$null
if (-not $env:GF_PATHS_PROVISIONING -or [string]::IsNullOrWhiteSpace($env:GF_PATHS_PROVISIONING)) {
  $env:GF_PATHS_PROVISIONING = Join-Path (Split-Path $scriptRoot -Parent) 'grafana\provisioning'
} [void]$null
Write-Host "Using data path: $($env:GF_PATHS_DATA)" -ForegroundColor Gray
Write-Host "Provisioning path: $($env:GF_PATHS_PROVISIONING)" -ForegroundColor Gray

# Foreground mode: run in HOME as working dir
if ($Foreground) {
  Write-Host "Starting Grafana in foreground mode (Ctrl+C to stop)..." -ForegroundColor Green
  Push-Location $env:GF_PATHS_HOME
  try {
    & $grafanaExe
  } finally {
    Pop-Location
  }
} else {
  # New window: run server with working directory at HOME
  Start-Process -FilePath $grafanaExe -WorkingDirectory $env:GF_PATHS_HOME -WindowStyle Normal
  Write-Host "Grafana started in new window" -ForegroundColor Green
}
