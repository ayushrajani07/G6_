#!/usr/bin/env powershell
# DEPRECATED LAUNCHER: start_live_dashboard_v2.ps1
# This variant is superseded by scripts/start_live_dashboard.ps1 (unified single-process dashboard).
# It will be removed in a future cleanup wave after one release.
# Invocation continues to work but simply chains to the canonical script.

Write-Host "⚠️  DEPRECATED: start_live_dashboard_v2.ps1 -> use scripts/start_live_dashboard.ps1" -ForegroundColor Yellow
Write-Host "Chaining to canonical launcher..." -ForegroundColor Yellow
Write-Host "==============================" -ForegroundColor Green
Write-Host "✅ Panel Updates: Every 5 seconds" -ForegroundColor Cyan  
Write-Host "✅ UI Refresh: Every 2 seconds" -ForegroundColor Cyan
Write-Host "✅ Format: Streaming table with all columns" -ForegroundColor Cyan
Write-Host "✅ Data: Live runtime status" -ForegroundColor Cyan
Write-Host ""

& "${PSScriptRoot}/scripts/start_live_dashboard.ps1"