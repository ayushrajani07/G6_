# Starts simulator + panels bridge with correct env; restarts bridge on failure.
param(
    [string]$StatusFile = "data/runtime_status.json",
    [string]$PanelsDir = "data/panels",
    [int]$IntervalSec = 60,
    [double]$BridgeRefresh = 0.5
)

$ErrorActionPreference = 'Stop'

$env:G6_PANELS_DIR = $PanelsDir
$env:G6_OUTPUT_SINKS = 'stdout,logging,panels'
# Deprecated env vars G6_SUMMARY_READ_PANELS / G6_SUMMARY_PANELS_MODE removed (auto-detect now).

$python = ".venv\Scripts\python.exe"

# Start simulator if not running
Write-Host "[G6] Starting simulator..."
Start-Process -FilePath $python -ArgumentList "scripts/dev_tools.py", "simulate-status", "--status-file", $StatusFile, "--indices", "NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX", "--interval", "$IntervalSec", "--refresh", "1.0", "--open-market", "--with-analytics" -WindowStyle Minimized

# Unified summary will auto-detect panels directory.
Write-Host "[G6] Starting unified summary (auto panels detection)..."
& $python -m scripts.summary.app --refresh $BridgeRefresh --status-file $StatusFile
