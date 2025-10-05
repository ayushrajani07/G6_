<#!
.SYNOPSIS
  Interactive Git push menu for common workflows (default: push to main).

.DESCRIPTION
  Provides a text menu (or direct option via -Option) to perform routine git operations:
    1. Push to main (default)
    2. Push current branch
    3. Pull --rebase origin/<branch> then push
    4. Force-with-lease push (current branch)
    5. Create lightweight tag then push tag
    6. Push existing tag
    7. Push all tags
    8. Status & ahead/behind summary
    9. Dry-run push (no transfer)
   10. Fetch --prune
    0. Exit
  Includes safety checks for uncommitted changes & upstream existence.

.PARAMETER Option
  Optional numeric menu option to run non-interactively.

.PARAMETER Tag
  Tag name used for options that require a tag.

.PARAMETER Message
  Commit message to auto-commit staged + unstaged changes (before push) if provided.

.EXAMPLE
  ./scripts/git_push_menu.ps1                # interactive
  ./scripts/git_push_menu.ps1 -Option 1      # push to main
  ./scripts/git_push_menu.ps1 -Option 5 -Tag v0.6.0
  ./scripts/git_push_menu.ps1 -Message "chore: quick fix" -Option 1

.NOTES
  Requires git in PATH. Designed for Windows PowerShell 5.1+.
#>
param(
  [int]$Option = -1,
  [string]$Tag,
  [string]$Message
)

function Write-Section($text){ Write-Host "`n=== $text ===" -ForegroundColor Cyan }
function Fail($msg){ Write-Host "ERROR: $msg" -ForegroundColor Red; exit 1 }

# Ensure inside a git repo
if(-not (Test-Path .git)) { Fail "Not inside a git repository root." }

# Auto-commit if message provided and there are changes
$changes = git status --porcelain
if($Message){
  if($changes){
    Write-Host "Auto committing changes with message: $Message" -ForegroundColor Yellow
    git add -A || Fail "git add failed"
    git commit -m "$Message" || Write-Host "(No commit created - possibly nothing to commit)" -ForegroundColor DarkYellow
  } else {
    Write-Host "No changes to commit for provided -Message." -ForegroundColor DarkGray
  }
}

function Show-Menu {
  Write-Host "`nGit Push Menu" -ForegroundColor Green
  Write-Host "[1] Push to main (default)"
  Write-Host "[2] Push current branch"
  Write-Host "[3] Pull --rebase then push (current branch)"
  Write-Host "[4] Force-with-lease push (current branch)"
  Write-Host "[5] Create tag then push (requires -Tag)"
  Write-Host "[6] Push existing tag (requires -Tag)"
  Write-Host "[7] Push all tags"
  Write-Host "[8] Status & ahead/behind"
  Write-Host "[9] Dry-run push (current branch)"
  Write-Host "[10] Fetch --prune"
  Write-Host "[0] Exit"
}

function Require-CleanOrCommitted {
  $st = git status --porcelain
  if($st){
    Write-Host "Uncommitted changes detected:" -ForegroundColor Yellow
    $st | ForEach-Object { Write-Host "  $_" }
    $resp = Read-Host "Stage & commit automatically? (y/N)"
    if($resp -match '^[Yy]'){ git add -A; git commit -m "auto: staging before push" } else { Fail "Aborting due to uncommitted changes." }
  }
}

function AheadBehind($branch){
  git fetch origin $branch --quiet 2>$null | Out-Null
  $ahead = git rev-list --left-right --count origin/$branch...$branch 2>$null
  if($ahead){
    $parts = $ahead -split "\s+"
    if($parts.Length -eq 2){
      return "Behind:$($parts[0]) Ahead:$($parts[1])"
    }
  }
  return "(ahead/behind n/a)"
}

$CurrentBranch = (git rev-parse --abbrev-ref HEAD).Trim()
if(-not $CurrentBranch){ Fail "Unable to determine current branch." }

if($Option -lt 0){
  Show-Menu
  $Option = (Read-Host "Select option (default 1)" )
  if([string]::IsNullOrWhiteSpace($Option)){ $Option = 1 } else { $Option = [int]$Option }
}

switch($Option){
  1 { # Push to main
      Require-CleanOrCommitted
      Write-Section "Pushing to main"
      git fetch origin main
      git rebase origin/main 2>$null | Out-Null
      git push origin HEAD:main || Fail "Push failed" }
  2 { Require-CleanOrCommitted; Write-Section "Push current branch $CurrentBranch"; git push origin $CurrentBranch || Fail "Push failed" }
  3 { Require-CleanOrCommitted; Write-Section "Pull --rebase then push ($CurrentBranch)"; git fetch origin $CurrentBranch; git rebase origin/$CurrentBranch; git push origin $CurrentBranch || Fail "Push failed" }
  4 { Require-CleanOrCommitted; Write-Section "Force-with-lease push ($CurrentBranch)"; git push --force-with-lease origin $CurrentBranch || Fail "Force push failed" }
  5 { if(-not $Tag){ Fail "-Tag required for option 5" }; Require-CleanOrCommitted; Write-Section "Create tag $Tag & push"; git tag $Tag || Fail "Tag create failed"; git push origin $Tag || Fail "Tag push failed" }
  6 { if(-not $Tag){ Fail "-Tag required for option 6" }; Write-Section "Push existing tag $Tag"; git push origin $Tag || Fail "Tag push failed" }
  7 { Write-Section "Push all tags"; git push origin --tags || Fail "Push tags failed" }
  8 { Write-Section "Status"; git status; Write-Host "Branch $CurrentBranch $(AheadBehind $CurrentBranch)" -ForegroundColor Magenta }
  9 { Write-Section "Dry-run push ($CurrentBranch)"; git push --dry-run origin $CurrentBranch }
  10 { Write-Section "Fetch --prune"; git fetch --prune origin; Write-Host "Done." -ForegroundColor Green }
  0 { Write-Host "Exit."; exit 0 }
  default { Fail "Unknown option: $Option" }
}

Write-Host "Done." -ForegroundColor Green
