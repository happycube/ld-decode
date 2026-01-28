# Build script for creating Windows MSI installer
# Requires: Python, PyInstaller, WiX Toolset available in PATH

param(
    [string]$Version = "7.0.0"
)

$ErrorActionPreference = "Stop"

if ($null -ne $Version -and $Version -ne "" -and $Version.StartsWith('v')) {
    $Version = $Version.Substring(1)
}

# Update pyproject.toml with the version before building
Write-Host "Updating pyproject.toml with version: $Version" -ForegroundColor Yellow
$pyprojectPath = "pyproject.toml"
$pyprojectContent = Get-Content $pyprojectPath -Raw
$pyprojectContent = $pyprojectContent -replace 'version = "[^"]*"', "version = `"$Version`""
Set-Content $pyprojectPath $pyprojectContent

# WiX requires version format: x.x.x.x where x is 0-65534
# Sanitize version for MSI compatibility
$MsiVersion = $Version
if ($Version -match '^(\d+)\.(\d+)\.(\d+)') {
    # Extract major.minor.patch and add build number
    $MsiVersion = "$($matches[1]).$($matches[2]).$($matches[3]).0"
} elseif ($Version -notmatch '^\d+\.\d+\.\d+\.\d+$') {
    # Fallback for dev/invalid versions
    Write-Host "Warning: Version '$Version' is not MSI-compatible, using 0.0.0.1" -ForegroundColor Yellow
    $MsiVersion = "0.0.1.0"
}

Write-Host "Building ld-decode Windows installer" -ForegroundColor Cyan
Write-Host "  Full version: $Version" -ForegroundColor Cyan
Write-Host "  MSI version:  $MsiVersion" -ForegroundColor Cyan

# Step 1: Install dependencies
Write-Host "Installing Python dependencies..." -ForegroundColor Yellow
python -m pip install --upgrade pip setuptools wheel
python -m pip install pyinstaller
python -m pip install -e .
if ($LASTEXITCODE -ne 0) { 
    Write-Error "Failed to install dependencies"
    exit 1 
}

# Step 2: Build executable with PyInstaller
Write-Host "Building executable with PyInstaller..." -ForegroundColor Yellow
pyinstaller packaging/windows/ld-decode.spec --clean --noconfirm
if ($LASTEXITCODE -ne 0) { 
    Write-Error "PyInstaller failed"
    exit 1 
}

# Step 3: Build MSI with WiX
Write-Host "Building MSI installer..." -ForegroundColor Yellow

# Ensure build output directory exists for intermediate WiX artifacts
$null = New-Item -ItemType Directory -Force -Path build

# Ensure WiX tools are available on PATH
try {
    $null = Get-Command candle.exe -ErrorAction Stop
    $null = Get-Command light.exe -ErrorAction Stop
    $null = Get-Command heat.exe -ErrorAction Stop
} catch {
    Write-Error "WiX Toolset (candle.exe/light.exe/heat.exe) not found in PATH. Please install WiX and ensure its bin directory is on PATH."
    exit 1
}

# Harvest the PyInstaller output so all bundled files end up in the MSI
$appDir = Join-Path $PWD "dist\ld-decode"
if (-not (Test-Path $appDir)) {
    Write-Error "PyInstaller output folder not found at $appDir"
    exit 1
}

Write-Host "Harvesting files from $appDir..." -ForegroundColor Yellow

# Generate fragment with files from the bundle directory
& heat.exe dir "$appDir" -cg AppFiles -dr INSTALLFOLDER -gg -sfrag -sreg -srd -scom -ke -arch x64 -var wix.BundleSourceDir -out build\AppFiles.wxs
if ($LASTEXITCODE -ne 0) { 
    Write-Error "heat.exe failed with exit code $LASTEXITCODE"
    exit $LASTEXITCODE 
}

Write-Host "Compiling WiX sources..." -ForegroundColor Yellow

# Compile installer and files
& candle.exe -dVersion="$MsiVersion" -dBundleSourceDir="dist\ld-decode" -arch x64 packaging\windows\installer.wxs build\AppFiles.wxs -out build\
if ($LASTEXITCODE -ne 0) { 
    Write-Error "candle.exe failed with exit code $LASTEXITCODE"
    exit $LASTEXITCODE 
}

Write-Host "Linking MSI..." -ForegroundColor Yellow

# Link the MSI - use full version in filename but MSI version for internal metadata
& light.exe -dBundleSourceDir="dist\ld-decode" build\installer.wixobj build\AppFiles.wixobj -o "ld-decode-$Version-win64.msi" -ext WixUIExtension -sval
if ($LASTEXITCODE -ne 0) { 
    Write-Error "light.exe failed with exit code $LASTEXITCODE"
    exit $LASTEXITCODE 
}

Write-Host "Build complete: ld-decode-$Version-win64.msi" -ForegroundColor Green
