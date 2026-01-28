# Packaging Documentation

This directory contains packaging configurations for creating installation packages for ld-decode across multiple platforms.

## Platform Support

### Linux - Flatpak
**Location:** `packaging/flatpak/`
**Output:** `.flatpak` bundle

The Flatpak package provides a sandboxed installation compatible with most Linux distributions.

**Files:**
- `com.github.happycube.LdDecode.yml` - Flatpak manifest
- `com.github.happycube.LdDecode.metainfo.xml` - Application metadata
- `com.github.happycube.LdDecode.desktop` - Desktop entry

**Manual Build:**
```bash
flatpak-builder --force-clean build-dir packaging/flatpak/com.github.happycube.LdDecode.yml
flatpak-builder --repo=repo --force-clean build-dir packaging/flatpak/com.github.happycube.LdDecode.yml
flatpak build-bundle repo ld-decode.flatpak com.github.happycube.LdDecode
```

**Installation:**
```bash
flatpak install ld-decode-*.flatpak
flatpak run com.github.happycube.LdDecode
```

### Windows - MSI Installer
**Location:** `packaging/windows/`
**Output:** `.msi` installer

The MSI installer provides a standard Windows installation experience with Start Menu integration.

**Files:**
- `ld-decode.spec` - PyInstaller specification
- `installer.wxs` - WiX Toolset configuration
- `build_msi.ps1` - Build script

**Requirements:**
- Python 3.8+
- PyInstaller
- WiX Toolset v3.11+

**Manual Build:**
```powershell
.\packaging\windows\build_msi.ps1 -Version "7.0.0"
```

**Installation:**
Double-click the `.msi` file or run:
```powershell
msiexec /i ld-decode-7.0.0-win64.msi
```

### macOS - DMG Image
**Location:** `packaging/macos/`
**Output:** `.dmg` disk image

The DMG provides a drag-and-drop installation for macOS.

**Files:**
- `ld-decode.spec` - PyInstaller specification for macOS
- `build_dmg.sh` - Build script

**Requirements:**
- Python 3.8+
- PyInstaller
- create-dmg (via Homebrew)

**Manual Build:**
```bash
chmod +x packaging/macos/build_dmg.sh
./packaging/macos/build_dmg.sh 7.0.0
```

**Installation:**
1. Open the `.dmg` file
2. Drag `ld-decode.app` to the Applications folder

## CI/CD Integration

### Automated Builds
Every push triggers the build workflow ([`.github/workflows/build.yml`](../.github/workflows/build.yml)):
- Runs Python unit tests across multiple versions
- Runs functional tests with CMake
- Builds Python distribution artifacts (sdist/wheel) only
- Uploads `dist/` artifacts for download (7-day retention)

### Release Process
When a version tag is pushed (e.g., `v7.0.0`), the release workflow ([`.github/workflows/release.yml`](../.github/workflows/release.yml)):
1. Runs all tests from the build workflow
2. Builds OS installers/bundles in parallel using the scripts in `packaging/`:
	- Flatpak via the Flatpak manifest
	- Windows MSI via `packaging/windows/build_msi.ps1`
	- macOS DMG via `packaging/macos/build_dmg.sh`
3. Creates a GitHub Release
4. Attaches all installation packages to the release
5. Artifacts are retained for 90 days

**Creating a Release:**
```bash
git tag -a v7.0.0 -m "Release version 7.0.0"
git push origin v7.0.0
```

## Version Management

Version numbers are defined in:
- [`pyproject.toml`](../pyproject.toml) - Python package version
- [`lddecode/version`](../lddecode/version) - Runtime version file
- Packaging specs (should match `pyproject.toml`)

Update all version references before creating a release tag.

## Artifact Reuse

The release workflow reuses build artifacts from the initial test phase:
- Tests run once at the beginning
- Build jobs depend on successful tests
- All packaging jobs run in parallel after tests pass
- Artifacts are collected and attached to the GitHub Release

This ensures:
- Faster releases (tests run once, not per platform)
- Consistency (same tested code is packaged)
- Efficiency (parallel packaging jobs)

## Troubleshooting

### Flatpak Build Fails
- Ensure all source URLs and checksums are correct in the manifest
- Verify the runtime version is available
- Check that all dependencies are properly listed

### Windows MSI Build Fails
- Verify WiX Toolset is installed and in PATH
- Check that PyInstaller successfully created the executable
- Ensure GUIDs in `installer.wxs` are unique

### macOS DMG Build Fails
- Verify create-dmg is installed: `brew install create-dmg`
- Check that PyInstaller created a valid `.app` bundle
- The script includes a fallback to `hdiutil` if create-dmg fails

## Testing Packages Locally

### Flatpak
```bash
flatpak install --user ld-decode-*.flatpak
flatpak run com.github.happycube.LdDecode --help
```

### Windows
Install the MSI and run from Command Prompt:
```cmd
ld-decode --help
```

### macOS
Mount the DMG, copy to Applications, and run:
```bash
/Applications/ld-decode.app/Contents/MacOS/ld-decode --help
```
