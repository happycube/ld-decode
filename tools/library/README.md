# Library Components

**ld-decode Shared Library Components**

## Overview

The `library` directory contains shared components used throughout the ld-decode toolset. These libraries provide common functionality for TBC processing, video/audio handling, filtering, and metadata management.

## Directory Structure

```
library/
├── filter/          # Signal processing filters
├── tbc/             # TBC format and metadata handling
└── README.md        # This file
```

## Core Libraries

### Filter Library (`filter/`)

Digital signal processing filters for video and audio.

#### Components
- **`firfilter.h`**: Finite Impulse Response (FIR) filter template
- **`iirfilter.h`**: Infinite Impulse Response (IIR) filter template  
- **`deemp.h`**: De-emphasis filter for audio/video

#### Features
- Template-based generic filter implementations
- Configurable filter order and coefficients
- Optimized for real-time processing
- Type-safe compile-time configuration

#### Usage
```cpp
#include "filter/firfilter.h"

// Create 5-tap lowpass FIR filter
std::vector<double> coeffs = {0.1, 0.2, 0.4, 0.2, 0.1};
FIRFilter<double> lowpass(coeffs);

// Process samples
double output = lowpass.feed(input_sample);
```

See individual header files for detailed API documentation.

### TBC Library (`tbc/`)

Time Base Corrected video format handling and metadata management.

#### Components
- **`lddecodemetadata.h/cpp`**: TBC metadata management
- **`sourcevideo.h/cpp`**: TBC video file I/O
- **`sourceaudio.h/cpp`**: TBC audio file I/O
- **`dropouts.h/cpp`**: Dropout detection and management
- **`filters.h/cpp`**: Video-specific filters
- **`vbidecoder.h/cpp`**: VBI data extraction
- **`logging.h/cpp`**: Logging infrastructure

#### Features
- Complete TBC format support (PAL, NTSC, PAL-M)
- SQLite metadata backend
- Dropout tracking and correction
- VBI decoding (frame numbers, time codes, chapters)
- Field-level video access
- Audio PCM handling

#### Key Classes

##### `LdDecodeMetaData`
Central metadata management for TBC files.

```cpp
#include "tbc/lddecodemetadata.h"

LdDecodeMetaData metadata;
metadata.read("video.tbc.db");

// Access video parameters
VideoParameters params = metadata.getVideoParameters();
tbcDebugStream() << "System:" << params.system;
tbcDebugStream() << "Field width:" << params.fieldWidth;

// Access field information
qint32 firstField = metadata.getFirstFieldNumber(1);
FieldMetadata field = metadata.getField(firstField);
tbcDebugStream() << "SNR:" << field.vitsMetrics.snr;
```

##### `SourceVideo`
Read/write TBC video files.

```cpp
#include "tbc/sourcevideo.h"

SourceVideo source;
if (source.open("input.tbc", 1135)) {  // PAL width
    // Read field data
    std::vector<quint16> fieldData(1135 * 625);
    source.getFieldData(fieldData.data(), fieldNumber);
}
```

##### `DropOuts`
Manage dropout information.

```cpp
#include "tbc/dropouts.h"

DropOuts dropouts;
dropouts.append(fieldLine, startx, endx);
qint32 count = dropouts.size();
```

## Building

The libraries are built automatically as part of the ld-decode CMake build system:

```bash
cd ld-decode
mkdir build && cd build
cmake ..
make
```

Libraries are built as static libraries linked into each tool:
- `libfilter.a`: Filter library
- `libtbc.a`: TBC library

## Dependencies

### Qt Framework
Most library components require Qt5:
- **QtCore**: Core functionality
- **QtGui**: Image handling (some components)
- **QtSql**: SQLite metadata backend

### Build Tools
- CMake 3.10+
- C++14 compatible compiler (GCC 7+, Clang 5+, MSVC 2017+)
- Qt5 development packages

### External Libraries
- **FFTW3**: Fast Fourier Transform (optional, for some filters)
- **SQLite3**: Via Qt5Sql

## API Documentation

Complete API documentation is generated using Doxygen:

```bash
# Generate documentation
doxygen Doxyfile

# View documentation
xdg-open html/index.html
```

Documentation includes:
- Class diagrams (PlantUML)
- API reference
- Usage examples
- Implementation notes

## Design Principles

### Template-Based Filters
- Type-safe at compile time
- Zero runtime overhead for type selection
- Supports float, double, int types
- Coefficients validated at construction

### Metadata Abstraction
- SQLite metadata backend with unified API
- Automatic format detection
- Lazy loading for performance
- Thread-safe reading

### Modular Architecture
- Libraries are independent where possible
- Minimal coupling between components
- Easy to test and maintain
- Clear separation of concerns

## Common Use Cases

### 1. Read TBC Metadata
```cpp
LdDecodeMetaData metadata;
if (metadata.read("video.tbc.db")) {
    VideoParameters params = metadata.getVideoParameters();
    // Process video parameters
}
```

### 2. Apply FIR Filter
```cpp
std::vector<double> coeffs = computeLowpassCoeffs(0.25);
FIRFilter<double> filter(coeffs);

for (double sample : inputSamples) {
    double filtered = filter.feed(sample);
    outputSamples.push_back(filtered);
}
```

### 3. Read Field Data
```cpp
SourceVideo source;
source.open("input.tbc", fieldWidth);

std::vector<quint16> fieldData(fieldWidth * fieldHeight);
source.getFieldData(fieldData.data(), fieldNumber);
```

### 4. Process Dropouts
```cpp
DropOuts dropouts = metadata.getFieldDropOuts(fieldNumber);
for (qint32 i = 0; i < dropouts.size(); i++) {
    qint32 startx, endx;
    dropouts.getStartEnd(i, startx, endx);
    // Conceal dropout from startx to endx
}
```

## Testing

Unit tests for library components:

```bash
# Run all tests
cd build
ctest

# Run specific test
./test-firfilter
./test-metadata
```

Tests cover:
- Filter correctness
- Metadata read/write
- Dropout management
- VBI decoding
- Edge cases and error handling

## Contributing

When adding to the library:

1. **Follow Existing Patterns**: Match coding style and structure
2. **Add Documentation**: Use Doxygen comments
3. **Write Tests**: Add unit tests for new functionality
4. **Update Diagrams**: Add PlantUML diagrams for new classes
5. **Check Dependencies**: Minimize external dependencies

## Performance Considerations

### Filters
- Template instantiation happens at compile time
- Coefficient normalization done once at construction
- `feed()` method inlined for zero-call overhead
- Consider SIMD optimizations for critical paths

### Metadata
- Use SQLite for large files (>100K fields)

- Lazy loading avoids reading entire file
- Cache frequently accessed fields

### Video I/O
- Read/write in sequential field order when possible
- Buffer multiple fields to reduce I/O calls
- Use memory mapping for large files (future optimization)

## File Format Specifications

### TBC Format
Binary file containing sequential field data:
- 16-bit unsigned samples
- Little-endian byte order
- No header (metadata in separate SQLite database)
- Fixed width per line (e.g., 1135 for PAL)

### SQLite Metadata
> [!WARNING]  
> The SQLite metadata format is **internal to ld-decode tools only** and subject to change without notice. External tools and scripts should **not** access this database directly. Instead, use `ld-export-metadata` or similar tools to export metadata in stable, documented formats.

Efficient binary format with tables:
- `video_parameters`: Video system settings  
- `fields`: Per-field metadata
- `dropouts`: Dropout locations
- Indexed for fast field lookup

## Troubleshooting

### Build Issues

**Qt not found:**
```bash
export Qt5_DIR=/usr/lib/x86_64-linux-gnu/cmake/Qt5
cmake ..
```

**Missing FFTW:**
```bash
sudo apt-get install libfftw3-dev
```

### Runtime Issues

**Cannot open TBC file:**
- Check file exists and has read permissions
- Verify field width matches actual TBC format
- Check metadata file (.json.sqlite) exists

**Metadata errors:**
- Validate SQLite database integrity
- Check SQLite database isn't corrupted
- Ensure metadata version matches library version




