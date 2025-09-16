<#!
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
  # Grafana
  [string]$GrafanaHome = 'C:\Program Files\GrafanaLabs\grafana\grafana-12.1.1',
  [switch]$ForegroundGrafana,
  [switch]$AltGrafanaPort,
  # InfluxDB (optional)
  [switch]$StartInflux,
  [switch]$SetupInflux,
  [string]$InfluxdExe = 'C:\InfluxDB\influxd.exe',
  [string]$InfluxCliExe = 'C:\InfluxDB\influx.exe',
  [string]$InfluxDataDir = 'C:\InfluxDB\data',
  [string]$InfluxConfigName = 'g6-config',
  [string]$InfluxOrg = 'g6',
  [string]$InfluxBucket = 'g6_metrics',
  [int]$InfluxRetentionHours = 720,
  [string]$InfluxAdminUser = 'admin',
  [string]$InfluxAdminPassword,
  [string]$InfluxAdminToken
)
$ErrorActionPreference = 'Stop'
Write-Host '=== Starting Observability Stack (Prometheus / Grafana / Influx) ===' -ForegroundColor Cyan

# 1. Prometheus
$promExe = Join-Path $PrometheusDir 'prometheus.exe'
if (-not (Test-Path $promExe)) { Write-Host 'Prometheus not found - skipping (install to enable).' -ForegroundColor Yellow } else {
  Write-Host 'Launching Prometheus...' -ForegroundColor Green
  Start-Process -FilePath $promExe -ArgumentList "--config.file=$PromConfig" -WorkingDirectory $PrometheusDir
}

# 2. Grafana (reuse existing start_grafana.ps1)
$startGraf = Join-Path (Get-Location) 'scripts\start_grafana.ps1'
if (-not (Test-Path $startGraf)) { Write-Host 'start_grafana.ps1 missing.' -ForegroundColor Yellow }
else {
  $grafArgs = @('-GrafanaHome', $GrafanaHome)
  if ($ForegroundGrafana) { $grafArgs += '-Foreground' }
  if ($AltGrafanaPort) { $grafArgs += '-AltPort' }
  Write-Host 'Launching Grafana...' -ForegroundColor Green
  Start-Process -FilePath 'powershell.exe' -ArgumentList '-ExecutionPolicy','Bypass','-File',$startGraf,@($grafArgs) -WindowStyle Minimized
}

# 3. InfluxDB (optional)
if ($StartInflux -or $SetupInflux) {
  if (-not (Test-Path $InfluxdExe)) {
    Write-Host "Influxd executable not found at $InfluxdExe" -ForegroundColor Yellow
  }
  else {
    if ($StartInflux) {
      Write-Host 'Launching InfluxDB...' -ForegroundColor Green
      $influxArgs = @()
      if ($InfluxDataDir) { $influxArgs += "--bolt-path=$InfluxDataDir\\influxd.bolt"; $influxArgs += "--engine-path=$InfluxDataDir\\engine" }
      Start-Process -FilePath $InfluxdExe -ArgumentList $influxArgs -WindowStyle Minimized
    }
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
        if ($LASTEXITCODE -eq 0) {
          Write-Host 'Influx setup completed.' -ForegroundColor Green
        } else {
          Write-Host "Influx setup exited with code $LASTEXITCODE" -ForegroundColor Red
        }
      }
    }
  }
}

Write-Host 'All start commands issued. Verify processes & dashboards (and Influx if enabled).' -ForegroundColor Cyan
