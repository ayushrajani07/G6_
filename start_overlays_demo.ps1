param(
  [string]$Port = "9109",
  [string]$Index = "NIFTY",
  [string]$Expiry = "this_week",
  [string]$Offset = "ATM",
  [string]$Layout = "grid",
  [string]$Output = "overlays_demo.html",
  [int]$IntervalMs = 1000
)

Write-Host "Starting mock live updates server on port $Port for $Index:$Expiry:$Offset..."
Start-Process -FilePath "python" -ArgumentList "scripts/mock_live_updates.py --port $Port --pairs $Index`:$Expiry`:$Offset --interval 1.0" -WindowStyle Minimized
Start-Sleep -Seconds 1

Write-Host "Generating overlays HTML with live polling..."
python scripts/plot_weekday_overlays.py `
  --live-root data/g6_data `
  --weekday-root data/weekday_master `
  --index $Index --expiry-tag $Expiry --offset $Offset `
  --layout $Layout `
  --live-endpoint http://127.0.0.1:$Port/live --live-interval-ms $IntervalMs `
  --theme dark --enable-zscore --enable-bands --bands-multiplier 2.0 `
  --output $Output

Write-Host "Demo ready: $Output"