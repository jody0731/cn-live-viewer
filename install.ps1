# Install cn-live-viewer for the current user on Windows: a private Python environment, the command, and a Start
# menu shortcut. In PowerShell, from a clone of the repository or on its own:
#   powershell -ExecutionPolicy Bypass -File install.ps1
$ErrorActionPreference = 'Stop'

# from this folder when it is a clone, otherwise the latest version from GitHub (a zip, so git isn't needed)
$src = 'https://github.com/jody0731/cn-live-viewer/archive/refs/heads/main.zip'
if ($PSScriptRoot -and (Test-Path (Join-Path $PSScriptRoot 'pyproject.toml'))) { $src = $PSScriptRoot }

if (-not (Get-Command mpv -ErrorAction SilentlyContinue)) {
    Write-Warning 'mpv is not installed. It is needed to watch: see https://mpv.io/installation/ (e.g. scoop install extras/mpv)'
}

# the py launcher comes with Python from python.org; plain "python" may be the Microsoft Store placeholder
$python = $null
foreach ($cmd in @('py', 'python')) {
    if (Get-Command $cmd -ErrorAction SilentlyContinue) { $python = $cmd; break }
}
if (-not $python) { throw 'Python 3.10 or newer is needed: https://www.python.org/downloads/' }
& $python -c 'import sys; sys.exit(sys.version_info < (3, 10))'
if ($LASTEXITCODE -ne 0) { throw 'Python 3.10 or newer is needed: https://www.python.org/downloads/' }

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
