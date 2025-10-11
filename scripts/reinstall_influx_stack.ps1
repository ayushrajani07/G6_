param(
  [string]$ServerVersion = '2.7.5',
  [string]$ServerInstallDir = 'C:\Program Files\InfluxData\influxdb2',
  [switch]$InstallService,
  [switch]$StartAfterInstall,
  [switch]$PurgeData,
  [string]$CliVersion = 'latest'
)

$ErrorActionPreference = 'Stop'
try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 } catch {}

function Stop-And-Delete-Service {
  param([string]$Name)
  try {
    $svc = Get-Service -Name $Name -ErrorAction SilentlyContinue
    if ($svc) {
      Write-Host ("[cleanup] Stopping service: {0}" -f $Name) -ForegroundColor Yellow
      if ($svc.Status -ne 'Stopped') { Stop-Service -Name $Name -Force -ErrorAction SilentlyContinue }
      Start-Sleep -Milliseconds 500
      Write-Host ("[cleanup] Deleting service: {0}" -f $Name) -ForegroundColor Yellow
      sc.exe delete $Name | Out-Null
    }
  } catch { Write-Host ("[cleanup] Service cleanup error for {0}: {1}" -f $Name, $_.Exception.Message) -ForegroundColor DarkYellow }
}

function Kill-Processes {
  param([string[]]$ProcessNames)
  foreach ($pn in $ProcessNames) {
    try {
      Get-Process -Name $pn -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    } catch {}
  }
}

function Remove-IfExists {
  param([string]$Path, [switch]$Recurse)
  try {
    if (Test-Path $Path) {
      Write-Host ("[cleanup] Removing: {0}" -f $Path) -ForegroundColor Yellow
      if ($Recurse) { Remove-Item -Recurse -Force -LiteralPath $Path -ErrorAction SilentlyContinue }
      else { Remove-Item -Force -LiteralPath $Path -ErrorAction SilentlyContinue }
    }
  } catch { Write-Host ("[cleanup] Failed to remove {0}: {1}" -f $Path, $_.Exception.Message) -ForegroundColor DarkYellow }
}

Write-Host ("[reinstall] Preparing to reinstall InfluxDB v{0} and CLI (CliVersion={1})" -f $ServerVersion,$CliVersion) -ForegroundColor Cyan

# 1) Stop/delete likely services
$svcNames = @('influxdb','InfluxDB','influxdb2','InfluxDB2','influxd')
foreach ($s in $svcNames) { Stop-And-Delete-Service -Name $s }

# 2) Kill stray processes
Kill-Processes -ProcessNames @('influxd','influx')

# 3) Remove previous installs (binaries)
$binDirs = @(
  'C:\Program Files\InfluxData\influxdb',
  'C:\Program Files\InfluxData\influxdb2',
  'C:\influxdata\influxdb',
  'C:\influxdata\influxdb2',
  'C:\influxdata\influx-cli'
)
foreach ($d in $binDirs) { Remove-IfExists -Path $d -Recurse }

# 4) Optionally purge data (disabled by default for safety)
if ($PurgeData) {
  $dataDirs = @('C:\InfluxDB','C:\influxdb','C:\ProgramData\InfluxDB')
  foreach ($d in $dataDirs) { Remove-IfExists -Path $d -Recurse }
  Write-Host "[reinstall] Data purged (C:\InfluxDB, etc.)" -ForegroundColor Yellow
} else {
  Write-Host "[reinstall] Preserving existing data directories (run with -PurgeData to delete)" -ForegroundColor DarkCyan
}

# 5) Install InfluxDB v2 server (with URL and version fallbacks)
if (-not (Test-Path $ServerInstallDir)) { New-Item -ItemType Directory -Force -Path $ServerInstallDir | Out-Null }
$srvZip = Join-Path $env:TEMP ("influxdb2-{0}.zip" -f $ServerVersion)

# Build fallback versions
$knownGood = @('2.7.5','2.7.4','2.7.1')
$versionsToTry = @()
if ($ServerVersion -and $ServerVersion -ne '') { $versionsToTry += $ServerVersion }
$versionsToTry += $knownGood
$versionsToTry = $versionsToTry | Select-Object -Unique

# URL patterns to try (CDN and GitHub)
$patterns = @(
  'https://dl.influxdata.com/influxdb/releases/influxdb2-{0}-windows-amd64.zip',
  'https://dl.influxdata.com/influxdb/releases/influxdb2-{0}-windows-x86_64.zip',
  'https://github.com/influxdata/influxdb/releases/download/v{0}/influxdb2-{0}-windows-amd64.zip'
)

$downloaded = $false
foreach ($ver in $versionsToTry) {
  foreach ($pat in $patterns) {
    $url = ($pat -f $ver)
    try {
      Write-Host ("[reinstall] Trying server download: {0}" -f $url) -ForegroundColor DarkCyan
      Invoke-WebRequest -Uri $url -OutFile $srvZip -UseBasicParsing -ErrorAction Stop
      Write-Host ("[reinstall] Downloaded server {0}" -f $ver) -ForegroundColor Green
      $downloaded = $true
      break
    } catch {
      Write-Host ("[reinstall] Not found: {0}" -f $url) -ForegroundColor DarkYellow
    }
  }
  if ($downloaded) { break }
}

if (-not $downloaded) { throw "Unable to download InfluxDB v2 server. Try manual download from https://github.com/influxdata/influxdb/releases and re-run." }

Write-Host "[reinstall] Extracting server..." -ForegroundColor DarkCyan
Expand-Archive -Path $srvZip -DestinationPath $ServerInstallDir -Force

$influxd = Get-ChildItem -Path $ServerInstallDir -Recurse -Filter influxd.exe -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty FullName
if (-not $influxd) { throw "influxd.exe not found after extract in $ServerInstallDir" }
Write-Host ("[reinstall] Server installed at: {0}" -f $influxd) -ForegroundColor Green

# 6) Update env override for downstream scripts
[Environment]::SetEnvironmentVariable('G6_INFLUXD_EXE', $influxd, 'User')
Write-Host ("[reinstall] Set G6_INFLUXD_EXE (User) to: {0}" -f $influxd) -ForegroundColor Green

# 7) Optionally install as Windows service
if ($InstallService) {
  $svcName = 'influxdb2'
  $bin = '"' + $influxd + '"'
  Write-Host ("[reinstall] Installing service: {0}" -f $svcName) -ForegroundColor DarkCyan
  New-Service -Name $svcName -BinaryPathName $bin -DisplayName 'InfluxDB 2' -StartupType Automatic -ErrorAction SilentlyContinue | Out-Null
  Start-Service -Name $svcName -ErrorAction SilentlyContinue
}

# 8) Install CLI (using repo script for resilience)
$cliScript = Join-Path (Split-Path $PSScriptRoot -Parent) 'scripts\install_influx_cli.ps1'
if (Test-Path $cliScript) {
  Write-Host "[reinstall] Installing CLI via helper script..." -ForegroundColor DarkCyan
  if ($CliVersion -and $CliVersion -ne 'latest') {
    powershell -ExecutionPolicy Bypass -File $cliScript -Version $CliVersion
  } else {
    powershell -ExecutionPolicy Bypass -File $cliScript
  }
} else {
  # Fallback direct CLI install
  $cliVer = if ($CliVersion -eq 'latest') { '2.7.5' } else { $CliVersion }
  $cliUrl = "https://dl.influxdata.com/influxdb/releases/influxdb2-client-$cliVer-windows-amd64.zip"
  $cliZip = Join-Path $env:TEMP ("influx-cli-{0}.zip" -f $cliVer)
  $cliDir = 'C:\influxdata\influx-cli'
  if (-not (Test-Path $cliDir)) { New-Item -ItemType Directory -Force -Path $cliDir | Out-Null }
  Write-Host ("[reinstall] Downloading CLI: {0}" -f $cliUrl) -ForegroundColor DarkCyan
  Invoke-WebRequest -Uri $cliUrl -OutFile $cliZip -UseBasicParsing
  Expand-Archive -Path $cliZip -DestinationPath $cliDir -Force
  $influxCli = Get-ChildItem -Path $cliDir -Recurse -Filter influx.exe | Select-Object -First 1 -ExpandProperty FullName
  if ($influxCli) {
    [Environment]::SetEnvironmentVariable('Path', $env:Path + ';' + (Split-Path $influxCli -Parent), 'User')
    Write-Host ("[reinstall] CLI installed at: {0}" -f $influxCli) -ForegroundColor Green
  }
}

Write-Host "[reinstall] Complete." -ForegroundColor Green
if ($StartAfterInstall) {
  Write-Host "[reinstall] Starting influxd (foreground). Press Ctrl+C to stop." -ForegroundColor Yellow
  & $influxd
}
