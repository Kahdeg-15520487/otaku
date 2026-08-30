#!/usr/bin/env pwsh
# otaku's one-line install on Windows:
#
#     powershell -ExecutionPolicy Bypass -c "irm https://otaku.sh/install.ps1 | iex"
#
# The PowerShell half of install.sh, and what that file says holds here
# too: its canonical home is the otaku repository itself --
# github.com/enclavum/otaku -- and otaku.sh serves it from there by
# redirect, so what you audit here is exactly what the pipe runs. All it
# does is make sure uv is on the machine and then run
# `uv tool install otaku`. uv is the reason this stays short: it brings
# its own CPython when the system has none, and Windows never has one.
#
# It takes no options, because `iex` is handed a string and cannot pass
# any: a particular release, or anything else worth choosing, is
# `uv tool install otaku==0.4.0` and its own flags.
#
# It never asks for administrator and never writes outside your user
# profile. The one thing it changes that you own is the user PATH, in
# HKCU\Environment, and only when uv's bin directory is missing from it.
# An otaku that uv, pipx, Scoop or Chocolatey already put on the machine
# is reported, not replaced -- updating one is `otaku update`'s job, and
# it knows which installer to ask. Only an otaku of unknown origin is
# installed alongside, with a warning.
#
# PowerShell and not a .bat: a batch file cannot fetch over HTTPS, cannot
# add a directory to the PATH without flattening the registry's
# REG_EXPAND_SZ into a literal string, and has no error handling worth
# the name. Windows PowerShell 5.1 ships in the box on every Windows 10
# and 11, and is the floor this asks for.
#
# ASCII ONLY, on purpose: Windows PowerShell 5.1 reads a .ps1 file as the
# system ANSI codepage unless the file carries a BOM, so a saved copy of
# a UTF-8 file with an em dash in it is mojibake on most of the planet.
# The pipe above is decoded from the HTTP charset and would survive; a
# downloaded file would not, and both have to read.

$ErrorActionPreference = 'Stop'

# A native command that writes to stderr is not a failed one -- uv
# reports its progress there -- and on PowerShell 7.3+ the preference
# above would otherwise turn every such line into a terminating error.
# The exit code is what this script reads instead.
if (Test-Path variable:PSNativeCommandUseErrorActionPreference) {
    $PSNativeCommandUseErrorActionPreference = $false
}

# Windows PowerShell 5.1 still negotiates TLS 1.0 first on unpatched
# builds, and astral.sh answers 1.2 and up; without this the download
# fails as a closed connection and explains nothing.
try {
    [Net.ServicePointManager]::SecurityProtocol =
        [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
} catch {
    # PowerShell 7 on a platform where ServicePointManager is inert: it
    # negotiates TLS 1.2+ on its own, so there is nothing to fix.
}

$UvInstallerUrl = 'https://astral.sh/uv/install.ps1'
$IssuesUrl = 'https://github.com/enclavum/otaku/issues'

# The interpreter to fall back on when uv finds nothing it can use. Only
# ever downloaded in that case -- a machine with any 3.11+ keeps it.
$PythonFallback = '3.13'

# This script ends early two ways -- a refusal, and an otaku that is
# already installed -- and NEITHER may be `exit`. At the top of a session
# (`irm ... | iex`, or the script typed at the prompt) `exit` closes the
# reader's window, taking with it the message they were meant to read.
# Both endings are this exception instead, caught by the one handler on
# the last lines of the file, which decides there whether a process is
# owed an exit code.
$Stop = 'otaku-install-stop'
$script:Failed = $false

# ---------------------------------------------------------------- output
#
# Write-Host, and its own -ForegroundColor rather than ANSI escapes: the
# legacy console window renders escapes as text, and this has to be
# legible in whatever terminal the reader opened.

function Set-Colors {
    $script:Color = [string]::IsNullOrEmpty($env:NO_COLOR)
}

function Say {
    param([string]$Text = '')
    Write-Host $Text
}

function Step {
    param([string]$Text)
    if ($script:Color) {
        Write-Host '==> ' -NoNewline -ForegroundColor Cyan
    } else {
        Write-Host '==> ' -NoNewline
    }
    Write-Host $Text
}

function Note {
    param([string]$Text)
    if ($script:Color) {
        Write-Host "    $Text" -ForegroundColor DarkGray
    } else {
        Write-Host "    $Text"
    }
}

function Warn {
    param([string]$Text)
    if ($script:Color) {
        Write-Host 'warning: ' -NoNewline -ForegroundColor Yellow
    } else {
        Write-Host 'warning: ' -NoNewline
    }
    Write-Host $Text
}

function Die {
    param([string]$Text)
    if ($script:Color) {
        Write-Host 'error: ' -NoNewline -ForegroundColor Red
    } else {
        Write-Host 'error: ' -NoNewline
    }
    Write-Host $Text
    $script:Failed = $true
    throw $Stop
}

# The other early ending: nothing is wrong, there is simply nothing left
# to do. Said its piece already, so it only has to stop.
function Stop-Run {
    throw $Stop
}

# What the owner of an already-installed otaku needs: how to run it, and
# how to bring it to the newest release.
function Show-Hints {
    Say '  otaku            start playing in terminal'
    Say '  otaku web        start playing in web interface'
    Say '  otaku update     update to the newest version'
}

# ------------------------------------------------------------- utilities

# `command -v`, minus anything that is not a program: a PowerShell
# function, alias or cmdlet named otaku is not an install, and asking one
# for --version would run it.
function Find-Tool {
    param([string]$Name)
    $found = Get-Command -Name $Name -CommandType Application -ErrorAction SilentlyContinue
    if (-not $found) { return $null }
    return @($found)[0].Source
}

# A path as the reader would write it themselves.
function Format-Path {
    param([string]$Path)
    if ($script:UserHome -and $Path.StartsWith($script:UserHome, [StringComparison]::OrdinalIgnoreCase)) {
        return '~' + $Path.Substring($script:UserHome.Length)
    }
    return $Path
}

# Running a program and READING what it said are not the same act, and
# only the second one is dangerous: Windows PowerShell 5.1 turns a native
# command's stderr into a TERMINATING error the moment that stream is
# captured while $ErrorActionPreference is 'Stop'. A program that worked
# and merely remarked on something would fail the step that read it. So
# every capture in this file goes through here, which lowers the
# preference around the call and hands the exit code back in
# $script:LastCode. Only stdout is returned; a caller that wants the
# reader to SEE a failure runs the program again, unredirected, where
# capturing nothing makes it safe.
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
    # Everything it said, not the first row of it: `| Select-Object
    # -First 1` on the call itself stops the pipeline early, and what
    # $LASTEXITCODE says after an early stop is not the program's answer.
    # Callers take the row they want from what comes back.
    return $output
}

# Two directories are the same directory whatever their case and however
# many backslashes they end in -- the PATH is full of both.
function Test-SamePath {
    param([string]$Left, [string]$Right)
    if (-not $Left -or -not $Right) { return $false }
    # Trimmed in place rather than into `$left` and `$right`, which name
    # the parameters back: PowerShell tells variables apart by name and
    # not by case, and a local that differs only in its first letter is
    # the same variable.
    return [string]::Equals(
        $Left.TrimEnd('\', '/'), $Right.TrimEnd('\', '/'), [StringComparison]::OrdinalIgnoreCase)
}

# ------------------------------------------------------------ the checks

function Test-Shell {
    if ($PSVersionTable.PSVersion.Major -lt 5) {
        Die @"
this needs PowerShell 5 or newer, and finds $($PSVersionTable.PSVersion).
       Windows 10 and 11 ship 5.1 in the box. On an older Windows,
       install PowerShell 7: https://aka.ms/powershell
"@
    }

    # PowerShell 7 runs on macOS and Linux, where this is the wrong half
    # of the pair. $IsWindows does not exist before 6, and there the
    # answer is always yes.
    $windows = if (Test-Path variable:IsWindows) { $IsWindows } else { $true }
    if (-not $windows) {
        Die @"
this is the Windows installer, and this is not Windows. Run the other one:
       curl -LsSf https://otaku.sh/install.sh | sh
"@
    }
}

# The architecture of WINDOWS, which is not always the architecture of
# the shell asking: a 32-bit PowerShell on a 64-bit machine reports x86
# in PROCESSOR_ARCHITECTURE and tells the truth in PROCESSOR_ARCHITEW6432
# instead, and an emulated x64 shell on an ARM64 machine does the same.
function Get-WindowsArchitecture {
    $arch = $env:PROCESSOR_ARCHITEW6432
    if (-not $arch) { $arch = $env:PROCESSOR_ARCHITECTURE }
    switch ($arch) {
        'AMD64' { return 'x64' }
        'ARM64' { return 'arm64' }
        'x86'   { return 'x86' }
        default {
            # Windows always sets one of the two, so this is a machine
            # nobody has described. Unknown is not a refusal: the install
            # is attempted and the wheel gets to say whether it fits.
            if (-not $arch) { return 'unknown' }
            return $arch.ToLower()
        }
    }
}

# otaku itself is pure Python and runs anywhere, but cryptography is not,
# and it publishes exactly one Windows wheel: win_amd64. What that costs
# the other two architectures is decided here rather than in the middle
# of a failing build.
function Test-Architecture {
    $script:Arch = Get-WindowsArchitecture

    if ($script:Arch -eq 'x86') {
        # A source build wants a Rust toolchain and an OpenSSL, which is
        # not an install anybody performs to try a chat client.
        Die @"
otaku needs 64-bit Windows, and this is 32-bit.
       The cryptography library it is built on no longer publishes a
       32-bit Windows wheel, so there is nothing here that can be
       installed without building it from source.
"@
    }

    if ($script:Arch -eq 'arm64') {
        # Not a refusal: Windows runs x64 under its own emulation, and
        # Install-Otaku falls back to an x64 CPython, which matches the
        # wheel. Said up front so a slower otaku is not a surprise.
        Warn @"
this is an ARM64 machine, and cryptography ships no ARM64 Windows wheel.
         otaku will be installed on an x64 CPython instead, which
         Windows runs under emulation -- it works, and it starts a
         little slower.
"@
    }
}

# An otaku already on the machine: whoever owns it should keep owning it.
# Installing a second copy leaves two otakus with one name, and whichever
# PATH happens to prefer wins -- including for `otaku update`, which
# reads the running install to decide how to upgrade it.
function Test-ExistingOtaku {
    $otaku = Find-Tool 'otaku'
    if (-not $otaku) { return }

    # The name with its version when the binary answers -- "otaku 0.4.0
    # is already installed" says what they have and sets up the update
    # row below. A binary that will not answer still gets the plain
    # report.
    $name = 'otaku'
    $reported = Read-Program $otaku @('--version')
    if ($script:LastCode -eq 0 -and $reported -match '^otaku') {
        $name = ($reported | Select-Object -First 1) -replace ', version ', ' '
    }

    # Each installer keeps its shims in a directory of its own, which is
    # the only thing a bare .exe on the PATH says about its owner --
    # there is no symlink to follow on Windows.
    $owner = switch -Wildcard ($otaku) {
        '*\scoop\shims\*'   { 'Scoop' ; break }
        '*\pipx\*'          { 'pipx' ; break }
        '*\chocolatey\*'    { 'Chocolatey' ; break }
        '*\uv\tools\*'      { 'uv' ; break }
        default {
            if (Test-SamePath (Split-Path -Parent $otaku) $script:BinDir) { 'uv' } else { $null }
        }
    }

    if ($owner -eq 'uv') {
        Say "$name is already installed in:"
        Note $otaku
        Say ''
        Show-Hints
        Stop-Run
    }

    if ($owner) {
        Say "$name is already installed, and $owner owns it:"
        Note $otaku
        Say ''
        Show-Hints
        Stop-Run
    }

    Warn @"
another otaku is already on your PATH:
         $otaku
         This installs uv's own copy alongside it, first on PATH -- the
         new one wins in new shells until the old one is removed.
"@
}

# ------------------------------------------------------------------ work

function Install-Uv {
    $uv = Find-Tool 'uv'
    if ($uv) {
        Step 'uv is already here'
        Note $uv
        $script:Uv = $uv
        return
    }

    Step 'installing uv - otaku''s installer (python package and project manager)'
    Note "$UvInstallerUrl, about 35 MB, into $script:BinDir"

    # To a file rather than straight into iex: a download that stops
    # halfway is still a string, and iex would run the half of it that
    # arrived. A file can at least be looked at first.
    $temp = Join-Path ([IO.Path]::GetTempPath()) ("otaku-install-$([guid]::NewGuid()).ps1")
    try {
        try {
            Invoke-WebRequest -Uri $UvInstallerUrl -OutFile $temp -UseBasicParsing
        } catch {
            Die "could not download uv's installer from $UvInstallerUrl - $($_.Exception.Message)"
        }
        if (-not (Get-Content -LiteralPath $temp -Raw)) {
            Die "uv's installer came back empty - a network or proxy problem"
        }

        # UV_NO_MODIFY_PATH (and the older name uv still reads): this
        # script owns the PATH edit below, and two installers writing one
        # registry value is how you get it twice.
        $env:UV_INSTALL_DIR = $script:BinDir
        $env:UV_NO_MODIFY_PATH = '1'
        $env:INSTALLER_NO_MODIFY_PATH = '1'
        try {
            # In a PowerShell of its own, not this one. uv's installer
            # ends in `catch { exit 1 }`, and `exit` inside a script block
            # run here would take THIS script down with it -- before the
            # check below, and with uv's message as the last word instead
            # of one of ours. A child process turns that into an exit
            # code. It also keeps the installer's own environment
            # ($InformationPreference, its functions) out of ours, and it
            # inherits the three variables just set.
            & $script:Shell -NoProfile -ExecutionPolicy Bypass -File $temp *> $null
            $code = $LASTEXITCODE
        } finally {
            Remove-Item env:UV_INSTALL_DIR, env:UV_NO_MODIFY_PATH, env:INSTALLER_NO_MODIFY_PATH `
                -ErrorAction SilentlyContinue
        }
        if ($code -ne 0) {
            Die "uv's installer failed (exit $code). Try it on its own to see why:
       irm $UvInstallerUrl | iex"
        }
    } finally {
        Remove-Item -LiteralPath $temp -Force -ErrorAction SilentlyContinue
    }

    $script:Uv = Join-Path $script:BinDir 'uv.exe'
    if (-not (Test-Path -LiteralPath $script:Uv)) {
        Die "uv installed but is not at $script:Uv - please report this at $IssuesUrl"
    }
}

# uv puts otaku's shim in the same directory it puts itself, so one edit
# covers both. The user PATH is the one file here that the reader owns,
# so it is announced and idempotent.
#
# This runs before the install, not after: exporting the directory first
# means uv finds it on PATH and keeps its own "not on your PATH" advice
# to itself, leaving one account of the matter instead of two.
function Add-InstallDirToPath {
    foreach ($entry in ($env:Path -split ';')) {
        if (Test-SamePath $entry $script:BinDir) {
            $script:PathAction = 'present'
            return
        }
    }
    $env:Path = "$script:BinDir;$env:Path"  # so this run can verify what it installed

    $registry = 'registry::HKEY_CURRENT_USER\Environment'

    # GetValue with DoNotExpandEnvironmentNames, because the user PATH is
    # a REG_EXPAND_SZ and routinely holds a %USERPROFILE%: read it the
    # ordinary way and the expansion is what gets written back, freezing
    # somebody else's variable into a literal path forever. The write
    # side of the same care is -Type ExpandString. (Both, and the
    # broadcast below, are how uv's own installer does it.)
    $current = @()
    try {
        $current = (Get-Item -LiteralPath $registry).GetValue(
            'Path', '', 'DoNotExpandEnvironmentNames') -split ';' -ne ''
    } catch {
        $current = @()
    }

    foreach ($entry in $current) {
        if (Test-SamePath $entry $script:BinDir) {
            $script:PathAction = 'pending'
            $script:PathNote = @"
your PATH already has it - open a new terminal to pick it up,
    or run this once in the current one:
        `$env:Path = "$script:BinDir;`$env:Path"
"@
            return
        }
    }

    try {
        Set-ItemProperty -LiteralPath $registry -Name 'Path' -Type ExpandString `
            -Value ((, $script:BinDir + $current) -join ';')

        # Setting any user variable through .NET broadcasts
        # WM_SETTINGCHANGE, which is what tells Explorer to re-read the
        # environment it hands to every terminal it opens. Without it the
        # new PATH is real but nothing started from the Start menu sees
        # it until the next sign-in. Setting a name nobody uses and
        # removing it again is the broadcast with no side effect.
        $ping = "otaku-installer-$([guid]::NewGuid())"
        [Environment]::SetEnvironmentVariable($ping, '1', 'User')
        [Environment]::SetEnvironmentVariable($ping, [NullString]::Value, 'User')
    } catch {
        $script:PathAction = 'manual'
        $script:PathNote = @"
$script:BinDir could not be added to your PATH ($($_.Exception.Message)). Add it:
         `$env:Path = "$script:BinDir;`$env:Path"
"@
        return
    }

    $script:PathAction = 'added'
    $script:PathNote = @"
added to your PATH - open a new terminal to pick it up,
    or run this once in the current one:
        `$env:Path = "$script:BinDir;`$env:Path"
"@
}

function Install-Otaku {
    Step 'installing otaku'

    # --force because the check above only sees an otaku that is on PATH:
    # one uv installed into a directory the shell never picked up is
    # invisible there, and a plain install would stop at "already
    # installed" rather than making the shim this run promises.
    & $script:Uv tool install --force otaku
    if ($LASTEXITCODE -eq 0) { return }

    # The likeliest reason for that failure is the interpreter: otaku
    # needs 3.11+ and uv reached for something older. Ask for a version
    # by name and uv downloads a managed CPython rather than searching.
    Step "retrying with a managed CPython $PythonFallback - the usual cause is no Python 3.11+"
    & $script:Uv tool install --force --python $PythonFallback otaku
    if ($LASTEXITCODE -eq 0) { return }

    if ($script:Arch -eq 'arm64') {
        # On ARM64 the wheel is the likelier cause than the interpreter:
        # an ARM64 CPython finds no cryptography wheel at all and falls
        # back to the sdist, which wants Rust. Naming the platform in the
        # request gets an x64 CPython, which Windows emulates and which
        # the win_amd64 wheel fits.
        Step 'retrying with an x64 CPython - ARM64 has no cryptography wheel'
        & $script:Uv tool install --force --python "cpython-$PythonFallback-windows-x86_64" otaku
        if ($LASTEXITCODE -eq 0) { return }

        Die @"
the install failed on ARM64. The output above says why; the usual reason
       is cryptography, which publishes no ARM64 Windows wheel and cannot
       be built without a Rust toolchain. Two ways around it:
         - install otaku under WSL: wsl --install, then
           curl -LsSf https://otaku.sh/install.sh | sh
         - install an x64 Python yourself and point uv at it:
           uv tool install --python <path to x64 python.exe> otaku
       If neither fits, please report it at $IssuesUrl
"@
    }

    Die @"
the install failed. The output above says why; if it is not
       something you can fix, please report it at $IssuesUrl
"@
}

function Confirm-Install {
    $otaku = Join-Path $script:BinDir 'otaku.exe'
    if (-not (Test-Path -LiteralPath $otaku)) {
        Die "otaku installed but its program is not at
       $otaku
       Please report this at $IssuesUrl"
    }

    $reported = Read-Program $otaku @('--version')
    $script:Version = ($reported | Select-Object -First 1)
    if ($script:LastCode -eq 0 -and $script:Version) { return }

    # Asked once quietly and answered badly, so ask again in the open:
    # whatever it prints -- a traceback, a missing DLL -- is the only
    # useful thing this step can hand the reader, and Read-Program
    # swallowed it. Unredirected, so nothing is captured and nothing
    # turns an ordinary line into an error of its own.
    $code = $script:LastCode
    Say ''
    Note 'asked for its version, it said:'
    & $otaku --version
    Die "otaku is installed, at
       $otaku
       but it will not run (exit $code). What it printed is above;
       please report it at $IssuesUrl"
}

function Show-Finish {
    Say ''
    Step $script:Version
    Say ''
    Say '  otaku            start playing in terminal'
    Say '  otaku web        start playing in web interface'
    Say ''
    Say "Your stories and settings are in $(Format-Path (Join-Path $script:UserHome '.otaku'))"

    switch ($script:PathAction) {
        # Something the script did, not something the reader must fix.
        'added'   { Say ''; Note $script:PathNote }
        'pending' { Say ''; Note $script:PathNote }
        'manual'  { Say ''; Warn $script:PathNote }
    }

    # The terminal is the medium here, and the two Windows ships are not
    # the same one: otaku draws in 24-bit colour, which the console host
    # renders as approximations at best.
    if (-not $env:WT_SESSION) {
        Say ''
        Note 'Windows Terminal renders otaku best - it is the default on Windows 11,'
        Note 'and free from the Microsoft Store on Windows 10.'
    }
}

# ------------------------------------------------------------------ main
#
# Everything runs from here, called on the last line of the file -- the
# shape install.sh has, for the same reason read differently. `curl | sh`
# hands the shell a stream and runs whatever bytes arrived; PowerShell
# parses the whole string before it runs any of it, so a truncated
# download is already a parse error rather than half an install. What the
# shape buys here is that the two files stay the same file in two
# languages, and that dot-sourcing this one defines its functions without
# installing anything.

function Invoke-Main {
    Set-Colors

    $script:UserHome = if ($HOME) { $HOME } else { $env:USERPROFILE }
    $script:Arch = ''
    $script:Uv = ''
    $script:Version = ''
    $script:LastCode = 0
    $script:PathAction = ''
    $script:PathNote = ''

    # This very PowerShell, to run uv's installer in a second copy of --
    # whichever of the two the reader opened, since 5.1 and 7 are
    # different programs and only one of them is certainly installed.
    $script:Shell = $null
    try { $script:Shell = (Get-Process -Id $PID).Path } catch { }
    if (-not $script:Shell) { $script:Shell = 'powershell.exe' }

    # Where uv installs itself and its tools' shims, by its own rules.
    $script:BinDir = if ($env:XDG_BIN_HOME) {
        $env:XDG_BIN_HOME
    } else {
        Join-Path $script:UserHome '.local\bin'
    }

    Test-Shell
    Test-Architecture
    Test-ExistingOtaku
    Install-Uv

    # uv knows better than the guess above where its shims go; ask it
    # once it exists, and only trust an answer that looks like a path.
    # An older uv that has no --bin to give simply leaves the guess
    # standing, which is the same directory it would have named.
    $bin = Read-Program $script:Uv @('tool', 'dir', '--bin')
    if ($script:LastCode -eq 0) {
        $first = ($bin | Select-Object -First 1)
        if ($first -and [IO.Path]::IsPathRooted($first.Trim())) {
            $script:BinDir = $first.Trim()
        }
    }

    Add-InstallDirToPath
    Install-Otaku
    Confirm-Install
    Show-Finish
}

# A PowerShell that was started to run one thing and then end -- the
# `powershell -c "..."` the README advertises, a `-File` run, a CI step --
# is owed an exit code, and ending it is what it was for. A session the
# reader is standing in is owed the opposite: it must survive, whatever
# happened. So the code is set only where a switch says this process came
# with an errand. Ambiguity resolves toward leaving the window open.
function Test-DedicatedShell {
    $arguments = [Environment]::GetCommandLineArgs()
    if ($arguments.Count -lt 2) { return $false }

    $errand = $false
    foreach ($argument in $arguments[1..($arguments.Count - 1)]) {
        # Anchored, so -ExecutionPolicy is never mistaken for -e.
        if ($argument -match '^-{1,2}(c|command|f|file|e|encodedcommand)$') { $errand = $true }
        # -NoExit says the reader means to stay in it afterwards, which
        # settles the question whatever else is on the line.
        if ($argument -match '^-{1,2}noe') { return $false }
    }
    return $errand
}

try {
    Invoke-Main
} catch {
    # Its own two endings are already spoken for -- Die printed the
    # reason, Stop-Run had nothing left to say. Anything else is a fault
    # nobody planned, and rethrowing puts it where a fault belongs: on
    # the screen, in full, and still without closing anything.
    if ("$_" -ne $Stop) { throw }
}

if ($script:Failed -and (Test-DedicatedShell)) { exit 1 }
