Param(
    [string]$StatusFile = "data/runtime_status.json",
    [int]$Port = 8765,
    [string]$ListenHost = "127.0.0.1"
)

$env:STATUS_FILE = $StatusFile
Write-Host "Starting G6 WebSocket service (status=$StatusFile host=$ListenHost port=$Port)" -ForegroundColor Green
uvicorn src.console.ws_service:app --host $ListenHost --port $Port
