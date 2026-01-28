# Windows MSI Installer Build

This directory contains the build configuration for creating a Windows MSI installer for ld-decode.

## Prerequisites

1. **Python 3.8+** - Download from [python.org](https://www.python.org/downloads/)
2. **WiX Toolset v3.11+** - Download from [wixtoolset.org](https://wixtoolset.org/releases/) or install via chocolatey:
   ```powershell
   choco install wixtoolset -y
   ```

## Files

- `build_msi.ps1` - Main build script
- `ld-decode.spec` - PyInstaller specification for bundling Python application
- `installer.wxs` - WiX Toolset configuration for MSI generation
- `test_build.ps1` - Validation and test script

## Quick Start

### Test Your Environment
```powershell
.\packaging\windows\test_build.ps1 -DryRun
```

### Build MSI Locally
```powershell
.\packaging\windows\build_msi.ps1 -Version "7.0.0"
```

Or use the test script to verify prerequisites and build:
```powershell
.\packaging\windows\test_build.ps1
```

## Build Process

The build script performs these steps:

1. **Install Dependencies** - Installs PyInstaller and project dependencies
2. **Bundle with PyInstaller** - Creates standalone executable in `dist/ld-decode/`
3. **Harvest Files** - Uses WiX `heat.exe` to scan all bundled files
4. **Compile WiX** - Uses `candle.exe` to compile installer configuration
5. **Link MSI** - Uses `light.exe` to create final MSI installer

## Output

The build creates:
- `ld-decode-{version}-win64.msi` - Installable MSI package
- `dist/ld-decode/` - PyInstaller bundle directory
- `build/` - Intermediate build artifacts

## Installation

The MSI installer:
- Installs to `C:\Program Files\ld-decode\`
- Adds ld-decode to system PATH
- Creates Start Menu shortcut
- Supports standard Windows install/uninstall

## Troubleshooting

### WiX tools not found
Ensure WiX Toolset bin directory is in your PATH. Default locations:
- `C:\Program Files (x86)\WiX Toolset v3.14\bin`
- `C:\Program Files (x86)\WiX Toolset v3.11\bin`

Manually add to PATH:
```powershell
$env:PATH += ";C:\Program Files (x86)\WiX Toolset v3.14\bin"
```

### PyInstaller fails
Ensure all dependencies are installed:
```powershell
python -m pip install -e .
```

### Permission errors during install
Run PowerShell as Administrator when building.

## Key Fixes Applied

This build configuration was completely refactored to fix multiple issues:

1. **Fixed WiX tool invocation** - Changed from `$tool.Source` to proper `& tool.exe` syntax
2. **Added error handling** - Proper `$ErrorActionPreference` and exit code checking
3. **Fixed version parameter** - Now properly uses `$(var.Version)` in WiX
4. **WiX version sanitization** - Converts non-compliant versions (e.g., `0.0.0-dev-abc123`) to valid MSI format (`0.0.1.0`)
5. **Added validation** - New test script to verify environment before building
6. **Improved logging** - Color-coded output with progress indicators
7. **Added missing flags** - `--noconfirm`, `-sfrag`, `-sval`, etc.
8. **Better path handling** - Consistent use of Windows path separators

### Version Format Requirements

WiX MSI requires versions in format `x.x.x.x` where each component is 0-65534:
- `7.0.0` → `7.0.0.0` ✓
- `1.2.3-beta` → `1.2.3.0` ✓
- `0.0.0-dev-abc123` → `0.0.1.0` ✓ (fallback)

The build script automatically sanitizes versions to MSI-compliant format while keeping the original version in the filename.

## CI/CD

The GitHub Actions workflow automatically:
- Installs WiX Toolset via chocolatey
- Detects correct WiX path
- Runs the build script
- Uploads MSI as artifact

See `.github/workflows/build.yml` for CI configuration.
