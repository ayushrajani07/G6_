<#!
Monitors a Windows service or process by name and enforces a soft memory ceiling.
If Working Set (MB) exceeds threshold for sustained interval, actions are taken.
Actions supported:
  - Log only
  - Restart service (if -ServiceName provided)
  - Kill process (if -KillOnBreach)
Requires: PowerShell 5+.
#>
param(
  [Parameter(Mandatory=$true)][string]$ProcessName,
  [int]$ThresholdMB = 1024,
  [int]$ConfirmAfterSeconds = 30,
  [int]$PollSeconds = 5,
  [string]$ServiceName,
  [switch]$KillOnBreach,
  [string]$LogFile = 'memory_watchdog.log'
)
$ErrorActionPreference = 'Stop'
Write-Host "[watchdog] Monitoring $ProcessName (threshold=${ThresholdMB}MB)" -ForegroundColor Cyan
$breachStart = $null

function Get-MemMB($p) { [math]::Round($p.WorkingSet64 / 1MB,2) }

while ($true) {
  $procs = Get-Process -Name $ProcessName -ErrorAction SilentlyContinue
  if (-not $procs) {
    Start-Sleep -Seconds $PollSeconds
    continue
  }
  $maxMem = ($procs | Sort-Object WorkingSet64 -Descending | Select-Object -First 1)
  $memMB = Get-MemMB $maxMem
  $timestamp = (Get-Date).ToString('s')
  $line = "${timestamp} mem=${memMB}MB pid=$($maxMem.Id)"
  Add-Content -Path $LogFile -Value $line
  if ($memMB -ge $ThresholdMB) {
    if (-not $breachStart) { $breachStart = Get-Date }
    $elapsed = (New-TimeSpan -Start $breachStart -End (Get-Date)).TotalSeconds
    if ($elapsed -ge $ConfirmAfterSeconds) {
      Write-Host "[watchdog] Threshold sustained (${memMB}MB >= ${ThresholdMB}MB for ${elapsed}s)" -ForegroundColor Yellow
      if ($ServiceName) {
        Write-Host "[watchdog] Restarting service $ServiceName" -ForegroundColor Magenta
        try { Restart-Service -Name $ServiceName -Force -ErrorAction Stop } catch { Write-Host "Service restart failed: $_" -ForegroundColor Red }
      } elseif ($KillOnBreach) {
        Write-Host "[watchdog] Killing process pid=$($maxMem.Id)" -ForegroundColor Red
        try { Stop-Process -Id $maxMem.Id -Force } catch { Write-Host "Kill failed: $_" -ForegroundColor Red }
      } else {
        Write-Host '[watchdog] Breach logged (no action mode).' -ForegroundColor DarkYellow
      }
      $breachStart = $null
    }
  } else {
    $breachStart = $null
  }
  Start-Sleep -Seconds $PollSeconds
}
