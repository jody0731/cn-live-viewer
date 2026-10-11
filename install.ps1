# Install cn-live-viewer for the current user on Windows. In PowerShell:
#   irm https://raw.githubusercontent.com/jody0731/cn-live-viewer/main/install.ps1 | iex
# or from a clone of the repository:
#   powershell -ExecutionPolicy Bypass -File install.ps1          (add -Yes to install what's missing without asking)
# It needs Python 3.10+ and mpv, and installs what's missing after asking once. Each comes from winget when that
# works, otherwise from its official download: Python's installer from python.org (for this user, no admin rights
# needed), mpv's Windows build from its GitHub releases into cn-live-viewer's own folder. Then cn-live-viewer goes into
# a private Python environment, the app launcher into the Start menu, and the installed copy checks itself.
param([switch]$Yes)

# in a script block, so that run with "irm | iex" it leaves no functions or settings behind in your PowerShell
& {
    $ErrorActionPreference = 'Stop'
    $ProgressPreference = 'SilentlyContinue'     # Windows PowerShell's download progress bar slows downloads a lot
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    $app_dir = Join-Path $env:LOCALAPPDATA 'cn-live-viewer'
    $mpv_dir = Join-Path $app_dir 'mpv'          # where a downloaded mpv goes; cn-live-viewer looks here too
    $venv = Join-Path $app_dir 'venv'
    $python_series = '3.14'                      # the Python it installs when there's none (CI tests 3.10 to 3.14)
    $python_fallback = '3.14.8'                  # if python.org can't say which 3.14 is the latest
    $user_pythons = Join-Path $env:LOCALAPPDATA 'Programs\Python'   # where python.org's installer puts it for one user

    # from this folder when it is a clone, otherwise the latest version from GitHub (a zip, so git isn't needed)
    $src = 'https://github.com/jody0731/cn-live-viewer/archive/refs/heads/main.zip'
    if ($PSScriptRoot -and (Test-Path (Join-Path $PSScriptRoot 'pyproject.toml')) -and
        (Test-Path (Join-Path $PSScriptRoot 'src\cn_live_viewer'))) { $src = $PSScriptRoot }

    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if ($env:CNLV_NO_WINGET) { $winget = $null }     # CI: test the downloads

    function Ask([string]$question) {
        if ($Yes) { return $true }
        $answer = Read-Host "$question [Y/n]"
        return -not ($answer -match '^[nN]')
    }

    # a program just installed is on the PATH of new sessions only; read it again for this one
    function Update-SessionPath {
        $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
                    [Environment]::GetEnvironmentVariable('Path', 'User')
    }

    # ------------------------------------------------------------ Python

    # The full path of a Python 3.10+, or $null. Windows comes with a python.exe that only points to the Microsoft
    # Store: it prints "Python was not found" and fails. Windows PowerShell turns that message into an error, which
    # with 'Stop' would end the installer, hence 'Continue' while asking.
    function Test-Python([string]$exe) {
        $ErrorActionPreference = 'Continue'
        try {
            # no double quotes in it: Windows PowerShell passes them to programs wrongly
            $out = & $exe -c 'import sys; print(sys.executable) if sys.version_info >= (3, 10) else sys.exit(1)' 2>$null
            if ($LASTEXITCODE -eq 0 -and $out) {
                $path = "$($out | Select-Object -Last 1)".Trim()
                if ($path -and (Test-Path $path)) { return $path }
            }
        } catch { }
        return $null
    }

    # the py launcher and python on PATH, then installs that aren't on PATH (python.org's installer doesn't add
    # Python to PATH unless asked, and a fresh install isn't on this session's PATH)
    function Find-Python {
        $tries = @(@('py', 'python', 'python3') | Where-Object { Get-Command $_ -ErrorAction SilentlyContinue })
        $tries += @(Get-ChildItem "$user_pythons\Python3*\python.exe", "$env:ProgramFiles\Python3*\python.exe" -ErrorAction SilentlyContinue |
                    Sort-Object { [int]($_.Directory.Name -replace '\D', '') } -Descending | ForEach-Object { $_.FullName })
        foreach ($try in $tries) {
            $exe = Test-Python $try
            if (-not $exe) { continue }
            if ($env:CNLV_NO_SYSTEM_PYTHON -and $exe -notlike "$user_pythons*") { continue }   # CI: as on a PC without Python
            return $exe
        }
        return $null
    }

    # python.org's installer for the latest 3.14, for this user only (no admin rights), with the py launcher, and
    # added to PATH
    function Get-PythonInstaller {
        $version = $python_fallback
        try {
            $names = (Invoke-RestMethod 'https://www.python.org/api/v2/downloads/release/?is_published=true&pre_release=false').name
            $latest = $names | Where-Object { $_ -match "^Python $([regex]::Escape($python_series))\.\d+$" } |
                      ForEach-Object { [version]($_ -replace '^Python ', '') } | Sort-Object -Descending | Select-Object -First 1
            if ($latest) { $version = "$latest" }
        } catch { Write-Warning "python.org didn't list its releases ($_); using Python $version" }
        $arch = if ($env:PROCESSOR_ARCHITECTURE -eq 'ARM64') { 'arm64' } else { 'amd64' }
        $file = "python-$version-$arch.exe"
        $setup = Join-Path $env:TEMP $file
        Write-Host "Downloading Python $version from python.org ..."
        Invoke-WebRequest "https://www.python.org/ftp/python/$version/$file" -OutFile $setup -UseBasicParsing
        Write-Host "Installing Python $version for this user (about a minute) ..."
        $p = Start-Process $setup -Wait -PassThru -ArgumentList @(
            '/quiet', 'InstallAllUsers=0', 'PrependPath=1', 'Include_test=0', 'Include_launcher=1', 'InstallLauncherAllUsers=0')
        Remove-Item $setup -ErrorAction SilentlyContinue
        if ($p.ExitCode -ne 0 -and $p.ExitCode -ne 3010) { throw "Python's installer failed (exit code $($p.ExitCode))" }
        Update-SessionPath
    }

    function Install-Python {
        if ($winget) {
            winget install --id "Python.Python.$python_series" --exact --scope user --accept-package-agreements --accept-source-agreements
            Update-SessionPath
            if (Find-Python) { return }
            Write-Warning "winget couldn't install Python; downloading it from python.org instead."
        }
        Get-PythonInstaller
    }

    # ------------------------------------------------------------ mpv

    function Find-Mpv {
        $onpath = Get-Command mpv -ErrorAction SilentlyContinue
        if ($onpath) { return $onpath.Source }
        $here = Join-Path $mpv_dir 'mpv.exe'
        if (Test-Path $here) { return $here }
        return $null
    }

    # mpv's official Windows build from its latest GitHub release (a zip), into $mpv_dir
    function Get-MpvRelease {
        $arch = if ($env:PROCESSOR_ARCHITECTURE -eq 'ARM64') { 'aarch64-pc-windows-msvc' } else { 'x86_64-w64-mingw32' }
        $release = Invoke-RestMethod 'https://api.github.com/repos/mpv-player/mpv/releases/latest' -Headers @{ 'User-Agent' = 'cn-live-viewer' }
        $asset = $release.assets | Where-Object { $_.name -like "*-$arch.zip" } | Select-Object -First 1
        if (-not $asset) { throw "mpv's latest release has no $arch build" }
        Write-Host "Downloading $($asset.name) ($([math]::Round($asset.size / 1MB)) MB) from GitHub ..."
        $zip = Join-Path $env:TEMP $asset.name
        Invoke-WebRequest $asset.browser_download_url -OutFile $zip -UseBasicParsing
        if (Test-Path $mpv_dir) { Remove-Item $mpv_dir -Recurse -Force }
        Expand-Archive $zip -DestinationPath $mpv_dir -Force
        Remove-Item $zip
        # the release zip holds another zip (mpv-git-<date>-<commit>-x86_64.zip) with the program: unpack that too
        foreach ($round in 1..2) {
            if (Get-ChildItem $mpv_dir -Recurse -Filter mpv.exe) { break }
            foreach ($inner in Get-ChildItem $mpv_dir -Recurse -Filter *.zip) {
                Expand-Archive $inner.FullName -DestinationPath $mpv_dir -Force
                Remove-Item $inner.FullName
            }
        }
        $exe = Get-ChildItem $mpv_dir -Recurse -Filter mpv.exe | Select-Object -First 1
        if (-not $exe) { throw "the download didn't contain mpv.exe" }
        if ($exe.DirectoryName -ne $mpv_dir) {          # the zip had a folder inside: lift its contents
            Get-ChildItem $exe.DirectoryName | Move-Item -Destination $mpv_dir -Force
        }
    }

    function Install-Mpv {
        if ($winget) {
            winget install --id shinchiro.mpv --exact --accept-package-agreements --accept-source-agreements
            Update-SessionPath
            if (Find-Mpv) { return }
            Write-Warning ("winget couldn't install mpv; downloading it from GitHub instead. (If winget reported " +
                           "0x80073cfc or 'Failed when searching source', winget itself needs fixing: update 'App " +
                           "Installer' in the Microsoft Store, or run 'winget source reset --force' as administrator.)")
        }
        Get-MpvRelease
    }

    # ------------------------------------------------------------ what's missing

    $python = Find-Python
    $mpv = Find-Mpv
    $missing = @()
    if (-not $python) { $missing += "Python $python_series" }
    if (-not $mpv) { $missing += 'mpv' }
    if ($python) { Write-Host "Python: $python" }
    if ($mpv) { Write-Host "mpv: $mpv" }
    if ($missing) {
        $how = if ($winget) { 'with winget, or from the official downloads if winget fails' } else { 'from the official downloads (python.org, GitHub)' }
        if (-not (Ask "Missing: $($missing -join ', '). Install now, $how?")) {
            throw "cn-live-viewer needs $($missing -join ' and '). Install them yourself (see the README), or run this again."
        }
        if (-not $python) {
            Install-Python
            $python = Find-Python
            if (-not $python) { throw 'Python was installed but cannot be found. Open a new PowerShell window and run this again.' }
            Write-Host "Python: $python"
        }
        if (-not $mpv) {
            try { Install-Mpv } catch { Write-Warning "Installing mpv failed: $_" }
            $mpv = Find-Mpv
            if ($mpv) { Write-Host "mpv: $mpv" }
        }
    }

    # ------------------------------------------------------------ cn-live-viewer

    Write-Host 'Installing cn-live-viewer ...'
    & $python -m venv --clear $venv
    if ($LASTEXITCODE -ne 0) { throw "Could not create a Python environment in $venv (if cn-live-viewer is running, close it and try again)" }
    $vpy = Join-Path $venv 'Scripts\python.exe'
    & $vpy -m pip install --quiet --disable-pip-version-check --upgrade pip
    & $vpy -m pip install --quiet --disable-pip-version-check $src
    if ($LASTEXITCODE -ne 0) { throw 'Could not install cn-live-viewer' }

    $exe = Join-Path $venv 'Scripts\cn-live-viewer.exe'
    & $exe desktop
    Write-Host ''
    & $exe check                                     # what's in place: Python, the libraries, mpv
    $ready = $LASTEXITCODE -eq 0
    Write-Host ''
    if ($ready) {
        Write-Host 'Installed. Start "CN Live Viewer" from the Start menu.'
    } else {
        Write-Warning 'Installed, but not ready to play yet (see above). Run this again, or install mpv: https://mpv.io/installation/'
    }
    Write-Host "Command line: & '$exe' 333003   (to type just cn-live-viewer, add $(Split-Path $exe) to your PATH)"
}
