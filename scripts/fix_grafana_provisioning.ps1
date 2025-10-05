# Quick fix for Grafana provisioning directories
$ErrorActionPreference = 'Stop'

Write-Host "🔧 Quick Fix: Creating Grafana Provisioning Directories" -ForegroundColor Cyan

$provisioningPath = "C:\Users\ASUS\Documents\G6\qq\g6_reorganized\grafana\provisioning"
Write-Host "Base path: $provisioningPath" -ForegroundColor Yellow

# Create all required directories
$directories = @(
    'plugins',
    'alerting',
    'alerting\rules', 
    'alerting\templates',
    'dashboards',
    'datasources',
    'notifiers'
)

foreach ($dir in $directories) {
    $fullPath = Join-Path $provisioningPath $dir

    if (-not (Test-Path $fullPath)) {
        New-Item -Path $fullPath -ItemType Directory -Force | Out-Null
        Write-Host "✅ Created: $dir" -ForegroundColor Green

        # Create placeholder file
        $placeholder = Join-Path $fullPath ".gitkeep"
        "# Provisioning directory for $dir`n# Created: $(Get-Date)" | Out-File -FilePath $placeholder -Encoding UTF8
    } else {
        Write-Host "✅ Already exists: $dir" -ForegroundColor Green
    }
}

# Fix dashboard provisioning config to prevent duplicate UIDs
$dashboardConfigPath = Join-Path $provisioningPath "dashboards\dashboard.yml"
$dashboardConfigDir = Split-Path $dashboardConfigPath -Parent

if (-not (Test-Path $dashboardConfigDir)) {
    New-Item -Path $dashboardConfigDir -ItemType Directory -Force | Out-Null
}

# Create clean dashboard configuration
$dashboardConfig = @"
apiVersion: 1

providers:
  - name: 'G6 Dashboards'
    orgId: 1
    folder: 'G6 Platform'
    type: file
    disableDeletion: false
    updateIntervalSeconds: 30
    allowUiUpdates: true
    options:
      path: C:\Users\ASUS\Documents\G6\qq\g6_reorganized\grafana\dashboards
"@

$dashboardConfig | Out-File -FilePath $dashboardConfigPath -Encoding UTF8
Write-Host "✅ Created clean dashboard provisioning config" -ForegroundColor Green

# Check if Grafana database exists and fix permissions if needed
$grafanaDataPath = "C:\GrafanaData\data"
$grafanaDbPath = Join-Path $grafanaDataPath "grafana.db"

if (Test-Path $grafanaDbPath) {
    Write-Host "🔧 Fixing database permissions..." -ForegroundColor Yellow
    try {
        # Get current user and set appropriate permissions
        $currentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
        icacls $grafanaDbPath /grant "$($currentUser):(F)" /inheritance:r | Out-Null
        Write-Host "✅ Database permissions updated" -ForegroundColor Green
    } catch {
        Write-Host "⚠️  Could not update database permissions: $($_.Exception.Message)" -ForegroundColor Yellow
    }
} else {
    Write-Host "ℹ️  Grafana database not found (will be created on first run)" -ForegroundColor Blue
}

Write-Host ""
Write-Host "🎉 Provisioning fix complete!" -ForegroundColor Green
Write-Host "Now you can run: .\start_all.ps1 -Debug -ForegroundGrafana" -ForegroundColor White