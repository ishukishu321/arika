Param(
    [string]$RepoDir
)

# Sanitize incoming RepoDir (handles stray quotes and trailing backslashes)
if ([string]::IsNullOrWhiteSpace($RepoDir)) {
    # default to repo root (parent of this scripts folder)
    $RepoDir = Split-Path -Path $PSScriptRoot -Parent
} else {
    # remove surrounding quotes if present
    $RepoDir = $RepoDir.Trim('"')
    # Trim trailing backslashes
    while ($RepoDir.EndsWith('\')) { $RepoDir = $RepoDir.Substring(0, $RepoDir.Length - 1) }
}

if (-not (Test-Path -Path $RepoDir)) {
    Write-Warning "Repo directory '$RepoDir' not found. Falling back to script parent folder."
    $RepoDir = Split-Path -Path $PSScriptRoot -Parent
}

try {
    Set-Location -Path $RepoDir -ErrorAction Stop
} catch {
    Write-Error "Failed to set location to '$RepoDir': $_"
    exit 1
}

function Test-Python {
    try {
        $out = & python --version 2>&1
        if ($LASTEXITCODE -eq 0) { Write-Host "Python found: $out"; return $true }
    } catch {}
    try {
        $out = & py -3 --version 2>&1
        if ($LASTEXITCODE -eq 0) { Write-Host "py launcher found: $out"; return $true }
    } catch {}
    return $false
}

function Try-WingetInstall {
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Write-Host "Attempting to install Python via winget..."
        $args = 'install','--exact','--id','Python.Python.3','-e','--accept-package-agreements','--accept-source-agreements'
        $p = Start-Process -FilePath winget -ArgumentList $args -Wait -PassThru -NoNewWindow
        return $p.ExitCode -eq 0
    }
    return $false
}

function Try-DownloadInstaller {
    param($version = '3.12.6')
    $url = "https://www.python.org/ftp/python/$version/python-$version-amd64.exe"
    $tmp = Join-Path $env:TEMP "python-$version-amd64.exe"
    Write-Host "Downloading Python $version from $url to $tmp..."
    try {
        Invoke-WebRequest -Uri $url -OutFile $tmp -UseBasicParsing -ErrorAction Stop
    } catch {
        Write-Warning "Download failed: $_"
        return $false
    }
    Write-Host "Running installer (may prompt for elevation)..."
    $args = '/quiet','InstallAllUsers=1','PrependPath=1','Include_pip=1'
    $p = Start-Process -FilePath $tmp -ArgumentList $args -Verb RunAs -Wait -PassThru
    return $p.ExitCode -eq 0
}

# Main flow
if (Test-Python) {
    Write-Host "Python already available."
} else {
    $installed = $false
    try {
        $installed = Try-WingetInstall
    } catch {
        Write-Warning "winget attempt failed: $_"
    }
    if (-not $installed) {
        Write-Host "winget install not available or failed; falling back to direct download."
        $installed = Try-DownloadInstaller -version '3.12.6'
    }
    Start-Sleep -Seconds 2
    if (-not (Test-Python)) {
        Write-Error "Python installation did not make 'python' available on PATH. Please install Python manually and re-run setup.bat."
        exit 1
    }
}

Write-Host "Launching installer.py with the system Python..."
try {
    & python installer.py
    exit $LASTEXITCODE
} catch {
    Write-Error "Failed to run installer.py: $_"
    exit 1
}
