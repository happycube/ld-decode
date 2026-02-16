# Quick Start: CI/CD Setup

## ✅ What's Been Configured

Your repository now has a complete CI/CD pipeline with automated packaging for Linux, Windows, and macOS.

### Files Created

#### GitHub Actions Workflows
- [`.github/workflows/build.yml`](.github/workflows/build.yml) - Main build and test workflow
- [`.github/workflows/release.yml`](.github/workflows/release.yml) - Automated release packaging
- [`.github/workflows/tests.yml`](.github/workflows/tests.yml) - Updated to use build.yml

#### Linux Flatpak
- [`packaging/flatpak/com.github.happycube.LdDecode.yml`](packaging/flatpak/com.github.happycube.LdDecode.yml) - Flatpak manifest
- [`packaging/flatpak/com.github.happycube.LdDecode.metainfo.xml`](packaging/flatpak/com.github.happycube.LdDecode.metainfo.xml) - App metadata
- [`packaging/flatpak/com.github.happycube.LdDecode.desktop`](packaging/flatpak/com.github.happycube.LdDecode.desktop) - Desktop entry
- [`packaging/flatpak/requirements.txt`](packaging/flatpak/requirements.txt) - Python dependencies

#### Windows MSI
- [`packaging/windows/ld-decode.spec`](packaging/windows/ld-decode.spec) - PyInstaller config
- [`packaging/windows/installer.wxs`](packaging/windows/installer.wxs) - WiX installer config
- [`packaging/windows/build_msi.ps1`](packaging/windows/build_msi.ps1) - Build script

#### macOS DMG
- [`packaging/macos/ld-decode.spec`](packaging/macos/ld-decode.spec) - PyInstaller config for macOS
- [`packaging/macos/build_dmg.sh`](packaging/macos/build_dmg.sh) - Build script

#### Documentation
- [`CICD.md`](CICD.md) - Complete CI/CD documentation
- [`packaging/README.md`](packaging/README.md) - Packaging documentation
- [`.gitignore`](.gitignore) - Updated with packaging artifacts

#### Configuration Updates
- [`pyproject.toml`](pyproject.toml) - Added `ld-decode` script entry point

## 🚀 How to Use

### Every Commit
When you push code to `main`, `master`, or `develop`:
1. Tests run on Python 3.8-3.12
2. Functional tests execute
3. Build artifacts are created for all platforms
4. Artifacts are available for download (7 days)

### Creating a Release

1. **Update version numbers:**
   ```bash
   # Edit pyproject.toml - change version = "7.0.0" to your version
   # Edit lddecode/version - update version number
   ```

2. **Commit and tag:**
   ```bash
   git add pyproject.toml lddecode/version
   git commit -m "Bump version to 7.0.0"
   git tag -a v7.0.0 -m "Release version 7.0.0"
   git push origin main
   git push origin v7.0.0
   ```

3. **Automatic process:**
   - ✅ All tests run
   - ✅ Flatpak package built
   - ✅ Windows MSI installer built
   - ✅ macOS DMG disk image built
   - ✅ GitHub Release created
   - ✅ All packages attached to release

### Manual Release (Optional)
You can trigger a release without a git tag:
1. Go to GitHub Actions tab
2. Select "Release" workflow
3. Click "Run workflow"
4. Enter version number (e.g., `7.0.0`)

## 📦 Installation Packages

After a release, users can install via:

**Linux (Flatpak):**
```bash
flatpak install ld-decode-7.0.0-x86_64.flatpak
flatpak run com.github.happycube.LdDecode
```

**Windows (MSI):**
```powershell
# Double-click the .msi or:
msiexec /i ld-decode-7.0.0-win64.msi
```

**macOS (DMG):**
1. Open the `.dmg`
2. Drag to Applications
3. Run from Applications folder

## 🔍 Monitoring

### Build Status
Check the Actions tab on GitHub to see:
- Current workflow runs
- Build logs for each platform
- Test results
- Download artifacts

### Badges (Optional)
Add to your README.md:
```markdown
![Build Status](https://github.com/USERNAME/ld-decode/workflows/Build%20and%20Test/badge.svg)
![Release](https://github.com/USERNAME/ld-decode/workflows/Release/badge.svg)
```

## 🛠️ Next Steps

1. **Test the workflow:**
   ```bash
   git add .
   git commit -m "Add CI/CD packaging infrastructure"
   git push
   ```
   Watch the Actions tab to see the build workflow run.

2. **Create a test release:**
   ```bash
   git tag v7.0.0-test
   git push origin v7.0.0-test
   ```
   This will trigger the full release process.

3. **Customize (if needed):**
   - Update app icons for Windows/macOS
   - Adjust build scripts for your specific needs
   - Modify Flatpak permissions in the manifest
   - Add code signing for Windows/macOS

## 📚 Additional Resources

- **Full CI/CD Guide:** See [CICD.md](CICD.md)
- **Packaging Details:** See [packaging/README.md](packaging/README.md)
- **Build Instructions:** See [BUILD.md](BUILD.md)
- **Contributing:** See [CONTRIBUTING.md](CONTRIBUTING.md)

## ⚠️ Important Notes

1. **Version Consistency:** Always update both `pyproject.toml` and `lddecode/version`
2. **Tag Format:** Release tags must start with 'v' (e.g., `v7.0.0`)
3. **Artifact Retention:** Build artifacts kept 7 days, release artifacts 90 days
4. **Platform Dependencies:** MSI requires WiX Toolset, DMG requires create-dmg (handled by CI)

## 🐛 Troubleshooting

If builds fail:
1. Check the Actions tab for error logs
2. Review [packaging/README.md](packaging/README.md) troubleshooting section
3. Test packaging locally using the build scripts
4. Ensure all dependencies are properly listed in pyproject.toml

---

**Ready to go! 🎉** Your next push will automatically trigger the build workflow.
