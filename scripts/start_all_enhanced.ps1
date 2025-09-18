# Enhanced start_all.ps1 with debugging and provisioning directory creation
param(
  # Prometheus
  [string]$PrometheusDir = 'C:\Prometheus',
  [string]$PromConfig = 'C:\Users\ASUS\Documents\G6\qq\g6_reorganized\prometheus.yml',
  [switch]$AutoDetectPrometheus = $true,
  [int]$PrometheusPort = 9090,
  # Grafana
  [string]$GrafanaHome = 'C:\Program Files\GrafanaLabs\grafana\grafana-12.1.1',
  [switch]$ForegroundGrafana,
  [switch]$AltGrafanaPort,
  [switch]$AutoDetectGrafana = $true,
  [int]$GrafanaPort = 3000,
  [string]$ProvisioningPath = 'C:\Users\ASUS\Documents\G6\qq\g6_reorganized\grafana\provisioning',
  # InfluxDB (optional)
  [switch]$StartInflux = $true,
  [switch]$SetupInflux,
  [switch]$AutoDetectInflux = $true,
  [string]$InfluxdExe = 'C:\InfluxDB\influxd.exe',
  [string]$InfluxCliExe = 'C:\InfluxDB\influx.exe',
  [string]$InfluxDataDir = 'C:\InfluxDB\data',
  [int]$InfluxPort = 8086,
  [string]$InfluxConfigName = 'g6-config',
  [string]$InfluxOrg = 'g6',
  [string]$InfluxBucket = 'g6_metrics',
  [int]$InfluxRetentionHours = 720,
  [string]$InfluxAdminUser = 'admin',
  [string]$InfluxAdminPassword,
  [string]$InfluxAdminToken,
  # Debug options
  [switch]$Debug,
  [switch]$FixProvisioning
)

function Write-DebugLog {
    param([string]$Message, [string]$Level = 'INFO')
    if ($Debug) {
        $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
        $color = switch ($Level) {
            'ERROR' { 'Red' }
            'WARN' { 'Yellow' }
            'SUCCESS' { 'Green' }
            default { 'White' }
        }
        Write-Host "[$timestamp] $Level`: $Message" -ForegroundColor $color
    }
}

function Fix-ProvisioningDirectories {
    param([string]$BasePath)
    Write-Host "🔧 Fixing Grafana provisioning directories..." -ForegroundColor Cyan

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
        $fullPath = Join-Path $BasePath $dir
        if (-not (Test-Path $fullPath)) {
            Write-DebugLog "Creating directory: $fullPath" 'INFO'
            New-Item -Path $fullPath -ItemType Directory -Force | Out-Null
            Write-Host "✅ Created: $dir" -ForegroundColor Green

            # Create placeholder file
            $placeholder = Join-Path $fullPath ".gitkeep"
            "# Provisioning directory for $dir" | Out-File -FilePath $placeholder -Encoding UTF8
        } else {
            Write-Host "✅ Exists: $dir" -ForegroundColor Green
        }
    }
}

function Test-PortListening {
    param([int]$Port, [int]$TimeoutSeconds = 10, [string]$Name = 'service', [int]$InitialDelayMs = 0)
    Write-DebugLog "Testing port $Port for $Name (timeout: ${TimeoutSeconds}s)" 'INFO'

    if ($InitialDelayMs -gt 0) { 
        Write-DebugLog "Initial delay: ${InitialDelayMs}ms" 'INFO'
        Start-Sleep -Milliseconds $InitialDelayMs 
    }

    for ($i = 0; $i -lt ($TimeoutSeconds * 2); $i++) {
        try {
            $conn = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue
            if ($conn) { 
                Write-DebugLog "Port $Port is listening" 'SUCCESS'
                return $true 
            }
        } catch { 
            Write-DebugLog "Port check attempt $($i+1) failed: $($_.Exception.Message)" 'WARN'
        }
        Start-Sleep -Milliseconds 500
    }
    Write-DebugLog "Port $Port is not listening after $TimeoutSeconds seconds" 'ERROR'
    return $false
}

function Invoke-HttpHealth {
    param([string]$Url, [int]$TimeoutSeconds = 2)
    Write-DebugLog "HTTP health check: $Url" 'INFO'
    try {
        $c = New-Object System.Net.Http.HttpClient
        $c.Timeout = [TimeSpan]::FromSeconds($TimeoutSeconds)
        $resp = $c.GetAsync($Url).GetAwaiter().GetResult()
        $result = [pscustomobject]@{ Code = [int]$resp.StatusCode; Success = $resp.IsSuccessStatusCode }
        Write-DebugLog "HTTP response: $($result.Code) (Success: $($result.Success))" 'INFO'
        return $result
    } catch {
        Write-DebugLog "HTTP health check failed: $($_.Exception.Message)" 'ERROR'
        return [pscustomobject]@{ Code = -1; Success = $false }
    }
}

function Resolve-Grafana {
    param([string]$GrafRoot, [switch]$AttemptDetect)
    $exe = Join-Path (Join-Path $GrafRoot 'bin') 'grafana-server.exe'
    Write-DebugLog "Looking for Grafana at: $exe" 'INFO'

    if (Test-Path $exe) { 
        Write-DebugLog "Found Grafana: $exe" 'SUCCESS'
        return $exe 
    }

    if ($AttemptDetect -or $true) {
        $bases = @(
            'C:\Program Files\GrafanaLabs\grafana',
            'C:\Grafana',
            'C:\Program Files',
            'C:\Program Files (x86)'
        )

        foreach ($b in $bases) {
            if (-not (Test-Path $b)) { continue }
            Write-DebugLog "Searching Grafana installations in: $b" 'INFO'

            $dirs = Get-ChildItem -Path $b -Directory -ErrorAction SilentlyContinue | 
                   Where-Object { $_.Name -like 'grafana*' }

            foreach ($d in ($dirs | Sort-Object LastWriteTime -Descending)) {
                $maybe = Join-Path (Join-Path $d.FullName 'bin') 'grafana-server.exe'
                Write-DebugLog "Checking candidate: $maybe" 'INFO'
                if (Test-Path $maybe) { 
                    Write-DebugLog "Found Grafana: $maybe" 'SUCCESS'
                    return $maybe 
                }
            }
        }
    }
    Write-DebugLog "Grafana not found" 'ERROR'
    return $exe
}

# Main execution
$ErrorActionPreference = 'Stop'
Write-Host '=== Starting Enhanced Observability Stack (Prometheus / Grafana / Influx) ===' -ForegroundColor Cyan

if ($Debug) {
    Write-Host "🐛 Debug mode enabled" -ForegroundColor Yellow
}

# Fix provisioning directories if requested
if ($FixProvisioning) {
    Fix-ProvisioningDirectories -BasePath $ProvisioningPath
}

# Grafana startup with enhanced debugging
Write-Host "🚀 Starting Grafana..." -ForegroundColor Green
$startGraf = Join-Path (Get-Location) 'scripts\start_grafana.ps1'

if (-not (Test-Path $startGraf)) { 
    Write-Host '❌ start_grafana.ps1 missing - will try direct launch' -ForegroundColor Yellow

    # Direct Grafana launch
    $grafanaExeResolved = Resolve-Grafana -GrafRoot $GrafanaHome -AttemptDetect:$AutoDetectGrafana

    if (Test-Path $grafanaExeResolved) {
        Write-Host "🔧 Launching Grafana directly: $grafanaExeResolved" -ForegroundColor Yellow

        # Set environment variables for Grafana
        $env:GF_PATHS_DATA = "C:\GrafanaData\data"
        $env:GF_PATHS_LOGS = "C:\GrafanaData\log"  
        $env:GF_PATHS_PLUGINS = "C:\GrafanaData\plugins"
        $env:GF_PATHS_PROVISIONING = $ProvisioningPath

        if ($ForegroundGrafana) {
            Write-Host "Starting Grafana in foreground mode (Ctrl+C to stop)..." -ForegroundColor Green
            & $grafanaExeResolved
        } else {
            Start-Process -FilePath $grafanaExeResolved -WindowStyle Minimized
            Write-Host "✅ Grafana started in background" -ForegroundColor Green
        }
    } else {
        Write-Host "❌ Grafana executable not found" -ForegroundColor Red
    }
} else {
    # Use existing start_grafana.ps1
    $grafanaExeResolved = Resolve-Grafana -GrafRoot $GrafanaHome -AttemptDetect:$AutoDetectGrafana

    if (-not (Test-Path $grafanaExeResolved)) {
        Write-Host "❌ Grafana server executable not found" -ForegroundColor Red
    } else {
        $grafArgs = @('-GrafanaHome', (Split-Path (Split-Path $grafanaExeResolved -Parent) -Parent))
        if ($ForegroundGrafana) { $grafArgs += '-Foreground' }
        if ($AltGrafanaPort) { $grafArgs += '-AltPort'; $GrafanaPort = 3001 }

        Write-Host "Launching Grafana via script: $startGraf" -ForegroundColor Green
        Write-DebugLog "Grafana arguments: $($grafArgs -join ' ')" 'INFO'

        $flatArgs = @('-ExecutionPolicy','Bypass','-File', $startGraf) + $grafArgs
        Start-Process -FilePath 'powershell.exe' -ArgumentList $flatArgs -WindowStyle Minimized
        Write-Host "✅ Grafana started via script" -ForegroundColor Green
    }
}

# Enhanced verification
Write-Host '--- Verifying Grafana startup ---' -ForegroundColor Cyan

$effectiveGrafPort = $GrafanaPort
if ($AltGrafanaPort) { $effectiveGrafPort = 3001 }

$grafOk = $false
Write-Host "🔍 Checking Grafana on port $effectiveGrafPort..." -ForegroundColor Yellow

if (Test-PortListening -Port $effectiveGrafPort -Name 'Grafana' -TimeoutSeconds 10 -InitialDelayMs 2000) {
    Write-Host "🔍 Grafana port is open, checking health endpoint..." -ForegroundColor Yellow

    # Extended health probe with better feedback
    for ($g = 0; $g -lt 30; $g++) {
        $health = Invoke-HttpHealth -Url ("http://localhost:$effectiveGrafPort/api/health") -TimeoutSeconds 3
        if ($health.Success -and $health.Code -eq 200) { 
            $grafOk = $true
            break 
        }
        Write-Host "." -NoNewline -ForegroundColor Yellow
        Start-Sleep -Milliseconds 2000
    }
    Write-Host "" # New line after dots
}

if ($grafOk) {
    Write-Host "✅ Grafana is healthy and listening on: http://localhost:$effectiveGrafPort" -ForegroundColor Green
} else {
    Write-Host "❌ Grafana not responding on: http://localhost:$effectiveGrafPort" -ForegroundColor Red
    Write-Host "💡 Troubleshooting suggestions:" -ForegroundColor Yellow
    Write-Host "   1. Check if provisioning directories exist" -ForegroundColor White
    Write-Host "   2. Verify dashboard configuration has no duplicate UIDs" -ForegroundColor White
    Write-Host "   3. Check Grafana logs: C:\GrafanaData\log\grafana.log" -ForegroundColor White
    Write-Host "   4. Ensure database permissions are correct" -ForegroundColor White
}

Write-Host '=== Startup Complete ===' -ForegroundColor Cyan
Write-Host "Grafana Status: $(if($grafOk){'✅ Running'}else{'❌ Failed'})" -ForegroundColor $(if($grafOk){'Green'}else{'Red'})

if (-not $grafOk) {
    Write-Host ""
    Write-Host "🔧 Quick Fix Commands:" -ForegroundColor Yellow
    Write-Host "1. Check what's running: Get-Process | Where-Object {\$_.ProcessName -like '*grafana*'}" -ForegroundColor White
    Write-Host "2. Check logs: Get-Content 'C:\GrafanaData\log\grafana.log' -Tail 20" -ForegroundColor White
    Write-Host "3. Kill and restart: Stop-Process -Name 'grafana*' -Force; .\start_all_enhanced.ps1 -FixProvisioning -ForegroundGrafana" -ForegroundColor White
}