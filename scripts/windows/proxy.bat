@echo off
setlocal EnableDelayedExpansion

:: Check if input file is provided
if "%~1"=="" (
    echo Please provide an input file.
    pause
    exit /b 1
)

:: Set input file path from drag and drop
set "INPUT_FILE=%~1"

:: Prompt for audio codec
set /p "AUDIO_CODEC=Choose audio codec (aac or opus): "
if /i "%AUDIO_CODEC%"=="opus" (
    set "AUDIO_CODEC=libopus"
    set "AUDIO_CODEC_NAME=opus"
) else (
    set "AUDIO_CODEC=aac"
    set "AUDIO_CODEC_NAME=aac"
)

:: Prompt for video codec
set /p "VIDEO_CODEC=Choose video codec (avc (default), hevc, or av1): "
if /i "%VIDEO_CODEC%"=="hevc" (
    set "VIDEO_CODEC=libx265"
    set "VIDEO_CODEC_NAME=hevc"
) else if /i "%VIDEO_CODEC%"=="av1" (
    set "VIDEO_CODEC=libaom-av1"
    set "VIDEO_CODEC_NAME=av1"
) else (
    set "VIDEO_CODEC=libx264"
    set "VIDEO_CODEC_NAME=avc"
)

:: Prompt for 2-pass encoding
set /p "TWOPASS=Use 2-pass encoding? (yes or no): "
if /i "%TWOPASS%"=="yes" (
    set "TWOPASS_OPTION=1"
) else (
    set "TWOPASS_OPTION=0"
)

:: Prompt for GPU acceleration
set /p "GPU_ACCEL=Use GPU acceleration? (yes or no): "
if /i "%GPU_ACCEL%"=="yes" (
    set "GPU_ACCEL_OPTION=1"
) else (
    set "GPU_ACCEL_OPTION=0"
)

:: Generate output file path with codec name appended and ensure MP4 extension
for %%F in ("%INPUT_FILE%") do (
    set "FILENAME=%%~nF"
    set "EXTENSION=%%~xF"
    set "OUTPUT_FILE=%%~dpnF_YT_%VIDEO_CODEC_NAME%_%AUDIO_CODEC_NAME%.mp4"
)

:: Check if ffmpeg is installed
where ffmpeg >nul 2>&1
if errorlevel 1 (
    echo ffmpeg is not installed or not in your PATH.
    pause
    exit /b 1
)

:: Detect video resolution and aspect ratio
for /f "tokens=2 delims=," %%A in ('ffmpeg -i "%INPUT_FILE%" 2^>^1 ^| findstr /r /c:"Stream.*Video:.*"') do set VIDEO_INFO=%%A
for %%A in (!VIDEO_INFO!) do (
    for /f "tokens=1 delims=,[" %%B in ("%%A") do set RESOLUTION=%%B
)

for /f "tokens=2 delims=:" %%A in ('ffmpeg -i "%INPUT_FILE%" 2^>^1 ^| findstr /c:"Display Aspect Ratio"') do set DAR=%%A

:: Set default values for NTSC
set "SCALE=720:480"
set "FRAME_RATE=29.97"
set "DEINTERLACE_FPS=59.94"
set "GOP_SIZE=60"
set "COLOR_RANGE=tv"
set "COLOR_PRIMARIES=smpte170m"
set "COLORSPACE=smpte170m"
set "COLOR_TRC=bt709"

:: Check if the resolution matches PAL (720x576) and set PAL values
if "%RESOLUTION%"=="720x576" (
    set "SCALE=720:576"
    set "FRAME_RATE=25"
    set "DEINTERLACE_FPS=50"
    set "GOP_SIZE=50"
    set "COLOR_PRIMARIES=bt470bg"
    set "COLORSPACE=bt470bg"
)

:: Set aspect ratio settings
if "%DAR%"=="4:3" (
    set "ASPECT_FILTER=setdar=4/3"
) else if "%DAR%"=="16:9" (
    set "ASPECT_FILTER=setdar=16/9"
) else (
    set "ASPECT_FILTER="
)

:: Construct the filter chain
set "FILTER_CHAIN=bwdif,scale=%SCALE%,fps=%DEINTERLACE_FPS%,format=yuv420p"
if defined ASPECT_FILTER (
    set "FILTER_CHAIN=%FILTER_CHAIN%,%ASPECT_FILTER%"
)

:: Check for GPU support if enabled
set "ENCODER_OPTIONS=-c:v %VIDEO_CODEC% -b:v 8000k -threads 8"
if "%GPU_ACCEL_OPTION%"=="1" (
    ffmpeg -hide_banner -encoders > encoders.txt
    if "%VIDEO_CODEC%"=="libx264" (
        findstr /c:" h264_nvenc" encoders.txt >nul
        if %errorlevel% equ 0 (
            set "ENCODER_OPTIONS=-c:v h264_nvenc -b:v 8000k -preset slow"
        )
    ) else if "%VIDEO_CODEC%"=="libx265" (
        findstr /c:" hevc_nvenc" encoders.txt >nul
        if %errorlevel% equ 0 (
            set "ENCODER_OPTIONS=-c:v hevc_nvenc -b:v 8000k -preset slow"
        )
    )
    del encoders.txt
)

:: Perform encoding
if "%TWOPASS_OPTION%"=="1" (
    :: First Pass
    echo Starting first pass...
    ffmpeg -y -i "%INPUT_FILE%" -vf "%FILTER_CHAIN%" %ENCODER_OPTIONS% -pass 1 -passlogfile "%FILENAME%" -f null NUL
    if errorlevel 1 (
        echo First pass encoding failed. 
        pause
        exit /b 1
    )

    :: Second Pass
    echo Starting second pass...
    ffmpeg -y -i "%INPUT_FILE%" -vf "%FILTER_CHAIN%" %ENCODER_OPTIONS% -pass 2 -passlogfile "%FILENAME%" -movflags +faststart -color_range %COLOR_RANGE% -color_primaries %COLOR_PRIMARIES% -colorspace %COLORSPACE% -color_trc %COLOR_TRC% -c:a %AUDIO_CODEC% -b:a 320k "%OUTPUT_FILE%"
    if errorlevel 1 (
        echo Second pass encoding failed.
        pause
        exit /b 1
    )

    :: Clean up pass log files
    del "%FILENAME%-0.log" "%FILENAME%-0.log.mbtree" 2>nul
) else (
    ffmpeg -y -i "%INPUT_FILE%" -vf "%FILTER_CHAIN%" %ENCODER_OPTIONS% -movflags +faststart -color_range %COLOR_RANGE% -color_primaries %COLOR_PRIMARIES% -colorspace %COLORSPACE% -color_trc %COLOR_TRC% -c:a %AUDIO_CODEC% -b:a 320k "%OUTPUT_FILE%"
    if errorlevel 1 (
        echo Encoding failed.
        pause
        exit /b 1
    )
)

echo Encoding successful.
pause

endlocal