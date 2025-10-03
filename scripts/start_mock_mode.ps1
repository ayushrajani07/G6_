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

Write-Host "Starting G6 in MOCK mode (interval=$Interval, status=$StatusFile) [orchestrator loop]" -ForegroundColor Cyan
if (-not $env:G6_SUPPRESS_LEGACY_LOOP_WARN) {
    Write-Host "(Legacy unified_main path deprecated; using orchestrator loop runner)" -ForegroundColor Yellow
}

python scripts/run_orchestrator_loop.py --config config/g6_config.json --interval $Interval --cycles 0 --auto-snapshots
