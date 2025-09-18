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

function Fix-DatabasePermissions {
    param([string]$DataPath)
    Write-Host "🔧 Fixing Grafana database permissions..." -ForegroundColor Cyan
    
    $dbPath = Join-Path $DataPath "grafana.db"
    if (Test-Path $dbPath) {
        try {
            # Set more restrictive permissions
            $acl = Get-Acl $dbPath
            $accessRule = New-Object System.Security.AccessControl.FileSystemAccessRule(
                $env:USERNAME, "FullControl", "Allow"
            )
            $acl.SetAccessRule($accessRule)
            Set-Acl -Path $dbPath -AclObject $acl
            Write-Host "✅ Database permissions updated" -ForegroundColor Green
        } catch {
            Write-Host "⚠️  Could not update database permissions: $($_.Exception.Message)" -ForegroundColor Yellow
        }
    }
}

function Resolve-Prometheus {
    param([string]$Dir, [switch]$AttemptDetect)
    $exe = Join-Path $Dir 'prometheus.exe'
    Write-DebugLog "Looking for Prometheus at: $exe" 'INFO'
    
    if (Test-Path $exe) { 
        Write-DebugLog "Found Prometheus: $exe" 'SUCCESS'
        return $exe 
    }
    
    if ($AttemptDetect -or $true) {
        $candidates = @(
            'C:\Prometheus\prometheus.exe',
            'C:\Program Files\Prometheus\prometheus.exe',
            'C:\ProgramData\Prometheus\prometheus.exe'
        )
        
        foreach ($c in $candidates) { 
            Write-DebugLog "Checking candidate: $c" 'INFO'
            if (Test-Path $c) { 
                Write-DebugLog "Found Prometheus: $c" 'SUCCESS'
                return $c 
            } 
        }
        
        # Search versioned subdirectories
        $base = 'C:\Prometheus'
        if (Test-Path $base) {
            Write-DebugLog "Searching versioned directories in: $base" 'INFO'
            $sub = Get-ChildItem -Path $base -Directory -ErrorAction SilentlyContinue | 
                   Where-Object { $_.Name -like 'prometheus*' } | 
                   Sort-Object LastWriteTime -Descending | 
                   Select-Object -First 1
            if ($sub) {
                $maybe = Join-Path $sub.FullName 'prometheus.exe'
                Write-DebugLog "Checking versioned candidate: $maybe" 'INFO'
                if (Test-Path $maybe) { 
                    Write-DebugLog "Found Prometheus: $maybe" 'SUCCESS'
                    return $maybe 
                }
            }
        }
    }
    Write-DebugLog "Prometheus not found" 'ERROR'
    return $exe
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

function Resolve-Influxd {
    param([string]$Path, [switch]$AttemptDetect)
    Write-DebugLog "Looking for InfluxDB at: $Path" 'INFO'
    
    if (Test-Path $Path) { 
        Write-DebugLog "Found InfluxDB: $Path" 'SUCCESS'
        return $Path 
    }
    
    if ($AttemptDetect -or $true) {
        $candidates = @(
            'C:\influxdata\influxdb2\influxd.exe',
            'C:\Program Files\InfluxData\influxdb2\influxd.exe',
            'C:\Program Files\InfluxData\influxdb\influxd.exe'
        )
        foreach ($c in $candidates) { 
            Write-DebugLog "Checking candidate: $c" 'INFO'
            if (Test-Path $c) { 
                Write-DebugLog "Found InfluxDB: $c" 'SUCCESS'
                return $c 
            } 
        }
    }
    Write-DebugLog "InfluxDB not found" 'ERROR'
    return $Path
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
    
    # Fix database permissions
    $grafanaDataPath = "C:\GrafanaData\data"
    if (Test-Path $grafanaDataPath) {
        Fix-DatabasePermissions -DataPath $grafanaDataPath
    }
}

# 1. Prometheus
Write-Host "🚀 Starting Prometheus..." -ForegroundColor Green
$resolvedProm = Resolve-Prometheus -Dir $PrometheusDir -AttemptDetect:$AutoDetectPrometheus

if (Test-Path $resolvedProm) {
    $promWorkDir = Split-Path $resolvedProm -Parent
    Write-Host "Launching Prometheus: $resolvedProm" -ForegroundColor Green
    Write-DebugLog "Prometheus working directory: $promWorkDir" 'INFO'
    Write-DebugLog "Prometheus config: $PromConfig" 'INFO'
    
    if (Test-Path $PromConfig) {
        Start-Process -FilePath $resolvedProm -ArgumentList "--config.file=$PromConfig" -WorkingDirectory $promWorkDir
        Write-Host "✅ Prometheus started" -ForegroundColor Green
    } else {
        Write-Host "❌ Prometheus config not found: $PromConfig" -ForegroundColor Red
    }
} else {
    Write-Host "❌ Prometheus not found (looked at $resolvedProm)" -ForegroundColor Red
}

# 2. Grafana
Write-Host "🚀 Starting Grafana..." -ForegroundColor Green
$startGraf = Join-Path (Get-Location) 'scripts\start_grafana.ps1'

if (-not (Test-Path $startGraf)) { 
    Write-Host '❌ start_grafana.ps1 missing.' -ForegroundColor Red 
} else {
    $grafanaExeResolved = Resolve-Grafana -GrafRoot $GrafanaHome -AttemptDetect:$AutoDetectGrafana
    
    if (-not (Test-Path $grafanaExeResolved)) {
        Write-Host "❌ Grafana server executable not found" -ForegroundColor Red
    } else {
        $grafArgs = @('-GrafanaHome', (Split-Path (Split-Path $grafanaExeResolved -Parent) -Parent))
        if ($ForegroundGrafana) { $grafArgs += '-Foreground' }
        if ($AltGrafanaPort) { $grafArgs += '-AltPort'; $GrafanaPort = 3001 }
        
        Write-Host "Launching Grafana (resolved executable: $grafanaExeResolved)" -ForegroundColor Green
        Write-DebugLog "Grafana arguments: $($grafArgs -join ' ')" 'INFO'
        
        $flatArgs = @('-ExecutionPolicy','Bypass','-File', $startGraf) + $grafArgs
        Start-Process -FilePath 'powershell.exe' -ArgumentList $flatArgs -WindowStyle Minimized
        Write-Host "✅ Grafana started" -ForegroundColor Green
    }
}

# 3. InfluxDB (optional)
if ($StartInflux -or $SetupInflux) {
    Write-Host "🚀 Starting InfluxDB..." -ForegroundColor Green
    $InfluxdExe = Resolve-Influxd -Path $InfluxdExe -AttemptDetect:$AutoDetectInflux
    
    if (-not (Test-Path $InfluxdExe)) {
        Write-Host "❌ Influxd executable not found" -ForegroundColor Red
    } elseif ($StartInflux) {
        Write-Host "Launching InfluxDB: $InfluxdExe" -ForegroundColor Green
        $influxArgs = @()
        if ($InfluxDataDir) { 
            Write-DebugLog "InfluxDB data directory: $InfluxDataDir" 'INFO'
            $influxArgs += "--bolt-path=$InfluxDataDir\influxd.bolt"
            $influxArgs += "--engine-path=$InfluxDataDir\engine" 
        }
        Start-Process -FilePath $InfluxdExe -ArgumentList $influxArgs -WindowStyle Minimized
        Write-Host "✅ InfluxDB started" -ForegroundColor Green
    }
    
    if ($SetupInflux) {
        if (-not (Test-Path $InfluxCliExe)) {
            Write-Host "❌ Influx CLI not found at $InfluxCliExe" -ForegroundColor Red
        } else {
            $missing = @()
            if (-not $InfluxAdminPassword) { $missing += 'InfluxAdminPassword' }
            if (-not $InfluxAdminToken) { $missing += 'InfluxAdminToken' }
            
            if ($missing.Count -gt 0) {
                Write-Host ("❌ Cannot run setup; missing: {0}" -f ($missing -join ', ')) -ForegroundColor Red
            } else {
                Write-Host '🔧 Running one-time Influx setup...' -ForegroundColor Green
                $retention = "$InfluxRetentionHours" + 'h'
                
                Write-DebugLog "InfluxDB setup parameters:" 'INFO'
                Write-DebugLog "  Username: $InfluxAdminUser" 'INFO'
                Write-DebugLog "  Org: $InfluxOrg" 'INFO'
                Write-DebugLog "  Bucket: $InfluxBucket" 'INFO'
                Write-DebugLog "  Retention: $retention" 'INFO'
                
                & $InfluxCliExe setup --skip-confirmation `
                  --username $InfluxAdminUser `
                  --password $InfluxAdminPassword `
                  --org $InfluxOrg `
                  --bucket $InfluxBucket `
                  --retention $retention `
                  --token $InfluxAdminToken `
                  --name $InfluxConfigName
                  
                if ($LASTEXITCODE -eq 0) {
                    Write-Host '✅ Influx setup completed.' -ForegroundColor Green
                } else {
                    Write-Host "❌ Influx setup exited with code $LASTEXITCODE" -ForegroundColor Red
                }
            }
        }
    }
}

# Verification with enhanced feedback
Write-Host '--- Verifying service ports (extended wait) ---' -ForegroundColor Cyan

# Prometheus
$promOk = Test-PortListening -Port $PrometheusPort -Name 'Prometheus' -InitialDelayMs 500
if ($promOk) { 
    Write-Host "✅ Prometheus listening on: http://localhost:$PrometheusPort" -ForegroundColor Green 
} else { 
    Write-Host "❌ Prometheus not listening on: http://localhost:$PrometheusPort" -ForegroundColor Red 
}

# Grafana
$effectiveGrafPort = $GrafanaPort
if ($AltGrafanaPort) { $effectiveGrafPort = 3001 }

$grafOk = $false
if (Test-PortListening -Port $effectiveGrafPort -Name 'Grafana' -TimeoutSeconds 5 -InitialDelayMs 1000) {
    Write-Host "🔍 Grafana port is open, checking health endpoint..." -ForegroundColor Yellow
    
    # Up to 60s health probe loop
    for ($g = 0; $g -lt 30; $g++) {
        $health = Invoke-HttpHealth -Url ("http://localhost:$effectiveGrafPort/api/health") -TimeoutSeconds 2
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
    Write-Host "✅ Grafana listening on: http://localhost:$effectiveGrafPort" -ForegroundColor Green
} else {
    Write-Host "❌ Grafana not responding on: http://localhost:$effectiveGrafPort" -ForegroundColor Red
    Write-Host "💡 Check Grafana logs for errors, especially provisioning issues" -ForegroundColor Yellow
}

# InfluxDB
if ($StartInflux) {
    $influxOk = $false
    if (Test-PortListening -Port $InfluxPort -Name 'InfluxDB' -InitialDelayMs 500 -TimeoutSeconds 10) {
        # Influx root may 404; probe /health
        $health = Invoke-HttpHealth -Url ("http://localhost:$InfluxPort/health") -TimeoutSeconds 3
        if ($health.Success -and $health.Code -eq 200) { $influxOk = $true }
    }
    
    if ($influxOk) { 
        Write-Host "✅ InfluxDB listening on: http://localhost:$InfluxPort" -ForegroundColor Green 
    } else { 
        Write-Host "❌ InfluxDB not responding on: http://localhost:$InfluxPort" -ForegroundColor Red 
    }
}

Write-Host '=== Startup Summary ===' -ForegroundColor Cyan
Write-Host "Prometheus: $(if($promOk){'✅ Running'}else{'❌ Failed'})" -ForegroundColor $(if($promOk){'Green'}else{'Red'})
Write-Host "Grafana:    $(if($grafOk){'✅ Running'}else{'❌ Failed'})" -ForegroundColor $(if($grafOk){'Green'}else{'Red'})
if ($StartInflux) {
    Write-Host "InfluxDB:   $(if($influxOk){'✅ Running'}else{'❌ Failed'})" -ForegroundColor $(if($influxOk){'Green'}else{'Red'})
}

if (-not $grafOk) {
    Write-Host "" -ForegroundColor Yellow
    Write-Host "🔧 Troubleshooting Tips for Grafana:" -ForegroundColor Yellow
    Write-Host "1. Run with -FixProvisioning to create missing directories" -ForegroundColor White
    Write-Host "2. Check dashboard provisioning for duplicate UIDs" -ForegroundColor White
    Write-Host "3. Verify provisioning path exists: $ProvisioningPath" -ForegroundColor White
    Write-Host "4. Run with -Debug for detailed logging" -ForegroundColor White
}

Write-Host 'All start commands issued. (Verification complete.)' -ForegroundColor Cyan