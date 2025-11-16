# LD-Analyse Feature Implementation Progress

## Branch Information
- **Branch:** `ld-analyse/pal-chroma-updates`
- **Fork URL:** https://github.com/harrypm/ld-decode
- **PR URL:** https://github.com/harrypm/ld-decode/pull/new/ld-analyse/pal-chroma-updates

## Completed Features

### Feature 1: Red Border Around Active Area ✅
- **Commit:** 962348be
- **Files:** mainwindow.cpp
- **Description:** Draws 4-pixel red rectangle around active video region when chroma decoding enabled
- **Location:** updateImageViewer() function, lines 531-548

### Feature 2: JSON-Only Metadata Loading ✅
- **Commit:** 65c429e8
- **Files:** tbcsource.cpp
- **Description:** Allow opening .json metadata files without corresponding .tbc video files
- **Enables:** VBI inspection, VITC viewing, graph analysis without video data
- **Location:** startBackgroundLoad() function, lines 1214-1223

## Remaining Features

### Feature 3: JSON SNR Fixer Tool
- **Type:** Tools menu with Ctrl+J shortcut
- **Purpose:** Detect and fix outlier bPSNR values above 50 dB
- **Implementation:** 
  - Add Tools menu to mainwindow.ui
  - Add on_actionFix_JSON_SNR_triggered() handler
  - Implement fixJsonSnrValues() in tbcsource
  - Rolling average detection method
  - Auto-backup to .bup file

### Feature 4: Scan-Line Oscilloscope Fix
- **Type:** Interface simplification
- **Purpose:** Fix vectorscope to work correctly with Y/C combined sources
- **Implementation:**
  - Simplify showTraceImage() signature
  - Field blending logic
  - Color differentiation (red/green by field)

## Session Summary
- Started with clean ld-decode clone
- Implemented and committed 2 features (Red border, JSON loading)
- Created feature branch on fork
- Ready to implement remaining 2 features

## Next Steps
1. Implement JSON SNR Fixer
2. Implement Oscilloscope fixes
3. Build and test
4. Create PR to main ld-decode repo
