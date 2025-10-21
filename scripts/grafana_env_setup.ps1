param(
  [switch]$Persist # Use -Persist to set system-wide env vars
)

# Set recommended Grafana environment variables for this repo
$EnvMap = @{
  'GF_PATHS_HOME'         = 'C:\Program Files\GrafanaLabs\grafana'
  'GF_PATHS_PLUGINS'      = 'C:\Program Files\GrafanaLabs\grafana\data\plugins'
  'GF_PATHS_PROVISIONING' = "$PSScriptRoot\..\grafana\provisioning" | Resolve-Path | ForEach-Object { $_.Path }
  'G6_GRAFANA_DASH_PATH'  = "$PSScriptRoot\..\grafana\dashboards"    | Resolve-Path | ForEach-Object { $_.Path }
  'G6_GRAFANA_FOLDER_NAME'= 'G6 Platform'
  'G6_PROM_URL'           = 'http://127.0.0.1:9090'
}

Write-Host "Setting Grafana env vars for current session..." -ForegroundColor Cyan
foreach ($k in $EnvMap.Keys) {
  $v = $EnvMap[$k]
  [Environment]::SetEnvironmentVariable($k, $v, 'Process')
  Write-Host ("  {0} = {1}" -f $k, $v)
}

if ($Persist) {
  Write-Host "Persisting env vars system-wide (-Persist) ..." -ForegroundColor Yellow
  foreach ($k in $EnvMap.Keys) {
    $v = $EnvMap[$k]
    [Environment]::SetEnvironmentVariable($k, $v, 'Machine')
    Write-Host ("  [Machine] {0} = {1}" -f $k, $v)
  }
  Write-Host "You may need to restart the Grafana service and/or your shell for changes to take effect." -ForegroundColor Yellow
}

Write-Host "Done. To verify:" -ForegroundColor Green
Write-Host "  `$env:GF_PATHS_HOME    -> $env:GF_PATHS_HOME"
Write-Host "  `$env:GF_PATHS_PLUGINS -> $env:GF_PATHS_PLUGINS"
Write-Host "  `$env:GF_PATHS_PROVISIONING -> $env:GF_PATHS_PROVISIONING"
