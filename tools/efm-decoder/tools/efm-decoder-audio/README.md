# efm-decoder-audio

**EFM Data24 to Audio Decoder**

## Overview

efm-decoder-audio converts Data24 sections into 16-bit stereo PCM audio according to IEC 60908 specifications. This tool handles the final stage of audio decoding for CD audio and LaserDisc digital audio tracks, producing standard WAV files with detailed metadata.

## Usage

```bash
efm-decoder-audio [options] <input.d24> <output.wav>
```

## Options

#### Standard Options
- `-h, --help` - Display help information
- `-v, --version` - Display version information
- `-d, --debug` - Show debug output
- `-q, --quiet` - Suppress info and warning messages

#### Audio Processing
- `--audacity-labels` - Output WAV metadata as Audacity labels
- `--no-audio-concealment` - Do not conceal errors in the audio data
- `--zero-pad` - Zero pad the audio data from 00:00:00
- `--no-wav-header` - Output raw audio data without WAV header

#### Debug Options
- `--show-audio` - Show Audio frame data
- `--show-audio-debug` - Show Data24 to audio decoding debug
- `--show-audio-correction-debug` - Show Audio correction debug
- `--show-all-debug` - Show all decoding debug

### Arguments

- `input` - Input Data24 section file (from efm-decoder-d24)
- `output` - Output WAV audio file

## Processing Pipeline

The decoding sequence performed by efm-decoder-audio:

1. **Data24 Sections** → Input from efm-decoder-d24 (or stdin via Unix pipes)
2. **Audio Frame Extraction** → Extract 16-bit stereo samples
3. **Error Concealment** → Interpolate or silence corrupted samples
4. **WAV Generation** → Standard 44.1kHz 16-bit stereo output
5. **Metadata Export** → Optional Audacity label file generation

**Unix Pipelining**: efm-decoder-audio supports stdin/stdout using `-`, allowing direct connection to other EFM decoder tools without intermediate files.

## Audio Output Format

### WAV Specifications
- **Sample Rate**: 44.1 kHz (44,100 samples/second)
- **Bit Depth**: 16-bit signed integer
- **Channels**: 2 (stereo)
- **Format**: Standard WAV with proper headers

### Quality Metrics
Each Data24 section (1/75 second) produces:
- 588 stereo sample pairs (44,100 ÷ 75 = 588)
- 2,352 bytes of audio data per section
- Total data rate: 176.4 KB/second

## Error Concealment

The tool provides sophisticated error handling:

### Concealment Methods
- **Interpolation**: Average of adjacent valid samples
- **Silencing**: Zero amplitude for uncorrectable errors
- **Detection**: Flags all concealed/silenced regions

### Concealment Control
- Default behavior performs automatic concealment for best audio quality
- Use `--no-audio-concealment` option to disable concealment

## Metadata Output

### Audacity Labels Format
When `--audacity-labels` is specified, generates a .txt file containing:
- **Timestamp precision**: Millisecond accuracy for individual samples
- **Error locations**: Concealed and silenced sample positions
- **Track information**: CD track boundaries (when available)
- **Time codes**: Both Audacity time and CDDA format timestamps

### Example Metadata
```
2038.365964	2038.366100	Silenced: 33:58:27
0.000000	175.333333	Track: 01 [00:00:00-02:53:25]
175.346667	470.520000	Track: 02 [00:00:00-04:55:13]
```

## Pipeline Integration

### Input Requirements
- Data24 sections from efm-decoder-d24
- Properly error-corrected data (CIRC processing completed)

### Common Workflows

#### Standard Audio Extraction
```bash
# Complete pipeline for audio using Unix pipes
efm-decoder-f2 input.efm - | efm-decoder-d24 - - | efm-decoder-audio - output.wav --audacity-labels

# Alternative: step by step with files
efm-decoder-f2 input.efm temp.f2
efm-decoder-d24 temp.f2 temp.d24
efm-decoder-audio temp.d24 output.wav --audacity-labels
```

#### Multi-Source Quality Enhancement
```bash
# Stack multiple sources first
efm-stacker-f2 source1.f2 source2.f2 source3.f2 stacked.f2
efm-decoder-d24 stacked.f2 stacked.d24
efm-decoder-audio stacked.d24 output.wav --audacity-labels
```

## Performance Considerations

- Real-time processing: ~75x faster than real-time on modern hardware
- Memory usage: Minimal (processes sections sequentially)
- Quality depends heavily on CIRC correction effectiveness from efm-decoder-d24



