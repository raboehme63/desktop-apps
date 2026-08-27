# Build the Windows onedir bundle and, if Inno Setup is installed, the setup EXE.
# Usage (from repo root or this folder):
#   powershell -ExecutionPolicy Bypass -File packaging\build.ps1

[CmdletBinding()]
param(
    [switch]$SkipInstaller
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$PackagingDir = $PSScriptRoot
$Root = Split-Path -Parent $PackagingDir
Set-Location $Root

function Get-AppVersion {
    $about = Get-Content -Raw -Path (Join-Path $Root 'apps\traveljournal\src\traveljournal\__about__.py')
    if ($about -match '__version__\s*=\s*"([^"]+)"') {
        return $Matches[1]
    }
    throw 'Could not read __version__ from traveljournal.__about__.'
}

function Get-VenvPython {
    $candidate = Join-Path $Root '.venv\Scripts\python.exe'
    if (Test-Path $candidate) {
        return $candidate
    }
    throw 'Missing .venv. Create it first (see README.md) and install travelcore + traveljournal.'
}

function Find-Iscc {
    $cmd = Get-Command iscc -ErrorAction SilentlyContinue
    if ($cmd) {
        return $cmd.Source
    }
    foreach ($path in @(
            "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
            "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
        )) {
        if (Test-Path $path) {
            return $path
        }
    }
    return $null
}

$Version = Get-AppVersion
$Python = Get-VenvPython
$env:TRAVELJOURNAL_VERSION = $Version

Write-Host "Reisetagebuch R$Version - Windows package"
Write-Host "Python: $Python"

Write-Host 'Installing PyInstaller into the venv (build tool only)...'
& $Python -m pip install --disable-pip-version-check 'pyinstaller>=6.11,<7'
if ($LASTEXITCODE -ne 0) {
    throw 'pip install pyinstaller failed.'
}

$DistDir = Join-Path $Root 'dist'
$WorkDir = Join-Path $Root 'build\pyinstaller'
$Spec = Join-Path $PackagingDir 'traveljournal.spec'
$BundleDir = Join-Path $DistDir 'Reisetagebuch'

if (Test-Path $BundleDir) {
    Write-Host "Removing previous bundle $BundleDir"
    $deadline = (Get-Date).AddSeconds(30)
    $removed = $false
    while ((Get-Date) -lt $deadline) {
        try {
            Remove-Item -LiteralPath $BundleDir -Recurse -Force -ErrorAction Stop
            $removed = -not (Test-Path $BundleDir)
            if ($removed) { break }
        }
        catch {
            Start-Sleep -Seconds 1
        }
    }
    if (-not $removed) {
        throw "Could not remove $BundleDir (file lock, often Windows Defender). Close the app and retry."
    }
}

Write-Host 'Freezing with PyInstaller (onedir). This takes several minutes...'
& $Python -m PyInstaller --noconfirm --clean --distpath $DistDir --workpath $WorkDir $Spec
if ($LASTEXITCODE -ne 0) {
    throw 'PyInstaller failed.'
}

$Exe = Join-Path $BundleDir 'Reisetagebuch.exe'
$WorkExe = Join-Path $WorkDir 'traveljournal\Reisetagebuch.exe'
# Windows Defender often locks or delays the freshly linked bootloader EXE, so
# COLLECT can finish without it. Copy from the work directory if needed.
if (-not (Test-Path $Exe)) {
    $deadline = (Get-Date).AddSeconds(20)
    while (-not (Test-Path $WorkExe) -and (Get-Date) -lt $deadline) {
        Start-Sleep -Milliseconds 500
    }
    if (Test-Path $WorkExe) {
        Write-Host 'COLLECT missed Reisetagebuch.exe (often a Defender scan). Copying from work directory.'
        Copy-Item $WorkExe $Exe -Force
    }
}
if (-not (Test-Path $Exe)) {
    throw "Expected $Exe after PyInstaller."
}

$ZipPath = Join-Path $DistDir "Reisetagebuch-$Version-windows.zip"
if (Test-Path $ZipPath) {
    Remove-Item $ZipPath -Force
}
Write-Host "Writing portable zip $ZipPath"
Compress-Archive -Path (Join-Path $BundleDir '*') -DestinationPath $ZipPath -CompressionLevel Optimal

$SetupPath = Join-Path $DistDir "Reisetagebuch-$Version-setup.exe"
$Iscc = Find-Iscc
if ($SkipInstaller) {
    Write-Host 'Skipping Inno Setup (-SkipInstaller).'
}
elseif ($null -eq $Iscc) {
    Write-Host "Inno Setup 6 was not found. Portable zip is ready: $ZipPath"
    Write-Host 'To build a Setup-EXE, install Inno Setup 6 from https://jrsoftware.org/isinfo.php'
    Write-Host 'and re-run this script (ISCC.exe on PATH or under Program Files).'
}
else {
    Write-Host "Compiling installer with $Iscc"
    & $Iscc "/DMyAppVersion=$Version" (Join-Path $PackagingDir 'installer.iss')
    if ($LASTEXITCODE -ne 0) {
        throw 'Inno Setup compiler failed.'
    }
    if (-not (Test-Path $SetupPath)) {
        throw "Expected $SetupPath after Inno Setup."
    }
}

Write-Host ''
Write-Host 'Done.'
Write-Host "  Folder: $BundleDir"
Write-Host "  Zip:    $ZipPath"
if (Test-Path $SetupPath) {
    Write-Host "  Setup:  $SetupPath"
}
