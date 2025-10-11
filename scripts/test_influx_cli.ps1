param(
  [string]$CliPath = ''
)

$ErrorActionPreference = 'Continue'
function Find-InfluxCli {
  if ($CliPath -and (Test-Path $CliPath)) { return $CliPath }
  $candidates = @(
    'C:\influxdata\influx-cli\influx.exe',
    'C:\influxdata\influxdb2\influx.exe',
    'C:\Program Files\InfluxData\influxdb2\influx.exe',
    'C:\Program Files\InfluxData\influxdb2-client\influx.exe'
  )
  foreach ($c in $candidates) { if (Test-Path $c) { return $c } }
  $fromPath = (Get-Command influx.exe -ErrorAction SilentlyContinue)
  if ($fromPath) { return $fromPath.Source }
  return $null
}

$exe = Find-InfluxCli
if (-not $exe) { Write-Host "[test] influx.exe not found (install first via scripts/install_influx_cli.ps1)" -ForegroundColor Yellow; exit 1 }

$env:NO_PROXY = 'localhost,127.0.0.1'
$env:HTTP_PROXY = ''
$env:HTTPS_PROXY = ''

Write-Host ("[test] Using CLI: {0}" -f $exe) -ForegroundColor Cyan
& $exe version

Write-Host "[test] Ping 127.0.0.1:8086" -ForegroundColor Cyan
& $exe ping --host http://127.0.0.1:8086

if ($env:G6_INFLUX_TOKEN) {
  $org = if ($env:G6_INFLUX_ORG) { $env:G6_INFLUX_ORG } else { 'g6' }
  $host = if ($env:G6_INFLUX_URL) { $env:G6_INFLUX_URL } else { 'http://127.0.0.1:8086' }
  Write-Host "[test] Creating/activating CLI config 'local' from env" -ForegroundColor Cyan
  & $exe config create --config-name local --host $host --org $org --token $env:G6_INFLUX_TOKEN --active
  Write-Host "[test] Listing orgs/buckets" -ForegroundColor Cyan
  & $exe org list
  & $exe bucket list
}

Write-Host "[test] Done." -ForegroundColor Cyan
