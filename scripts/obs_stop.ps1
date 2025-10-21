param(
  [int]$PrometheusPort = 9091,
  [int]$GrafanaPort = 3002,
  [int]$MetricsPort = 9108,
  [int]$OverlayPort = 9109,
  [int]$InfluxPort = 8087,
  [switch]$Aggressive
)

function Get-PidsByPort {
  param([int]$Port)
  $pids = @()
  try {
    $conns = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction Stop
    $pids += ($conns | Select-Object -ExpandProperty OwningProcess | Where-Object { $_ })
  } catch {
    # Fallback to netstat parsing if not elevated or cmdlet unavailable
    try {
      $lines = & netstat -ano | Select-String ":$Port "
      foreach ($ln in $lines) {
        $t = ($ln.ToString() -replace '\s+', ' ').Trim().Split(' ')
        if ($t.Length -ge 5 -and $t[-2] -match 'LISTENING') {
          $pid = [int]$t[-1]
          if ($pid -and ($pids -notcontains $pid)) { $pids += $pid }
        }
      }
    } catch {}
  }
  return ($pids | Sort-Object -Unique)
}

function Stop-Pids {
  param([int[]]$Pids,[string]$Label)
  foreach ($procId in ($Pids | Sort-Object -Unique)) {
    try {
      if (Get-Process -Id $procId -ErrorAction SilentlyContinue) {
        Write-Host ("Stopping {0} PID {1}" -f $Label,$procId) -ForegroundColor DarkGray
        Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
      }
    } catch {}
  }
}

function Stop-ByPort {
  param([int]$Port,[string]$Label)
  $pids = Get-PidsByPort -Port $Port
  if ($pids.Count -gt 0) { Stop-Pids -Pids $pids -Label $Label }
}

function Stop-PythonByScript {
  param([string]$ScriptName)
  try {
    $procs = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
      $_.Name -match 'python' -and $_.CommandLine -match [Regex]::Escape($ScriptName)
    }
    foreach ($p in $procs) {
      try {
        Write-Host ("Stopping python({0}) PID {1}" -f $ScriptName,$p.ProcessId) -ForegroundColor DarkGray
        Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
      } catch {}
    }
  } catch {}
}

Write-Host '=== G6 Baseline Observability Stop ===' -ForegroundColor Cyan
Stop-ByPort -Port $GrafanaPort -Label 'grafana'
Stop-ByPort -Port $PrometheusPort -Label 'prometheus'
Stop-ByPort -Port $InfluxPort -Label 'influxdb'
Stop-ByPort -Port $MetricsPort -Label 'metrics'
Stop-ByPort -Port $OverlayPort -Label 'overlay'

# Extra guard: specifically target our python helper scripts
Stop-PythonByScript -ScriptName 'scripts/start_metrics_server.py'
Stop-PythonByScript -ScriptName 'scripts/overlay_exporter.py'

if ($Aggressive) {
  Write-Host 'Aggressive mode: attempting name-based termination for grafana-server, prometheus, influxd' -ForegroundColor Yellow
  foreach ($name in @('grafana-server','prometheus','influxd')) {
    try { Get-Process -Name $name -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue } catch {}
  }
}

# Final status summary of monitored ports
foreach ($p in @(
  @{ Port=$GrafanaPort; Name='grafana' },
  @{ Port=$PrometheusPort; Name='prometheus' },
  @{ Port=$InfluxPort; Name='influxdb' },
  @{ Port=$MetricsPort; Name='metrics' },
  @{ Port=$OverlayPort; Name='overlay' }
)) {
  $rem = Get-PidsByPort -Port $p.Port
  if ($rem.Count -gt 0) {
    Write-Host ("WARNING: {0} still listening on :{1} (PIDs: {2})" -f $p.Name,$p.Port,($rem -join ',')) -ForegroundColor DarkYellow
  } else {
    Write-Host ("OK: {0} not listening on :{1}" -f $p.Name,$p.Port) -ForegroundColor Green
  }
}

Write-Host 'Stop sequence completed.' -ForegroundColor Green

exit 0
