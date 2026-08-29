#!/usr/bin/env pwsh
# The reverse of install.ps1, for testing installs on a machine made
# clean again. Dev tooling: lives in scripts/, never served, never
# advertised. The PowerShell half of uninstall.sh.
#
# Removes only what uv owns. An otaku installed by pipx, Scoop or
# Chocolatey is reported with its owner's own uninstall command instead.
# Stories and settings in ~\.otaku are never touched, and the PATH entry
# install.ps1 may have added to HKCU\Environment is left alone -- shared
# config, harmless, and registry surgery is not worth the risk in a test
# helper.
#
#   scripts\uninstall.ps1        remove otaku
#   scripts\uninstall.ps1 -Uv    also remove uv itself: binaries, managed
#                                pythons, tools, cache -- any OTHER uv
#                                tools on the machine go with it
#
# ASCII only, for the reason install.ps1 gives at its head.

[CmdletBinding()]
param(
    [switch]$Uv
)

$ErrorActionPreference = 'Stop'
if (Test-Path variable:PSNativeCommandUseErrorActionPreference) {
    $PSNativeCommandUseErrorActionPreference = $false
}

function Say {
    param([string]$Text = '')
    Write-Host $Text
}

function Die {
    param([string]$Text)
    Write-Host "error: $Text" -ForegroundColor Red
    exit 1
}

function Find-Tool {
    param([string]$Name)
    $found = Get-Command -Name $Name -CommandType Application -ErrorAction SilentlyContinue
    if (-not $found) { return $null }
    return @($found)[0].Source
}

# Reading what a program said, safely -- the rule and the reason are
# install.ps1's, in the long comment over its own Read-Program: capturing
# a native command's stderr while $ErrorActionPreference is 'Stop' turns
# any ordinary remark into a terminating error. The exit code comes back
# in $script:LastCode.
function Read-Program {
    param([string]$Program, [string[]]$Arguments)
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $output = & $Program @Arguments 2>$null
        $script:LastCode = $LASTEXITCODE
    } catch {
        $output = $null
        $script:LastCode = -1
    } finally {
        $ErrorActionPreference = $previous
    }
    return $output
}

# Foreign owners keep their otaku: removing it is their command's job.
$otaku = Find-Tool 'otaku'
if ($otaku) {
    switch -Wildcard ($otaku) {
        '*\scoop\shims\*' { Die 'Scoop owns this otaku - remove it with: scoop uninstall otaku' }
        '*\pipx\*'        { Die 'pipx owns this otaku - remove it with: pipx uninstall otaku' }
        '*\chocolatey\*'  { Die 'Chocolatey owns this otaku - remove it with: choco uninstall otaku' }
    }
}

# NOT $uv: PowerShell tells two variables apart by name and not by case,
# so `$uv` and the `-Uv` switch above are one variable, and the path
# would be assigned straight into the switch.
$uvPath = Find-Tool 'uv'
$installed = $false
if ($uvPath) {
    $tools = Read-Program $uvPath @('tool', 'list')
    $installed = $script:LastCode -eq 0 -and (@($tools) -match '^otaku ').Count -gt 0
}

if ($installed) {
    & $uvPath tool uninstall otaku
    Say 'otaku removed'
} else {
    Say 'no uv-installed otaku found'
}

if ($Uv) {
    if ($uvPath) {
        # The order uv's own docs give: cache, managed pythons, tools,
        # then the binaries.
        Read-Program $uvPath @('cache', 'clean') | Out-Null
        foreach ($command in @('python', 'tool')) {
            $answer = Read-Program $uvPath @($command, 'dir')
            $directory = ($answer | Select-Object -First 1)
            if ($script:LastCode -eq 0 -and $directory -and (Test-Path -LiteralPath $directory.Trim())) {
                Remove-Item -LiteralPath $directory.Trim() -Recurse -Force -ErrorAction SilentlyContinue
            }
        }
        $binDir = Split-Path -Parent $uvPath
        foreach ($name in @('uv.exe', 'uvx.exe')) {
            Remove-Item -LiteralPath (Join-Path $binDir $name) -Force -ErrorAction SilentlyContinue
        }
        Say 'uv removed'
    } else {
        Say 'no uv found'
    }
}

$userHome = if ($HOME) { $HOME } else { $env:USERPROFILE }
Say "Stories and settings in $(Join-Path $userHome '.otaku') are untouched."
