# Install cn-live-viewer for the current user on Windows. In PowerShell, from a clone of the repository:
#   powershell -ExecutionPolicy Bypass -File install.ps1          (add -Yes to install Python and mpv without asking)
# or on its own:
#   irm https://raw.githubusercontent.com/jody0731/cn-live-viewer/main/install.ps1 | iex
# First it installs what's missing, Python 3.10+ and mpv, with winget (asking first). Then cn-live-viewer goes into
# a private Python environment, and the app launcher into the Start menu.
param([switch]$Yes)
$ErrorActionPreference = 'Stop'

# from this folder when it is a clone, otherwise the latest version from GitHub (a zip, so git isn't needed)
$src = 'https://github.com/jody0731/cn-live-viewer/archive/refs/heads/main.zip'
if ($PSScriptRoot -and (Test-Path (Join-Path $PSScriptRoot 'pyproject.toml')) -and
    (Test-Path (Join-Path $PSScriptRoot 'src\cn_live_viewer'))) { $src = $PSScriptRoot }

function Ask([string]$question) {
    if ($Yes) { return $true }
    $answer = Read-Host "$question [Y/n]"
    return -not ($answer -match '^[nN]')
}

# a program just installed by winget is on the PATH of new sessions only; read it again for this one
function Update-SessionPath {
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
                [Environment]::GetEnvironmentVariable('Path', 'User')
}

# the py launcher comes with Python from python.org; plain "python" may be the Microsoft Store placeholder
function Find-Python {
    foreach ($cmd in @('py', 'python')) {
        if (Get-Command $cmd -ErrorAction SilentlyContinue) {
            & $cmd -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>$null
            if ($LASTEXITCODE -eq 0) { return $cmd }
        }
    }
    return $null
}

$winget = Get-Command winget -ErrorAction SilentlyContinue

# ---------------------------------------------------------------- what the system needs

$python = Find-Python
if (-not $python -and $winget -and (Ask 'Python 3.10 or newer is needed. Install Python 3.13 with winget?')) {
    winget install --id Python.Python.3.13 --exact --accept-package-agreements --accept-source-agreements
    Update-SessionPath
    $python = Find-Python
}
if (-not $python) { throw 'Python 3.10 or newer is needed: https://www.python.org/downloads/' }

if (-not (Get-Command mpv -ErrorAction SilentlyContinue)) {
    if ($winget -and (Ask 'mpv is needed to watch. Install it with winget (shinchiro.mpv)?')) {
        winget install --id shinchiro.mpv --exact --accept-package-agreements --accept-source-agreements
        Update-SessionPath
    }
    if (-not (Get-Command mpv -ErrorAction SilentlyContinue)) {
        Write-Warning 'mpv is not installed yet. It is needed to watch: see https://mpv.io/installation/'
    }
}

# ---------------------------------------------------------------- cn-live-viewer

$venv = Join-Path $env:LOCALAPPDATA 'cn-live-viewer\venv'
& $python -m venv --clear $venv
if ($LASTEXITCODE -ne 0) { throw 'Could not create a Python environment' }
$vpy = Join-Path $venv 'Scripts\python.exe'
& $vpy -m pip install --quiet --upgrade pip
& $vpy -m pip install --quiet $src
if ($LASTEXITCODE -ne 0) { throw 'Could not install cn-live-viewer' }

$exe = Join-Path $venv 'Scripts\cn-live-viewer.exe'
& $exe desktop
Write-Host ''
Write-Host 'Installed. Start "CN Live Viewer" from the Start menu.'
Write-Host "Command line: & '$exe' 333003   (to type just cn-live-viewer, add $(Split-Path $exe) to your PATH)"
