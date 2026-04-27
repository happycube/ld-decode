# CI/CD and Release Process

This repository uses GitHub Actions for continuous integration, automated testing, and release packaging.

## Workflows

### 1. Build and Test ([`.github/workflows/build.yml`](.github/workflows/build.yml))
**Triggers:** Push to main/master/develop, Pull Requests

**Jobs:**
- **python-tests**: Tests on Python 3.8-3.12
- **functional-tests**: CMake-based functional tests
- **build-linux**: Creates Python wheels for Linux
- **build-windows**: Creates Python wheels for Windows
- **build-macos**: Creates Python wheels for macOS

**Artifacts:** Platform-specific wheels (7-day retention)

### 2. Release ([`.github/workflows/release.yml`](.github/workflows/release.yml))
**Triggers:** Version tags (e.g., `v7.0.0`), Manual workflow dispatch

**Jobs:**
1. **test**: Reuses the build.yml workflow for all tests
2. **build-flatpak**: Creates Linux Flatpak package
3. **build-windows-msi**: Creates Windows MSI installer
4. **build-macos-dmg**: Creates macOS DMG disk image
5. **create-release**: Assembles GitHub Release with all packages
6. **publish-flatpak**: Instructions for Flathub publication

**Artifacts:** Installation packages (90-day retention)

## Creating a Release

### Prerequisites
1. Update version in [`pyproject.toml`](pyproject.toml)
2. Update version in [`lddecode/version`](lddecode/version)
3. Update CHANGELOG or release notes
4. Commit all changes

### Release Steps
```bash
# Create and push a version tag
git tag -a v7.0.0 -m "Release version 7.0.0"
git push origin v7.0.0
```

### What Happens Automatically
1. ✅ All tests run across multiple Python versions
2. ✅ Functional tests execute with CMake
3. ✅ Flatpak package is built for Linux
4. ✅ MSI installer is built for Windows
5. ✅ DMG disk image is built for macOS
6. ✅ GitHub Release is created with all packages attached
7. ✅ Release notes are auto-generated from commits

### Manual Release Trigger
You can also trigger a release manually from the GitHub Actions tab:
1. Go to Actions → Release workflow
2. Click "Run workflow"
3. Enter the version number (e.g., `7.0.0`)

## Installation Packages

### Linux - Flatpak
**Location:** `packaging/flatpak/`
```bash
# Install
flatpak install ld-decode-7.0.0-x86_64.flatpak

# Run
flatpak run com.github.happycube.LdDecode
```

### Windows - MSI Installer
```powershell
# Install (GUI or command line)
msiexec /i ld-decode-7.0.0-win64.msi

# Run from any command prompt
ld-decode --help
```

### macOS - DMG Disk Image
1. Download and open `ld-decode-7.0.0-macos.dmg`
2. Drag `ld-decode.app` to Applications
3. Run from Applications or terminal:
   ```bash
   /Applications/ld-decode.app/Contents/MacOS/ld-decode
   ```

## Artifact Reuse Strategy

The release workflow is designed for efficiency:
- **Single test run**: Tests execute once at the start, not per platform
- **Parallel packaging**: All three packages build simultaneously
- **Artifact retention**: Build artifacts kept for 7 days, releases for 90 days
- **No redundant builds**: Each commit builds once, tagged releases reuse artifacts

## Development Workflow

### For Contributors
```bash
# Your PR triggers:
1. Python tests (all supported versions)
2. Functional tests
3. Build verification for all platforms
```

### For Maintainers
```bash
# Merging to main/master:
1. All tests run
2. Build artifacts are created
3. Ready for manual testing

# Creating a release tag:
1. Full test suite runs
2. All platform packages are built
3. GitHub Release is published automatically
```

## Troubleshooting

### Build Failures
- Check the Actions tab for detailed logs
- Each job logs are available separately
- Download artifacts to test locally

### Package Testing
See [`packaging/README.md`](packaging/README.md) for:
- Manual build instructions
- Local testing procedures
- Platform-specific requirements

### Version Mismatches
Ensure version consistency across:
- `pyproject.toml`
- `lddecode/version`
- Git tag (must start with 'v')

## Additional Resources

- **Packaging Documentation**: See [`packaging/README.md`](packaging/README.md)
- **Build Instructions**: See [`BUILD.md`](BUILD.md)
- **Installation Guide**: See [`INSTALL.md`](INSTALL.md)
- **Contributing**: See [`CONTRIBUTING.md`](CONTRIBUTING.md)
