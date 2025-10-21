# Restart Grafana Windows service safely
try {
  $svc = Get-Service -ErrorAction Stop | Where-Object { $_.Name -match 'grafana' }
  if (-not $svc) { Write-Host 'Grafana service not found. Skipping restart.' -ForegroundColor Yellow; exit 0 }
  if ($svc.Status -eq 'Running') {
    Write-Host ("Restarting service {0}" -f $svc.Name) -ForegroundColor Cyan
    Restart-Service -Name $svc.Name -Force -ErrorAction Stop
  } else {
    Write-Host ("Starting service {0}" -f $svc.Name) -ForegroundColor Cyan
    Start-Service -Name $svc.Name -ErrorAction Stop
  }
  Start-Sleep -Seconds 2
  Get-Service $svc.Name | Select-Object Name, Status | Format-Table -AutoSize
} catch {
  Write-Host ("Grafana service restart failed: {0}" -f $_.Exception.Message) -ForegroundColor Red
  exit 1
}
