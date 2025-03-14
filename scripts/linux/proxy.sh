#!/bin/bash

# Check if input file is provided
if [ -z "$1" ]; then
    echo "Please provide an input file."
    exit 1
fi

INPUT_FILE="$1"
FILENAME="${INPUT_FILE%.*}"
OUTPUT_FILE="${FILENAME}_YT.mp4"

# Prompt for audio codec
read -p "Choose audio codec (aac or opus): " AUDIO_CODEC
if [ "$AUDIO_CODEC" == "opus" ]; then
    AUDIO_CODEC="libopus"
else
    AUDIO_CODEC="aac"
fi

# Prompt for video codec
read -p "Choose video codec (avc (default), hevc, or av1): " VIDEO_CODEC
if [ "$VIDEO_CODEC" == "hevc" ]; then
    VIDEO_CODEC="libx265"
elif [ "$VIDEO_CODEC" == "av1" ]; then
    VIDEO_CODEC="libaom-av1"
else
    VIDEO_CODEC="libx264"
fi

# Prompt for 2-pass encoding
read -p "Use 2-pass encoding? (yes or no): " TWOPASS
if [ "$TWOPASS" == "yes" ]; then
    TWOPASS_OPTION=1
else
    TWOPASS_OPTION=0
fi

# Prompt for GPU acceleration
read -p "Use GPU acceleration? (yes or no): " GPU_ACCEL
if [ "$GPU_ACCEL" == "yes" ]; then
    GPU_ACCEL_OPTION=1
else
    GPU_ACCEL_OPTION=0
fi

# Check if ffmpeg is installed
if ! command -v ffmpeg &> /dev/null; then
    echo "ffmpeg is not installed or not in your PATH."
    exit 1
fi

# Detect video resolution and aspect ratio
RESOLUTION=$(ffmpeg -i "$INPUT_FILE" 2>&1 | grep Stream | grep Video: | grep -oE '[0-9]{3,}x[0-9]{3,}')
DAR=$(ffmpeg -i "$INPUT_FILE" 2>&1 | grep -oP 'DAR \K[0-9:]+')

# Set default values for NTSC
SCALE="720:480"
FRAME_RATE="29.97"
DEINTERLACE_FPS="59.94"
GOP_SIZE="60"
COLOR_RANGE="tv"
COLOR_PRIMARIES="smpte170m"
COLORSPACE="smpte170m"
COLOR_TRC="bt709"

# Check if the resolution matches PAL and set PAL values
if [ "$RESOLUTION" == "720x576" ]; then
    SCALE="720:576"
    FRAME_RATE="25"
    DEINTERLACE_FPS="50"
    GOP_SIZE="50"
    COLOR_PRIMARIES="bt470bg"
    COLORSPACE="bt470bg"
fi

# Set aspect ratio settings
if [ "$DAR" == "4:3" ]; then
    ASPECT_FILTER="setdar=4/3"
elif [ "$DAR" == "16:9" ]; then
    ASPECT_FILTER="setdar=16/9"
else
    ASPECT_FILTER=""
fi

# Construct the filter chain
FILTER_CHAIN="bwdif,scale=${SCALE},fps=${DEINTERLACE_FPS},format=yuv420p"
if [ -n "$ASPECT_FILTER" ]; then
    FILTER_CHAIN="${FILTER_CHAIN},${ASPECT_FILTER}"
fi

# Check for GPU support if enabled
ENCODER_OPTIONS="-c:v ${VIDEO_CODEC} -b:v 8000k -threads 8"
if [ "$GPU_ACCEL_OPTION" -eq 1 ]; then
    if [ "$VIDEO_CODEC" == "libx264" ] && ffmpeg -hide_banner -encoders | grep -q "h264_nvenc"; then
        ENCODER_OPTIONS="-c:v h264_nvenc -b:v 8000k -preset slow"
    elif [ "$VIDEO_CODEC" == "libx265" ] && ffmpeg -hide_banner -encoders | grep -q "hevc_nvenc"; then
        ENCODER_OPTIONS="-c:v hevc_nvenc -b:v 8000k -preset slow"
    fi
fi

# Perform encoding
if [ "$TWOPASS_OPTION" -eq 1 ]; then
    # First Pass
    echo "Starting first pass..."
    ffmpeg -y -i "$INPUT_FILE" -vf "$FILTER_CHAIN" $ENCODER_OPTIONS -pass 1 -passlogfile "$FILENAME" -f null /dev/null
    if [ $? -ne 0 ]; then
        echo "First pass encoding failed."
        exit 1
    fi

    # Second Pass
    echo "Starting second pass..."
    ffmpeg -y -i "$INPUT_FILE" -vf "$FILTER_CHAIN" $ENCODER_OPTIONS -pass 2 -passlogfile "$FILENAME" -movflags +faststart -color_range $COLOR_RANGE -color_primaries $COLOR_PRIMARIES -colorspace $COLORSPACE -color_trc $COLOR_TRC -c:a $AUDIO_CODEC -b:a 320k "$OUTPUT_FILE"
    if [ $? -ne 0 ]; then
        echo "Second pass encoding failed."
        exit 1
    fi

    # Clean up pass log files
    rm -f "$FILENAME-0.log" "$FILENAME-0.log.mbtree"
else
    ffmpeg -y -i "$INPUT_FILE" -vf "$FILTER_CHAIN" $ENCODER_OPTIONS -movflags +faststart -color_range $COLOR_RANGE -color_primaries $COLOR_PRIMARIES -colorspace $COLORSPACE -color_trc $COLOR_TRC -c:a $AUDIO_CODEC -b:a 320k "$OUTPUT_FILE"
    if [ $? -ne 0 ]; then
        echo "Encoding failed."
        exit 1
    fi
fi

echo "Encoding successful."
