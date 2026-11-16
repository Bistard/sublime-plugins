[CmdletBinding()]
param(
    [string[]]$Plugin,
    [string]$PackagesDir = (Join-Path $env:APPDATA "Sublime Text\Packages")
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot

$Candidates = Get-ChildItem -LiteralPath $RepoRoot -Directory | Where-Object {
    $_.Name -notmatch '^(\.|scripts)' -and (
        (Test-Path (Join-Path $_.FullName ".python-version")) -or
        @(Get-ChildItem -LiteralPath $_.FullName -Filter "*.sublime-*" -File).Count -gt 0
    )
}

if ($Plugin -and $Plugin.Count -gt 0) {
    $Candidates = $Candidates | Where-Object { $Plugin -contains $_.Name }
}

foreach ($Dir in $Candidates) {
    $Target = Join-Path $PackagesDir $Dir.Name
    if (-not (Test-Path -LiteralPath $Target)) {
        Write-Host "[skip] $($Dir.Name) is not installed in Packages." -ForegroundColor DarkGray
        continue
    }

    $Item = Get-Item -LiteralPath $Target -Force
    if (-not ($Item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw "Refusing to remove non-junction directory: $Target"
    }

    # Remove junction itself without touching target source files
    $Item.Delete()
    Write-Host "[unlinked] $($Dir.Name)" -ForegroundColor Yellow
}
