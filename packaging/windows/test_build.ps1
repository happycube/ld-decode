# Test script to verify Windows build prerequisites and run a dry-run test
# Run this on Windows to check if your environment is ready

param(
    [switch]$DryRun
)

$ErrorActionPreference = "Continue"

Write-Host "`n=== ld-decode Windows Build Test ===" -ForegroundColor Cyan
Write-Host ""

# Check Python
Write-Host "Checking Python..." -ForegroundColor Yellow
try {
    $pythonVersion = python --version 2>&1
    Write-Host "  ✓ $pythonVersion" -ForegroundColor Green
} catch {
    Write-Host "  ✗ Python not found in PATH" -ForegroundColor Red
    exit 1
}

# Check pip
Write-Host "Checking pip..." -ForegroundColor Yellow
try {
    $pipVersion = python -m pip --version 2>&1
    Write-Host "  ✓ $pipVersion" -ForegroundColor Green
} catch {
    Write-Host "  ✗ pip not available" -ForegroundColor Red
    exit 1
}

# Check PyInstaller
Write-Host "Checking PyInstaller..." -ForegroundColor Yellow
try {
    $pyinstallerVersion = pyinstaller --version 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  ✓ PyInstaller $pyinstallerVersion" -ForegroundColor Green
    } else {
        Write-Host "  ! PyInstaller not installed - will be installed during build" -ForegroundColor Yellow
    }
} catch {
    Write-Host "  ! PyInstaller not installed - will be installed during build" -ForegroundColor Yellow
}

# Check WiX Toolset
Write-Host "Checking WiX Toolset..." -ForegroundColor Yellow
$wixFound = $false
$wixTools = @("candle.exe", "light.exe", "heat.exe")

foreach ($tool in $wixTools) {
    try {
        $toolPath = Get-Command $tool -ErrorAction Stop
        Write-Host "  ✓ $tool found at $($toolPath.Source)" -ForegroundColor Green
        $wixFound = $true
    } catch {
        Write-Host "  ✗ $tool not found in PATH" -ForegroundColor Red
    }
}

if (-not $wixFound) {
    Write-Host "`nWiX Toolset is not installed or not in PATH!" -ForegroundColor Red
    Write-Host "Install WiX from: https://wixtoolset.org/releases/" -ForegroundColor Yellow
    Write-Host "Or via chocolatey: choco install wixtoolset" -ForegroundColor Yellow
    exit 1
}

# Check project structure
Write-Host "Checking project structure..." -ForegroundColor Yellow
$requiredFiles = @(
    "packaging\windows\build_msi.ps1",
    "packaging\windows\installer.wxs",
    "packaging\windows\ld-decode.spec",
    "lddecode\main.py",
    "pyproject.toml"
)

foreach ($file in $requiredFiles) {
    if (Test-Path $file) {
        Write-Host "  ✓ $file" -ForegroundColor Green
    } else {
        Write-Host "  ✗ $file missing" -ForegroundColor Red
        exit 1
    }
}

Write-Host "`nAll prerequisites met!" -ForegroundColor Green

# Test version sanitization
Write-Host "`nTesting version sanitization..." -ForegroundColor Yellow
$testVersions = @("7.0.0", "1.2.3-beta", "0.0.0-dev-abc123")
foreach ($v in $testVersions) {
    if ($v -match '^(\d+)\.(\d+)\.(\d+)') {
        $sanitized = "$($matches[1]).$($matches[2]).$($matches[3]).0"
    } else {
        $sanitized = "0.0.1.0"
    }
    Write-Host "  $v -> $sanitized" -ForegroundColor Cyan
}

if ($DryRun) {
    Write-Host "`nDry run mode - skipping actual build" -ForegroundColor Yellow
    Write-Host "Run without -DryRun to execute: .\packaging\windows\build_msi.ps1" -ForegroundColor Yellow
} else {
    Write-Host "`nStarting build..." -ForegroundColor Cyan
    Write-Host "Running: .\packaging\windows\build_msi.ps1 -Version 'test'" -ForegroundColor Yellow
    & .\packaging\windows\build_msi.ps1 -Version "test"
    
    if ($LASTEXITCODE -eq 0) {
        Write-Host "`n✓ Build completed successfully!" -ForegroundColor Green
        if (Test-Path "ld-decode-test-win64.msi") {
            $msiInfo = Get-Item "ld-decode-test-win64.msi"
            Write-Host "MSI created: $($msiInfo.FullName) ($([math]::Round($msiInfo.Length/1MB, 2)) MB)" -ForegroundColor Cyan
        }
    } else {
        Write-Host "`n✗ Build failed with exit code $LASTEXITCODE" -ForegroundColor Red
        exit $LASTEXITCODE
    }
}
