param(
  [switch]$StartPrometheus = $true,
  [switch]$StartGrafana = $true,
  [switch]$StartInflux = $true,
  [string]$PrometheusConfig = 'C:\Users\ASUS\Documents\G6\qq\g6_reorganized\prometheus.yml',
  [int[]]$PrometheusPorts = @(9090..9100),
  [int[]]$GrafanaPorts = @(3000..3010),
  [int[]]$InfluxPorts = @(8086..8096),
  [string]$GrafanaDataRoot = 'C:\GrafanaData',
  [string]$InfluxDataDir = 'C:\InfluxDB\data',
  [switch]$OpenBrowser
)

$ErrorActionPreference = 'Continue'

function Test-PortListening {
  param([int]$Port, [int]$TimeoutSeconds = 3, [int]$InitialDelayMs = 0)
  if ($InitialDelayMs -gt 0) { Start-Sleep -Milliseconds $InitialDelayMs }
  for ($i=0; $i -lt ($TimeoutSeconds*2); $i++) {
    try { if (Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue) { return $true } } catch {}
    Start-Sleep -Milliseconds 500
  }
  return $false
}

# Fast non-waiting port check used during initial discovery to avoid long pauses
function Test-PortBoundQuick { param([int]$Port) try { return $null -ne (Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue) } catch { return $false } }

function Invoke-HttpHealth {
  param([string]$Url, [int]$TimeoutSeconds = 3, [switch]$Insecure)
  try {
    if ($Url -like 'https*' -and $Insecure) {
      $h = New-Object System.Net.Http.HttpClientHandler
      $h.ServerCertificateCustomValidationCallback = { param($sender,$cert,$chain,$errors) return $true }
      $c = [System.Net.Http.HttpClient]::new($h)
    } else { $c = [System.Net.Http.HttpClient]::new() }
    $c.Timeout = [TimeSpan]::FromSeconds($TimeoutSeconds)
    $r = $c.GetAsync($Url).GetAwaiter().GetResult()
    return [pscustomobject]@{ Code=[int]$r.StatusCode; Ok=$r.IsSuccessStatusCode }
  } catch { return [pscustomobject]@{ Code=-1; Ok=$false } }
}

function Find-FreePort { param([int[]]$Range) foreach ($p in $Range) { try { if (-not (Get-NetTCPConnection -LocalPort $p -ErrorAction SilentlyContinue)) { return $p } } catch {} } return $null }

# Simple TCP reachability check
function Test-TcpConnect {
  param([string]$Target='127.0.0.1',[int]$Port,[int]$TimeoutMs=1200)
  try {
    $client = New-Object System.Net.Sockets.TcpClient
    $iar = $client.BeginConnect($Target, $Port, $null, $null)
    if (-not $iar.AsyncWaitHandle.WaitOne($TimeoutMs, $false)) { $client.Close(); return $false }
    $client.EndConnect($iar); $client.Close(); return $true
  } catch { return $false }
}

# Helpers to inspect port owners and match expected processes
function Get-PortOwners {
  param([int]$Port)
  try {
    $pids = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess
    if (-not $pids) { return @() }
    $out = @()
    foreach ($pid in ($pids | Sort-Object -Unique)) {
      try { $proc = Get-Process -Id $pid -ErrorAction SilentlyContinue; if ($proc) { $out += [pscustomobject]@{ Pid=$pid; Name=$proc.ProcessName } } } catch {}
    }
    return $out
  } catch { return @() }
}

function PortOwnedByExpected {
  param([int]$Port,[string[]]$ExpectedNames)
  $owners = Get-PortOwners -Port $Port
  if (-not $owners -or $owners.Count -eq 0) { return $false }
  foreach ($o in $owners) {
    foreach ($exp in $ExpectedNames) {
      if ($o.Name -and ($o.Name.ToLower() -eq $exp.ToLower())) { return $true }
    }
  }
  return $false
}

# Returns first Grafana port in the provided range that is owned by grafana-server
function Get-GrafanaBoundPort {
  param([int[]]$Range)
  foreach ($p in $Range) {
    if (Test-PortBoundQuick -Port $p) {
      if (PortOwnedByExpected -Port $p -ExpectedNames @('grafana-server')) { return $p }
    }
  }
  return $null
}

function Next-FreePort {
  param([int[]]$Range, [int]$After = -1)
  foreach ($p in $Range) {
    if ($p -le $After) { continue }
    try { if (-not (Get-NetTCPConnection -LocalPort $p -ErrorAction SilentlyContinue)) { return $p } } catch {}
  }
  return $null
}

function Resolve-Prometheus {
  $cands = @(
    'C:\Prometheus\prometheus.exe',
    'C:\Prometheus\prometheus-3.5.0.windows-amd64\prometheus.exe',
    'C:\Program Files\Prometheus\prometheus.exe',
    'C:\ProgramData\Prometheus\prometheus.exe'
  )
  foreach ($c in $cands) { if (Test-Path $c) { return $c } }
  try {
    $base = 'C:\Prometheus'
    if (Test-Path $base) {
      $d = Get-ChildItem -Path $base -Directory -ErrorAction SilentlyContinue | Where-Object { $_.Name -like 'prometheus*' } | Sort-Object LastWriteTime -Descending | Select-Object -First 1
      if ($d) { $m = Join-Path $d.FullName 'prometheus.exe'; if (Test-Path $m) { return $m } }
    }
  } catch {}
  return $null
}

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

function Resolve-Influxd {
  if ($env:G6_INFLUXD_EXE -and (Test-Path $env:G6_INFLUXD_EXE)) { return $env:G6_INFLUXD_EXE }
  $cands = @(
    'C:\Program Files\InfluxData\influxdb2\influxd.exe',
    'C:\Program Files\InfluxData\influxdb\influxd.exe',
    'C:\influxdata\influxdb2\influxd.exe'
  )
  foreach ($c in $cands) { if (Test-Path $c) { return $c } }
  try {
    $base = 'C:\influxdata'
    if (Test-Path $base) {
      $d = Get-ChildItem -Path $base -Directory -ErrorAction SilentlyContinue | Where-Object { $_.Name -like 'influxdb*' } | Sort-Object LastWriteTime -Descending | Select-Object -First 1
      if ($d) { $m = Join-Path $d.FullName 'influxd.exe'; if (Test-Path $m) { return $m } }
    }
  } catch {}
  return $null
}

function Probe-Prometheus { param([int]$Port, [int]$WaitSeconds = 2)
  # Try HTTP first
  $h = Invoke-HttpHealth -Url ("http://127.0.0.1:{0}/-/ready" -f $Port) -TimeoutSeconds 3
  if ($h.Ok -and $h.Code -eq 200) { return $true }
  $b = Invoke-HttpHealth -Url ("http://127.0.0.1:{0}/api/v1/status/buildinfo" -f $Port) -TimeoutSeconds 3
  if ($b.Ok -and $b.Code -eq 200) { return $true }
  # TCP-level fallback
  if (Test-TcpConnect -Target '127.0.0.1' -Port $Port -TimeoutMs ([Math]::Max(800, $WaitSeconds*500))) { return $true }
  return $false
}

function Probe-Grafana { param([int]$Port, [int]$WaitSeconds = 5)
  # HTTP
  $h = Invoke-HttpHealth -Url ("http://127.0.0.1:{0}/api/health" -f $Port)
  if ($h.Ok -and $h.Code -eq 200) { return $true }
  # HTTPS fallback (self-signed tolerated)
  $s = Invoke-HttpHealth -Url ("https://127.0.0.1:{0}/api/health" -f $Port) -Insecure
  if ($s.Ok -and $s.Code -eq 200) { return $true }
  # TCP-level fallback
  if (Test-TcpConnect -Target '127.0.0.1' -Port $Port -TimeoutMs ([Math]::Max(800, $WaitSeconds*500))) { return $true }
  return $false
}

function Probe-Influx { param([int]$Port, [int]$WaitSeconds = 5)
  foreach ($u in @("http://127.0.0.1:{0}/health","http://127.0.0.1:{0}/ping","https://127.0.0.1:{0}/health","https://127.0.0.1:{0}/ping")) {
    $url = [string]::Format($u,$Port)
    $insec = $url.StartsWith('https')
    $r = Invoke-HttpHealth -Url $url -Insecure:([bool]$insec)
    if ($r.Ok -and ($r.Code -in 200,204)) { return $true }
    if ($r.Code -in 401,403) { return $true }
  }
  # TCP-level fallback
  if (Test-TcpConnect -Target '127.0.0.1' -Port $Port -TimeoutMs ([Math]::Max(800, $WaitSeconds*500))) { return $true }
  return $false
}

function Ensure-Dir { param([string]$Path) if (-not (Test-Path $Path)) { New-Item -ItemType Directory -Force -Path $Path | Out-Null } }

Write-Host '=== Auto-Resolve Observability Stack (Prometheus / Grafana / Influx) ===' -ForegroundColor Cyan

# Discovery: check if already up (only treat as up if owned by the expected process)
$promPort = $null; foreach ($p in $PrometheusPorts) { if (Test-PortBoundQuick -Port $p) { if (PortOwnedByExpected -Port $p -ExpectedNames @('prometheus')) { $promPort = $p; break } else { Write-Host ("Port {0} bound but not by Prometheus; will start on a free port." -f $p) -ForegroundColor DarkYellow } } }
$influxPort = $null; foreach ($p in $InfluxPorts) { if (Test-PortBoundQuick -Port $p) { if (PortOwnedByExpected -Port $p -ExpectedNames @('influxd')) { $influxPort = $p; break } else { Write-Host ("Port {0} bound but not by influxd; will start on a free port." -f $p) -ForegroundColor DarkYellow } } }
$grafPort = $null; foreach ($p in $GrafanaPorts) { if (Test-PortBoundQuick -Port $p) { if (PortOwnedByExpected -Port $p -ExpectedNames @('grafana-server')) { $grafPort = $p; break } else { Write-Host ("Port {0} bound but not by grafana-server; will start on a free port." -f $p) -ForegroundColor DarkYellow } } }

# Launch all three quickly (non-blocking) if not already bound
$startedPromPort = $null
# Resolve executables upfront
$promExe = $null
if ($StartPrometheus) { $promExe = Resolve-Prometheus }
if (-not $promPort -and $StartPrometheus) {
  if ($promExe) {
    $startedPromPort = Find-FreePort -Range $PrometheusPorts
    if ($startedPromPort) {
      Write-Host ("Starting Prometheus on :{0}" -f $startedPromPort) -ForegroundColor Green
      $args = @("--config.file=$PrometheusConfig","--web.listen-address=127.0.0.1:$startedPromPort")
      Start-Process -FilePath $promExe -ArgumentList $args -WorkingDirectory (Split-Path $promExe -Parent)
    } else { Write-Host 'No free Prometheus port found in range.' -ForegroundColor Yellow }
  } else { Write-Host 'Prometheus executable not found. Skipping start.' -ForegroundColor DarkYellow }
}

$startedInfluxPort = $null
# Resolve influxd upfront
$influxd = $null
if ($StartInflux) { $influxd = Resolve-Influxd }
if (-not $influxPort -and $StartInflux) {
  if ($influxd) {
    $startedInfluxPort = Find-FreePort -Range $InfluxPorts
    if ($startedInfluxPort) {
      Ensure-Dir -Path $InfluxDataDir
      $args = @("--http-bind-address=127.0.0.1:$startedInfluxPort","--bolt-path=$InfluxDataDir\influxd.bolt","--engine-path=$InfluxDataDir\engine")
      Write-Host ("Starting InfluxDB on :{0}" -f $startedInfluxPort) -ForegroundColor Green
      Start-Process -FilePath $influxd -ArgumentList $args -WindowStyle Minimized
    } else { Write-Host 'No free Influx port found in range.' -ForegroundColor Yellow }
  } else { Write-Host 'influxd.exe not found. Skipping start.' -ForegroundColor DarkYellow }
}

$startedGrafPort = $null
# Resolve grafana upfront
$graf = $null
if ($StartGrafana) { $graf = Resolve-Grafana }
if (-not $grafPort -and $StartGrafana) {
  if ($graf) {
    $startedGrafPort = Find-FreePort -Range $GrafanaPorts
    if ($startedGrafPort) {
      Ensure-Dir -Path (Join-Path $GrafanaDataRoot 'data')
      Ensure-Dir -Path (Join-Path $GrafanaDataRoot 'log')
      Ensure-Dir -Path (Join-Path $GrafanaDataRoot 'plugins')
      [Environment]::SetEnvironmentVariable('GF_SERVER_HTTP_PORT',"$startedGrafPort")
      [Environment]::SetEnvironmentVariable('GF_SERVER_HTTP_ADDR','0.0.0.0')
      [Environment]::SetEnvironmentVariable('GF_PATHS_HOME',$graf.Home)
      [Environment]::SetEnvironmentVariable('GF_PATHS_DATA', (Join-Path $GrafanaDataRoot 'data'))
      [Environment]::SetEnvironmentVariable('GF_PATHS_LOGS', (Join-Path $GrafanaDataRoot 'log'))
      [Environment]::SetEnvironmentVariable('GF_PATHS_PLUGINS', (Join-Path $GrafanaDataRoot 'plugins'))
      [Environment]::SetEnvironmentVariable('GF_PATHS_PROVISIONING', (Join-Path (Split-Path $PSScriptRoot -Parent) 'grafana\provisioning'))
      Write-Host ("Starting Grafana on :{0}" -f $startedGrafPort) -ForegroundColor Green
      Start-Process -FilePath $graf.Exe -WorkingDirectory $graf.Home -WindowStyle Normal
    } else { Write-Host 'No free Grafana port found in range.' -ForegroundColor Yellow }
  } else { Write-Host 'Grafana not found. Skipping start.' -ForegroundColor DarkYellow }
}

# Choose ports to probe (existing or started)
if (-not $promPort) { $promPort = $startedPromPort }
if (-not $influxPort) { $influxPort = $startedInfluxPort }
if (-not $grafPort) { $grafPort = $startedGrafPort }

# Wait before first health check so services can initialize
Write-Host 'Waiting 10 seconds before first health check...' -ForegroundColor DarkGray
Start-Sleep -Seconds 10

# First health checks in order: Prometheus -> Influx -> Grafana
$promHealthy = $false; if ($promPort) { Write-Host ("Checking Prometheus @ http://127.0.0.1:{0}" -f $promPort) -ForegroundColor Gray; $promHealthy = Probe-Prometheus -Port $promPort -WaitSeconds 8 }
$influxHealthy = $false; if ($influxPort) { Write-Host ("Checking InfluxDB  @ http://127.0.0.1:{0}" -f $influxPort) -ForegroundColor Gray; $influxHealthy = Probe-Influx -Port $influxPort -WaitSeconds 8 }
$grafHealthy = $false; if ($grafPort) { Write-Host ("Checking Grafana   @ http://127.0.0.1:{0}" -f $grafPort) -ForegroundColor Gray; $grafHealthy = Probe-Grafana -Port $grafPort -WaitSeconds 12 }

$promUrl = if ($promPort) { "http://127.0.0.1:$promPort" } else { $null }
$influxUrl = if ($influxPort) { "http://127.0.0.1:$influxPort" } else { $null }
$grafUrl = if ($grafPort) { "http://127.0.0.1:$grafPort" } else { $null }

Write-Host ''
Write-Host '--- Initial Health (instant) ---' -ForegroundColor Cyan
Write-Host ("Prometheus: {0}" -f ($(if ($promUrl) {"$promUrl status=" + ($(if ($promHealthy){'OK'}else{'DOWN'}))} else {'not started'})))
Write-Host ("InfluxDB:   {0}" -f ($(if ($influxUrl){"$influxUrl status=" + ($(if ($influxHealthy){'OK'}else{'DOWN'}))} else {'not started'})))
Write-Host ("Grafana:    {0}" -f ($(if ($grafUrl)  {"$grafUrl status=" + ($(if ($grafHealthy){'OK'}else{'DOWN'}))} else {'not started'})))

# Iteratively move to next free port for any service still failing, waiting 10s between attempts
function Start-PrometheusOnPort { param([string]$Exe,[int]$Port)
  $args = @("--config.file=$PrometheusConfig","--web.listen-address=127.0.0.1:$Port")
  Start-Process -FilePath $Exe -ArgumentList $args -WorkingDirectory (Split-Path $Exe -Parent)
}
function Start-InfluxOnPort { param([string]$Exe,[int]$Port)
  Ensure-Dir -Path $InfluxDataDir
  $args = @("--http-bind-address=127.0.0.1:$Port","--bolt-path=$InfluxDataDir\influxd.bolt","--engine-path=$InfluxDataDir\engine")
  Start-Process -FilePath $Exe -ArgumentList $args -WindowStyle Minimized
}
function Start-GrafanaOnPort { param($Graf,[int]$Port)
  Ensure-Dir -Path (Join-Path $GrafanaDataRoot 'data')
  Ensure-Dir -Path (Join-Path $GrafanaDataRoot 'log')
  Ensure-Dir -Path (Join-Path $GrafanaDataRoot 'plugins')
  [Environment]::SetEnvironmentVariable('GF_SERVER_HTTP_PORT',"$Port")
  [Environment]::SetEnvironmentVariable('GF_SERVER_HTTP_ADDR','0.0.0.0')
  [Environment]::SetEnvironmentVariable('GF_PATHS_HOME',$Graf.Home)
  [Environment]::SetEnvironmentVariable('GF_PATHS_DATA', (Join-Path $GrafanaDataRoot 'data'))
  [Environment]::SetEnvironmentVariable('GF_PATHS_LOGS', (Join-Path $GrafanaDataRoot 'log'))
  [Environment]::SetEnvironmentVariable('GF_PATHS_PLUGINS', (Join-Path $GrafanaDataRoot 'plugins'))
  [Environment]::SetEnvironmentVariable('GF_PATHS_PROVISIONING', (Join-Path (Split-Path $PSScriptRoot -Parent) 'grafana\provisioning'))
  Start-Process -FilePath $Graf.Exe -WorkingDirectory $Graf.Home -WindowStyle Normal
}

if (-not ($promHealthy -and $influxHealthy -and $grafHealthy)) {
  # Attempt until healthy or no more free ports in range
  while ($true) {
    $madeProgress = $false

    if (-not $promHealthy -and $StartPrometheus -and $promExe) {
      $next = Next-FreePort -Range $PrometheusPorts -After ([int]($(if ($promPort){$promPort}else{-1})))
      if ($next) {
        Write-Host ("Prometheus still DOWN; trying next port :{0}" -f $next) -ForegroundColor Yellow
        Start-PrometheusOnPort -Exe $promExe -Port $next
        $promPort = $next
        $madeProgress = $true
      }
    }

    if (-not $influxHealthy -and $StartInflux -and $influxd) {
      $next = Next-FreePort -Range $InfluxPorts -After ([int]($(if ($influxPort){$influxPort}else{-1})))
      if ($next) {
        Write-Host ("InfluxDB still DOWN; trying next port :{0}" -f $next) -ForegroundColor Yellow
        Start-InfluxOnPort -Exe $influxd -Port $next
        $influxPort = $next
        $madeProgress = $true
      }
    }

    if (-not $grafHealthy -and $StartGrafana -and $graf) {
      $next = Next-FreePort -Range $GrafanaPorts -After ([int]($(if ($grafPort){$grafPort}else{-1})))
      if ($next) {
        Write-Host ("Grafana still DOWN; trying next port :{0}" -f $next) -ForegroundColor Yellow
        Start-GrafanaOnPort -Graf $graf -Port $next
        $grafPort = $next
        $madeProgress = $true
      }
    }

    if (-not $madeProgress) { break }

    Write-Host 'Waiting 10 seconds before re-checking health...' -ForegroundColor DarkGray
    Start-Sleep -Seconds 10

    # Re-check health after moving ports
    if (-not $promHealthy -and $promPort) { $promHealthy = Probe-Prometheus -Port $promPort -WaitSeconds 8 }
    if (-not $influxHealthy -and $influxPort) { $influxHealthy = Probe-Influx -Port $influxPort -WaitSeconds 8 }
    if (-not $grafHealthy -and $grafPort) { $grafHealthy = Probe-Grafana -Port $grafPort -WaitSeconds 12 }

    if ($promHealthy -and $influxHealthy -and $grafHealthy) { break }
  }
}

# Recompute URLs in case ports changed during iterative retries
$promUrl = if ($promPort) { "http://127.0.0.1:$promPort" } else { $null }
$influxUrl = if ($influxPort) { "http://127.0.0.1:$influxPort" } else { $null }
$grafUrl = if ($grafPort) { "http://127.0.0.1:$grafPort" } else { $null }

# Diagnostics: if multiple grafana-server processes detected, warn and show bound ports
try {
  $gprocs = Get-Process -Name grafana-server -ErrorAction SilentlyContinue
  if ($gprocs -and $gprocs.Count -gt 1) {
    $ports = @()
    foreach ($p in $GrafanaPorts) { if (Test-PortBoundQuick -Port $p) { if (PortOwnedByExpected -Port $p -ExpectedNames @('grafana-server')) { $ports += $p } } }
    Write-Host ("WARNING: Multiple grafana-server processes detected (PIDs: {0}) Ports: {1}. Consider stopping the Windows Grafana service to avoid duplicates." -f (($gprocs | Select-Object -ExpandProperty Id) -join ','), (($ports | Sort-Object -Unique) -join ',')) -ForegroundColor Yellow
  }
} catch {}

if ($influxHealthy -and $influxUrl) { [Environment]::SetEnvironmentVariable('G6_INFLUX_URL', $influxUrl) }

Write-Host ''
Write-Host '--- Final Summary ---' -ForegroundColor Cyan
Write-Host ("Prometheus: {0}" -f ($(if ($promUrl) {"$promUrl status=" + ($(if ($promHealthy){'OK'}else{'DOWN'}))} else {'not started'})))
Write-Host ("InfluxDB:   {0}" -f ($(if ($influxUrl){"$influxUrl status=" + ($(if ($influxHealthy){'OK'}else{'DOWN'}))} else {'not started'})))
Write-Host ("Grafana:    {0}" -f ($(if ($grafUrl)  {"$grafUrl status=" + ($(if ($grafHealthy){'OK'}else{'DOWN'}))} else {'not started'})))
Write-Host '---------------------' -ForegroundColor Cyan

if ($OpenBrowser -and $grafUrl -and $grafHealthy) { try { Start-Process msedge.exe ("-new-window {0}" -f $grafUrl) } catch { try { Start-Process $grafUrl } catch {} } }

exit 0
