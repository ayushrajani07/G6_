param(
  [int]$GrafanaPort = 3002,
  [switch]$Clean,
  [switch]$UseV1,
  # Prefer the known-working Infinity v3 dashboard (exclude v4 when set)
  [switch]$UseV3,
  # Optional: path to plugin-less v3 dashboard JSON to stage
  [string]$V3Path = 'C:\Users\ASUS\Documents\NOTES\analytics.json',
  # Start Grafana with anonymous Admin (no login form)
  [switch]$DisablePassword
)

$ErrorActionPreference = 'Continue'

Write-Host "Restarting only Grafana so dashboards update (leaving Prometheus/Influx/Web API running)..." -ForegroundColor Yellow

# Helper: ensure directory exists
function Ensure-Dir { param([string]$Path) if (-not (Test-Path $Path)) { New-Item -ItemType Directory -Force -Path $Path | Out-Null } }

# Helper: write UTF-8 without BOM (PowerShell 5.1's -Encoding UTF8 adds BOM)
function Write-TextNoBom {
  param(
    [Parameter(Mandatory=$true)][string]$Path,
    [Parameter(Mandatory=$true)][string]$Content
  )
  $dir = Split-Path -Path $Path -Parent
  if ($dir -and -not (Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
  $enc = New-Object System.Text.UTF8Encoding($false)
  [System.IO.File]::WriteAllText($Path, $Content, $enc)
}

# Compute repo root (one level up from this scripts directory)
$RepoRoot = Split-Path $PSScriptRoot -Parent

# 1) Stop Grafana (process or service), but do NOT touch other services
try {
  # Try service first if present
  $svc = Get-Service -ErrorAction SilentlyContinue | Where-Object { $_.Name -match 'grafana' }
  if ($svc -and $svc.Status -eq 'Running') {
    Write-Host ("Stopping Grafana service {0}" -f $svc.Name) -ForegroundColor DarkYellow
    Stop-Service -Name $svc.Name -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
  }
} catch {}

# Kill standalone grafana-server processes (don’t kill prometheus or influxd)
try {
  # Stop Windows-installed grafana.exe or grafana-server.exe if running
  Get-Process -Name 'grafana','grafana-server' -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
} catch {}

# Also stop any process currently listening on the target Grafana port (safety net)
try {
  $conn = Get-NetTCPConnection -LocalPort $GrafanaPort -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($conn) {
    try { Stop-Process -Id $conn.OwningProcess -Force -ErrorAction SilentlyContinue } catch {}
  }
} catch {}

# Optional: clean Grafana DB (forces re-provision on restart)
if ($Clean -or $env:G6_CLEAN_GRAFANA -eq '1') {
  $dbCandidates = @(
    'C:\GrafanaData\data\grafana.db',
    'C:\GrafanaData\data\grafana.sqlite'
  )
  foreach ($db in $dbCandidates) {
    try {
  if (Test-Path $db) { Write-Host "Removing $db ..." -ForegroundColor DarkYellow; Remove-Item -LiteralPath $db -Force -ErrorAction SilentlyContinue }
    } catch { Write-Host ("Warning: failed to remove {0}: {1}" -f $db, $_.Exception.Message) -ForegroundColor Red }
  }
}

# 2) Restage dashboards into a clean filtered directory used by provisioning
$GrafanaDataRoot = 'C:\GrafanaData'
$provRoot = Join-Path $GrafanaDataRoot 'provisioning_baseline'
$dsDir = Join-Path $provRoot 'datasources'
$dbDir = Join-Path $provRoot 'dashboards'
$dbFilteredDir = Join-Path $provRoot 'dashboards_src_filtered'
Ensure-Dir -Path $dsDir
Ensure-Dir -Path $dbDir
Ensure-Dir -Path $dbFilteredDir

# Clean filtered dir to avoid stale duplicates
try { Get-ChildItem -Path $dbFilteredDir -Filter *.json -File -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue } catch {}

# Copy latest dashboards from repo (generated first, then legacy)
try {
  # Auto-enable UseV3 if an external v3 dashboard path exists,
  # BUT prefer a repo-persisted patched JSON if present (more robust)
  $repoPatched = Join-Path $RepoRoot 'grafana/dashboards/generated/g6_analytics_infinity_v3_patched.json'
  $autoUseV3 = $UseV3 -or ($V3Path -and (Test-Path -LiteralPath $V3Path))
  if ((Test-Path -LiteralPath $repoPatched)) {
    if ($UseV3) { Write-Host 'Repo patched v3 detected; preferring repo JSON over external V3.' -ForegroundColor DarkYellow }
    $UseV3 = $false
  } elseif ($autoUseV3 -and -not $UseV3) {
    $UseV3 = $true
  }
  $dashboardsSrc = Join-Path $RepoRoot 'grafana/dashboards/generated'
  $dashboardsLegacy = Join-Path $RepoRoot 'grafana/dashboards'
  $excludeNames = @('manifest.json')
  if ($UseV3) {
    # Exclude all analytics dashboards from repo when staging external v3
    $excludeNames += 'g6_analytics_infinity.json'
    $excludeNames += 'g6_analytics_infinity_v2.json'
    $excludeNames += 'g6_analytics_infinity_v3.json'
    $excludeNames += 'g6_analytics_infinity_v4.json'
  }

  function Copy-IfNotExcluded {
    param([System.IO.FileInfo]$File)
    if ($excludeNames -contains $File.Name) { return }
    # When using external v3, skip any analytics dashboards regardless of exact filename
    if ($UseV3 -and ($File.Name -like 'g6_analytics_infinity*.json' -or $File.Name -like 'g6_analytics*.json')) { return }
    try {
      $raw = Get-Content -LiteralPath $File.FullName -Raw -ErrorAction Stop
      if ($raw -match '"uid"\s*:\s*"g6specauto"') { return }
    } catch {}
    Copy-Item -LiteralPath $File.FullName -Destination (Join-Path $dbFilteredDir $File.Name) -Force
  }

  if (Test-Path $dashboardsSrc) { Get-ChildItem -Path $dashboardsSrc -Filter *.json -File -ErrorAction SilentlyContinue | ForEach-Object { Copy-IfNotExcluded -File $_ } }

  # If external v3 file exists, copy it last to override any same-UID dashboard from repo
  if ($UseV3 -and $V3Path -and (Test-Path -LiteralPath $V3Path)) {
    try {
      $destName = 'g6_analytics_infinity_v3_external.json'
      $destPath = Join-Path $dbFilteredDir $destName
      Copy-Item -LiteralPath $V3Path -Destination $destPath -Force
      Write-Host ("Staged external v3 dashboard: {0}" -f $V3Path) -ForegroundColor DarkGreen

      # Apply requested axis overrides to the staged v3 file
      try {
        $jsonRaw = Get-Content -LiteralPath $destPath -Raw -ErrorAction Stop
        $doc = $jsonRaw | ConvertFrom-Json -ErrorAction Stop
        if ($doc) {
          # Normalize UID and clear numeric id to ensure deterministic provisioning
          try {
            $doc | Add-Member -NotePropertyName uid -NotePropertyValue 'g6-analytics-infinity-v3' -Force
            if ($doc.PSObject.Properties.Name -contains 'id') { $doc.id = $null }
            # Use shared crosshair (not shared tooltip) at dashboard level
            if ($doc.PSObject.Properties.Name -contains 'graphTooltip') { $doc.graphTooltip = 1 } else { $doc | Add-Member -NotePropertyName graphTooltip -NotePropertyValue 1 -Force }
            # Broaden default time window to cover simulated/CSV timestamps that can be ahead of local now
            if (-not $doc.time) { $doc | Add-Member -NotePropertyName time -NotePropertyValue (@{ from = 'now-12h'; to = 'now+6h' }) -Force }
            else {
              if (-not $doc.time.from) { $doc.time.from = 'now-12h' } else { $doc.time.from = 'now-12h' }
              if (-not $doc.time.to) { $doc.time.to = 'now+6h' } else { $doc.time.to = 'now+6h' }
            }
          } catch {}

          # Apply panel overrides (walk nested panels as well)
          $script:panelList = @()
          function Collect-Panels {
            param($node)
            if (-not $node) { return }
            if ($node.PSObject.Properties.Name -contains 'panels' -and $node.panels) {
              foreach ($child in $node.panels) { Collect-Panels $child }
            } else {
              $script:panelList += ,$node
            }
          }
          if ($doc) { Collect-Panels $doc }

          foreach ($p in $script:panelList) {
            if (-not $p) { continue }
            # Ensure fieldConfig/overrides
            if (-not $p.fieldConfig) { $p | Add-Member -MemberType NoteProperty -Name fieldConfig -Value (@{ defaults = @{}; overrides = @() }) }
            if (-not $p.fieldConfig.overrides) { $p.fieldConfig.overrides = @() }

            $title = [string]$p.title
            $addOverride = {
              param($matcherId, $matcherOpt, $axis = 'right', $axisLabel = $null)
              # Avoid duplicate overrides with same matcher
              $exists = $false
              foreach ($ov in $p.fieldConfig.overrides) {
                if ($ov.matcher -and $ov.matcher.id -eq $matcherId -and $ov.matcher.options -eq $matcherOpt) { $exists = $true; break }
              }
              if (-not $exists) {
                $ov = [pscustomobject]@{
                  matcher = [pscustomobject]@{ id = $matcherId; options = $matcherOpt }
                  properties = @(
                    [pscustomobject]@{ id = 'custom.axisPlacement'; value = $axis },
                    [pscustomobject]@{ id = 'custom.axisDisplayMode'; value = 'labels' }
                  )
                }
                if ($axisLabel) { $ov.properties += ,([pscustomobject]@{ id = 'custom.axisLabel'; value = $axisLabel }) }
                # Reserve space so both axes are visible even with overlapping scales
                $axisWidth = if ($axis -eq 'right') { 56 } else { 52 }
                $ov.properties += ,([pscustomobject]@{ id = 'custom.axisWidth'; value = $axisWidth })
                $p.fieldConfig.overrides += ,$ov
                try { Write-Host ("  Added axis override: panel='{0}' matcher='{1}' opts='{2}' axis='{3}'" -f $title, $matcherId, $matcherOpt, $axis) -ForegroundColor DarkCyan } catch {}
              }
            }

            # Delta panels: send PE to right axis for all indices
            $hasDelta = $false
            if ($p.targets) {
              foreach ($t in $p.targets) {
                if ($t -and $t.columns) {
                  foreach ($c in $t.columns) {
                    $sel = [string]$c.selector
                    if ($sel -match 'pe_delta|ce_delta') { $hasDelta = $true; break }
                  }
                }
                if ($hasDelta) { break }
              }
            }
            if ($hasDelta -or ($title -match 'Delta \(CE/PE\)')) {
              # Avoid using \b which becomes a backspace in JSON; use a boundary-safe pattern instead
              & $addOverride 'byRegexp' '(?:^|[^A-Za-z])PE(?:[^A-Za-z]|$)' 'right' 'PE'
              & $addOverride 'byRegexp' '(?:^|[^A-Za-z])CE(?:[^A-Za-z]|$)' 'left' 'CE'
            }

            # NS pair: SENSEX series on right for Theta/Vega/Gamma/Rho
            if ($title -match 'NIFTY \+ SENSEX' -and ($title -match 'Theta' -or $title -match 'Vega' -or $title -match 'Gamma' -or $title -match 'Rho')) {
              & $addOverride 'byRegexp' '.*SENSEX.*'
            }

            # BF pair: FINNIFTY series on right for Theta/Vega/Gamma/Rho
            if ($title -match 'BANKNIFTY \+ FINNIFTY' -and ($title -match 'Theta' -or $title -match 'Vega' -or $title -match 'Gamma' -or $title -match 'Rho')) {
              & $addOverride 'byRegexp' '.*FINNIFTY.*'
            }
          }

          # Write back updated JSON (staged + optional persisted copy in repo for robustness)
          $jsonOut = $doc | ConvertTo-Json -Depth 100
          Write-TextNoBom -Path $destPath -Content $jsonOut
          try {
            $repoPatched = Join-Path $RepoRoot 'grafana/dashboards/generated/g6_analytics_infinity_v3_patched.json'
            Write-TextNoBom -Path $repoPatched -Content $jsonOut
            Write-Host ("Persisted patched dashboard to repo: {0}" -f $repoPatched) -ForegroundColor DarkGreen
          } catch { Write-Host ("Warning: failed to persist patched dashboard into repo: {0}" -f $_.Exception.Message) -ForegroundColor DarkYellow }
          Write-Host 'Applied axis overrides to staged v3 dashboard.' -ForegroundColor DarkGreen

          # Do not persist a copy into the repo when staging external v3
        }
      } catch {
        Write-Host ("Warning: failed to apply axis overrides: {0}" -f $_.Exception.Message) -ForegroundColor DarkYellow
      }
    } catch {
      Write-Host ("Warning: failed to stage external v3 dashboard from {0}: {1}" -f $V3Path, $_.Exception.Message) -ForegroundColor DarkYellow
    }
  }
  $generatedNames = @{}
  if (Test-Path $dashboardsSrc) { Get-ChildItem -Path $dashboardsSrc -Filter *.json -File -ErrorAction SilentlyContinue | ForEach-Object { $generatedNames[$_.Name] = $true } }
  if (Test-Path $dashboardsLegacy) {
    Get-ChildItem -Path $dashboardsLegacy -Filter *.json -File -ErrorAction SilentlyContinue |
      Where-Object { -not $generatedNames.ContainsKey($_.Name) } |
      ForEach-Object { Copy-IfNotExcluded -File $_ }
  }
} catch { Write-Host "Warning: Could not restage dashboards: $($_.Exception.Message)" -ForegroundColor DarkYellow }

# Datasource provisioning (ensure Infinity + Prom are present)
try {
  $promUrl = if ($env:G6_PROM_URL) { $env:G6_PROM_URL } else { 'http://127.0.0.1:9090' }
  $dsYaml = @"
apiVersion: 1

datasources:
  - name: Prometheus
    type: prometheus
    access: proxy
    uid: PROM
    url: '$promUrl'
    isDefault: true
    editable: true
  - name: Infinity
    type: yesoreyeram-infinity-datasource
    access: proxy
    uid: INFINITY
    editable: true
    jsonData:
      allowedHosts:
        - http://127.0.0.1:9500
        - 127.0.0.1:9500
        - http://localhost:9500
"@
  Write-TextNoBom -Path (Join-Path $dsDir 'prometheus.yml') -Content $dsYaml

  $dbYaml = @"
apiVersion: 1

providers:
  - name: G6
    type: file
    disableDeletion: true
    editable: true
    options:
      path: '$(($dbFilteredDir -replace "\\","/"))'
"@
  Write-TextNoBom -Path (Join-Path $dbDir 'dashboards.yml') -Content $dbYaml
} catch { Write-Host "Warning: Could not ensure datasource/dashboard providers." -ForegroundColor DarkYellow }

# 3) Resolve Grafana and start only Grafana with provisioning pointed to our staged dir
function Resolve-Grafana {
  $bases = @('C:\Program Files\GrafanaLabs\grafana','C:\Grafana','C:\Program Files','C:\Program Files (x86)')
  foreach ($b in $bases) {
    if (-not (Test-Path $b)) { continue }
    $dirs = Get-ChildItem -Path $b -Directory -ErrorAction SilentlyContinue | Where-Object { $_.Name -like 'grafana*' }
    foreach ($d in ($dirs | Sort-Object LastWriteTime -Descending)) {
      $exe = Join-Path (Join-Path $d.FullName 'bin') 'grafana-server.exe'
      if (Test-Path $exe) { return [pscustomobject]@{ Home=(Split-Path (Split-Path $exe -Parent) -Parent); Exe=$exe } }
    }
  }
  return $null
}

$graf = Resolve-Grafana
if (-not $graf) { Write-Host 'Grafana not found. Install Grafana.' -ForegroundColor Red; exit 4 }

$dataDir = if ($env:G6_GRAFANA_DATA_DIR -and $env:G6_GRAFANA_DATA_DIR.Trim().Length -gt 0) { $env:G6_GRAFANA_DATA_DIR } else { Join-Path $GrafanaDataRoot 'data' }
$logsDir = Join-Path $GrafanaDataRoot 'log'
$pluginsDir = Join-Path $GrafanaDataRoot 'plugins'
Ensure-Dir -Path $dataDir; Ensure-Dir -Path $logsDir; Ensure-Dir -Path $pluginsDir
[Environment]::SetEnvironmentVariable('GF_SERVER_HTTP_PORT',"$GrafanaPort")
[Environment]::SetEnvironmentVariable('GF_SERVER_HTTP_ADDR','127.0.0.1')
[Environment]::SetEnvironmentVariable('GF_PATHS_HOME',$graf.Home)
[Environment]::SetEnvironmentVariable('GF_PATHS_DATA', $dataDir)
[Environment]::SetEnvironmentVariable('GF_PATHS_LOGS', $logsDir)
[Environment]::SetEnvironmentVariable('GF_PATHS_PLUGINS', $pluginsDir)
[Environment]::SetEnvironmentVariable('GF_PATHS_PROVISIONING', $provRoot)
# Keep plugin footprint minimal; Infinity only (no form/business plugins)
[Environment]::SetEnvironmentVariable('GF_INSTALL_PLUGINS','yesoreyeram-infinity-datasource')

# Default to passwordless unless explicitly suppressed via -DisablePassword:$false
$disablePasswordEffective = $true
if ($PSBoundParameters.ContainsKey('DisablePassword')) { $disablePasswordEffective = [bool]$DisablePassword }
if ($disablePasswordEffective) {
  [Environment]::SetEnvironmentVariable('GF_AUTH_ANONYMOUS_ENABLED','true')
  [Environment]::SetEnvironmentVariable('GF_AUTH_ANONYMOUS_ORG_ROLE','Admin')
  [Environment]::SetEnvironmentVariable('GF_AUTH_DISABLE_LOGIN_FORM','true')
  [Environment]::SetEnvironmentVariable('GF_AUTH_BASIC_ENABLED','false')
  [Environment]::SetEnvironmentVariable('GF_USERS_ALLOW_SIGN_UP','false')
  [Environment]::SetEnvironmentVariable('GF_SECURITY_ALLOW_EMBEDDING','true')
}

Write-Host ("Starting Grafana on :{0}" -f $GrafanaPort) -ForegroundColor Green
$gOut = Join-Path $logsDir 'grafana_stdout.log'
$gErr = Join-Path $logsDir 'grafana_stderr.log'
$argsStr = "--homepath `"$($graf.Home)`""
Start-Process -FilePath $graf.Exe -ArgumentList $argsStr -WorkingDirectory $graf.Home -RedirectStandardOutput $gOut -RedirectStandardError $gErr -WindowStyle Minimized

# 4) Wait for Grafana to be up, then open Analytics
$health = "http://127.0.0.1:$GrafanaPort/api/health"
Write-Host "Waiting for Grafana to be ready at $health ..." -ForegroundColor Gray
$deadline = (Get-Date).AddSeconds(90)
$ready = $false
while ((Get-Date) -lt $deadline) {
  try { $r = Invoke-WebRequest -UseBasicParsing -Uri $health -TimeoutSec 3; if ($r.StatusCode -eq 200) { $ready = $true; break } } catch {}
  Start-Sleep -Milliseconds 750
}
if (-not $ready) { Write-Host "Grafana did not report ready within timeout. Opening anyway..." -ForegroundColor DarkYellow }

# Poll dashboards and pick best available UID
# Default: prefer v4 -> v3 -> v2 -> v1
# -UseV3: prefer v3 (and v4 may be excluded above)
# -UseV1: fall back to original
if ($UseV1) {
  $preferredUids = @('g6-analytics-infinity')
} else {
  # Prefer v3 by default; v4 intentionally deprioritized/omitted
  $preferredUids = @('g6-analytics-infinity-v3','g6-analytics-infinity-v2','g6-analytics-infinity')
}
$chosenUid = $preferredUids[0]
$provSeconds = if ($UseV3) { 90 } else { 60 }
$provDeadline = (Get-Date).AddSeconds($provSeconds)
foreach ($uid in $preferredUids) {
  $dashApi = "http://127.0.0.1:$GrafanaPort/api/dashboards/uid/$uid"
  Write-Host "Checking for dashboard UID '$uid'..." -ForegroundColor Gray
  $found = $false
  $localSeconds = if ($UseV3) { 30 } else { 15 }
  $deadlineLocal = (Get-Date).AddSeconds($localSeconds)
  while ((Get-Date) -lt $deadlineLocal) {
    try { $dr = Invoke-WebRequest -UseBasicParsing -Uri $dashApi -TimeoutSec 3; if ($dr.StatusCode -eq 200) { $found = $true; break } } catch {}
    Start-Sleep -Milliseconds 750
  }
  if ($found) { $chosenUid = $uid; break }
}

$qsParts = @()
$qsStr = [string]::Join('&', $qsParts)
$dashUrl = ("http://127.0.0.1:{0}/d/{1}/{2}?{3}" -f $GrafanaPort, [string]$chosenUid, [string]$chosenUid, $qsStr)
Write-Host "Opening $dashUrl" -ForegroundColor Green
try { Start-Process $dashUrl | Out-Null } catch {}
