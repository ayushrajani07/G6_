param(
  [string]$PrometheusExe = 'C:\Prometheus\prometheus-3.5.0.windows-amd64\prometheus.exe',
  [int]$PrometheusPort = 9091,
  [int]$GrafanaPort = 3002,
  [int]$MetricsPort = 9108,
  [int]$OverlayPort = 9109,
  [int]$WebPort = 9500,
  [string]$GrafanaDataRoot = 'C:\GrafanaData',
  [switch]$StartMetricsServer = $true,
  [switch]$StartOverlayExporter = $true,
  [switch]$GrafanaAllowAnonymous,
  [switch]$GrafanaAnonymousEditor,
  # Permanently disable password by enabling Anonymous Admin and hiding login form
  [switch]$GrafanaDisablePassword,
  [switch]$OpenBrowser,
  [switch]$StartInflux = $true,
  [string]$InfluxExe = 'C:\Program Files\InfluxData\influxdb\influxd.exe',
  [int]$InfluxPort = 8087,
  [string]$InfluxDataDir
)

$ErrorActionPreference = 'Continue'

function Ensure-Dir { param([string]$Path) if (-not (Test-Path $Path)) { New-Item -ItemType Directory -Force -Path $Path | Out-Null } }
function Invoke-Http { param([string]$Url,[int]$Timeout=3) try { $wc = [System.Net.Http.HttpClient]::new(); $wc.Timeout=[TimeSpan]::FromSeconds($Timeout); $r=$wc.GetAsync($Url).GetAwaiter().GetResult(); return [pscustomobject]@{Ok=$r.IsSuccessStatusCode; Code=[int]$r.StatusCode} } catch { return [pscustomobject]@{Ok=$false; Code=-1} } }
function Wait-For-Ready { param([string]$Url,[int]$Tries=20,[int]$DelayMs=1000) for($i=0;$i -lt $Tries;$i++){ $r=Invoke-Http -Url $Url -Timeout 3; if($r.Ok -and $r.Code -eq 200){ return $true } Start-Sleep -Milliseconds $DelayMs } return $false }
function Resolve-Python {
  param([string]$Root)
  $venvPy = Join-Path $Root '.venv/Scripts/python.exe'
  if (Test-Path $venvPy) { return $venvPy }
  try { return (Get-Command python -ErrorAction Stop).Source } catch { return $null }
}

Write-Host "=== G6 Baseline Observability Start ===" -ForegroundColor Cyan

# Default to passwordless mode unless explicitly overridden by flags
$__hasDisable = $PSBoundParameters.ContainsKey('GrafanaDisablePassword')
$__hasAnon    = $PSBoundParameters.ContainsKey('GrafanaAllowAnonymous')
if (-not $__hasDisable -and -not $__hasAnon) {
  $GrafanaDisablePassword = $true
}

# Project root (repo root assumed as parent of this scripts folder)
$Root = Split-Path $PSScriptRoot -Parent
$PromConfig = Join-Path $Root 'prometheus.yml'
$RulesGen = Join-Path $Root 'prometheus_recording_rules_generated.yml'
$RulesSan = Join-Path $Root 'prometheus_recording_rules_generated.sanitized.yml'

# Logs & state
$LogDir = Join-Path $GrafanaDataRoot 'log'
$StateDir = Join-Path $GrafanaDataRoot 'obs'
Ensure-Dir -Path $LogDir
Ensure-Dir -Path $StateDir

# Default Influx data directory under Grafana data root if not provided
if (-not $InfluxDataDir) {
  $InfluxDataDir = Join-Path $GrafanaDataRoot 'influx'
}

# Sanitize rules (safe no-op if unchanged)
try {
  if (Test-Path $RulesGen) {
    & python (Join-Path $Root 'scripts/tools/sanitize_prom_rules.py') $RulesGen $RulesSan | Out-Host
  }
} catch {}

# Start metrics endpoint (for demo/smoke) on 127.0.0.1:9108
if ($StartMetricsServer) {
  try {
    Start-Process -FilePath (Get-Command python).Source -ArgumentList @((Join-Path $Root 'scripts/start_metrics_server.py'),'--host','127.0.0.1','--port',"$MetricsPort") -WindowStyle Minimized
    Write-Host ("Metrics server requested on :{0}" -f $MetricsPort) -ForegroundColor Gray
  } catch { Write-Host "Metrics server start failed (continuing)." -ForegroundColor DarkYellow }
}

# Start overlay exporter (tp family + weekday overlays) on 127.0.0.1:$OverlayPort
if ($StartOverlayExporter) {
  try {
    $args = @(
      (Join-Path $Root 'scripts/overlay_exporter.py'),
      '--host','127.0.0.1','--port',"$OverlayPort",
      '--base-dir',(Join-Path $Root 'data/g6_data'),
      '--weekday-root',(Join-Path $Root 'data/weekday_master'),
      '--status-file',(Join-Path $Root 'data/runtime_status.json'),
      '--expiry-tag','this_week','--expiry-tag','next_week',
      '--expiry-tag','this_month','--expiry-tag','next_month',
      '--offset','0'
    )
    Start-Process -FilePath (Get-Command python).Source -ArgumentList $args -WindowStyle Minimized
    Write-Host ("Overlay exporter requested on :{0}" -f $OverlayPort) -ForegroundColor Gray
  } catch { Write-Host "Overlay exporter start failed (continuing)." -ForegroundColor DarkYellow }
}

# Start lightweight web dashboard (FastAPI) providing JSON for Infinity (includes /api/live_csv)
try {
  $py = Resolve-Python -Root $Root
  $webOut = Join-Path $LogDir 'webapi_stdout.log'
  $webErr = Join-Path $LogDir 'webapi_stderr.log'
  if (-not $py) { throw "Python not found. Install Python or create .venv in repo root." }
  $uvArgs = @('-m','uvicorn','src.web.dashboard.app:app','--host','127.0.0.1','--port',"$WebPort","--reload")
  Start-Process -FilePath $py -ArgumentList $uvArgs -WorkingDirectory $Root -RedirectStandardOutput $webOut -RedirectStandardError $webErr -WindowStyle Minimized
  Write-Host ("Web API (dashboard) requested on :{0}" -f $WebPort) -ForegroundColor Gray
} catch { Write-Host "Web API start failed (continuing)." -ForegroundColor DarkYellow }

# Wait for Web API to become responsive (OpenAPI doc is a stable endpoint)
if (-not (Wait-For-Ready -Url ("http://127.0.0.1:{0}/openapi.json" -f $WebPort) -Tries 20 -DelayMs 750)) {
  Write-Host "Warning: Web API not responding yet on /openapi.json; Infinity panels may show connection errors. Check webapi_stderr.log under GrafanaData/log." -ForegroundColor DarkYellow
}

# Export Prom URL for Grafana provisioning
$promUrl = "http://127.0.0.1:$PrometheusPort"
[Environment]::SetEnvironmentVariable('G6_PROM_URL', $promUrl)

# Prepare Prometheus args
$promDataDir = Join-Path $GrafanaDataRoot ("prom_data_{0}" -f $PrometheusPort)
Ensure-Dir -Path $promDataDir
$promArgs = @("--config.file=$PromConfig","--web.listen-address=127.0.0.1:$PrometheusPort","--storage.tsdb.path=$promDataDir")
Write-Host ("Starting Prometheus on :{0}" -f $PrometheusPort) -ForegroundColor Green
try {
  Start-Process -FilePath $PrometheusExe -ArgumentList $promArgs -WorkingDirectory $Root -RedirectStandardOutput (Join-Path $LogDir 'prom_stdout.log') -RedirectStandardError (Join-Path $LogDir 'prom_stderr.log')
} catch {
  Write-Host "Failed to start Prometheus. Verify -PrometheusExe path." -ForegroundColor Red
  exit 2
}

# Wait for Prometheus
if (-not (Wait-For-Ready -Url ("{0}/-/ready" -f $promUrl) -Tries 25 -DelayMs 1000)) {
  # Fallback: single-shot check before aborting (handles races where readiness flips just after the loop)
  try {
    $code = (Invoke-WebRequest -Uri ("{0}/-/ready" -f $promUrl) -UseBasicParsing -TimeoutSec 3).StatusCode
  } catch { $code = 0 }
  if ($code -ne 200) {
    Write-Host "Prometheus not ready; see log files under $LogDir" -ForegroundColor Red
    exit 3
  } else {
    Write-Host "Prometheus became ready on fallback check." -ForegroundColor Yellow
  }
}

# Optional: InfluxDB start (best-effort)
function Resolve-Influx {
  $candidates = @(
    'C:\\Program Files\\InfluxData\\influxdb2\\influxd.exe',
    'C:\\Program Files\\InfluxData\\influxdb\\influxd.exe',
    'C:\\Influx\\influxd.exe'
  )
  foreach ($p in $candidates) { if (Test-Path $p) { return $p } }
  return $null
}

$influxExeToUse = $null
if ($StartInflux) {
  Ensure-Dir -Path $InfluxDataDir
  if ($InfluxExe -and -not (Test-Path $InfluxExe)) {
    Write-Host ("Provided InfluxExe not found: {0} (will try auto-detect)" -f $InfluxExe) -ForegroundColor DarkYellow
  }
  $influxExeToUse = if ($InfluxExe -and (Test-Path $InfluxExe)) { $InfluxExe } else { Resolve-Influx }
  if (-not $influxExeToUse) {
    Write-Host "InfluxDB not found (set -InfluxExe or install InfluxDB). Skipping." -ForegroundColor Yellow
  } else {
    Write-Host ("Starting InfluxDB on :{0}" -f $InfluxPort) -ForegroundColor Green
    $iOut = Join-Path $LogDir 'influx_stdout.log'
    $iErr = Join-Path $LogDir 'influx_stderr.log'
    # Bind to requested address; for InfluxDB 2.x this env var controls --http-bind-address
    $env:INFLUXD_HTTP_BIND_ADDRESS = "127.0.0.1:$InfluxPort"
    try {
      Start-Process -FilePath $influxExeToUse -WorkingDirectory $InfluxDataDir -RedirectStandardOutput $iOut -RedirectStandardError $iErr -WindowStyle Minimized
      if (-not (Wait-For-Ready -Url ("http://127.0.0.1:{0}/health" -f $InfluxPort) -Tries 20 -DelayMs 1000)) {
        Write-Host "InfluxDB not healthy yet; see log files under $LogDir" -ForegroundColor Yellow
      }
    } catch {
      Write-Host "Failed to start InfluxDB. Provide -InfluxExe path or install InfluxDB." -ForegroundColor DarkYellow
    }
  }
}

# Resolve Grafana
function Resolve-Grafana {
  $bases = @('C:\Program Files\GrafanaLabs\grafana','C:\Grafana','C:\Program Files','C:\Program Files (x86)')
  foreach ($b in $bases) {
    if (-not (Test-Path $b)) { continue }
    $dirs = Get-ChildItem -Path $b -Directory -ErrorAction SilentlyContinue | Where-Object { $_.Name -like 'grafana*' }
    foreach ($d in ($dirs | Sort-Object LastWriteTime -Descending)) {
      $exe = Join-Path (Join-Path $d.FullName 'bin') 'grafana-server.exe'
      if (Test-Path $exe) { return [pscustomobject]@{ Home=(Split-Path (Split-Path $exe -Parent) -Parent); Exe=$exe } }
    }
  }
  return $null
}
$graf = Resolve-Grafana
if (-not $graf) { Write-Host 'Grafana not found. Install Grafana or adjust Resolve-Grafana.' -ForegroundColor Red; exit 4 }

# Provisioning: write clean, absolute-path config under GrafanaDataRoot
$provRoot = Join-Path $GrafanaDataRoot 'provisioning_baseline'
$dsDir = Join-Path $provRoot 'datasources'
$dbDir = Join-Path $provRoot 'dashboards'
$dashboardsSrc = Join-Path $Root 'grafana/dashboards/generated'
$dashboardsLegacy = Join-Path $Root 'grafana/dashboards'
$dbFilteredDir = Join-Path $provRoot 'dashboards_src_filtered'
Ensure-Dir -Path $dsDir
Ensure-Dir -Path $dbDir
Ensure-Dir -Path $dbFilteredDir
# Clean filtered dir to avoid stale duplicates from previous runs
try { Get-ChildItem -Path $dbFilteredDir -Filter *.json -File -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue } catch {}
# Copy dashboards excluding manifest.json into filtered dir (generated first, then legacy)
try {
  $excludeNames = @('manifest.json')
  function Copy-IfNotExcluded {
    param([System.IO.FileInfo]$File)
    if ($excludeNames -contains $File.Name) { return }
    try {
      $raw = Get-Content -LiteralPath $File.FullName -Raw -ErrorAction Stop
      if ($raw -match '"uid"\s*:\s*"g6specauto"') {
        Write-Host ("Skipping dashboard with duplicate UID g6specauto: {0}" -f $File.Name) -ForegroundColor DarkYellow
        return
      }
    } catch {}
    Copy-Item -LiteralPath $File.FullName -Destination (Join-Path $dbFilteredDir $File.Name) -Force
  }

  Get-ChildItem -Path $dashboardsSrc -Filter *.json -File -ErrorAction Stop | ForEach-Object { Copy-IfNotExcluded -File $_ }
  # Also include legacy dashboards that are not in generated (avoid overwriting if same name exists)
  $generatedNames = @{}
  Get-ChildItem -Path $dashboardsSrc -Filter *.json -File -ErrorAction SilentlyContinue | ForEach-Object { $generatedNames[$_.Name] = $true }
  Get-ChildItem -Path $dashboardsLegacy -Filter *.json -File -ErrorAction SilentlyContinue |
    Where-Object { -not $generatedNames.ContainsKey($_.Name) } |
    ForEach-Object { Copy-IfNotExcluded -File $_ }
} catch { Write-Host "Warning: Could not stage dashboards (provisioning may be incomplete)." -ForegroundColor DarkYellow }
Set-Content -Path (Join-Path $dsDir 'prometheus.yml') -Encoding UTF8 -Value (@"
apiVersion: 1

datasources:
  - name: Prometheus
    type: prometheus
    access: proxy
    uid: PROM
    url: '$promUrl'
    isDefault: true
    editable: true
  - name: Infinity
    type: yesoreyeram-infinity-datasource
    access: proxy
    uid: INFINITY
    jsonData:
      allowedHosts:
        - 'http://127.0.0.1:9500'
        - 'http://localhost:9500'
    editable: true
"@)
Set-Content -Path (Join-Path $dbDir 'dashboards.yml') -Encoding UTF8 -Value (@"
apiVersion: 1

providers:
  - name: G6
    type: file
    disableDeletion: true
    editable: true
    options:
      path: '$(($dbFilteredDir -replace "\\","/"))'
"@)

# Grafana env & start
$dataDir = if ($env:G6_GRAFANA_DATA_DIR -and $env:G6_GRAFANA_DATA_DIR.Trim().Length -gt 0) { $env:G6_GRAFANA_DATA_DIR } else { Join-Path $GrafanaDataRoot 'data' }
$logsDir = Join-Path $GrafanaDataRoot 'log'
$pluginsDir = Join-Path $GrafanaDataRoot 'plugins'
Ensure-Dir -Path $dataDir
Ensure-Dir -Path $logsDir
Ensure-Dir -Path $pluginsDir
[Environment]::SetEnvironmentVariable('GF_SERVER_HTTP_PORT',"$GrafanaPort")
[Environment]::SetEnvironmentVariable('GF_SERVER_HTTP_ADDR','127.0.0.1')
[Environment]::SetEnvironmentVariable('GF_PATHS_HOME',$graf.Home)
[Environment]::SetEnvironmentVariable('GF_PATHS_DATA', $dataDir)
[Environment]::SetEnvironmentVariable('GF_PATHS_LOGS', $logsDir)
[Environment]::SetEnvironmentVariable('GF_PATHS_PLUGINS', $pluginsDir)
[Environment]::SetEnvironmentVariable('GF_PATHS_PROVISIONING', $provRoot)
#[Optional] Auto-install required plugins (Infinity) if not already installed
[Environment]::SetEnvironmentVariable('GF_INSTALL_PLUGINS','yesoreyeram-infinity-datasource,volkovlabs-form-panel')
if ($GrafanaDisablePassword) {
  # Anonymous Admin with login form hidden; basic auth off for clarity
  [Environment]::SetEnvironmentVariable('GF_AUTH_ANONYMOUS_ENABLED','true')
  [Environment]::SetEnvironmentVariable('GF_AUTH_ANONYMOUS_ORG_ROLE','Admin')
  [Environment]::SetEnvironmentVariable('GF_AUTH_DISABLE_LOGIN_FORM','true')
  [Environment]::SetEnvironmentVariable('GF_AUTH_BASIC_ENABLED','false')
  [Environment]::SetEnvironmentVariable('GF_USERS_ALLOW_SIGN_UP','false')
  [Environment]::SetEnvironmentVariable('GF_SECURITY_ALLOW_EMBEDDING','true')
  [Environment]::SetEnvironmentVariable('GF_SECURITY_DISABLE_GRAVATAR','true')
} elseif ($GrafanaAllowAnonymous) {
  [Environment]::SetEnvironmentVariable('GF_AUTH_ANONYMOUS_ENABLED','true')
  # Allow customizing dashboards via UI: use Editor role when -GrafanaAnonymousEditor is specified; otherwise Viewer
  $anonRole = if ($GrafanaAnonymousEditor) { 'Editor' } else { 'Viewer' }
  [Environment]::SetEnvironmentVariable('GF_AUTH_ANONYMOUS_ORG_ROLE', $anonRole)
  [Environment]::SetEnvironmentVariable('GF_SECURITY_ALLOW_EMBEDDING','true')
}

Write-Host ("Starting Grafana on :{0}" -f $GrafanaPort) -ForegroundColor Green
$gOut = Join-Path $LogDir 'grafana_stdout.log'
$gErr = Join-Path $LogDir 'grafana_stderr.log'
$argsStr = "--homepath `"$($graf.Home)`""
Start-Process -FilePath $graf.Exe -ArgumentList $argsStr -WorkingDirectory $graf.Home -RedirectStandardOutput $gOut -RedirectStandardError $gErr -WindowStyle Minimized

# Wait for Grafana
$grafUrl = "http://127.0.0.1:$GrafanaPort/api/health"
if (-not (Wait-For-Ready -Url $grafUrl -Tries 30 -DelayMs 1000)) {
  Write-Host "Grafana not healthy; see log files under $LogDir" -ForegroundColor Yellow
}

Write-Host ''
Write-Host '--- Baseline Summary ---' -ForegroundColor Cyan
Write-Host ("Prometheus: {0} status=OK" -f $promUrl)
Write-Host ("Grafana:    http://127.0.0.1:{0}" -f $GrafanaPort)
Write-Host ("Metrics:    http://127.0.0.1:{0}/metrics" -f $MetricsPort)
if ($StartOverlayExporter) { Write-Host ("Overlays:   http://127.0.0.1:{0}/metrics" -f $OverlayPort) }
Write-Host ("Web API:   http://127.0.0.1:{0}" -f $WebPort)
if ($StartInflux) {
  if ($influxExeToUse) {
    Write-Host ("InfluxDB:   http://127.0.0.1:{0}" -f $InfluxPort)
  } else {
    Write-Host "InfluxDB:   (skipped)"
  }
}
Write-Host '------------------------' -ForegroundColor Cyan

if ($OpenBrowser) {
  try {
    $base = "http://127.0.0.1:$GrafanaPort"
    $uids = @('g6-analytics-infinity-v4','g6-analytics-infinity-v3','g6-analytics-infinity-v2','g6-analytics-infinity')
    $chosen = $null
    foreach ($u in $uids) {
      try {
        $r = Invoke-WebRequest -UseBasicParsing -Uri ("$base/api/dashboards/uid/$u") -TimeoutSec 3
        if ($r.StatusCode -eq 200) { $chosen = $u; break }
      } catch {}
    }
    $urlToOpen = if ($chosen) { "$base/d/$chosen/$chosen" } else { $base }
    try { Start-Process msedge.exe ("-new-window {0}" -f $urlToOpen) } catch { try { Start-Process $urlToOpen } catch {} }
  } catch {
    try { Start-Process ("http://127.0.0.1:{0}" -f $GrafanaPort) } catch {}
  }
}

exit 0
