$ErrorActionPreference = 'SilentlyContinue'
$procs = Get-Process | Where-Object { $_.ProcessName -like 'grafana-server*' }
if (-not $procs) {
  Write-Host 'Grafana server process not found.' -ForegroundColor Yellow
  exit 0
}
foreach ($p in $procs) {
  Write-Host "Stopping Grafana PID $($p.Id)..." -ForegroundColor Cyan
  try { $p.CloseMainWindow() | Out-Null } catch {}
  Start-Sleep -Milliseconds 500
  if (-not $p.HasExited) {
    try { $p.Kill() } catch {}
  }
}
Write-Host 'Grafana stopped.' -ForegroundColor Green
