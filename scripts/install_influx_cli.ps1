param(
  [string]$Version = 'latest',
  [string]$InstallDir = 'C:\influxdata\influx-cli'
)

${ErrorActionPreference} = 'Stop'
try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 } catch {}
Write-Host ("[install] Influx v2 CLI target version {0}" -f $Version) -ForegroundColor Cyan
if (-not (Test-Path $InstallDir)) { New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null }

$zipPath = Join-Path $env:TEMP ("influx-cli-{0}.zip" -f ($Version -replace '[^0-9\.]+','any'))

# Known good versions from GitHub releases (Windows zip exists)
$knownGood = @(
  '2.7.5','2.7.4','2.7.3','2.7.1',
  '2.6.1','2.6.0','2.5.0','2.4.0','2.3.0','2.2.1'
)

# Build the version list to try
if ($Version -and $Version -ne 'latest') {
  $versionsToTry = @($Version) + $knownGood
} else {
  $versionsToTry = $knownGood
}
$versionsToTry = $versionsToTry | Select-Object -Unique

# Attempt multiple URL patterns (vendor CDN + GitHub) and fallback versions if needed
$patterns = @(
  # Influx CDN historical patterns
  'https://dl.influxdata.com/influxdb/releases/influxdb2-client-{0}-windows-amd64.zip',
  'https://dl.influxdata.com/influxdb/releases/influxdb2-client-{0}-windows-x86_64.zip',
  'https://dl.influxdata.com/influxdb/releases/influxdb2-client-{0}-windows.zip',
  # GitHub releases patterns
  'https://github.com/influxdata/influx-cli/releases/download/v{0}/influxdb2-client-{0}-windows-amd64.zip',
  'https://github.com/influxdata/influx-cli/releases/download/v{0}/influxdb2-client-{0}_windows_amd64.zip'
)

$downloaded = $false
foreach ($ver in $versionsToTry) {
  foreach ($pat in $patterns) {
    $url = ($pat -f $ver)
    try {
      Write-Host ("[install] Trying download: {0}" -f $url) -ForegroundColor DarkCyan
      Invoke-WebRequest -Uri $url -OutFile $zipPath -UseBasicParsing -ErrorAction Stop
      $downloaded = $true
      Write-Host ("[install] Downloaded CLI {0}" -f $ver) -ForegroundColor Green
      break
    } catch {
      Write-Host ("[install] Not found: {0}" -f $url) -ForegroundColor DarkYellow
      continue
    }
  }
  if ($downloaded) { break }
}

if (-not $downloaded) {
  throw "Unable to download influx v2 CLI automatically. Try a manual download from https://github.com/influxdata/influx-cli/releases (pick Windows amd64 zip) and extract into $InstallDir."
}

Write-Host "[install] Extracting..." -ForegroundColor DarkCyan
Expand-Archive -Path $zipPath -DestinationPath $InstallDir -Force

$exe = Get-ChildItem -Path $InstallDir -Recurse -Filter influx.exe -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty FullName
if (-not $exe) { throw "influx.exe not found after extract in $InstallDir" }
Write-Host ("[install] CLI installed at: {0}" -f $exe) -ForegroundColor Green

# Add to PATH (User scope)
$cliDir = Split-Path $exe -Parent
[System.Environment]::SetEnvironmentVariable('Path', $env:Path + ';' + $cliDir, 'User')
Write-Host ("[install] Added to PATH (User): {0}" -f $cliDir) -ForegroundColor Green

# Basic connectivity test (no auth) with proxy bypass for localhost
$env:NO_PROXY = 'localhost,127.0.0.1'
$env:HTTP_PROXY = ''
$env:HTTPS_PROXY = ''

Write-Host "[install] CLI version:" -ForegroundColor Cyan
& $exe version

Write-Host "[install] CLI ping (http://127.0.0.1:8086):" -ForegroundColor Cyan
& $exe ping --host http://127.0.0.1:8086

Write-Host "[install] Done. Open a new PowerShell window to pick up PATH if needed." -ForegroundColor Cyan
