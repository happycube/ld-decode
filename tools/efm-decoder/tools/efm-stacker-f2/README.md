# efm-stacker-f2

**EFM F2 Section Multi-Source Stacker**

## Overview

efm-stacker-f2 combines multiple F2 section files from different captures of the same source material to produce a higher-quality result through majority-vote error correction. This tool is essential for recovering heavily damaged or degraded EFM data by leveraging multiple independent captures.

## Usage

```bash
efm-stacker-f2 [options] <input1.f2> <input2.f2> [input3.f2 ...] <output.f2>
```

## Options

- `-h, --help` - Display help information
- `-v, --version` - Display version information
- `-d, --debug` - Show debug output and stacking statistics
- `-q, --quiet` - Suppress info and warning messages

### Arguments

- `inputs` - Two or more input F2 section files from different captures
- `output` - Output combined F2 section file

## Processing Algorithm

### Multi-Source Voting
The stacker examines each F2 frame across all input sources and uses a voting algorithm:

1. **Alignment**: Automatically aligns F2 sections across sources
2. **Comparison**: Compare each byte position across all sources
3. **Majority Vote**: Select the most common value at each position
4. **Confidence**: Higher confidence with more agreeing sources
5. **Error Flags**: Preserve error correction flags from individual sources

### Quality Improvement
- **2 sources**: Can correct errors where sources disagree and one is clearly wrong
- **3+ sources**: Majority voting provides robust error correction
- **5+ sources**: Excellent correction even with heavily damaged individual sources

## Alignment and Synchronization

### Automatic Alignment
The tool automatically handles:
- **Timing drift**: Small timing differences between captures
- **Section offset**: Different starting positions in the data stream
- **Metadata matching**: Ensures Q-channel data consistency across sources

### Sync Requirements
All input sources must represent the same original material:
- Same disc/recording
- Same time period (overlapping capture windows)  
- Compatible EFM format (same sampling parameters)

## Pipeline Integration

### Input Requirements
- Multiple F2 section files from efm-decoder-f2
- All sources should represent the same original material
- Sources can have different error patterns/locations

### Recommended Workflow

#### Multiple Capture Stacking
```bash
# Capture same disc multiple times
ld-decode disc_capture1.ldf disc1 --efm
ld-decode disc_capture2.ldf disc2 --efm  
ld-decode disc_capture3.ldf disc3 --efm

# Process each to F2 sections
efm-decoder-f2 disc1.efm disc1.f2
efm-decoder-f2 disc2.efm disc2.f2
efm-decoder-f2 disc3.efm disc3.f2

# Stack for improved quality
efm-stacker-f2 disc1.f2 disc2.f2 disc3.f2 stacked.f2

# Continue with normal pipeline using Unix pipes
efm-decoder-d24 stacked.f2 - | efm-decoder-audio - final.wav

# Or step by step
efm-decoder-d24 stacked.f2 stacked.d24
efm-decoder-audio stacked.d24 final.wav
```

#### Domesday Multi-Source Recovery
```bash
# Stack multiple Domesday captures
efm-stacker-f2 domesday1.f2 domesday2.f2 domesday3.f2 domesday4.f2 stacked.f2
efm-decoder-d24 stacked.f2 stacked.d24
efm-decoder-data stacked.d24 domesday.bin --output-metadata
vfs-verifier domesday.bin domesday_metadata.txt
```

## Performance and Quality Metrics

### Stacking Effectiveness
- **Error reduction**: Typically 10-100x reduction in uncorrectable errors
- **Processing time**: ~2-3x single-source processing time per additional source
- **Memory usage**: Scales linearly with number of sources
- **Quality improvement**: Diminishing returns after 5-7 sources

### Debug Output
When `--debug` is enabled, shows:
- Alignment statistics between sources
- Voting confidence levels  
- Error correction success rates
- Per-section quality improvements

## Quality Assessment

### Before Stacking
Check individual F2 files for:
- Different error patterns across sources
- Complementary good/bad sections
- Alignment feasibility

### After Stacking
The output quality can be verified by:
- Reduced error counts in downstream tools (efm-decoder-d24)
- Improved audio quality in final output
- Better sector recovery rates for data applications

## Technical Notes

### Section-Level Processing
- Operates on 98-frame F2 sections (1/75 second boundaries)
- Preserves section metadata and Q-channel information  
- Maintains ECMA-130 compliance for downstream processing

### Error Correction Integration
- Works in conjunction with CIRC correction (in efm-decoder-d24)
- Complementary to Reed-Solomon correction (for data applications)
- Improves input quality for subsequent error correction stages



