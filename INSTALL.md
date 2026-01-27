# Installing ld-decode

This document describes how to install the ld-decode Python package and its dependencies.

## Quick Install

### Production Installation

```bash
pip install .
```

### Development Installation (Editable)

```bash
pip install -e "."
```

### With Development Dependencies

```bash
pip install -e ".[dev]"
```

## Installation Methods

### 1. Virtual Environment (Recommended)

Create an isolated Python environment:

```bash
# Create virtual environment
python3 -m venv venv

# Activate it
source venv/bin/activate          # Linux/Mac
# or
.\venv\Scripts\activate           # Windows

# Install ld-decode
pip install .
```

**Advantages:**
- Isolated dependencies, no conflicts with system Python
- No sudo required
- Easy to test different versions
- Works on any system with Python

### 2. User Installation (No sudo)

Install to your user directory (`~/.local`):

```bash
pip install --user .
```

Executables go to `~/.local/bin` and Python modules to `~/.local/lib/python3.x/site-packages/`.

**Advantages:**
- No system-wide impact
- No sudo required
- Single user installation

### 3. System-wide Installation

Install to system Python (requires sudo):

```bash
sudo pip install .
```

Installs to `/usr/local/lib/python3.x/site-packages/` and executables to `/usr/local/bin/`.

### 4. Development/Editable Installation

For developers making code changes:

```bash
pip install -e .
```

Code changes are immediately reflected without reinstalling. Ideal for active development.

With development tools:

```bash
pip install -e ".[dev]"
```

Includes `pytest`, `jupyter`, and `pandas` for testing and notebooks.

## Installed Components

### Python Package

The `lddecode` package containing:
- `core.py` - Core decoding functions
- `utils.py` - Utility functions
- `efm_pll.py` - EFM PLL implementation
- `commpy_filters.py` - Filter implementations
- `fft8.py` - FFT implementations
- `fdls.py` - FDLS decoder
- `utils_logging.py` - Logging utilities
- `utils_plotting.py` - Plotting utilities

### Dependencies

Automatically installed:
- `numpy>=1.17` - Numerical computing
- `scipy>=1.3` - Scientific computing
- `matplotlib>=3.0` - Plotting and visualization
- `numba>=0.48` - High-performance computing

### Command-line Scripts

Available scripts (if entry points are configured):
- `ld-decode` - Main decoding script
- `ld-cut` - Cut/segment tool
- `ld-compress` - Compression tool
- `cx-expander` - Expander tool

## Verifying Installation

### Check Python Package

```bash
python3 -c "import lddecode; print(lddecode.__file__)"
```

### List Installed Package Info

```bash
pip show ld-decode
```

### Check Installed Version

```bash
python3 -c "import lddecode; print(lddecode.__version__)" 2>/dev/null || echo "Version info not available"
```

## Uninstalling

Remove the package with:

```bash
pip uninstall ld-decode
```

If installed in a virtual environment, deactivate and delete the environment:

```bash
deactivate
rm -rf venv
```

## Troubleshooting

### Python Module Not Found

If `import lddecode` fails:

1. Verify the package is installed:
   ```bash
   pip show ld-decode
   ```

2. Check you're using the correct Python interpreter:
   ```bash
   which python3
   python3 -c "import sys; print(sys.version_info)"
   ```

3. If using a virtual environment, ensure it's activated:
   ```bash
   source venv/bin/activate
   ```

4. Reinstall the package:
   ```bash
   pip uninstall ld-decode -y
   pip install .
   ```

### Permission Denied

If you get permission errors when installing system-wide:

```bash
# Use --user flag to install to user directory
pip install --user .

# Or use a virtual environment (recommended)
python3 -m venv venv
source venv/bin/activate
pip install .
```

### Version Conflicts

If you see dependency version warnings:

```bash
# Update pip and setuptools
pip install --upgrade pip setuptools wheel

# Try installing again
pip install .
```

### Scripts Not Found

If command-line scripts aren't accessible:

1. Check if they're installed:
   ```bash
   pip show ld-decode -f | grep bin
   ```

2. If using `--user` install, ensure `~/.local/bin` is in PATH:
   ```bash
   export PATH="$HOME/.local/bin:$PATH"
   ```
   
   Add this to `~/.bashrc` or `~/.zshrc` to make it permanent.

3. If using a virtual environment, ensure it's activated:
   ```bash
   source venv/bin/activate
   ```

## Next Steps

- See [BUILD.md](BUILD.md) for development setup and building from source
- See [CONTRIBUTING.md](CONTRIBUTING.md) for contribution guidelines
- See the [ld-decode documentation](https://happycube.github.io/ld-decode-docs/) for usage
