[CmdletBinding()]
param(
    [string[]]$Plugin,
    [string]$PackagesDir = (Join-Path $env:APPDATA "Sublime Text\Packages"),
    [switch]$SkipDependencies
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot

function ConvertFrom-SublimeJson {
    param([Parameter(Mandatory)][string]$Text)

    # Strip // line comments and /* */ block comments outside double-quoted strings,
    # then remove trailing commas before ] or } so Windows PowerShell 5.1 ConvertFrom-Json succeeds.
    $sb = New-Object System.Text.StringBuilder
    $len = $Text.Length
    $i = 0
    $inString = $false

    while ($i -lt $len) {
        $ch = $Text[$i]
        if ($inString) {
            [void]$sb.Append($ch)
            if ($ch -eq '\' -and ($i + 1) -lt $len) {
                $i++
                [void]$sb.Append($Text[$i])
            } elseif ($ch -eq '"') {
                $inString = $false
            }
            $i++
            continue
        }

        if ($ch -eq '"') {
            $inString = $true
            [void]$sb.Append($ch)
            $i++
            continue
        }

        if ($ch -eq '/' -and ($i + 1) -lt $len -and $Text[$i + 1] -eq '/') {
            $i += 2
            while ($i -lt $len -and $Text[$i] -ne "`n") { $i++ }
            continue
        }

        if ($ch -eq '/' -and ($i + 1) -lt $len -and $Text[$i + 1] -eq '*') {
            $i += 2
            while (($i + 1) -lt $len -and -not ($Text[$i] -eq '*' -and $Text[$i + 1] -eq '/')) { $i++ }
            $i += 2
            continue
        }

        [void]$sb.Append($ch)
        $i++
    }

    # Remove trailing commas outside string literals
    $noComments = $sb.ToString()
    $clean = New-Object System.Text.StringBuilder
    $len = $noComments.Length
    $i = 0
    $inString = $false

    while ($i -lt $len) {
        $ch = $noComments[$i]
        if ($inString) {
            [void]$clean.Append($ch)
            if ($ch -eq '\' -and ($i + 1) -lt $len) {
                $i++
                [void]$clean.Append($noComments[$i])
            } elseif ($ch -eq '"') {
                $inString = $false
            }
            $i++
            continue
        }

        if ($ch -eq '"') {
            $inString = $true
            [void]$clean.Append($ch)
            $i++
            continue
        }

        if ($ch -eq ',') {
            $j = $i + 1
            while ($j -lt $len -and [char]::IsWhiteSpace($noComments[$j])) { $j++ }
            if ($j -lt $len -and ($noComments[$j] -eq ']' -or $noComments[$j] -eq '}')) {
                $i++
                continue
            }
        }

        [void]$clean.Append($ch)
        $i++
    }

    return ($clean.ToString() | ConvertFrom-Json)
}

function Sync-PackageControlDependencies {
    param(
        [Parameter(Mandatory)][string]$PluginDir,
        [Parameter(Mandatory)][string]$PackagesRoot
    )

    $depsFile = Join-Path $PluginDir "package-control-deps.json"
    if (-not (Test-Path -LiteralPath $depsFile)) {
        return
    }

    $depsJson = ConvertFrom-SublimeJson -Text ([System.IO.File]::ReadAllText($depsFile, [System.Text.UTF8Encoding]::new($false)))
    $required = @()
    if ($null -ne $depsJson -and $null -ne $depsJson.installed_packages) {
        $required = @($depsJson.installed_packages | Where-Object { $_ -is [string] -and $_.Trim().Length -gt 0 } | ForEach-Object { $_.Trim() })
    }
    if ($required.Count -eq 0) {
        return
    }

    $sublimeDataDir = Split-Path -Parent $PackagesRoot
    $pcPackageZip = Join-Path $sublimeDataDir "Installed Packages\Package Control.sublime-package"
    $pcPackageDir = Join-Path $PackagesRoot "Package Control"
    $hasPackageControl = (Test-Path -LiteralPath $pcPackageZip) -or (Test-Path -LiteralPath $pcPackageDir)

    $userDir = Join-Path $PackagesRoot "User"
    $pcSettingsPath = Join-Path $userDir "Package Control.sublime-settings"

    $settingsObj = [ordered]@{}
    if (Test-Path -LiteralPath $pcSettingsPath) {
        $raw = [System.IO.File]::ReadAllText($pcSettingsPath, [System.Text.UTF8Encoding]::new($false))
        if ($raw.Trim().Length -gt 0) {
            $parsed = ConvertFrom-SublimeJson -Text $raw
            if ($null -ne $parsed) {
                foreach ($prop in $parsed.PSObject.Properties) {
                    $settingsObj[$prop.Name] = $prop.Value
                }
            }
        }
    }

    $existing = New-Object System.Collections.Generic.List[string]
    if ($settingsObj.Contains("installed_packages") -and $null -ne $settingsObj["installed_packages"]) {
        foreach ($pkg in @($settingsObj["installed_packages"])) {
            if ($pkg -is [string] -and $pkg.Trim().Length -gt 0) {
                [void]$existing.Add($pkg)
            }
        }
    }

    $added = New-Object System.Collections.Generic.List[string]
    foreach ($dep in $required) {
        if ($existing -contains $dep) {
            Write-Host "[dep] $dep already configured in Package Control.sublime-settings" -ForegroundColor DarkCyan
        } else {
            [void]$existing.Add($dep)
            [void]$added.Add($dep)
        }
    }

    if ($added.Count -gt 0) {
        if (-not (Test-Path -LiteralPath $userDir)) {
            New-Item -ItemType Directory -Path $userDir | Out-Null
        }
        $sorted = @($existing | Sort-Object -Unique)
        $settingsObj["installed_packages"] = $sorted
        $jsonOut = ($settingsObj | ConvertTo-Json -Depth 10) + "`n"
        [System.IO.File]::WriteAllText($pcSettingsPath, $jsonOut, [System.Text.UTF8Encoding]::new($false))
        $joined = ($added -join ", ")
        Write-Host "[dep] Added $joined to Package Control.sublime-settings (restart Sublime Text to install)" -ForegroundColor Green
    }

    if (-not $hasPackageControl) {
        $joinedReq = ($required -join ", ")
        Write-Warning "Package Control was not detected in $sublimeDataDir. Install Package Control in Sublime Text and restart so dependencies ($joinedReq) install automatically."
    }
}

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
        } else {
            throw "Target path already exists and is not a junction/symlink: $Target"
        }
    } else {
        New-Item -ItemType Junction -Path $Target -Target $Dir.FullName | Out-Null
        # Touch top-level plugin files so a running Sublime Text instance hot-loads immediately
        Get-ChildItem -LiteralPath $Dir.FullName -File | ForEach-Object {
            $_.LastWriteTime = Get-Date
        }
        Write-Host "[linked] $($Dir.Name) -> $($Dir.FullName)" -ForegroundColor Green
    }

    if (-not $SkipDependencies) {
        Sync-PackageControlDependencies -PluginDir $Dir.FullName -PackagesRoot $PackagesDir
    }
}
