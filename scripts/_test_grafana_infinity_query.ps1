# Temporary script: POST a QueryData to Grafana to validate Infinity parsing
$body = @{
  queries = @(
    @{
      refId = 'A'
      datasource = @{ type = 'yesoreyeram-infinity-datasource'; uid = 'INFINITY' }
      queryType = 'json'
      source = 'url'
      type = 'json'
      url = 'http://127.0.0.1:9500/api/live_csv?index=NIFTY&expiry_tag=this_week&offset=0&limit=1000&include_index=1'
      format = 'table'
      url_options = @{ method = 'GET'; params = @( @{ key = 'from_ms'; value = '0' }; @{ key = 'to_ms'; value = '9999999999999' }; @{ key = 'cb'; value = '1' } ) }
      json_options = @{ root_is_array = $true }
      columns = @( @{ selector = 'time_str'; text = 'Time'; type = 'time' }; @{ selector = 'tp'; text = 'TP'; type = 'number' } )
    }
  )
  range = @{ from = (Get-Date -Date '1970-01-01T00:00:00Z').ToString('o'); to = (Get-Date).ToString('o') }
}
$json = $body | ConvertTo-Json -Depth 10
Write-Host "Posting to Grafana /api/ds/query..."
try {
  $resp = Invoke-RestMethod -Uri 'http://127.0.0.1:3002/api/ds/query' -Method Post -Body $json -ContentType 'application/json' -TimeoutSec 30
  $resp | ConvertTo-Json -Depth 6 | Write-Host
} catch {
  Write-Host 'Request failed:' $_.Exception.Message
  exit 2
}
