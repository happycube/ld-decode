#!/bin/bash
# Build script for creating macOS DMG installer
# Requires: Python, PyInstaller, create-dmg

set -e

VERSION=${1:-7.0.0}

# Extract version from git tag if not provided
# If VERSION starts with 'v', remove it (e.g., v7.0.2 -> 7.0.2)
if [[ $VERSION == v* ]]; then
    VERSION="${VERSION#v}"
fi

echo "Building ld-decode macOS installer version $VERSION"

# Update pyproject.toml with the version before building
echo "Updating pyproject.toml with version: $VERSION"
sed -i.bak "s/version = \"[^\"]*\"/version = \"$VERSION\"/" pyproject.toml

# Step 1: Install dependencies
echo "Installing Python dependencies..."
python3 -m pip install --upgrade pip pyinstaller
pip3 install -e .

# Step 2: Build application bundle with PyInstaller
echo "Building application bundle with PyInstaller..."
pyinstaller packaging/macos/ld-decode.spec --clean

# Step 3: Create DMG
echo "Creating DMG installer..."

# Install create-dmg if not present
if ! command -v create-dmg &> /dev/null; then
    echo "Installing create-dmg..."
    brew install create-dmg
fi

# Create DMG
create-dmg \
    --volname "ld-decode" \
    --volicon "dist/ld-decode.app/Contents/Resources/icon.icns" \
    --window-pos 200 120 \
    --window-size 800 400 \
    --icon-size 100 \
    --icon "ld-decode.app" 200 190 \
    --hide-extension "ld-decode.app" \
    --app-drop-link 600 185 \
    "ld-decode-${VERSION}-macos.dmg" \
    "dist/ld-decode.app" || true

# If create-dmg fails (it often does on first try), use hdiutil as fallback
if [ ! -f "ld-decode-${VERSION}-macos.dmg" ]; then
    echo "Using hdiutil fallback..."
    mkdir -p dmg_staging
    cp -R dist/ld-decode.app dmg_staging/
    ln -s /Applications dmg_staging/Applications
    
    hdiutil create -volname "ld-decode" \
        -srcfolder dmg_staging \
        -ov -format UDZO \
        "ld-decode-${VERSION}-macos.dmg"
    
    rm -rf dmg_staging
fi

echo "Build complete: ld-decode-${VERSION}-macos.dmg"
