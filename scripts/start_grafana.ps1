param(
  [string]$GrafanaHome = 'C:\Program Files\GrafanaLabs\grafana\grafana-12.1.1',
  [switch]$Foreground,
  [switch]$AltPort,
  [int]$Port,
  [switch]$AutoPort,
  [switch]$DebugGrafana,
  [switch]$SafeMode
)

# Helper: set env var only if blank / unset
function Set-EnvIfEmpty {
  param(
    [string]$Name,
    [string]$Value
  )
  if (-not (Get-Item Env:$Name -ErrorAction SilentlyContinue) -or [string]::IsNullOrWhiteSpace((Get-Item Env:$Name).Value)) {
    [Environment]::SetEnvironmentVariable($Name, $Value)
  }
}

# Debug: show received arguments (helps diagnose port not being applied)
if ($GrafanaHome) { $GrafanaHome = $GrafanaHome.Trim().Trim('"') }
Write-Host "start_grafana.ps1 args -> GrafanaHome=$GrafanaHome Port=$Port AltPort=$AltPort AutoPort=$AutoPort Debug=$DebugGrafana SafeMode=$SafeMode" -ForegroundColor DarkCyan

# If the provided GrafanaHome doesn't exist, attempt simple discovery
if (-not (Test-Path $GrafanaHome)) {
  Write-Host "Provided GrafanaHome not found: $GrafanaHome -- attempting auto-detect" -ForegroundColor Yellow
  $candidates = @(
    'C:\Program Files\GrafanaLabs\grafana',
    'C:\Program Files\GrafanaLabs',
    'C:\Grafana'
  )
  foreach ($c in $candidates) {
    if (Test-Path $c) {
      $dir = Get-ChildItem -Path $c -Directory -ErrorAction SilentlyContinue | Where-Object { $_.Name -like 'grafana*' } | Sort-Object LastWriteTime -Descending | Select-Object -First 1
      if ($dir) { $GrafanaHome = $dir.FullName; Write-Host "Auto-detected GrafanaHome=$GrafanaHome" -ForegroundColor Green; break }
    }
  }
}

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

# Force IPv4 + IPv6 dual binding by specifying an explicit address if not set
if (-not $env:GF_SERVER_HTTP_ADDR -or [string]::IsNullOrWhiteSpace($env:GF_SERVER_HTTP_ADDR)) {
  [Environment]::SetEnvironmentVariable('GF_SERVER_HTTP_ADDR','0.0.0.0')
  Write-Host "GF_SERVER_HTTP_ADDR=0.0.0.0 (set by script)" -ForegroundColor Gray
}

if ($DebugGrafana) {
  [Environment]::SetEnvironmentVariable('GF_LOG_LEVEL','debug')
  [Environment]::SetEnvironmentVariable('GF_LOG_MODE','console')
  Write-Host "Debug logging enabled (GF_LOG_LEVEL=debug)" -ForegroundColor Yellow
}

if ($SafeMode) {
  # Disable plugin auto downloads & external plugins to minimize surface
  [Environment]::SetEnvironmentVariable('GF_PLUGIN_AUTO_INSTALL','false')
  [Environment]::SetEnvironmentVariable('GF_PLUGINS_ALLOW_LOADING_UNSIGNED_PLUGINS','')
  # Point plugins path to an isolated empty directory to skip loading extras
  $safePlugins = 'C:\GrafanaData\safe_plugins'
  if (-not (Test-Path $safePlugins)) { New-Item -ItemType Directory -Force -Path $safePlugins | Out-Null }
  [Environment]::SetEnvironmentVariable('GF_PATHS_PLUGINS', $safePlugins)
  Write-Host "SafeMode: plugin auto-install disabled; isolated plugins dir=$safePlugins" -ForegroundColor Yellow
}

function Test-PortInUse {
  param([int]$P)
  try { return $null -ne (Get-NetTCPConnection -LocalPort $P -ErrorAction SilentlyContinue) } catch { return $false }
}

# Determine desired port precedence: explicit -Port > -AltPort > env > default 3000
$explicitRequest = $false
if ($Port) { $desiredPort = $Port; $explicitRequest = $true }
elseif ($AltPort) { $desiredPort = 3001; $explicitRequest = $true }
elseif ($env:GF_SERVER_HTTP_PORT) { $desiredPort = [int]$env:GF_SERVER_HTTP_PORT }
else { $desiredPort = 3000 }

if (Test-PortInUse -P $desiredPort) {
  $pids = (Get-NetTCPConnection -LocalPort $desiredPort -ErrorAction SilentlyContinue | Select-Object -First 5 -ExpandProperty OwningProcess) -join ','
  Write-Host "Port $desiredPort already in use (PID(s): $pids)" -ForegroundColor Yellow
  if ($explicitRequest -and -not $AutoPort) {
    Write-Host "Explicit port requested and occupied. Free the port or re-run with -AutoPort to pick an alternate." -ForegroundColor Red
    exit 2
  }
  if ($AutoPort) {
    foreach ($alt in 3000..3010) {
      if (-not (Test-PortInUse -P $alt)) { $desiredPort = $alt; Write-Host "AutoPort selected free port $desiredPort" -ForegroundColor Green; break }
    }
  }
}

[Environment]::SetEnvironmentVariable("GF_SERVER_HTTP_PORT", "$desiredPort")
Write-Host "Using HTTP port: $desiredPort" -ForegroundColor Gray

# Ensure GF_PATHS_* present (fallback to GrafanaHome if not in .env)
# G6_ENHANCED_UI_MARKER: NEW fallback assignments (compatible with Windows PowerShell 5.1)
Set-EnvIfEmpty -Name 'GF_PATHS_HOME' -Value $GrafanaHome
Set-EnvIfEmpty -Name 'GF_PATHS_DATA' -Value 'C:\GrafanaData\data'
Set-EnvIfEmpty -Name 'GF_PATHS_LOGS' -Value 'C:\GrafanaData\log'
Set-EnvIfEmpty -Name 'GF_PATHS_PLUGINS' -Value 'C:\GrafanaData\plugins'
Set-EnvIfEmpty -Name 'GF_PATHS_PROVISIONING' -Value (Join-Path (Split-Path $scriptRoot -Parent) 'grafana\provisioning')
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
  Start-Sleep -Seconds 2
  $proc = Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.ProcessName -eq 'grafana-server' }
  if ($proc) {
    Write-Host "Grafana process detected (PID=$($proc.Id))" -ForegroundColor Green
  } else {
    Write-Host "WARNING: grafana-server process not detected after launch attempt." -ForegroundColor Yellow
    $logPath = Join-Path $env:GF_PATHS_LOGS 'grafana.log'
    if (Test-Path $logPath) {
      Write-Host "--- Recent grafana.log (tail 20) ---" -ForegroundColor DarkCyan
      Get-Content $logPath -Tail 20 | ForEach-Object { Write-Host $_ }
      Write-Host "--- End log tail ---" -ForegroundColor DarkCyan
    } else {
      Write-Host "No grafana.log found at $logPath yet." -ForegroundColor DarkYellow
    }
  }
}
