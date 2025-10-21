param(
    [string]$OutputDir = "env_snapshots",
    [switch]$IncludePython = $true,
    [switch]$IncludeGrafana = $true,
    [switch]$IncludePrometheus = $true
)

# Create output dir
$root = Resolve-Path -Path (Join-Path -Path $PSScriptRoot -ChildPath "..\..")
$target = Join-Path -Path $root -ChildPath $OutputDir
New-Item -ItemType Directory -Path $target -Force | Out-Null

# Timestamped folder
$ts = Get-Date -Format "yyyyMMdd_HHmmss"
$shotDir = Join-Path $target "snapshot_$ts"
New-Item -ItemType Directory -Path $shotDir -Force | Out-Null

# Save OS + shell basics
$sys = [ordered]@{}
$sys.OS = (Get-CimInstance Win32_OperatingSystem | Select-Object Caption, Version, BuildNumber)
$sys.Arch = $env:PROCESSOR_ARCHITECTURE
$sys.Hostname = $env:COMPUTERNAME
$sys.User = $env:USERNAME
$sys.PSVersion = $PSVersionTable.PSVersion.ToString()
$sysPath = Join-Path $shotDir 'system_info.json'
$sys | ConvertTo-Json -Depth 5 | Out-File -Encoding utf8 $sysPath

# Capture environment variables relevant to G6
$envKeys = @(
    'Path','PYTHONPATH','VIRTUAL_ENV','PIP_INDEX_URL','HTTP_PROXY','HTTPS_PROXY',
    'G6_*','PROMETHEUS_*','INFLUX*','GRAFANA_*'
)
$envOut = @{}
Get-ChildItem Env: | ForEach-Object {
    $k = $_.Name; $v = $_.Value
    foreach($pat in $envKeys){
        if($k -like $pat){ $envOut[$k] = $v; break }
    }
}
$envPath = Join-Path $shotDir 'env_vars.json'
$envOut | ConvertTo-Json -Depth 5 | Out-File -Encoding utf8 $envPath

# Python environment freeze
if($IncludePython){
    try{
        $py = "${root}\..\g6_reorganized\.venv\Scripts\python.exe"
        if(!(Test-Path $py)){
            $py = (Get-Command python -ErrorAction SilentlyContinue).Source
        }
        if($py){
            & $py -m pip freeze | Out-File -Encoding utf8 (Join-Path $shotDir 'requirements.freeze.txt')
            & $py -c "import sys; print(sys.version)" | Out-File -Encoding utf8 (Join-Path $shotDir 'python_version.txt')
        }
    } catch {}
}

# Project files of interest
$files = @(
    'pyproject.toml','requirements.txt','ruff.toml','mypy.ini','pytest.ini',
    'README.md','README_COMPREHENSIVE.md','README_CONSOLIDATED_DRAFT.md',
    'prometheus.yml','prometheus_rules.yml','prometheus_alerts.yml','alertmanager.yml',
    'scripts/obs_start.ps1','scripts/auto_stack.ps1','scripts/grafana_env_setup.ps1','scripts/grafana_restart.ps1',
    'start_live_dashboard_v2.ps1','start_overlays_demo.ps1','start_live_dashboard.bat'
)
$manifest = @()
foreach($f in $files){
    $p = Join-Path $root $f
    if(Test-Path $p){
        $dest = Join-Path $shotDir ($f -replace '/', '\\')
        $destDir = Split-Path $dest -Parent
        New-Item -ItemType Directory -Path $destDir -Force | Out-Null
        Copy-Item $p $dest -Force
        $manifest += $f
    }
}
$manifest | Out-File -Encoding utf8 (Join-Path $shotDir 'manifest.txt')

# Grafana provisioning and data (lightweight)
if($IncludeGrafana){
    $grafCfg = 'C:\\GrafanaData'
    if(Test-Path $grafCfg){
        $gOut = Join-Path $shotDir 'grafana'
        New-Item -ItemType Directory -Path $gOut -Force | Out-Null
        $paths = @('conf','provisioning','data\\plugins')
        foreach($d in $paths){
            $src = Join-Path $grafCfg $d
            if(Test-Path $src){
                $dst = Join-Path $gOut $d
                New-Item -ItemType Directory -Path (Split-Path $dst -Parent) -Force | Out-Null
                Copy-Item $src $dst -Recurse -Force -ErrorAction SilentlyContinue
            }
        }
    }
}

# Prometheus config snapshot
if($IncludePrometheus){
    $prom = Join-Path $root 'prometheus.yml'
    if(Test-Path $prom){ Copy-Item $prom (Join-Path $shotDir 'prometheus.yml') -Force }
}

"Snapshot created at $shotDir"
