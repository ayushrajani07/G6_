<#
Starts Prometheus, Grafana, and (optionally) InfluxDB / performs initial Influx setup.
Collector start removed per request; use a separate script to run the G6 collector if needed.

Influx Usage:
 - Provide -StartInflux to launch influxd.
 - Provide -SetupInflux (one-time) to run `influx setup` (requires CLI + parameters).

NOTE: Do not run -SetupInflux more than once; it is idempotent only if it detects existing metadata.
#>
param(
  # Prometheus
  [string]$PrometheusDir = 'C:\Prometheus',
  [string]$PromConfig = 'C:\Users\ASUS\Documents\G6\qq\g6_reorganized\prometheus.yml',
  [switch]$AutoDetectPrometheus = $true,
  [int]$PrometheusPort = 9090,

  # Grafana
  [string]$GrafanaHome = 'C:\Program Files\GrafanaLabs\grafana\grafana-12.1.1',
  [switch]$ForegroundGrafana,
  [switch]$AltGrafanaPort,
  [switch]$AutoDetectGrafana = $true,
  [int]$GrafanaPort = 3000,

  # G6_ENHANCED_UI_MARKER: NEW paths and switches
  [string]$GrafanaDataRoot = 'C:\GrafanaData',
  [string]$ProvisioningRoot = 'C:\Users\ASUS\Documents\G6\qq\g6_reorganized\grafana\provisioning',
  [switch]$FixGrafanaProvisioning,
  [switch]$ResetGrafanaDb,

  # InfluxDB (optional)
  [switch]$StartInflux = $true,
  [switch]$SetupInflux,
  [switch]$AutoDetectInflux = $true,
  [string]$InfluxdExe = 'C:\influxdata\influxdb2\influxd.exe',
  [string]$InfluxCliExe = 'C:\InfluxDB\influx.exe',
  [string]$InfluxDataDir = 'C:\InfluxDB\data',
  [int]$InfluxPort = 8086,
  [string]$InfluxConfigName = 'g6-config',
  [string]$InfluxOrg = 'g6',
  [string]$InfluxBucket = 'g6_metrics',
  [int]$InfluxRetentionHours = 720,
  [string]$InfluxAdminUser = 'admin',
  [string]$InfluxAdminPassword,
  [string]$InfluxAdminToken
)

# G6_ENHANCED_UI_MARKER: NEW .env loader (repo root)
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
  Write-Host "Loaded environment from: $envFile" -ForegroundColor Cyan
} else {
  Write-Host "No .env found at: $envFile (skipping)" -ForegroundColor DarkYellow
}

function Test-PortListening {
  param([int]$Port, [int]$TimeoutSeconds = 10, [string]$Name = 'service', [int]$InitialDelayMs = 0)
  if ($InitialDelayMs -gt 0) { Start-Sleep -Milliseconds $InitialDelayMs }
  for ($i=0; $i -lt ($TimeoutSeconds*2); $i++) {
    try {
      $conn = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue
      if ($conn) { return $true }
    } catch { }
    Start-Sleep -Milliseconds 500
  }
  return $false
}

function Invoke-HttpHealth {
  param([string]$Url, [int]$TimeoutSeconds = 2)
  try {
    $c = New-Object System.Net.Http.HttpClient
    $c.Timeout = [TimeSpan]::FromSeconds($TimeoutSeconds)
    $resp = $c.GetAsync($Url).GetAwaiter().GetResult()
    return [pscustomobject]@{ Code = [int]$resp.StatusCode; Success = $resp.IsSuccessStatusCode }
  } catch {
    return [pscustomobject]@{ Code = -1; Success = $false }
  }
}

# G6_ENHANCED_UI_MARKER: NEW stop any existing grafana* to avoid DB locks
function Stop-GrafanaIfRunning {
  try {
    $ps = Get-Process | Where-Object { $_.ProcessName -like 'grafana*' }
    if ($ps) {
      Write-Host "Stopping existing Grafana processes..." -ForegroundColor Yellow
      $ps | Stop-Process -Force -ErrorAction SilentlyContinue
      Start-Sleep -Seconds 1
    }
  } catch { }
}

# G6_ENHANCED_UI_MARKER: NEW ensure single dashboards provider + alerting hygiene
function Ensure-GrafanaProvisioning {
  param([string]$ProvisioningRoot, [string]$DashboardsPath)
  Write-Host "Ensuring Grafana provisioning at: $ProvisioningRoot" -ForegroundColor Cyan

  $needDirs = @('dashboards','datasources','plugins','alerting','alerting\rules','alerting\templates')
  foreach ($d in $needDirs) {
    $p = Join-Path $ProvisioningRoot $d
    if (-not (Test-Path $p)) { New-Item -ItemType Directory -Force -Path $p | Out-Null; Write-Host "Created $d" -ForegroundColor Green }
  }

  $dashProvDir = Join-Path $ProvisioningRoot 'dashboards'
  $provFile = Join-Path $dashProvDir 'dashboard.yml'
  if (-not (Test-Path $provFile)) {
    # G6_ENHANCED_UI_MARKER: NEW YAML provider here-string (ASCII only)
    $yaml = @"
apiVersion: 1

providers:
  - name: 'G6 Dashboards'
    orgId: 1
    folder: 'G6 Platform'
    type: file
    disableDeletion: false
    allowUiUpdates: true
    updateIntervalSeconds: 30
    options:
      path: $DashboardsPath
"@
    $yaml | Set-Content -Encoding UTF8 -Path $provFile
    Write-Host "Wrote dashboards provider: $provFile" -ForegroundColor Green
  } else {
    Write-Host "Dashboards provider exists: $provFile" -ForegroundColor Green
  }

  Get-ChildItem -Path $dashProvDir -Recurse -File -Include *.yml,*.yaml,*.json -ErrorAction SilentlyContinue |
    Where-Object { $_.FullName -ne $provFile } |
    ForEach-Object {
      $disabled = $_.FullName + '.disabled'
      if (-not (Test-Path $disabled)) {
        Rename-Item -Path $_.FullName -NewName ($_.Name + '.disabled')
        Write-Host "Disabled extra provider: $($_.FullName)" -ForegroundColor Yellow
      }
    }

  $alert = Join-Path $ProvisioningRoot 'alerting'
  if (Test-Path $alert) {
    Get-ChildItem -Path $alert -File -ErrorAction SilentlyContinue |
      Where-Object { $_.Extension -notin '.yaml','.yml','.json' } |
      Remove-Item -Force -ErrorAction SilentlyContinue
    @('rules','templates') | ForEach-Object {
      $p = Join-Path $alert $_
      if (Test-Path $p) {
        $hasYaml = Get-ChildItem -Path $p -File -Include *.yml,*.yaml,*.json -ErrorAction SilentlyContinue
        if (-not $hasYaml) { Remove-Item -Recurse -Force $p -ErrorAction SilentlyContinue }
      }
    }
    Write-Host "Cleaned alerting provisioning of non-YAML files" -ForegroundColor Green
  }
}

# G6_ENHANCED_UI_MARKER: NEW clean-slate DB (backup + remove)
function Reset-GrafanaDb {
  param([string]$GrafanaDataRoot)
  $db = Join-Path (Join-Path $GrafanaDataRoot 'data') 'grafana.db'
  if (Test-Path $db) {
    try {
      Get-Process | Where-Object { $_.ProcessName -like 'grafana*' } |
        Stop-Process -Force -ErrorAction SilentlyContinue
    } catch { }
    $backup = "$db.bak_$(Get-Date -Format yyyyMMdd_HHmmss)"
    Copy-Item $db $backup -ErrorAction SilentlyContinue
    Remove-Item $db -Force -ErrorAction SilentlyContinue
    Write-Host "Removed grafana.db (backup: $backup)" -ForegroundColor Yellow
  } else {
    Write-Host "No grafana.db at $db (nothing to reset)" -ForegroundColor DarkYellow
  }
}

function Resolve-Prometheus {
  param([string]$Dir, [switch]$AttemptDetect)
  $exe = Join-Path $Dir 'prometheus.exe'
  if (Test-Path $exe) { return $exe }
  if ($AttemptDetect -or $true) {
    $candidates = @('C:\Prometheus\prometheus.exe','C:\Program Files\Prometheus\prometheus.exe','C:\ProgramData\Prometheus\prometheus.exe')
    foreach ($c in $candidates) { if (Test-Path $c) { return $c } }
    $base = 'C:\Prometheus'
    if (Test-Path $base) {
      $sub = Get-ChildItem -Path $base -Directory -ErrorAction SilentlyContinue | Where-Object { $_.Name -like 'prometheus*' } | Sort-Object LastWriteTime -Descending | Select-Object -First 1
      if ($sub) { $maybe = Join-Path $sub.FullName 'prometheus.exe'; if (Test-Path $maybe) { return $maybe } }
    }
  }
  return $exe
}

function Resolve-Grafana {
  param([string]$GrafRoot, [switch]$AttemptDetect)
  $exe = Join-Path (Join-Path $GrafRoot 'bin') 'grafana-server.exe'
  if (Test-Path $exe) { return $exe }
  if ($AttemptDetect -or $true) {
    $bases = @('C:\Program Files\GrafanaLabs\grafana','C:\Grafana','C:\Program Files','C:\Program Files (x86)')
    foreach ($b in $bases) {
      if (-not (Test-Path $b)) { continue }
      $dirs = Get-ChildItem -Path $b -Directory -ErrorAction SilentlyContinue | Where-Object { $_.Name -like 'grafana*' }
      foreach ($d in ($dirs | Sort-Object LastWriteTime -Descending)) {
        $maybe = Join-Path (Join-Path $d.FullName 'bin') 'grafana-server.exe'
        if (Test-Path $maybe) { return $maybe }
      }
    }
  }
  return $exe
}

function Resolve-Influxd {
  param([string]$Path, [switch]$AttemptDetect)
  if (Test-Path $Path) { return $Path }
  if ($AttemptDetect -or $true) {
    $candidates = @('C:\influxdata\influxdb2\influxd.exe','C:\Program Files\InfluxData\influxdb2\influxd.exe','C:\Program Files\InfluxData\influxdb\influxd.exe')
    foreach ($c in $candidates) { if (Test-Path $c) { return $c } }
  }
  return $Path
}

$ErrorActionPreference = 'Stop'
Write-Host '=== Starting Observability Stack (Prometheus / Grafana / Influx) ===' -ForegroundColor Cyan

# Preflight provisioning / DB reset
if ($FixGrafanaProvisioning) {
  $dashPath = 'C:\Users\ASUS\Documents\G6\qq\g6_reorganized\grafana\dashboards'
  Ensure-GrafanaProvisioning -ProvisioningRoot $ProvisioningRoot -DashboardsPath $dashPath
}
if ($ResetGrafanaDb) { Reset-GrafanaDb -GrafanaDataRoot $GrafanaDataRoot }

# 1) Prometheus
$resolvedProm = Resolve-Prometheus -Dir $PrometheusDir -AttemptDetect:$AutoDetectPrometheus
if (Test-Path $resolvedProm) {
  $promWorkDir = Split-Path $resolvedProm -Parent
  Write-Host "Launching Prometheus: $resolvedProm" -ForegroundColor Green
  Start-Process -FilePath $resolvedProm -ArgumentList "--config.file=$PromConfig" -WorkingDirectory $promWorkDir
} else {
  Write-Host "Prometheus not found (looked at $resolvedProm)." -ForegroundColor Yellow
}

# 2) Grafana
Stop-GrafanaIfRunning
$grafanaExeResolved = Resolve-Grafana -GrafRoot $GrafanaHome -AttemptDetect:$AutoDetectGrafana
$startGraf = Join-Path $scriptRoot 'start_grafana.ps1'

# G6_ENHANCED_UI_MARKER: NEW launch honoring .env and new-window option
if (-not (Test-Path $grafanaExeResolved)) {
  Write-Host "Grafana server executable not found (searched under $GrafanaHome and common paths)." -ForegroundColor Yellow
} else {
  $homePath = $env:GF_PATHS_HOME
  if (-not $homePath) { $homePath = (Split-Path (Split-Path $grafanaExeResolved -Parent) -Parent) }
  if (Test-Path $startGraf) {
    $grafArgs = @('-GrafanaHome', (Split-Path (Split-Path $grafanaExeResolved -Parent) -Parent))
    if ($AltGrafanaPort) { $grafArgs += '-AltPort'; $GrafanaPort = 3001 }
    if ($ForegroundGrafana) {
      Write-Host "Launching Grafana (via script, foreground): $startGraf" -ForegroundColor Green
      Push-Location $homePath
      try { & powershell -ExecutionPolicy Bypass -File $startGraf @grafArgs -Foreground } finally { Pop-Location }
    } else {
      Write-Host "Launching Grafana in a new window (via script): $startGraf" -ForegroundColor Green
      Start-Process "$env:WINDIR\System32\WindowsPowerShell\v1.0\powershell.exe" `
        -ArgumentList @('-NoExit','-ExecutionPolicy','Bypass','-File',"`"$startGraf`"") `
        -WorkingDirectory $homePath `
        -WindowStyle Normal
    }
  } else {
    Write-Host "start_grafana.ps1 missing. Launching grafana-server directly." -ForegroundColor Yellow
    if ($ForegroundGrafana) {
      Push-Location $homePath
      try { & $grafanaExeResolved } finally { Pop-Location }
    } else {
      Start-Process "$env:WINDIR\System32\WindowsPowerShell\v1.0\powershell.exe" `
        -ArgumentList @('-NoExit','-Command',"`"Set-Location `"$homePath`"; & `"$grafanaExeResolved`"`"") `
        -WorkingDirectory $homePath `
        -WindowStyle Normal
    }
  }
}

# 3) InfluxDB (optional)
if ($StartInflux -or $SetupInflux) {
  $InfluxdExe = Resolve-Influxd -Path $InfluxdExe -AttemptDetect:$AutoDetectInflux
  if (-not (Test-Path $InfluxdExe)) {
    Write-Host "Influxd executable not found (after detection attempts)." -ForegroundColor Yellow
  } elseif ($StartInflux) {
    Write-Host "Launching InfluxDB: $InfluxdExe" -ForegroundColor Green
    $influxArgs = @()
    if ($InfluxDataDir) { $influxArgs += "--bolt-path=$InfluxDataDir\influxd.bolt"; $influxArgs += "--engine-path=$InfluxDataDir\engine" }
    Start-Process -FilePath $InfluxdExe -ArgumentList $influxArgs -WindowStyle Minimized
  }
  if ($SetupInflux) {
    if (-not (Test-Path $InfluxCliExe)) {
      Write-Host "Influx CLI not found at $InfluxCliExe" -ForegroundColor Yellow
    } else {
      $missing = @()
      if (-not $InfluxAdminPassword) { $missing += 'InfluxAdminPassword' }
      if (-not $InfluxAdminToken) { $missing += 'InfluxAdminToken' }
      if ($missing.Count -gt 0) {
        Write-Host ("Cannot run setup; missing: {0}" -f ($missing -join ', ')) -ForegroundColor Yellow
      } else {
        Write-Host 'Running one-time Influx setup...' -ForegroundColor Green
        $retention = "$InfluxRetentionHours" + 'h'
        & $InfluxCliExe setup --skip-confirmation `
          --username $InfluxAdminUser `
          --password $InfluxAdminPassword `
          --org $InfluxOrg `
          --bucket $InfluxBucket `
          --retention $retention `
          --token $InfluxAdminToken `
          --name $InfluxConfigName
        if ($LASTEXITCODE -eq 0) { Write-Host 'Influx setup completed.' -ForegroundColor Green }
        else { Write-Host "Influx setup exited with code $LASTEXITCODE" -ForegroundColor Red }
      }
    }
  }
}

# --- Verifying service ports (extended wait) ---
Write-Host '--- Verifying service ports (extended wait) ---' -ForegroundColor Cyan

# Prometheus quick probe
$promOk = Test-PortListening -Port $PrometheusPort -Name 'Prometheus' -InitialDelayMs 500
if ($promOk) { Write-Host ("listening on: http://localhost:{0} (Prometheus)" -f $PrometheusPort) -ForegroundColor Green }
else { Write-Host ("not listening: http://localhost:{0} (Prometheus)" -f $PrometheusPort) -ForegroundColor Yellow }

# Grafana up to 60s
$effectiveGrafPort = $GrafanaPort; if ($AltGrafanaPort) { $effectiveGrafPort = 3001 }
$grafOk = $false
if (Test-PortListening -Port $effectiveGrafPort -Name 'Grafana' -TimeoutSeconds 10 -InitialDelayMs 1000) {
  for ($g=0; $g -lt 30; $g++) {
    $health = Invoke-HttpHealth -Url ("http://localhost:{0}/api/health" -f $effectiveGrafPort) -TimeoutSeconds 3
    if ($health.Success -and $health.Code -eq 200) { $grafOk = $true; break }
    Start-Sleep -Seconds 2
  }
}
if ($grafOk) {
  Write-Host ("listening on: http://localhost:{0} (Grafana)" -f $effectiveGrafPort) -ForegroundColor Green

  # Optional: auto-open UI in new browser window (Edge) for better UX
  try {
    Start-Process msedge.exe "-new-window http://localhost:$effectiveGrafPort"
  } catch {
    Start-Process "http://localhost:$effectiveGrafPort"
  }

} else {
  Write-Host ("not listening: http://localhost:{0} (Grafana) -- check service logs" -f $effectiveGrafPort) -ForegroundColor Yellow
  Write-Host "Hint: ensure only one dashboards provider and only .yml/.yaml/.json in alerting provisioning." -ForegroundColor DarkYellow
}

# Influx up to 60s
$influxOk = $false
if ($StartInflux) {
  if (Test-PortListening -Port $InfluxPort -Name 'InfluxDB' -InitialDelayMs 500 -TimeoutSeconds 20) {
    for ($i=0; $i -lt 20; $i++) {
      $health = Invoke-HttpHealth -Url ("http://localhost:{0}/health" -f $InfluxPort) -TimeoutSeconds 3
      if ($health.Success -and $health.Code -eq 200) { $influxOk = $true; break }
      Start-Sleep -Seconds 2
    }
  }
  if ($influxOk) { Write-Host ("listening on: http://localhost:{0} (InfluxDB)" -f $InfluxPort) -ForegroundColor Green }
  else { Write-Host ("not listening: http://localhost:{0} (InfluxDB) -- or /health not ready" -f $InfluxPort) -ForegroundColor Yellow }
}

Write-Host 'All start commands issued. (Verification complete.)' -ForegroundColor Cyan
