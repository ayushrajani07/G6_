param(
  [string]$ServiceName = 'Grafana',
  [string]$GrafanaHome = 'C:\Program Files\GrafanaLabs\grafana\grafana-12.1.1',
  [string]$NssmPath = 'C:\nssm\win64\nssm.exe'
)
$ErrorActionPreference = 'Stop'
Write-Host "Installing Windows service $ServiceName for Grafana" -ForegroundColor Cyan

$exe = Join-Path $GrafanaHome 'bin\grafana-server.exe'
if (-not (Test-Path $exe)) { throw "grafana-server.exe not found at $exe" }

# Prefer NSSM if available; else fallback to sc.exe basic service (no graceful stop handling)
if (Test-Path $NssmPath) {
  & $NssmPath install $ServiceName $exe '---homepath' $GrafanaHome | Out-Null
  & $NssmPath set $ServiceName Start SERVICE_AUTO_START | Out-Null
  & $NssmPath set $ServiceName AppDirectory $GrafanaHome | Out-Null
  & $NssmPath set $ServiceName AppStopMethodSkip 0 | Out-Null
  & $NssmPath set $ServiceName AppThrottle 1500 | Out-Null
  Write-Host 'Service installed via NSSM.' -ForegroundColor Green
}
else {
  Write-Host 'NSSM not found, using sc.exe (limited stop behavior).' -ForegroundColor Yellow
  $binPath = '"' + $exe + '" "---homepath" ' + '"' + $GrafanaHome + '"'
  sc.exe create $ServiceName binPath= $binPath start= auto | Out-Null
}

Write-Host 'You can now start the service: Start-Service -Name "' $ServiceName '"' -ForegroundColor Cyan
