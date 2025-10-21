param(
  [string]$Port = "9109",
  [string]$Index = "NIFTY",
  [string]$Expiry = "this_week",
  [string]$Offset = "0",
  [string]$Layout = "grid",
  [string]$Output = "overlays_demo.html",
  [int]$IntervalMs = 1000
)

Write-Host "(mock_live_updates.py removed) Proceeding without live server; page will render static overlays unless you supply your own endpoint." -ForegroundColor Yellow

Write-Host "Generating overlays HTML with live polling..."
python scripts/plot_weekday_overlays.py `
  --live-root data/g6_data `
  --weekday-root data/weekday_master `
  --index $Index --expiry-tag $Expiry --offset $Offset `
  --layout $Layout `
  # --live-endpoint http://127.0.0.1:$Port/live --live-interval-ms $IntervalMs `  # (disabled: mock server removed)
  --theme dark --enable-zscore --enable-bands --bands-multiplier 2.0 `
  --output $Output

Write-Host "Demo ready: $Output"