param(
    [Parameter(Mandatory=$true)][string]$SnapshotDir
)

$root = Resolve-Path -Path (Join-Path -Path $PSScriptRoot -ChildPath "..\..")
$shot = Resolve-Path -Path $SnapshotDir

Write-Host "Restoring environment from: $shot" -ForegroundColor Cyan

# 1) Recreate venv and install pinned deps if available
$py = (Get-Command python -ErrorAction SilentlyContinue).Source
if(-not $py){ throw "Python not found on PATH. Please install Python 3.11+ first." }

$venvPath = Join-Path $root '.venv'
if(Test-Path $venvPath){ Remove-Item -Recurse -Force $venvPath }
& $py -m venv $venvPath
$venvPy = Join-Path $venvPath 'Scripts\python.exe'

# Upgrade pip
& $venvPy -m pip install --upgrade pip

$freeze = Join-Path $shot 'requirements.freeze.txt'
$req = Join-Path $root 'requirements.txt'
if(Test-Path $freeze){
    & $venvPy -m pip install -r $freeze
} elseif(Test-Path $req){
    & $venvPy -m pip install -r $req
}

# 2) Optional: restore Grafana config/provisioning (non-destructive)
$gsrc = Join-Path $shot 'grafana'
$gdst = 'C:\GrafanaData'
if(Test-Path $gsrc){
    Write-Host "Restoring Grafana config to $gdst" -ForegroundColor Yellow
    if(!(Test-Path $gdst)){ New-Item -ItemType Directory -Path $gdst | Out-Null }
    Copy-Item (Join-Path $gsrc '*') $gdst -Recurse -Force -ErrorAction SilentlyContinue
}

# 3) Prometheus config
$prom = Join-Path $shot 'prometheus.yml'
if(Test-Path $prom){ Copy-Item $prom (Join-Path $root 'prometheus.yml') -Force }

Write-Host "Restore complete. Activate venv and run tasks from VS Code Tasks menu." -ForegroundColor Green
