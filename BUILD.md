# Building ld-decode

This project uses CMake and enforces out-of-source builds. All build artifacts are kept in a separate `build/` directory, keeping the source tree clean.

## Cloning the Repository

This project uses git submodules for test data and dependencies. Clone the repository with `--recursive` to automatically fetch all submodules:

```bash
git clone --recursive https://github.com/happycube/ld-decode.git
cd ld-decode
```

**If you already cloned without `--recursive`**, initialize and update submodules:

```bash
git submodule update --init --recursive
```

## Quick Start

```bash
mkdir build
cd build
cmake -DCMAKE_BUILD_TYPE=RelWithDebInfo ..
make -j8
ctest --output-on-failure
```

## Step-by-Step Instructions

### 1. Create a Build Directory

```bash
mkdir build
cd build
```

Keep the build directory separate from the source tree. This is a CMake best practice.

### 2. Configure the Build

```bash
cmake -DCMAKE_BUILD_TYPE=RelWithDebInfo ..
```

This configures the build with:
- **RelWithDebInfo**: Release build with debug symbols for better profiling and debugging
- **..**: Points to the source directory (parent directory)

The cmake step will:
- Detect your system's compiler and libraries
- Find Qt6 libraries
- Configure build files for your platform

### 3. Build the Project

```bash
make -j8
```

Builds all targets using 8 parallel jobs. Adjust the number based on your CPU core count.

**Single-threaded build** (if parallel builds cause issues):
```bash
make
```

### 4. Run Tests

```bash
ctest --output-on-failure
```

Runs all tests sequentially. Tests must run sequentially due to shared testout directory.

**Run specific test**:
```bash
ctest -R chroma --output-on-failure
```

### 5. Install (Optional)

```bash
make install DESTDIR=/tmp/staging
```

Installs built binaries and libraries to the staging directory.

## Building Individual Tools

You can build specific tools or libraries without building the entire project:

```bash
# Build a single tool
make ld-analyse
make ld-chroma-decoder
make ld-json-converter
```

**Common tool targets:**
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

**Library targets:**
- `lddecode-library` - Core library
- `lddecode-chroma` - Chroma decoder library

**Test targets:**
- `testfilter` - Filter tests
- `testlinenumber` - Line number tests
- `testmetadata` - Metadata tests
- `testvbidecoder` - VBI decoder tests
- `testvitcdecoder` - VITC decoder tests

**View all available targets:**
```bash
make help | grep "^  [a-z]"
```

## Build Options

You can customize the build with additional CMake variables:

```bash
cmake -DCMAKE_BUILD_TYPE=Release ..
```

**Available build types:**
- `Debug` - Debug symbols, no optimization
- `Release` - Optimized, no debug symbols
- `RelWithDebInfo` - Optimized with debug symbols (recommended)
- `MinSizeRel` - Minimized size

### Qt Debug Symbols

To include Qt debug symbols for debugging Qt-related issues:

**Option 1: Debug build (full debug, no optimization)**
```bash
cd build
cmake -DCMAKE_BUILD_TYPE=Debug ..
make -j8
```

**Option 2: Optimized build with Qt debug symbols**
```bash
cd build
cmake -DCMAKE_BUILD_TYPE=RelWithDebInfo -DQT_DEBUG=ON ..
make -j8
```

**Option 3: Reconfigure existing build**
If you already have a build directory, you can reconfigure:
```bash
cd build
cmake -DCMAKE_BUILD_TYPE=RelWithDebInfo -DQT_DEBUG=ON ..
make -j8
```

Debug builds will be larger and slower but provide better debugging information for stepping through code and inspecting Qt internals.

## Troubleshooting

### Rebuilding After Source Changes

If you make changes to `CMakeLists.txt`, cmake will automatically reconfigure during the next `make` invocation.

### Clean Build

To perform a clean build:

```bash
rm -rf build
mkdir build
cd build
cmake -DCMAKE_BUILD_TYPE=RelWithDebInfo ..
make -j8
```

### In-Source Build Error

If you accidentally run cmake in the source directory, you'll see:

```
In-source builds are not allowed. Please create a build directory and run:
    mkdir build
    cd build
    cmake -DCMAKE_BUILD_TYPE=RelWithDebInfo ..
```

Simply follow those instructions to fix it.

## Dependencies

The project requires:
- CMake 3.16 or later
- Qt6 (Core, Gui, Widgets, Sql)
- C++17 compatible compiler (GCC 7+, Clang 5+, MSVC 2019+)
- FFTW3
- FFmpeg (libavcodec, libavformat, libavutil)
- Python 3.6+
- SQLite3

### Ubuntu/Debian

```bash
sudo apt-get install cmake qt6-base-dev libgl-dev libfftw3-dev libavformat-dev \
    libavcodec-dev libavutil-dev ffmpeg libsqlite3-dev libqt6sql6-sqlite
```

### macOS (Homebrew)

```bash
brew install cmake qt6 fftw ffmpeg sqlite3
```

## Build Output

All build artifacts are placed in the `build/` directory:
- `build/` - All CMake files, object files, and executables
- Source tree remains clean

The root directory only contains:
- Source code (`lddecode/`, `tools/`, `scripts/`, etc.)
- Configuration files (`CMakeLists.txt`, `setup.py`, etc.)
- Documentation

## For CI/CD

The GitHub Actions workflow uses:

```yaml
- name: Configure
  run: cd build && cmake -DCMAKE_BUILD_TYPE=RelWithDebInfo ..

- name: Build
  run: make -C build VERBOSE=1

- name: Run tests
  run: cd build && ctest --output-on-failure
```

Tests run sequentially (no `-j` flag) to avoid race conditions in the shared testout directory.
