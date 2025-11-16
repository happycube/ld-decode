# ld-analyse Oscilloscope Y/C Fixes - Session Log

**Date**: 2025
**Branch**: `ld-analyse/improvements`
**Status**: Completed and Pushed

---

## Summary

Fixed scanline oscilloscope display issues for dual-source (Y+C) TBC files, ensuring correct Y (luma) and C (chroma) channel display in all viewing modes. Added binary build GitHub Actions workflow for automated artifact generation.

---

## Issues Addressed

### 1. Y/C Data Extraction in BOTH_SOURCES Mode
**Problem**: When viewing dual-source TBC files (separate Y and C), the scanline oscilloscope was displaying incorrect luma (Y) traces. The oscilloscope was using the mono decoder's luma output instead of the chroma decoder's luma, which meant the Y trace didn't reflect the selected PAL/NTSC chroma decoder settings.

**Solution**: Modified `tbcsource.cpp::getScanLineData()` to use the chroma decoder's luma output (`chromaDecoder.getYData()`) instead of mono decoder when in `BOTH_SOURCES` mode, ensuring Y trace matches the selected decoder.

**Files Modified**:
- `tools/ld-analyse/tbcsource.cpp`

**Commit**: `96bdba2e` - "Fix scan-line oscilloscope Y/C data extraction in BOTH_SOURCES mode"

---

### 2. Chroma (C) Trace Mapping and Offset Handling
**Problem**: 
- In YC mode (combined Y+C display), the oscilloscope showed only luma, not the composite signal
- In C-only mode, the chroma trace was shifted vertically out of place
- The chroma offset (32767) was being incorrectly removed in the data extraction, but the oscilloscope expected raw chroma values to calculate centering itself

**Root Cause**: The chroma signal needed to be mapped as "composite minus luma" for correct vertical positioning in the oscilloscope, matching the "combine" feature logic used elsewhere in the codebase.

**Solution**: 
1. Modified `getScanLineData()` to keep raw chroma values (with offset intact) for oscilloscope's own centering calculation
2. For YC mode in BOTH_SOURCES: Generate synthetic composite by adding `(chroma - CHROMA_OFFSET)` to luma
3. Modified `oscilloscopedialog.cpp` to render C trace as `composite - luma` for accurate positioning
4. Preserved CHROMA_OFFSET constant and proper offset handling throughout the pipeline

**Technical Details**:
- `CHROMA_OFFSET = 32767` centers chroma around zero when subtracted
- Oscilloscope calculates midpoint IRE for chroma centering at line 201
- Composite generation for Y+C sources: `composite = luma + (chroma - CHROMA_OFFSET)`
- C trace display: `C = composite - Y` (computed in oscilloscope dialog)

**Files Modified**:
- `tools/ld-analyse/tbcsource.cpp` - Scanline data extraction and composite generation
- `tools/ld-analyse/oscilloscopedialog.cpp` - Chroma trace rendering calculation
- `tools/ld-analyse/tbcsource.h` - Validated (staged and committed)

**Commit**: `de5d6747` - "Fix scanline oscilloscope Y+C and C mapping for dual-source TBC"

---

## Binary Build Workflow Addition

### Phase 1: Initial Binary Build Workflow
**Problem**: Repository only had test workflows, no automated binary artifact generation for distribution and testing.

**Solution**: Created comprehensive GitHub Actions workflow for building release binaries on multiple platforms.

**Workflow Features**:
- **Linux Qt5 Build**: Ubuntu 22.04, full Qwt support
- **Linux Qt6 Build**: Ubuntu 22.04, no Qwt (unavailable for Qt6 on this platform)
- **macOS Build**: Latest macOS runner, Qt5 with Qwt
- **Triggers**: Push to `ld-analyse/improvements` and `main` branches, PRs, and releases
- **Artifacts**: Compressed tarballs (.tar.gz) with 30-day retention
- **Build Type**: Release (optimized)

**Files Created**:
- `.github/workflows/binary-builds.yml`

**Commit**: `badb93b6` - "Add binary build GitHub Actions workflow"

### Phase 2: Copy Production Workflows from vhs_decode Branch
**User Request**: Copy the complete, production-tested build workflows from the `vhs_decode` branch that include Windows, Linux, and macOS builds with proper packaging (AppImage, DMG, etc.).

**Solution**: Fetched and copied all build workflows from `fork/vhs_decode` branch.

**Workflows Copied**:
- **Linux Tools**: `build_linux_tools.yml` - Builds AppImage with linuxdeploy, Qt5, includes FlaLDF and scripts
- **Linux Decode**: `build_linux_decode.yml` - Builds Python decode tools
- **Windows Tools**: `build_windows_tools.yml` - Builds Windows executables with Qt6 via vcpkg, includes FFmpeg, FLAC, FlaLDF
- **Windows Decode**: `build_windows_decode.yml` - Builds Python decode tools for Windows
- **macOS Tools**: `build_macos_tools.yml` - Builds DMG for both x86_64 and ARM64, includes FlaLDF (x86_64 only)
- **macOS Decode**: `build_macos_decode.yml` - Builds Python decode tools for macOS
- **PyPI Publishing**: `push_pypi.yml` - Workflow for publishing to PyPI

**Trigger Method**: All workflows use `workflow_dispatch` for manual triggering, allowing on-demand testing.

**Commit**: `d6807011` - "Copy build workflows from vhs_decode branch"

---

## Testing and Validation

**User Validation**:
- User confirmed oscilloscope now correctly displays Y, C, and YC traces
- Chroma positioning "much more accurate"
- Y trace correctly reflects PAL/NTSC decoder selection in Y+C mode
- All view modes (field/frame/split) working correctly with oscilloscope

**Code Quality**:
- No compilation errors
- Consistent with existing codebase patterns
- Proper offset handling maintained throughout signal chain
- Integration with main window modes validated

---

## Git Push Summary

**Pushed to**: `fork/ld-analyse/improvements` (https://github.com/harrypm/ld-decode.git)

**Commits Pushed**:
1. `96bdba2e` - Fix scan-line oscilloscope Y/C data extraction in BOTH_SOURCES mode
2. `de5d6747` - Fix scanline oscilloscope Y+C and C mapping for dual-source TBC
3. `badb93b6` - Add binary build GitHub Actions workflow
4. `d6807011` - Copy build workflows from vhs_decode branch (+ session log)

**Push Stats**:
- First push: 24 objects, 5.12 KiB delta (oscilloscope fixes + initial workflow)
- Second push: 12 objects, 8.45 KiB delta (vhs_decode workflows + session log)

---

## Next Steps

### Testing Workflows
1. Navigate to: https://github.com/harrypm/ld-decode/actions
2. Manually trigger workflows to test:
   - **Build Linux tools** - Test AppImage generation
   - **Build Windows tools** - Test Windows Qt6 executable with bundled dependencies
   - **Build macOS tools** - Test DMG creation for both architectures
3. Download and validate artifacts from successful workflow runs
4. Test binaries on respective platforms

### Oscilloscope Testing
1. Test oscilloscope behavior with various TBC file types:
   - Single-source composite files
   - Dual-source Y+C files (S-Video style)
   - Chroma-only source files
   - PAL vs NTSC decoder outputs
2. Verify Y trace follows selected chroma decoder (PAL/NTSC)
3. Verify C trace positioning is accurate relative to Y and composite

---

## Technical Notes

### Signal Flow for Oscilloscope
```
TBC File(s) → ldDecodeMetaData → TBCSource
                                     ↓
                         getScanLineData() [tbcsource.cpp]
                                     ↓
                     ┌───────────────┴───────────────┐
                     ↓                               ↓
              BOTH_SOURCES                    ONE_SOURCE
         (Dual Y+C files)                 (Composite file)
                     ↓                               ↓
         chromaDecoder.getYData()          monoDecoder.getYData()
         chromaDecoder.getCData()          (no chroma)
                     ↓                               ↓
         Composite = Y + (C - 32767)       Composite = raw composite
                     ↓                               ↓
                     └───────────────┬───────────────┘
                                     ↓
                         OscilloscopeDialog::updateScope()
                                     ↓
                         Render Y, C, and YC traces
                         (C trace = Composite - Y)
```

### Key Constants
- `CHROMA_OFFSET = 32767` - Centers chroma signal around zero
- Oscilloscope expects raw chroma with offset for internal centering
- Composite generation removes offset: `Y + (C - CHROMA_OFFSET)`

---

## References

- Main repository: https://github.com/happycube/ld-decode
- User fork: https://github.com/harrypm/ld-decode
- Improvement branch: `ld-analyse/improvements`
- Related issues: Scanline oscilloscope Y/C display, chroma decoder integration

---

**Session completed successfully. All changes committed and pushed.**
