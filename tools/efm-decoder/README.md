# efm-decoder

**EFM Decoder Tools Suite**

## Overview

The efm-decoder suite provides a comprehensive collection of specialized tools for decoding Eight-to-Fourteen Modulation (EFM) encoded digital data from LaserDisc and Compact Disc captures. This modular approach replaces the deprecated single-tool `ld-process-efm` with specialized components that operate at different stages of the EFM decoding pipeline.

## Tool Suite Components

### efm-decoder tool
**EFM to F2 Section Processor** - Converts raw EFM data to synchronized F2 sections
- Input: Raw .efm files from ld-decode
- Output: .f2 section files  
- Function: Frame synchronization, deinterleaving, initial error detection

### efm-decoder tool 
**F2 Section Multi-Source Stacker** - Combines multiple F2 sources for improved quality
- Input: Multiple .f2 files from same source material
- Output: Enhanced .f2 file
- Function: Majority-vote error correction, multi-capture recovery

### efm-decoder tool
**D24 Data Processor** - Converts F2 sections to D24 format with CIRC error correction
- Input: .f2 section files
- Output: .d24 files with error correction applied
- Function: CIRC decoding, Reed-Solomon error correction, frame validation

### efm-decoder tool
**Audio Stream Decoder** - Extracts PCM audio from D24 data
- Input: .d24 files  
- Output: .wav audio files
- Function: Audio deinterleaving, sample reconstruction, format conversion

### efm-decoder tool
**Data Stream Decoder** - Extracts binary data from D24 streams  
- Input: .d24 files
- Output: .bin data files
- Function: Data sector extraction, file system recovery, metadata preservation

### efm-decoder tool
**Virtual File System Verifier** - Validates and analyzes recovered data
- Input: .bin data files
- Output: Verification reports and extracted files
- Function: VFS integrity checking, file extraction, quality assessment

## Standard Processing Workflows

### Audio Recovery (CD/LaserDisc Digital Audio)

#### Single-Source Workflow
```bash
# Standard pipeline for digital audio extraction
efm-decoder-f2 capture.efm capture.f2
efm-decoder-d24 capture.f2 capture.d24  
efm-decoder-audio capture.d24 final_audio.wav
```

#### Multi-Source Enhanced Recovery
```bash
# Multiple captures for damaged discs
efm-decoder-f2 capture1.efm capture1.f2
efm-decoder-f2 capture2.efm capture2.f2
efm-decoder-f2 capture3.efm capture3.f2

# Stack for improved quality
efm-stacker-f2 capture1.f2 capture2.f2 capture3.f2 stacked.f2

# Continue with enhanced input
efm-decoder-d24 stacked.f2 enhanced.d24
efm-decoder-audio enhanced.d24 recovered_audio.wav
```

### Data Recovery (Domesday LaserDisc, CD-ROM)

#### Standard Data Extraction
```bash
# Pipeline for data disc recovery
efm-decoder-f2 data_capture.efm data.f2
efm-decoder-d24 data.f2 data.d24
efm-decoder-data data.d24 recovered_data.bin --output-metadata data_info.txt
```

#### Complete Domesday Recovery with Verification
```bash
# Multi-source Domesday disc recovery
efm-decoder-f2 domesday1.efm dom1.f2
efm-decoder-f2 domesday2.efm dom2.f2  
efm-decoder-f2 domesday3.efm dom3.f2

# Stack multiple sources
efm-stacker-f2 dom1.f2 dom2.f2 dom3.f2 domesday_stacked.f2

# Process to final data
efm-decoder-d24 domesday_stacked.f2 domesday.d24
efm-decoder-data domesday.d24 domesday.bin --output-metadata domesday_meta.txt

# Verify and extract VFS content
vfs-verifier domesday.bin domesday_report.txt \
  --vfs-type domesday \
  --extract-files \
  --verify-checksums \
  --output-dir domesday_extracted
```

## Pipeline Architecture

### EFM Decoding Stages

The EFM decoding process involves multiple clearly defined stages:

```
Raw EFM Data → F2 Sections → D24 Data → Audio/Data Output
     ↓              ↓            ↓           ↓
efm-decoder-f2  [stacking]  efm-decoder-d24  decoder-audio/data
                    ↓
              efm-stacker-f2
```

### Stage Descriptions

1. **Raw EFM (.efm)** - Output from ld-decode containing synchronized EFM bitstream
2. **F2 Sections (.f2)** - Deinterleaved 98-frame sections with sync and error detection
3. **D24 Data (.d24)** - CIRC error-corrected data ready for final decoding
4. **Final Output** - PCM audio (.wav) or binary data (.bin) with optional verification

### Multi-Source Enhancement

The pipeline supports multi-source stacking at the F2 level:
- Capture same material multiple times with different equipment/settings
- Combine sources using majority-vote error correction
- Dramatically improves recovery of damaged or degraded media
- Particularly effective for archive-quality Domesday LaserDisc recovery

## Advanced Features

### Pipelining Capabilities
- **Streaming Processing**: Tools can process data in chunks for memory efficiency
- **Parallel Sources**: Multiple captures can be processed simultaneously 
- **Quality Assessment**: Each stage provides error statistics and quality metrics
- **Format Flexibility**: Support for both audio and data applications

### Error Correction Hierarchy
1. **Hardware Level**: ld-decode RF signal recovery
2. **EFM Level**: efm-decoder-f2 frame sync and validation  
3. **Multi-Source**: efm-stacker-f2 voting correction
4. **CIRC Level**: efm-decoder-d24 Reed-Solomon correction
5. **Application Level**: Format-specific validation (vfs-verifier)

### Quality Enhancement Strategies
- **Multiple Captures**: Different hardware, settings, environmental conditions
- **Temporal Diversity**: Captures at different times for aging media
- **Hardware Diversity**: Different laser assemblies, tracking mechanisms
- **Parameter Tuning**: Optimized settings per capture session

## Performance and Scalability

### Processing Requirements
- **CPU**: Multi-threaded processing for Reed-Solomon operations
- **Memory**: Scales with source count for stacking operations
- **Storage**: Intermediate files require 2-3x source data size
- **Time**: Real-time processing possible for single sources

### Optimization Strategies
- **Chunked Processing**: Handle large files without memory constraints
- **Parallel Decode**: Process multiple sources simultaneously
- **Progressive Enhancement**: Start with best single source, add others as available
- **Quality-Based Selection**: Automatically select optimal source combinations

## Technical Background

### Eight-to-Fourteen Modulation (EFM)
- **Purpose**: Channel coding for optical storage reliability
- **Encoding**: 8-bit data → 14-bit channel patterns + 3 merge bits
- **Benefits**: DC-free signal, clock recovery, minimum transition density
- **Constraints**: Run-length limits (3-11 transitions), spectral shaping

### Cross-Interleaved Reed-Solomon Code (CIRC)
- **C1 Code**: (32,28) RS code, corrects random errors
- **C2 Code**: (28,24) RS code, corrects burst errors  
- **Interleaving**: 108-frame delay spread, 4000+ bit burst correction
- **Integration**: Works with EFM constraints and optical tracking

### Frame Structure and Timing
- **F3 Frames**: 588 channel bits, 1/7350 second duration
- **F2 Sections**: 98 F3 frames, 1/75 second (sector timing)
- **Synchronization**: 24-bit sync pattern + frame validation
- **Data Capacity**: 24 bytes user data + 8 bytes error correction per frame



