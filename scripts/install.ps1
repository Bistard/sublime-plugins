[CmdletBinding()]
param(
    [string[]]$Plugin,
    [string]$PackagesDir = (Join-Path $env:APPDATA "Sublime Text\Packages")
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot

if (-not (Test-Path -LiteralPath $PackagesDir)) {
    throw "Sublime Text Packages directory not found at: $PackagesDir"
}

$Candidates = Get-ChildItem -LiteralPath $RepoRoot -Directory | Where-Object {
    $_.Name -notmatch '^(\.|scripts)' -and (
        (Test-Path (Join-Path $_.FullName ".python-version")) -or
        @(Get-ChildItem -LiteralPath $_.FullName -Filter "*.sublime-*" -File).Count -gt 0
    )
}

if ($Plugin -and $Plugin.Count -gt 0) {
    $Candidates = $Candidates | Where-Object { $Plugin -contains $_.Name }
}

if (-not $Candidates) {
    Write-Warning "No matching Sublime plugin directories found in $RepoRoot."
    exit 0
}

foreach ($Dir in $Candidates) {
    $Target = Join-Path $PackagesDir $Dir.Name
    if (Test-Path -LiteralPath $Target) {
        $Item = Get-Item -LiteralPath $Target -Force
        if ($Item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
            Write-Host "[skip] $($Dir.Name) already linked -> $($Item.Target)" -ForegroundColor Cyan
            continue
        }
        throw "Target path already exists and is not a junction/symlink: $Target"
    }

    New-Item -ItemType Junction -Path $Target -Target $Dir.FullName | Out-Null
    # Touch top-level plugin files so a running Sublime Text instance hot-loads immediately
    Get-ChildItem -LiteralPath $Dir.FullName -File | ForEach-Object {
        $_.LastWriteTime = Get-Date
    }
    Write-Host "[linked] $($Dir.Name) -> $($Dir.FullName)" -ForegroundColor Green
}
