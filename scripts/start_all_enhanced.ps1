<#
DEPRECATED SCRIPT SHIM

This script (start_all_enhanced.ps1) has been deprecated in favor of the unified
start_all.ps1 launcher. It will be removed after 2025-10-31.

Rationale:
- Reduced duplication (single orchestration entrypoint)
- Simplified troubleshooting guidance (docs now reference start_all.ps1)

Behavior:
- Emits a deprecation banner (always)
- Forwards all arguments to start_all.ps1 (best-effort)
- Exits with the same exit code as the invoked script

Suppression:
Set $env:G6_SUPPRESS_DEPRECATIONS = 1 to hide this banner (global policy).
#>

param([Parameter(ValueFromRemainingArguments=$true)][string[]]$Rest)

$ErrorActionPreference = 'Stop'

if (-not $env:G6_SUPPRESS_DEPRECATIONS) {
    Write-Host "[DEPRECATED] start_all_enhanced.ps1 -> Use start_all.ps1 (removal after 2025-10-31)" -ForegroundColor Yellow
}

$target = Join-Path (Get-Location) 'scripts\start_all.ps1'
if (-not (Test-Path $target)) {
    Write-Host "❌ Cannot locate scripts/start_all.ps1 (expected alongside this shim)." -ForegroundColor Red
    exit 2
}

Write-Host "→ Delegating to start_all.ps1 $($Rest -join ' ')" -ForegroundColor Cyan

# Re-invoke PowerShell with same execution policy bypass for convenience
$argsList = @('-ExecutionPolicy','Bypass','-File', $target) + $Rest
powershell.exe @argsList
$code = $LASTEXITCODE
exit $code