Param(
    [string]$StatusFile = "data/runtime_status.json",
    [int]$Interval = 60,
    [switch]$Attach
)

$env:G6_USE_MOCK_PROVIDER = "1"
if ($Attach) {
    $env:G6_TERMINAL_MODE = "attach"
}

# Ensure data directory exists
$dir = Split-Path $StatusFile -Parent
if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }

Write-Host "Starting G6 in MOCK mode (interval=$Interval, status=$StatusFile)" -ForegroundColor Cyan

python -m src.unified_main --interval $Interval --runtime-status-file $StatusFile --mock-data
