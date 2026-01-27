#!/bin/bash
# CI/CD Setup Validation Script
# Verifies that all required files are in place for the CI/CD pipeline

set -e

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

ERRORS=0
WARNINGS=0

echo "🔍 Validating CI/CD Setup for ld-decode"
echo "========================================"
echo ""

# Function to check if file exists
check_file() {
    local file=$1
    local critical=$2
    
    if [ -f "$file" ]; then
        echo -e "${GREEN}✓${NC} Found: $file"
        return 0
    else
        if [ "$critical" = "true" ]; then
            echo -e "${RED}✗${NC} Missing (CRITICAL): $file"
            ((ERRORS++))
        else
            echo -e "${YELLOW}!${NC} Missing (optional): $file"
            ((WARNINGS++))
        fi
        return 1
    fi
}

# Function to check if directory exists
check_dir() {
    local dir=$1
    
    if [ -d "$dir" ]; then
        echo -e "${GREEN}✓${NC} Found directory: $dir"
        return 0
    else
        echo -e "${RED}✗${NC} Missing directory: $dir"
        ((ERRORS++))
        return 1
    fi
}

echo "📋 Checking GitHub Actions Workflows..."
check_file ".github/workflows/build.yml" true
check_file ".github/workflows/release.yml" true
check_file ".github/workflows/tests.yml" false
echo ""

echo "📦 Checking Flatpak Configuration..."
check_dir "packaging/flatpak"
check_file "packaging/flatpak/com.github.happycube.LdDecode.yml" true
check_file "packaging/flatpak/com.github.happycube.LdDecode.metainfo.xml" true
check_file "packaging/flatpak/com.github.happycube.LdDecode.desktop" true
check_file "packaging/flatpak/requirements.txt" false
echo ""

echo "🪟 Checking Windows Packaging..."
check_dir "packaging/windows"
check_file "packaging/windows/ld-decode.spec" true
check_file "packaging/windows/installer.wxs" true
check_file "packaging/windows/build_msi.ps1" true
echo ""

echo "🍎 Checking macOS Packaging..."
check_dir "packaging/macos"
check_file "packaging/macos/ld-decode.spec" true
check_file "packaging/macos/build_dmg.sh" true
echo ""

echo "📚 Checking Documentation..."
check_file "tech-docs/CICD.md" true
check_file "packaging/README.md" true
check_file "tech-docs/QUICKSTART_CICD.md" false
echo ""

echo "⚙️  Checking Configuration Files..."
check_file "pyproject.toml" true
check_file "lddecode/version" true
check_file ".gitignore" true
echo ""

echo "🔬 Validating pyproject.toml..."
if grep -q '\[project.scripts\]' pyproject.toml; then
    echo -e "${GREEN}✓${NC} Script entry points configured"
else
    echo -e "${YELLOW}!${NC} Warning: No script entry points in pyproject.toml"
    ((WARNINGS++))
fi

if grep -q 'version = ' pyproject.toml; then
    VERSION=$(grep 'version = ' pyproject.toml | head -1 | sed 's/.*"\(.*\)".*/\1/')
    echo -e "${GREEN}✓${NC} Version found in pyproject.toml: $VERSION"
else
    echo -e "${RED}✗${NC} No version found in pyproject.toml"
    ((ERRORS++))
fi
echo ""

echo "🧪 Checking Python Environment..."
if command -v python3 &> /dev/null; then
    PYTHON_VERSION=$(python3 --version)
    echo -e "${GREEN}✓${NC} Python found: $PYTHON_VERSION"
else
    echo -e "${RED}✗${NC} Python3 not found"
    ((ERRORS++))
fi

if python3 -c "import lddecode" 2>/dev/null; then
    echo -e "${GREEN}✓${NC} lddecode module importable"
else
    echo -e "${YELLOW}!${NC} Warning: lddecode module not installed (run 'pip install -e .')"
    ((WARNINGS++))
fi
echo ""

echo "📊 Summary"
echo "=========="
if [ $ERRORS -eq 0 ] && [ $WARNINGS -eq 0 ]; then
    echo -e "${GREEN}✅ All checks passed!${NC}"
    echo ""
    echo "Your CI/CD setup is complete and ready to use."
    echo "Next steps:"
    echo "  1. Commit and push: git add . && git commit -m 'Add CI/CD' && git push"
    echo "  2. Watch the build: Check the Actions tab on GitHub"
    echo "  3. Create a release: git tag v7.0.0 && git push origin v7.0.0"
    exit 0
elif [ $ERRORS -eq 0 ]; then
    echo -e "${YELLOW}⚠️  Setup complete with $WARNINGS warning(s)${NC}"
    echo ""
    echo "The CI/CD pipeline will work, but you may want to address the warnings."
    exit 0
else
    echo -e "${RED}❌ Setup incomplete: $ERRORS error(s), $WARNINGS warning(s)${NC}"
    echo ""
    echo "Please fix the critical errors before proceeding."
    exit 1
fi
