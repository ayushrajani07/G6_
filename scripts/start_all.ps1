<#
Starts Prometheus, Grafana, and (optionally) InfluxDB / performs initial Influx setup.
Collector start removed per request; use a separate script to run the G6 collector if needed.

Influx Usage:
 - Provide -StartInflux to launch influxd.
 - Provide -SetupInflux (one-time) to run `influx setup` (requires CLI + parameters).

NOTE: Do not run -SetupInflux more than once; it is idempotent only if it detects existing metadata.
#
# Added automation:
#  -GrafanaSelfTest / -SelfTest : After launch, actively probes port & /api/health with diagnostics.
#  -ProvisionPrometheusDatasource : Creates a Prometheus datasource provisioning YAML if missing.
#  -SafeGrafana : already routes to -SafeMode for trimmed plugin load.
#  -DeepGrafanaDebug : more verbose logging + immediate process detection.
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
  [switch]$DeepGrafanaDebug,
  [switch]$SafeGrafana,
  [switch]$GrafanaSelfTest,
  [switch]$SelfTest,
  [switch]$ProvisionPrometheusDatasource,
  [switch]$ShowGrafanaLogOnFail,

  # Paths / provisioning
  [string]$GrafanaDataRoot = 'C:\GrafanaData',
  [string]$ProvisioningRoot = 'C:\Users\ASUS\Documents\G6\qq\g6_reorganized\grafana\provisioning',
  [switch]$FixGrafanaProvisioning,
  [switch]$ResetGrafanaDb,

  # InfluxDB (optional)
  [switch]$StartInflux = $true,
  [switch]$SetupInflux,
  [switch]$AutoDetectInflux = $true,
  [string]$InfluxdExe = 'C:\influxdata\influxdb2\influxd.exe',
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

# Consolidated quick verification for Grafana (port bind + /api/health)
function Test-GrafanaQuick {
  param(
    [int]$Port,
    [int]$BindTimeoutSeconds = 10,
    [int]$HealthAttempts = 30,
    [int]$HealthDelaySeconds = 2
  )
  if (-not (Test-PortListening -Port $Port -Name 'Grafana' -TimeoutSeconds $BindTimeoutSeconds -InitialDelayMs 1000)) {
    return [pscustomobject]@{ Bound=$false; Healthy=$false; Code=$null }
  }
  for ($i=0; $i -lt $HealthAttempts; $i++) {
    $h = Invoke-HttpHealth -Url ("http://localhost:{0}/api/health" -f $Port) -TimeoutSeconds 3
    if ($h.Success -and $h.Code -eq 200) { return [pscustomobject]@{ Bound=$true; Healthy=$true; Code=$h.Code } }
    Start-Sleep -Seconds $HealthDelaySeconds
  }
  return [pscustomobject]@{ Bound=$true; Healthy=$false; Code=$h.Code }
}

# Self-test routine for Grafana to reduce manual debugging.
function Invoke-GrafanaSelfTest {
  param(
    [int]$Port,
    [int]$MaxSeconds = 45,
    [string]$DataRoot = 'C:\GrafanaData'
  )
  Write-Host "[SelfTest] Starting Grafana health probe on port $Port (timeout ${MaxSeconds}s)" -ForegroundColor Cyan
  $start    = Get-Date
  $bound    = $false
  $healthy  = $false
  $procId   = $null
  $lastErr  = $null
  $lastCode = $null
  $attempt  = 0
  $hosts    = @('localhost','127.0.0.1')

  while ((Get-Date) - $start -lt [TimeSpan]::FromSeconds($MaxSeconds)) {
    $attempt++
    $p = Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.ProcessName -eq 'grafana-server' }
    if ($p) { $procId = $p.Id }
    $tcp = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue
    if ($tcp) { $bound = $true }
    if ($bound) {
      foreach ($h in $hosts) {
        try {
          $resp = Invoke-HttpHealth -Url ("http://{0}:{1}/api/health" -f $h,$Port) -TimeoutSeconds 4
          $lastCode = $resp.Code
          if ($resp.Success -and $resp.Code -eq 200) { $healthy = $true; break }
        } catch {
          $lastErr = $_.Exception.Message
        }
      }
      if ($healthy) { break }
    }
    Start-Sleep -Milliseconds 900
  }

  if ($healthy) {
    Write-Host "[SelfTest] SUCCESS: Grafana healthy on http://localhost:$Port/api/health (PID=$procId attempts=$attempt)" -ForegroundColor Green
    return $true
  }

  Write-Host ("[SelfTest] FAILURE: Grafana not healthy (PID={0} Bound={1} LastHTTP={2} LastErr='{3}')" -f $procId,$bound,$lastCode,$lastErr) -ForegroundColor Yellow
  $logPath = Join-Path $DataRoot 'log/grafana.log'
  if (Test-Path $logPath) {
    Write-Host "[SelfTest] Last 60 log lines:" -ForegroundColor DarkCyan
    try {
      Get-Content $logPath -Tail 60 | ForEach-Object { Write-Host $_ }
    } catch {
      Write-Host "[SelfTest] Unable to read log: $($_.Exception.Message)" -ForegroundColor Red
    }
  } else {
    Write-Host "[SelfTest] grafana.log not found at $logPath" -ForegroundColor DarkYellow
  }

  if (-not $procId) {
    Write-Host "[SelfTest] No grafana-server process detected. Foreground debug suggestion:" -ForegroundColor DarkYellow
  } elseif (-not $bound) {
  Write-Host "[SelfTest] Process exists but port $Port not bound - possible security tool/network filter or premature termination." -ForegroundColor DarkYellow
  } else {
    Write-Host "[SelfTest] Port bound but /api/health failed (code=$lastCode). Try foreground run and longer timeout." -ForegroundColor DarkYellow
  }
  Write-Host "[SelfTest] Next step (copy/paste):" -ForegroundColor Cyan
  Write-Host "  powershell -ExecutionPolicy Bypass -File .\\scripts\\start_grafana.ps1 -Port $Port -Foreground -DebugGrafana -SafeMode" -ForegroundColor Gray
  return $false
}
 

function Ensure-PrometheusDatasource {
  param(
    [string]$ProvisioningRoot,
    [string]$PromURL = 'http://localhost:9090'
  )
  $dsDir = Join-Path $ProvisioningRoot 'datasources'
  if (-not (Test-Path $dsDir)) { New-Item -ItemType Directory -Force -Path $dsDir | Out-Null }
  $dsFile = Join-Path $dsDir 'prometheus.yml'
  if (Test-Path $dsFile) {
    Write-Host "Datasource provisioning already present: $dsFile" -ForegroundColor DarkGray
    return
  }
  $yamlLines = @(
    'apiVersion: 1',
    'datasources:',
    '  - name: Prometheus',
    '    type: prometheus',
    '    access: proxy',
    "    url: $PromURL",
    '    isDefault: true',
    '    editable: true'
  )
  ($yamlLines -join [Environment]::NewLine) | Set-Content -Encoding UTF8 -Path $dsFile
  Write-Host "Provisioned Prometheus datasource: $dsFile" -ForegroundColor Green
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
    $provLines = @(
      'apiVersion: 1',
      '',
      'providers:',
      "  - name: 'G6 Dashboards'",
      '    orgId: 1',
      "    folder: 'G6 Platform'",
      '    type: file',
      '    disableDeletion: false',
      '    allowUiUpdates: true',
      '    updateIntervalSeconds: 30',
      '    options:',
      "      path: $DashboardsPath"
    )
    ($provLines -join [Environment]::NewLine) | Set-Content -Encoding UTF8 -Path $provFile
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
  $grafHomeValue = (Split-Path (Split-Path $grafanaExeResolved -Parent) -Parent)
  # Pass GrafanaHome without embedding quotes; Start-Process preserves argument boundaries
  $grafArgs = @('-GrafanaHome', $grafHomeValue)
  if ($AltGrafanaPort) { $GrafanaPort = 3001; $grafArgs += '-Port'; $grafArgs += $GrafanaPort }
  else { $grafArgs += '-Port'; $grafArgs += $GrafanaPort }
  if ($DeepGrafanaDebug) { $grafArgs += '-DebugGrafana' }
  if ($SafeGrafana) { $grafArgs += '-SafeMode' }
    if ($ForegroundGrafana) {
      Write-Host "Launching Grafana (via script, foreground): $startGraf (Port=$GrafanaPort)" -ForegroundColor Green
      Push-Location $homePath
      try { & powershell -ExecutionPolicy Bypass -File $startGraf @grafArgs -Foreground } finally { Pop-Location }
    } else {
      Write-Host "Launching Grafana in a new window (via script): $startGraf (Port=$GrafanaPort)" -ForegroundColor Green
      $psArgs = @('-NoExit','-ExecutionPolicy','Bypass','-File',"`"$startGraf`"") + $grafArgs
      Start-Process "$env:WINDIR\System32\WindowsPowerShell\v1.0\powershell.exe" -ArgumentList $psArgs -WorkingDirectory $homePath -WindowStyle Normal
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

# Grafana up to 60s using consolidated helper
$effectiveGrafPort = $GrafanaPort; if ($AltGrafanaPort) { $effectiveGrafPort = 3001 }
$gq = Test-GrafanaQuick -Port $effectiveGrafPort
if ($gq.Bound -and $gq.Healthy) {
  Write-Host ("listening on: http://localhost:{0} (Grafana)" -f $effectiveGrafPort) -ForegroundColor Green
  try { Start-Process msedge.exe "-new-window http://localhost:$effectiveGrafPort" } catch { Start-Process "http://localhost:$effectiveGrafPort" }
} else {
  Write-Host ("not listening: http://localhost:{0} (Grafana) -- check service logs (Bound={1} Code={2})" -f $effectiveGrafPort,$gq.Bound,$gq.Code) -ForegroundColor Yellow
  Write-Host "Hint: ensure only one dashboards provider and only .yml/.yaml/.json in alerting provisioning." -ForegroundColor DarkYellow
  if ($ShowGrafanaLogOnFail) {
    try {
      $logPath = Join-Path $GrafanaDataRoot 'log/grafana.log'
      if (Test-Path $logPath) {
        Write-Host "--- Last 80 lines of grafana.log ---" -ForegroundColor Cyan
        Get-Content $logPath -Tail 80 | ForEach-Object { Write-Host $_ }
        Write-Host "--- End of grafana.log tail ---" -ForegroundColor Cyan
      } else { Write-Host "Grafana log not found at $logPath" -ForegroundColor DarkYellow }
    } catch { Write-Host "Failed to tail grafana.log: $($_.Exception.Message)" -ForegroundColor Red }
  }
}

# Optional self-test (runs regardless of earlier quick probe result if requested)
if ($GrafanaSelfTest -or $SelfTest) {
  $st = Invoke-GrafanaSelfTest -Port $effectiveGrafPort -DataRoot $GrafanaDataRoot
  if ($ProvisionPrometheusDatasource) {
    Write-Host "[Provision] Creating Prometheus datasource (selfTestPassed=$st)" -ForegroundColor Cyan
    Ensure-PrometheusDatasource -ProvisioningRoot $ProvisioningRoot
  }
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
