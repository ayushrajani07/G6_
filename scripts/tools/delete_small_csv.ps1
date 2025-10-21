param(
    [Parameter(Mandatory=$true)] [string]$Root,
    [int]$MinDataRows = 20,
    [string]$LogPath
)

if (-not (Test-Path -LiteralPath $Root)) {
    Write-Error "Root not found: $Root"
    exit 1
}

$deleted = @()
$skipped = @()

$files = Get-ChildItem -Path $Root -Recurse -Filter *.csv -File -ErrorAction SilentlyContinue
foreach ($f in $files) {
    $lines = 0
    try {
        $reader = [System.IO.File]::OpenText($f.FullName)
        try {
            # Read up to MinDataRows + 1 (header) lines and stop early
            $limit = $MinDataRows + 1
            while (($null -ne $reader.ReadLine()) -and ($lines -lt $limit)) { $lines++ }
        } finally {
            $reader.Close()
        }
    } catch {
        Write-Warning "Failed to read '$($f.FullName)': $_"
        continue
    }
    $dataRows = [Math]::Max($lines - 1, 0)
    if ($dataRows -lt $MinDataRows) {
        try {
            Remove-Item -LiteralPath $f.FullName -Force
            $deleted += [pscustomobject]@{ path=$f.FullName; data_rows=$dataRows }
        } catch {
            Write-Warning "Failed to delete '$($f.FullName)': $_"
        }
    } else {
        $skipped += [pscustomobject]@{ path=$f.FullName; data_rows=$dataRows }
    }
}

if ($LogPath) {
    try { $deleted | Export-Csv -Path $LogPath -NoTypeInformation -Encoding UTF8 } catch {}
}

Write-Output ("Deleted: {0} file(s)" -f $deleted.Count)
Write-Output ("Skipped: {0} file(s)" -f $skipped.Count)