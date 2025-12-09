# Installing ld-decode

This document describes how to install ld-decode tools and libraries after building.

## Quick Install

### Using Staging Directory (No sudo required)

```bash
cd build
make install DESTDIR=/tmp/staging
```

This installs all built targets to the staging directory without requiring root privileges.

### System-wide Installation (Requires sudo)

```bash
cd build
sudo make install
```

This installs to `/usr/local` and requires root privileges to write to system directories.

## Installation Overview

ld-decode uses the standard CMake install process. Built binaries, libraries, and Python modules are installed to target directories based on the system type and build configuration.

### Sudo Requirements

- **Staging directory** (`DESTDIR=/tmp/staging` or similar): No sudo needed
- **System directories** (`/usr/local`, `/usr`, `/opt`): Requires `sudo`
- **Custom user directory** (e.g., `~/.local`): No sudo needed with appropriate prefix

### Default Installation Directories

When you build ld-decode, the `make install` command will place files in standard system directories:

| Component | Default Location | Notes |
|-----------|------------------|-------|
| Executables (tools) | `/usr/local/bin` | Command-line tools like `ld-analyse`, `ld-chroma-decoder` |
| Libraries | `/usr/local/lib` | Compiled C++ libraries |
| Python modules | `/usr/local/lib/python*/site-packages` | `lddecode` Python package |
| Headers | `/usr/local/include` | Development headers |
| CMake configs | `/usr/local/lib/cmake` | CMake package configuration files |

### Using a Staging Directory (Recommended)

For testing or packaging, install to a staging directory instead:

```bash
make install DESTDIR=/tmp/staging
```

This places files in:
```
/tmp/staging/
├── usr/local/bin/         # Executables
├── usr/local/lib/         # Libraries
└── usr/local/lib/python3.x/site-packages/  # Python modules
```

**Advantage:** You can examine and test the installation without affecting your system, or prepare files for packaging.

### Custom Installation Prefix

To use a different base directory (instead of `/usr/local`):

```bash
cd build
cmake -DCMAKE_INSTALL_PREFIX=/opt/ld-decode ..
make -j8
make install
```

This will install to:
```
/opt/ld-decode/
├── bin/         # Executables
├── lib/         # Libraries
└── lib/python3.x/site-packages/  # Python modules
```

**Combining with DESTDIR:**
```bash
cmake -DCMAKE_INSTALL_PREFIX=/opt/ld-decode ..
make install DESTDIR=/tmp/staging
```

Files go to: `/tmp/staging/opt/ld-decode/`

## Installation Components

### Executables

Tools are installed to `bin/`:
- `ld-analyse` - GUI analysis tool
- `ld-chroma-decoder` - Chroma decoder
- `ld-chroma-encoder` - Chroma encoder
- `ld-json-converter` - JSON to SQLite converter
- `ld-process-vbi` - VBI processor
- `ld-process-vits` - VITS processor
- `ld-cut` - Cut/segment tool
- `ld-ldf-reader` - LDF file reader
- `ld-discmap` - Disc mapper
- `ld-dropout-correct` - Dropout corrector
- `ld-lds-converter` - LDS format converter
- `ld-export-metadata` - Export metadata tool
- `ld-disc-stacker` - Disc stacker

### Libraries

C++ libraries are installed to `lib/`:
- `liblddecode-library.a` - Core static library
- `liblddecode-chroma.a` - Chroma decoding library

### Python Modules

The Python package is installed to `lib/python3.x/site-packages/`:
- `lddecode/` - Main Python package
  - `core.py` - Core decoding functions
  - `utils.py` - Utility functions
  - `efm_pll.py` - EFM PLL implementation
  - `commpy_filters.py` - Filter implementations
  - Other supporting modules

After installation, you can import in Python:
```python
import lddecode
from lddecode.core import LDDecode
```

## Verifying Installation

### Check Executables

```bash
# If installed to /usr/local/bin
which ld-analyse
ld-analyse --version

# If installed to custom location
/opt/ld-decode/bin/ld-analyse --version
```

### Check Python Module

```bash
python3 -c "import lddecode; print(lddecode.__file__)"
```

### List Installed Files

With DESTDIR staging:
```bash
find /tmp/staging -type f
```

This shows all files that would be installed to the system.

## Uninstalling

If you installed to system directories and need to uninstall, you'll need to manually remove files. The staging directory approach avoids this:

```bash
# With DESTDIR staging, just remove the directory
rm -rf /tmp/staging
```

For system-wide installations, CMake doesn't provide a built-in uninstall command. You would need to:
1. Keep track of installed files
2. Manually remove them
3. Or use your system's package manager if you packaged it

## Installation Examples

### Development Installation (Staging Directory)

Build and install to a temporary staging directory for testing:

```bash
mkdir build
cd build
cmake -DCMAKE_BUILD_TYPE=RelWithDebInfo ..
make -j8
make install DESTDIR=/tmp/ld-decode-staging

# Test the installation
/tmp/ld-decode-staging/usr/local/bin/ld-analyse --version
```

### System-wide Installation

Install to `/usr/local` (may require sudo):

```bash
mkdir build
cd build
cmake -DCMAKE_BUILD_TYPE=Release ..
make -j8
sudo make install

# Test the installation
ld-analyse --version
which ld-analyse
```

### Custom Prefix Installation

Install to a custom location (e.g., `/opt/ld-decode`):

```bash
mkdir build
cd build
cmake -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/opt/ld-decode ..
make -j8
sudo make install

# Add to PATH (add to ~/.bashrc for permanent)
export PATH=/opt/ld-decode/bin:$PATH
ld-analyse --version
```

### Creating a Package

Prepare files for creating an RPM or DEB package:

```bash
mkdir build
cd build
cmake -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/usr ..
make -j8
make install DESTDIR=./package-root

# Inspect the package structure
tree ./package-root
```

## Troubleshooting

### Permission Denied

If you get "Permission denied" when installing to system directories:

```bash
sudo make install
```

Or use DESTDIR to avoid needing sudo:
```bash
make install DESTDIR=$HOME/ld-decode-install
```

### Python Module Not Found

If `import lddecode` fails after installation:

1. Check the Python version used for installation:
   ```bash
   python3 -c "import sys; print(sys.version_info)"
   ```

2. Verify installation location:
   ```bash
   find /usr/local -name "lddecode" -type d
   ```

3. Check PYTHONPATH if using custom prefix:
   ```bash
   export PYTHONPATH=/opt/ld-decode/lib/python3.x/site-packages:$PYTHONPATH
   python3 -c "import lddecode"
   ```

4. **Using a Virtual Environment** (Recommended for Development)
   
   If you're developing or want to avoid system-wide Python packages, use a virtual environment:
   
   ```bash
   # Create a virtual environment
   python3 -m venv ~/ld-decode-venv
   
   # Activate it
   source ~/ld-decode-venv/bin/activate
   
   # Install dependencies
   pip install -r requirements.txt
   
   # Install ld-decode Python module
   cd build
   make install DESTDIR=~/ld-decode-staging
   
   # Or install directly into the venv
   cd ..
   pip install -e .
   ```
   
   **Benefits of virtual environments:**
   - Isolated Python dependencies
   - No sudo required
   - Easy to test different versions
   - Won't conflict with system Python packages
   
   **Note:** When using a virtual environment, remember to activate it before running ld-decode Python tools:
   ```bash
   source ~/ld-decode-venv/bin/activate
   ```
   
   To make this permanent, add the activation command to your `~/.bashrc` or `~/.zshrc`.

5. **System vs. User Installation**
   
   If you don't want to use sudo or affect the system Python installation:
   
   ```bash
   # Install to user directory (~/.local)
   cd build
   cmake -DCMAKE_INSTALL_PREFIX=~/.local ..
   make -j8
   make install
   
   # Python will automatically find packages in ~/.local
   python3 -c "import lddecode"
   ```

### Tools Not in PATH

If executables are installed but not found:

```bash
# Check installation
ls -l /usr/local/bin/ld-*

# Add to PATH (add to ~/.bashrc for permanent)
export PATH=/usr/local/bin:$PATH

# Or use full path
/usr/local/bin/ld-analyse
```

For custom prefix:
```bash
export PATH=/opt/ld-decode/bin:$PATH
```
