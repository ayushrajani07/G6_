#!/usr/bin/env powershell
# G6 Live Dashboard Launcher
# Starts the panel updater service and summary view with live data refreshing every 5 seconds

Write-Host "Starting G6 Live Dashboard..." -ForegroundColor Green
Write-Host "================================" -ForegroundColor Green

# Set panels directory (auto-detect controls behavior; legacy panels mode env removed)
$env:G6_PANELS_DIR = "data/panels"

Write-Host "Starting unified live dashboard (single process)..." -ForegroundColor Yellow
Write-Host "   - Panels written in-process by unified summary" -ForegroundColor Cyan
Write-Host "   - UI refresh every 2 seconds" -ForegroundColor Cyan
Write-Host "   - Press Ctrl+C to stop" -ForegroundColor Cyan
Write-Host ""

# Register cleanup handler
Register-EngineEvent -SourceIdentifier PowerShell.Exiting -SupportEvent -Action {
    Write-Host "`nStopping services..." -ForegroundColor Yellow
    Get-Job -Name "PanelUpdater" -ErrorAction SilentlyContinue | Stop-Job
    Get-Job -Name "PanelUpdater" -ErrorAction SilentlyContinue | Remove-Job
}

try {
    # Start the unified summary app (legacy summary_view.py removed 2025-10-03)
    & "C:/Users/ASUS/Documents/G6/qq/g6_reorganized/.venv/Scripts/python.exe" -m scripts.summary.app --refresh 2
}
finally {
    Write-Host "`nCleaning up..." -ForegroundColor Yellow
    Write-Host "Dashboard stopped." -ForegroundColor Green
}