# Version Reporting Implementation

This document describes the unified version reporting system for ld-decode and ld-ldf-reader-py across all build types.

## Overview

All instances of ld-decode and ld-ldf-reader-py now report version information in a consistent format:

- **Format**: `branch:commit[:dirty]`
- **Release builds**: `release:7.0.0`
- **Development builds**: `develop/7.0.3-2-gd0eee56c`
- **With uncommitted changes**: `main:7.0.3-2-gd0eee56c:dirty`

This applies to:
- Source builds
- GitHub Actions packages
- Flatpak
- MSI (Windows)
- DMG (macOS)

## How It Works

### Version Resolution Priority

1. **Version File** (`lddecode/version`): Contains `branch:commit[:dirty]` - created during build
2. **Git Repository**: Live git information if available
3. **Defaults**: `main:unknown` if neither above are available

### Components

#### 1. Version Generation Script
- **Location**: `scripts/generate_version.py`
- **Purpose**: Generate version info from git
- **Usage**:
  ```bash
  scripts/generate_version.py              # Full version
  scripts/generate_version.py --branch     # Branch only
  scripts/generate_version.py --commit     # Commit only
  scripts/generate_version.py --dirty      # Exit code 0 if dirty
  scripts/generate_version.py -f "{branch}@{commit}"  # Custom format
  ```

#### 2. Version File
- **Location**: `lddecode/version`
- **Format**: Single line: `branch:commit[:dirty]`
- **Default**: `main:unknown`
- **Auto-generated**: During builds by CMake, build scripts, or CI/CD

#### 3. Python Utilities
- **File**: `lddecode/utils.py`
- **Functions**:
  - `get_version()`: Returns version string from file or git
  - `get_git_info()`: Returns `(branch, commit)` tuple
  - `is_git_dirty()`: Returns `True` if uncommitted changes

#### 4. Command-line Tools
All support `--version` or `-v` flags:
- `ld-decode --version`
- `ld-cut --version`
- `ld-ldf-reader-py --version`

Output format for CLI tools:
- Release: `7.0.0`
- Development: `branch/commit`
- With changes: `branch/commit-dirty`

## Build System Integration

### CMake
- **File**: `CMakeLists.txt`
- **Function**: `generate_version_file()`
- Generates `lddecode/version` during configuration
- Automatically detects git status

### Windows MSI Build
- **File**: `packaging/windows/build_msi.ps1`
- Generates version file before PyInstaller build
- Uses PowerShell git commands
- Updates both `pyproject.toml` and `lddecode/version`

### macOS DMG Build
- **File**: `packaging/macos/build_dmg.sh`
- Generates version file before PyInstaller build
- Uses bash git commands
- Updates both `pyproject.toml` and `lddecode/version`

### Flatpak Build
- **File**: `packaging/flatpak/com.github.happycube.LdDecode.yml`
- Generates version file as part of build module
- Uses bash git commands within container

### GitHub Actions Workflow
- **File**: `.github/workflows/build.yml`
- Generates version file for each build type:
  - Flatpak build
  - Windows MSI build
  - macOS DMG build
- Uses the branch/commit info from git or tag

## Version Format Details

### Components

- **branch**: Git branch name or "release"
  - "release" for tagged versions or detached HEAD
  - Actual branch name for development builds

- **commit**: Git commit information
  - Exact version tag (e.g., "7.0.0") for tagged commits
  - Output of `git describe --tags --always` for dev builds
  - "unknown" if git info unavailable

- **dirty**: Optional suffix `:dirty`
  - Added if working directory has uncommitted changes
  - Omitted if everything is committed

### Examples

| Scenario | Version String |
|----------|----------------|
| Release tag v7.0.0 on main | `release:7.0.0` |
| Main branch 2 commits ahead | `main:7.0.3-2-gd0eee56c` |
| Main with local changes | `main:7.0.3-2-gd0eee56c:dirty` |
| Packaged without git repo | `main:unknown` (unless version file updated) |
| Feature branch | `feature/xyz:abc1234` |
| Feature branch with changes | `feature/xyz:abc1234:dirty` |

## Testing the Version System

### Test in Source Build
```bash
# Test Python functions
python3 -c "from lddecode.utils import get_git_info; print(get_git_info())"

# Test CLI tools
python3 ld-decode --version
python3 ld-cut --version
python3 ld-ldf-reader-py --version
```

### Test with CMake
```bash
mkdir -p build
cd build
cmake ..
cat ../lddecode/version  # Should show git info
```

### Test Package Scenario
```bash
# Simulate packaged build by modifying version file
echo "release:7.0.0" > lddecode/version
python3 ld-decode --version  # Should output "7.0.0"
```

### Test Dirty Flag
```bash
# Make a change
echo "# test" >> lddecode/utils.py
python3 ld-decode --version  # Should end with "-dirty"

# Clean up
git checkout lddecode/utils.py
```

## File Changes Summary

### New Files
- `scripts/generate_version.py` - Standalone version generation utility
- `lddecode/version` - Version file template

### Modified Files
- `lddecode/utils.py` - Enhanced version detection functions
- `lddecode/main.py` - Already had version support
- `lddecode/ldf_reader.py` - Already had version support
- `ld-cut` - Added version support
- `ld-ldf-reader-py` - Added version support and imports
- `CMakeLists.txt` - Added version generation function
- `packaging/windows/build_msi.ps1` - Added version file generation
- `packaging/macos/build_dmg.sh` - Added version file generation
- `packaging/flatpak/com.github.happycube.LdDecode.yml` - Added version file generation
- `.github/workflows/build.yml` - Added version file generation for all build types

## Troubleshooting

### Version shows "unknown"
- Ensure git repository is available
- Check that `.git` directory exists
- Verify git commands work: `git describe --tags --always`

### Version not showing dirty flag
- Check uncommitted files: `git status --porcelain`
- Ensure git repo is in working directory
- Test with a simple change: `echo test >> file.txt`

### Different versions in different packages
- Ensure build scripts generate version file
- Check that version file is not outdated
- Run `cmake ..` or build script to regenerate

### Version shows "release" instead of branch name
- Likely on a detached HEAD state
- Can occur when checking out a tag
- This is expected behavior for packaged releases
