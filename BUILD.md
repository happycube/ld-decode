# Building ld-decode

ld-decode is a Python package for decoding LaserDisc RF captures. This document describes how to build and prepare it for development.

## Quick Start

### For Users (Installation Only)

```bash
pip install .
```

See [INSTALL.md](INSTALL.md) for detailed installation instructions.

### For Developers

```bash
# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: .\venv\Scripts\activate

# Install in editable mode with dev dependencies
pip install -e ".[dev]"
```

## Prerequisites

- **Python 3.6 or later** (tested on Python 3.6 through 3.12)
- **pip** (Python package installer)
- **git** (for cloning the repository)

## Cloning the Repository

```bash
git clone --recurse-submodules https://github.com/happycube/ld-decode.git
cd ld-decode
```

If you already cloned without `--recurse-submodules`, initialize the testdata submodule:

```bash
git submodule update --init --recursive
```

## Development Setup

### 1. Create a Virtual Environment

```bash
python3 -m venv venv
source venv/bin/activate          # Linux/macOS
# or
.\venv\Scripts\activate           # Windows
```

### 2. Upgrade pip and Build Tools

```bash
pip install --upgrade pip setuptools wheel
```

### 3. Install in Editable Mode

For development with automatic code reloading:

```bash
# Basic installation
pip install -e .

# With development tools (recommended for developers)
pip install -e ".[dev]"
```

The `-e` flag installs the package in editable mode, so changes to the source code are immediately reflected without reinstalling.

### 4. Verify Installation

```bash
# Check the package is installed
python -c "import lddecode; print(lddecode.__file__)"

# List installed package info
pip show ld-decode

# Run the main CLI tool
ld-decode --help
```

## Project Structure

- **lddecode/** - Core Python package containing:
  - `core.py` - Main decoding functions
  - `main.py` - CLI entry point
  - `utils.py` - Utility functions
  - `efm_pll.py` - EFM PLL implementation
  - `fdls.py` - FDLS implementation
  - Filter and plotting utilities

- **scripts/** - Helper scripts for development and testing
  - `test-decode` - Test decoding pipeline
  - `test-chroma` - Chroma test tools
  - Various encoding and processing scripts

- **notebooks/** - Jupyter notebooks for experimentation and documentation

- **testdata/** - Sample data for testing

## Dependencies

### Core Dependencies (Automatically Installed)

```
matplotlib>=3.0      # Plotting and visualization
numba>=0.48         # High-performance numerical computing
numpy>=1.17         # Numerical arrays and operations
scipy>=1.3          # Scientific computing
```

### Development Dependencies

Install with: `pip install -e ".[dev]"`

```
jupyter>=1.0        # Interactive notebooks
pandas>=1.0         # Data analysis
pytest>=6.0         # Testing framework
pytest-cov>=2.10    # Code coverage
```

### Documentation Dependencies

Install with: `pip install -e ".[docs]"`

```
sphinx>=3.0              # Documentation generator
sphinx-rtd-theme>=0.5   # ReadTheDocs theme
```

## Building Distribution Packages

To create distributable packages (wheel and source tarball):

```bash
pip install build
python -m build
```

This creates in the `dist/` directory:
- `ld_decode-7.0.0-py3-none-any.whl` - Binary wheel
- `ld-decode-7.0.0.tar.gz` - Source distribution

## Running Tests

With development dependencies installed:

```bash
pytest                      # Run all tests
pytest --cov=lddecode     # Run with coverage report
pytest -v                  # Verbose output
```

## Troubleshooting

### Virtual Environment Not Activated

If you get "command not found" or "No module named" errors, ensure your virtual environment is activated:

```bash
source venv/bin/activate  # Linux/macOS
# or
.\venv\Scripts\activate   # Windows
```

### Module Import Errors

Ensure the package is installed in editable mode:

```bash
pip install -e .
```

### Dependency Issues

Clean reinstall:

```bash
pip uninstall ld-decode -y
pip install -e ".[dev]"
```

### Python Version Mismatch

Verify you're using Python 3.6+:

```bash
python --version
```

## Code Quality Tools

The project uses:
- **black** - Code formatting (100 char line length)
- **isort** - Import organization
- **pylint** - Code linting
- **mypy** - Type checking

Configure these in `pyproject.toml`.

## Additional Resources

- [INSTALL.md](INSTALL.md) - Installation methods and options
- [CONTRIBUTING.md](CONTRIBUTING.md) - Contributing guidelines
- [README.md](README.md) - Project overview
- [ld-decode documentation](https://happycube.github.io/ld-decode-docs/) - Complete usage guide
