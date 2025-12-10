#!/usr/bin/env python3
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from multiprocessing import (
    cpu_count,
    Pipe,
    SimpleQueue,
    Process,
    freeze_support,
    current_process,
    Event,
)
from multiprocessing.sharedctypes import Value
from datetime import datetime, timedelta
import os
import sys
from typing import Optional
import signal
from numba import njit, guvectorize
import numba
import atexit
import asyncio
from setproctitle import setproctitle
from contextlib import nullcontext

import numpy as np
import soundfile as sf

from vhsdecode.hifi.utils import (
    DecoderSharedMemory,
    DecoderState,
    PostProcessorSharedMemory,
    NumbaAudioArray,
)

import argparse
import lddecode.utils as lddu
from vhsdecode.cmdcommons import (
    test_input_file,
    test_output_file,
    TestInputFile,
    TestOutputFile,
)
from vhsdecode.hifi.HiFiDecode import (
    HiFiDecode,
    SpectralNoiseReduction,
    DCBlocker,
    Expander,
    Deemphasis,
    DEFAULT_EXPANDER_GAIN,
    DEFAULT_EXPANDER_RATIO,
    DEFAULT_EXPANDER_ATTACK_TAU,
    DEFAULT_EXPANDER_RELEASE_TAU,
    DEFAULT_VHS_EXPANDER_WEIGHTING_TAU_1,
    DEFAULT_VHS_EXPANDER_WEIGHTING_TAU_2,
    DEFAULT_VHS_EXPANDER_WEIGHTING_DB_PER_OCTAVE,
    DEFAULT_VHS_EXPANDER_WEIGHTING_BANDWIDTH,
    DEFAULT_8MM_EXPANDER_WEIGHTING_TAU_1,
    DEFAULT_8MM_EXPANDER_WEIGHTING_TAU_2,
    DEFAULT_8MM_EXPANDER_WEIGHTING_DB_PER_OCTAVE,
    DEFAULT_8MM_EXPANDER_WEIGHTING_BANDWIDTH,
    DEFAULT_VHS_DEEMPHASIS_TAU_1,
    DEFAULT_VHS_DEEMPHASIS_TAU_2,
    DEFAULT_VHS_DEEMPHASIS_DB_PER_OCTAVE,
    DEFAULT_VHS_DEEMPHASIS_BANDWIDTH,
    DEFAULT_8MM_DEEMPHASIS_TAU_1,
    DEFAULT_8MM_DEEMPHASIS_TAU_2,
    DEFAULT_8MM_DEEMPHASIS_DB_PER_OCTAVE,
    DEFAULT_8MM_DEEMPHASIS_BANDWIDTH,
    DEFAULT_SPECTRAL_NR_AMOUNT,
    DEFAULT_RESAMPLER_QUALITY,
    DEFAULT_FINAL_AUDIO_RATE,
    REAL_DTYPE,
    DEMOD_QUADRATURE,
    DEMOD_HILBERT,
    DEFAULT_DEMOD,
)
from vhsdecode.hifi.TimeProgressBar import TimeProgressBar
import io

try:
    import sounddevice as sd

    SOUNDDEVICE_AVAILABLE = True
except (ImportError, OSError):
    SOUNDDEVICE_AVAILABLE = False

try:
    try:
        from PyQt6.QtWidgets import QApplication, QMessageBox
    except ImportError:
        from PyQt5.QtWidgets import QApplication, QMessageBox

    from vhsdecode.hifi.HifiUi import (
        ui_parameters_to_decode_options,
        decode_options_to_ui_parameters,
        FileIODialogUI,
        FileOutputDialogUI,
    )

    HIFI_UI = True
except ImportError as e:
    print(e)
    HIFI_UI = False

STOP_STATE = 0
PLAY_STATE = 1
PAUSE_STATE = 2
PREVIEW_STATE = 3

STOP_NOT_REQUESTED = 0
STOP_REQUESTED = 1
STOP_IMMEDIATE_REQUESTED = 2

NORMALIZE_FILE_SUFFIX = "tmp_normalize.raw"


default_threads = cpu_count()
parser = argparse.ArgumentParser(
    description="Extracts audio from RAW HiFi FM RF captures"
)

parser.add_argument(
    "infile",
    metavar="infile",
    type=str,
    help="source file",
    nargs="?",
    default="",
    action=TestInputFile,
)
parser.add_argument(
    "outfile",
    metavar="outfile",
    type=str,
    help="base name for destination files",
    nargs="?",
    default="",
    action=TestOutputFile,
)
parser.add_argument(
    "--frequency",
    "-f",
    dest="inputfreq",
    metavar="FREQ",
    type=lddu.parse_frequency,
    default=40,
    help="RF sampling frequency in source file (default is 40MHz)",
)
parser.add_argument(
    "--overwrite",
    dest="overwrite",
    action="store_true",
    default=False,
    help="Overwrite existing decode files.",
)
parser.add_argument(
    "--threads",
    "-t",
    metavar="threads",
    type=int,
    default=default_threads,
    help="number of CPU threads to use",
)
parser.add_argument(
    "--gui",
    dest="UI",
    action="store_true",
    default=False,
    help="Opens hifi-decode GUI graphical user interface",
)
parser.add_argument(
    "--gnuradio",
    dest="GRC",
    action="store_true",
    default=False,
    help="Opens ZMQ REP pipe to gnuradio at port 5555",
)
parser.add_argument(
    "--preview",
    dest="preview",
    action="store_true",
    default=False,
    help="Preview the audio through your speakers as it decodes. Uses preview quality (faster and noisier)",
)

system_options_group = parser.add_argument_group("System options")
system_options_group.add_argument(
    "--pal",
    "-p",
    dest="pal",
    action="store_true",
    help="source is in PAL format",
)
system_options_group.add_argument(
    "--ntsc",
    "-n",
    dest="ntsc",
    action="store_true",
    help="source is in NTSC format",
)
system_options_group.add_argument(
    "--8mm",
    dest="format_8mm",
    action="store_true",
    default=False,
    help="Use settings for Video8 and Hi8 tape formats.",
)

demod_options = parser.add_argument_group("Demodulation options")
demod_options.add_argument(
    "--demod",
    dest="demod_type",
    type=str.lower,
    default=DEFAULT_DEMOD,
    help=f"Set the FM demodulation type (default: {DEFAULT_DEMOD}) ({DEMOD_QUADRATURE}, {DEMOD_HILBERT})",
)
demod_options.add_argument(
    "--bias_guess",
    "--bg",
    dest="bias_guess",
    action="store_true",
    default=False,
    help="Do carrier bias guess",
)
demod_options.add_argument(
    "--auto_fine_tune",
    dest="auto_fine_tune",
    type=str.lower,
    default="on",
    help="Set auto tuning of the analog front end on/off",
)
demod_options.add_argument(
    "--AFE_vco_deviation",
    dest="afe_vco_deviation",
    type=lddu.parse_frequency,
    default=0,
    help="Overrides the VCO maximum deviation. This represents the maximum frequency offset + or - from the center frequency.",
)
demod_options.add_argument(
    "--AFE_left_carrier",
    dest="afe_left_carrier",
    type=lddu.parse_frequency,
    default=0,
    help="Overrides the left carrier center frequency.",
)
demod_options.add_argument(
    "--AFE_right_carrier",
    dest="afe_right_carrier",
    type=lddu.parse_frequency,
    default=0,
    help="Overrides the right carrier center frequency.",
)

audio_processing_options_group = parser.add_argument_group("Audio processing options")
audio_processing_options_group.add_argument(
    "--audio_rate",
    "--ar",
    dest="rate",
    type=int,
    default=DEFAULT_FINAL_AUDIO_RATE,
    help=f"Output sample rate in Hz (default {DEFAULT_FINAL_AUDIO_RATE})",
)
audio_processing_options_group.add_argument(
    "--audio_mode",
    dest="mode",
    type=str,
    help=(
        "Audio mode (s: stereo, mpx: stereo with mpx, l: left channel, r: right channel, sum: mono sum) - "
        "defaults to s other than on 8mm which defaults to mpx."
        " 8mm mono is not auto detected currently so has to be manually specified as l."
    ),
)
audio_processing_options_group.add_argument(
    "--resampler_quality",
    dest="resampler_quality",
    type=str,
    default=DEFAULT_RESAMPLER_QUALITY,
    help=f"Sets quality of resampling to use in the audio chain. (default is {DEFAULT_RESAMPLER_QUALITY}). "
    f"Range (low, medium, high): low being faster, and high having best quality",
)
audio_processing_options_group.add_argument(
    "--normalize",
    dest="normalize",
    action="store_true",
    default=False,
    help=f"Automatically amplifies the audio to the peak gain of the decode. "
    f'This will create a temporary file ending in "{NORMALIZE_FILE_SUFFIX}" that is deleted after the amplification step is complete.',
)
audio_processing_options_group.add_argument(
    "--gain",
    dest="gain",
    type=float,
    default=1.0,
    help="Manually adjust the gain/volume of the output audio (default is 1.0).",
)

noise_reduction_options_group = parser.add_argument_group("Noise reduction options")
noise_reduction_options_group.add_argument(
    "--head_switching_interpolation",
    dest="head_switching_interpolation",
    type=str.lower,
    default="on",
    help='Enables head switching noise interpolation. (defaults to "on").',
)
noise_reduction_options_group.add_argument(
    "--muting",
    dest="muting",
    type=str.lower,
    default="on",
    help='Mutes the audio when there is no hifi carrier. (defaults to "on").',
)
noise_reduction_options_group.add_argument(
    "--NR_spectral_amount",
    dest="spectral_nr_amount",
    type=float,
    default=DEFAULT_SPECTRAL_NR_AMOUNT,
    help=f"Sets the amount of broadband spectral noise reduction to apply. (default is {DEFAULT_SPECTRAL_NR_AMOUNT}). "
    f"Range (0~1): 0 being off, 1 being full spectral noise reduction",
)

expander_options_group = parser.add_argument_group("Expander tuning options (advanced)")
expander_options_group.add_argument(
    "--expander",
    dest="enable_expander",
    type=str.lower,
    default="on",
    help="Set expander block on/off",
)

expander_options_group.add_argument(
    "--expander_gain",
    dest="expander_gain",
    type=float,
    default=DEFAULT_EXPANDER_GAIN,
    help=f"Sets the expander gain (default is {DEFAULT_EXPANDER_GAIN}). "
    f"Range (0~30): Higher values increase output gain of the expander",
)
expander_options_group.add_argument(
    "--expander_ratio",
    dest="expander_ratio",
    type=float,
    default=DEFAULT_EXPANDER_RATIO,
    help=f"Sets the ratio (default is {DEFAULT_EXPANDER_RATIO}). "
    f"Range (1~2): Higher values increase the ratio of the expander",
)
expander_options_group.add_argument(
    "--expander_attack_tau",
    dest="expander_attack_tau",
    type=float,
    default=DEFAULT_EXPANDER_ATTACK_TAU,
    help=f"Sets the expander attack speed in tau (default is {DEFAULT_EXPANDER_ATTACK_TAU}).",
)
expander_options_group.add_argument(
    "--expander_release_tau",
    dest="expander_release_tau",
    type=float,
    default=DEFAULT_EXPANDER_RELEASE_TAU,
    help=f"Sets the expander release speed in tau (default is {DEFAULT_EXPANDER_RELEASE_TAU}).",
)
expander_options_group.add_argument(
    "--expander_weighting_low_tau",
    dest="expander_weighting_low_tau",
    type=float,
    help=f"Sets the expander weighting high-pass shelf filter low point in tau (defaults: [VHS: {DEFAULT_VHS_EXPANDER_WEIGHTING_TAU_1}] [8mm: {DEFAULT_8MM_EXPANDER_WEIGHTING_TAU_1}]).",
)
expander_options_group.add_argument(
    "--expander_weighting_high_tau",
    dest="expander_weighting_high_tau",
    type=float,
    help=f"Sets the expander weighting high-pass shelf filter high point in tau (defaults: [VHS: {DEFAULT_VHS_EXPANDER_WEIGHTING_TAU_2}] [8mm: {DEFAULT_8MM_EXPANDER_WEIGHTING_TAU_2}]).",
)
expander_options_group.add_argument(
    "--expander_weighting_db_per_octave",
    dest="expander_weighting_db_per_octave",
    type=float,
    help=f"Sets the expander weighting high-pass shelf filter cutoff rate (defaults: [VHS: {DEFAULT_VHS_EXPANDER_WEIGHTING_DB_PER_OCTAVE}] [8mm: {DEFAULT_8MM_EXPANDER_WEIGHTING_DB_PER_OCTAVE}]).",
)
expander_options_group.add_argument(
    "--expander_weighting_bandwidth",
    dest="expander_weighting_bandwidth",
    type=float,
    help=f"Sets the expander weighting high-pass shelf filter bandwidth (defaults: [VHS: {DEFAULT_VHS_EXPANDER_WEIGHTING_BANDWIDTH}] [8mm: {DEFAULT_8MM_EXPANDER_WEIGHTING_BANDWIDTH}]).",
)

deemphasis_options_group = parser.add_argument_group(
    "Deemphasis tuning options (advanced)"
)
deemphasis_options_group.add_argument(
    "--deemphasis",
    dest="enable_deemphasis",
    type=str.lower,
    default="on",
    help="Set deemphasis block on/off",
)
deemphasis_options_group.add_argument(
    "--deemphasis_low_tau",
    dest="deemphasis_low_tau",
    type=float,
    help=f"Sets the deemphasis low-pass shelf filter low point in tau (defaults: [VHS: {DEFAULT_VHS_DEEMPHASIS_TAU_1}] [8mm: {DEFAULT_8MM_DEEMPHASIS_TAU_1}])",
)
deemphasis_options_group.add_argument(
    "--deemphasis_high_tau",
    dest="deemphasis_high_tau",
    type=float,
    help=f"Sets the deemphasis low-pass shelf filter high point in tau (defaults: [VHS: {DEFAULT_VHS_DEEMPHASIS_TAU_2}] [8mm: {DEFAULT_8MM_DEEMPHASIS_TAU_2}])",
)
deemphasis_options_group.add_argument(
    "--deemphasis_db_per_octave",
    dest="deemphasis_db_per_octave",
    type=float,
    help=f"Sets the deemphasis low-pass shelf filter cutoff rate (defaults: [VHS: {DEFAULT_VHS_DEEMPHASIS_DB_PER_OCTAVE}] [8mm: {DEFAULT_8MM_DEEMPHASIS_DB_PER_OCTAVE}])",
)
deemphasis_options_group.add_argument(
    "--deemphasis_bandwidth",
    dest="deemphasis_bandwidth",
    type=float,
    help=f"Sets the deemphasis low-pass shelf filter bandwidth (defaults: [VHS: {DEFAULT_VHS_DEEMPHASIS_BANDWIDTH}] [8mm: {DEFAULT_8MM_DEEMPHASIS_BANDWIDTH}])",
)

def test_ld_tools(ld_tool):
    shell_command = [ld_tool, "--help"]
    try:
        p = subprocess.Popen(
            shell_command,
            shell=False,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=False,
        )
        print(f"Found {ld_tool}")
        p.communicate()
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        print(f"WARN: {ld_tool} not installed (or not in PATH)")

def test_if_flac_is_installed():
    shell_command = ["flac", "-version"]
    try:
        p = subprocess.Popen(
            shell_command,
            shell=False,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=False,
        )
        # prints ffmpeg version and closes the process
        stdout_as_string = p.stdout.read().decode("utf-8")
        version = stdout_as_string.split("\n")[0]
        print(f"Found {version}")
        p.communicate()
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        print("WARN: flac not installed (or not in PATH)")
        return False


def test_if_ffmpeg_is_installed():
    shell_command = ["ffmpeg", "-version"]
    try:
        p = subprocess.Popen(
            shell_command,
            shell=False,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=False,
        )
        # prints ffmpeg version and closes the process
        stdout_as_string = p.stdout.read().decode("utf-8")
        version = stdout_as_string.split("\n")[0]
        print(f"Found {version}")
        p.communicate()
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        print("WARN: ffmpeg not installed (or not in PATH)")
        return False


class BufferedInputStream(io.RawIOBase):
    def __init__(self, buffer):
        self.buffer = buffer
        self._pos: int = 0

    def readinto(self, buffer):
        bytes_read = self.buffer.readinto(buffer)
        if not bytes_read:
            return 0

        self._pos += bytes_read
        return bytes_read

    def readable(self):
        return True

    def seekable(self):
        return False

    def writable(self):
        return False

    def close(self):
        pass

    def fileno(self):
        return self.buffer.fileno()

    def isatty(self):
        return self.buffer.isatty()

    def tell(self):
        # hack, there is no way to know the current position
        return int(-1e6) if self._pos == 0 else self._pos

    def seek(self, offset, whence=io.SEEK_SET):
        return self.tell()


class LDToolFileReader(BufferedInputStream):
    def __init__(self, ld_tool, file_path, input_argument=""):
        shell_command = [ld_tool, input_argument, file_path]
        p = subprocess.Popen(
            shell_command,
            shell=False,
            stdout=subprocess.PIPE,
            universal_newlines=False,
        )
        self.buffer = p.stdout
        self._pos: int = 0


class FlacFileReader(BufferedInputStream):
    def __init__(self, file_path):
        shell_command = [
            "flac",
            "-d",
            "-c",
            "-s",
            "--force-raw-format",
            "--endian",
            "little",
            "--sign",
            "signed",
            file_path,
        ]
        p = subprocess.Popen(
            shell_command,
            shell=False,
            stdout=subprocess.PIPE,
            universal_newlines=False,
        )
        self.buffer = p.stdout
        self._pos: int = 0


# executes ffmpeg and reads stdout as a file
class FFMpegFileReader(BufferedInputStream):
    def __init__(self, file_path):
        # Force ffmpeg to ignore duration metadata and read until actual EOF
        shell_command = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-ignore_unknown",
            "-i",
            file_path,
            "-f",
            "s16le",
            "-acodec",
            "pcm_s16le",
            "-avoid_negative_ts",
            "disabled",
            "-",
        ]
        p = subprocess.Popen(
            shell_command,
            shell=False,
            stdout=subprocess.PIPE,
            universal_newlines=False,
        )
        self.buffer = p.stdout
        self._pos: int = 0


class UnseekableSoundFile(sf.SoundFile):
    def __init__(self, file_path, mode, channels, samplerate, format, subtype, endian):
        self.file_path = file_path
        self._overlap = np.array([], dtype=np.int16)
        super().__init__(
            file_path,
            mode,
            channels=channels,
            samplerate=samplerate,
            format=format,
            subtype=subtype,
            endian=endian,
        )

    def seek(self, offset, whence=io.SEEK_SET):
        return self.file_path.seek(offset, whence)

    def close(self):
        pass

    def buffer_read_into(self, buffer, dtype="int16"):
        item_size = np.dtype(dtype).itemsize
        bytes_read = self.file_path.readinto(buffer)

        assert bytes_read % item_size == 0, "data is misaligned"
        bytes_read //= np.dtype(dtype).itemsize

        return bytes_read


class UnSigned16BitFileReader(io.RawIOBase):
    def __init__(self, file_path):
        self.file_path = file_path
        self.file = open(file_path, "rb")

    def readinto(self, buffer):
        buffer_uint16 = np.frombuffer(buffer, dtype=np.uint16)
        bytes_read = self.file.readinto(buffer_uint16)
        UnSigned16BitFileReader.uint16_to_int16(buffer_uint16, buffer)
        if not bytes_read:
            return 0

        return bytes_read

    @staticmethod
    @guvectorize(
        [
            (
                numba.types.Array(numba.types.uint16, 1, "C"),
                numba.types.Array(numba.types.int16, 1, "C"),
            )
        ],
        "(n)->(n)",
        cache=True,
        fastmath=True,
        nopython=True,
    )
    def uint16_to_int16(uint16_in, int16_out):
        for i in range(len(uint16_in)):
            int16_out[i] = uint16_in[i] - 2**15

    def readable(self):
        return True

    def close(self):
        self.file.close()


# This part is what opens the file
# The samplerate here could be anything
def as_soundfile(pathR, sample_rate=DEFAULT_FINAL_AUDIO_RATE):
    path = pathR.lower()
    extension = pathR.lower().split(".")[-1]
    if "raw" == extension or "s16" == extension:
        return sf.SoundFile(
            pathR,
            "r",
            channels=1,
            samplerate=int(sample_rate),
            format="RAW",
            subtype="PCM_16",
            endian="LITTLE",
        )
    elif "u8" == extension or "r8" == extension:
        return sf.SoundFile(
            pathR,
            "r",
            channels=1,
            samplerate=int(sample_rate),
            format="RAW",
            subtype="PCM_U8",
            endian="LITTLE",
        )
    elif "s8" == extension:
        return sf.SoundFile(
            pathR,
            "r",
            channels=1,
            samplerate=int(sample_rate),
            format="RAW",
            subtype="PCM_S8",
            endian="LITTLE",
        )
    elif "u16" == extension or "r16" == extension:
        return UnseekableSoundFile(
            UnSigned16BitFileReader(pathR),
            "r",
            channels=1,
            samplerate=int(sample_rate),
            format="RAW",
            subtype="PCM_16",
            endian="LITTLE",
        )
    elif "flac" == extension:
        return sf.SoundFile(
            pathR,
            "r",
        )
    elif "ldf" == extension:
        try:
            if test_ld_tools("ld-ldf-reader"):
                return UnseekableSoundFile(
                    LDToolFileReader("ld-ldf-reader", pathR),
                    "r",
                    channels=1,
                    samplerate=int(sample_rate),
                    format="RAW",
                    subtype="PCM_16",
                    endian="LITTLE",
                )
            print(
                "WARN: ld-ldf-reader is not installed. LDF file format may not decode correctly"
            )
        except Exception as e:
            print(
                "WARN: Unexpected error opening ld-ldf-reader, LDF file format may not decode correctly", e
            )
        
        try:    
            if test_if_flac_is_installed():
                return UnseekableSoundFile(
                    FlacFileReader(pathR),
                    "r",
                    channels=1,
                    samplerate=int(sample_rate),
                    format="RAW",
                    subtype="PCM_16",
                    endian="LITTLE",
                )
            if test_if_ffmpeg_is_installed():
                return UnseekableSoundFile(
                    FFMpegFileReader(pathR),
                    "r",
                    channels=1,
                    samplerate=int(sample_rate),
                    format="RAW",
                    subtype="PCM_16",
                    endian="LITTLE",
                )
        except Exception as e:
            pass

        return sf.SoundFile(
            pathR,
            "r",
        )
    elif "lds" == extension:
        try:
            if test_ld_tools("ld-lds-converter"):
                return UnseekableSoundFile(
                    LDToolFileReader("ld-lds-converter", pathR, "-i"),
                    "r",
                    channels=1,
                    samplerate=int(sample_rate),
                    format="RAW",
                    subtype="PCM_16",
                    endian="LITTLE",
                )
            print(
                "ERROR: Unable to decode LDS without ld-lds-converter. Please install the program and try again."
            )
        except Exception as e:
            print(
                "ERROR: Unexpected error opening ld-lds-converter", e
            )
    elif "-" == path:
        try:
            return UnseekableSoundFile(
                BufferedInputStream(sys.stdin.buffer),
                "r",
                channels=1,
                samplerate=int(sample_rate),
                format="RAW",
                subtype="PCM_16",
                endian="LITTLE",
            )
        except Exception as e:
            print("Failed to open standard in, unable to decode")
            raise e
    else:
        print("WARN: Unknown file format.")
        print("WARN: Attempting to decode with ffmpeg")
        try:
            if test_if_ffmpeg_is_installed():
                return UnseekableSoundFile(
                    FFMpegFileReader(pathR),
                    "r",
                    channels=1,
                    samplerate=int(sample_rate),
                    format="RAW",
                    subtype="PCM_16",
                    endian="LITTLE",
                )
        except Exception:
            pass
        print("WARN: Attempting to decode with SoundFile")
        return sf.SoundFile(pathR, "r")


def get_normalize_filename(path, sample_rate):
    return f"{path}_{int(sample_rate)}_f32_{NORMALIZE_FILE_SUFFIX}"


normalize_parameters = {
    "channels": 2,
    "format": "RAW",  # TODO: update to FLAC 32 bit when supported by soundfile
    "subtype": "FLOAT",
}


def as_outputfile(path, sample_rate, normalize):
    if normalize:
        return sf.SoundFile(
            get_normalize_filename(path, sample_rate),
            "w",
            samplerate=int(sample_rate),
            **normalize_parameters,
        )
    elif ".wav" in path.lower():
        return sf.SoundFile(
            path,
            "w",
            channels=2,
            samplerate=int(sample_rate),
            format="WAV",
            subtype="PCM_16",
        )
    else:
        return sf.SoundFile(
            path,
            "w",
            channels=2,
            samplerate=int(sample_rate),
            format="FLAC",
            subtype="PCM_24",
            compression_level=1.0,
        )


def seconds_to_str(seconds: float) -> str:
    delta = timedelta(seconds=seconds)

    hours, remainder = divmod(delta.total_seconds(), 3600)
    minutes, seconds = divmod(remainder, 60)
    return "{:01}:{:02}:{:06.3f}".format(int(hours), int(minutes), seconds)


def log_decode(
    start_time: datetime,
    frames: int,
    audio_samples: int,
    blocks_enqueued: int,
    input_rate: int,
    audio_rate: int,
):
    elapsed_time: timedelta = datetime.now() - start_time

    input_time: float = frames / (2 * input_rate)
    input_time_format: str = seconds_to_str(input_time)

    audio_time: float = audio_samples / audio_rate
    audio_time_format: str = seconds_to_str(audio_time)

    audio_buffer_time = max(0, input_time - audio_time)
    audio_buffer_time_format: str = seconds_to_str(audio_buffer_time)

    relative_speed: float = input_time / elapsed_time.total_seconds()
    elapsed_time_format: str = seconds_to_str(elapsed_time.total_seconds())

    print(
        f"- Decoding speed: {round(frames / (1e3 * elapsed_time.total_seconds()))} kFrames/s ({relative_speed:.2f}x), {int(blocks_enqueued)} blocks enqueued\n"
        + f"- Input position: {input_time_format}\n"
        + f"- Audio position: {audio_time_format}\n"
        + f"- Audio buffer  : {audio_buffer_time_format}\n"
        + f"- Wall time     : {elapsed_time_format}"
    )


def cleanup_process(process):
    atexit.unregister(process.terminate)
    atexit.unregister(process.join)
    process.terminate()
    process.join()


class PostProcessor:
    def __init__(
        self,
        decode_options: dict,
        decoder_out_queue,
        channel_size,
        post_processor_shared_memory_idle_queue,
        decoder_shared_memory_idle_queue,
        blocks_enqueued,
        out_conn,
        peak_gain,
    ):
        self.final_audio_rate = decode_options["audio_rate"]
        self.enable_expander = decode_options["enable_expander"]
        self.enable_deemphasis = decode_options["enable_deemphasis"]
        self.spectral_nr_amount = decode_options["spectral_nr_amount"]
        self.peak_gain = peak_gain

        # create processes and wire up queues
        #
        #                                 (left channel)
        #                               spectral_noise_reduction_worker --> expander_worker
        #                             /                                                            \
        # data in --[block_sorter]----                                                              --> mix_to_stereo_worker --> data out
        #                             \   (right channel)                                          /
        #                               spectral_noise_reduction_worker --> expander_worker

        self.decoder_out_queue = decoder_out_queue
        self.mix_to_stereo_worker_output = out_conn
        self.blocks_enqueued = blocks_enqueued
        self.decoder_shared_memory_idle_queue = decoder_shared_memory_idle_queue

        self.post_processor_shared_memory = []
        self.post_processor_shared_memory_idle_queue = (
            post_processor_shared_memory_idle_queue
        )
        self.post_processor_num_shared_memory = 16
        for i in range(self.post_processor_num_shared_memory):
            shared_memory = PostProcessorSharedMemory.get_shared_memory(
                channel_size, f"hifi_post_mem_{i}"
            )
            self.post_processor_shared_memory.append(shared_memory)
            self.post_processor_shared_memory_idle_queue.put(shared_memory.name)
            atexit.register(shared_memory.close)
            atexit.register(shared_memory.unlink)

        block_sort_l_in_rx, block_sort_l_in_tx = Pipe(duplex=False)
        block_sort_r_in_rx, block_sort_r_in_tx = Pipe(duplex=False)
        self.block_sorter_process = Process(
            target=PostProcessor.block_sorter_worker,
            name="hifi_block_sort",
            args=(
                self.decoder_out_queue,
                self.decoder_shared_memory_idle_queue,
                self.blocks_enqueued,
                self.post_processor_shared_memory_idle_queue,
                block_sort_l_in_tx,
                block_sort_r_in_tx,
            ),
        )
        self.block_sorter_process.start()
        atexit.register(self.block_sorter_process.terminate)
        atexit.register(self.block_sorter_process.join)

        dc_blocker_worker_l_rx, dc_blocker_worker_l_tx = Pipe(duplex=False)
        self.dc_blocker_worker_l = Process(
            target=PostProcessor.dc_block_worker,
            name="hifi_dc_block_l",
            args=(
                block_sort_l_in_rx,
                dc_blocker_worker_l_tx,
                self.final_audio_rate,
            ),
        )
        self.dc_blocker_worker_l.start()
        atexit.register(self.dc_blocker_worker_l.terminate)
        atexit.register(self.dc_blocker_worker_l.join)

        dc_blocker_worker_r_rx, dc_blocker_worker_r_tx = Pipe(duplex=False)
        self.dc_blocker_worker_r = Process(
            target=PostProcessor.dc_block_worker,
            name="hifi_dc_block_r",
            args=(
                block_sort_r_in_rx,
                dc_blocker_worker_r_tx,
                self.final_audio_rate,
            ),
        )
        self.dc_blocker_worker_r.start()
        atexit.register(self.dc_blocker_worker_r.terminate)
        atexit.register(self.dc_blocker_worker_r.join)

        spectral_nr_worker_l_rx, spectral_nr_worker_l_tx = Pipe(duplex=False)
        self.spectral_nr_worker_l = Process(
            target=PostProcessor.spectral_noise_reduction_worker,
            name="hifi_spec_nr_l",
            args=(
                dc_blocker_worker_l_rx,
                spectral_nr_worker_l_tx,
                self.spectral_nr_amount,
                self.final_audio_rate,
            ),
        )
        self.spectral_nr_worker_l.start()
        atexit.register(self.spectral_nr_worker_l.terminate)
        atexit.register(self.spectral_nr_worker_l.join)

        spectral_nr_worker_r_rx, spectral_nr_worker_r_tx = Pipe(duplex=False)
        self.spectral_nr_worker_r = Process(
            target=PostProcessor.spectral_noise_reduction_worker,
            name="hifi_spec_nr_r",
            args=(
                dc_blocker_worker_r_rx,
                spectral_nr_worker_r_tx,
                self.spectral_nr_amount,
                self.final_audio_rate,
            ),
        )
        self.spectral_nr_worker_r.start()
        atexit.register(self.spectral_nr_worker_r.terminate)
        atexit.register(self.spectral_nr_worker_r.join)

        expander_worker_l_out_rx, expander_worker_l_out_tx = Pipe(duplex=False)
        self.expander_worker_l = Process(
            target=PostProcessor.expander_worker,
            name="hifi_expander_l",
            args=(
                spectral_nr_worker_l_rx,
                expander_worker_l_out_tx,
                self.enable_expander,
                self.enable_deemphasis,
                self.final_audio_rate,
                decode_options["expander_gain"],
                decode_options["expander_ratio"],
                decode_options["expander_attack_tau"],
                decode_options["expander_release_tau"],
                decode_options["expander_weighting_low_tau"],
                decode_options["expander_weighting_high_tau"],
                decode_options["expander_weighting_db_per_octave"],
                decode_options["expander_weighting_bandwidth"],
                decode_options["deemphasis_low_tau"],
                decode_options["deemphasis_high_tau"],
                decode_options["deemphasis_db_per_octave"],
                decode_options["deemphasis_bandwidth"],
            ),
        )
        self.expander_worker_l.start()
        atexit.register(self.expander_worker_l.terminate)
        atexit.register(self.expander_worker_l.join)

        expander_worker_r_out_rx, expander_worker_r_out_tx = Pipe(duplex=False)
        self.expander_worker_r = Process(
            target=PostProcessor.expander_worker,
            name="hifi_expander_r",
            args=(
                spectral_nr_worker_r_rx,
                expander_worker_r_out_tx,
                self.enable_expander,
                self.enable_deemphasis,
                self.final_audio_rate,
                decode_options["expander_gain"],
                decode_options["expander_ratio"],
                decode_options["expander_attack_tau"],
                decode_options["expander_release_tau"],
                decode_options["expander_weighting_low_tau"],
                decode_options["expander_weighting_high_tau"],
                decode_options["expander_weighting_db_per_octave"],
                decode_options["expander_weighting_bandwidth"],
                decode_options["deemphasis_low_tau"],
                decode_options["deemphasis_high_tau"],
                decode_options["deemphasis_db_per_octave"],
                decode_options["deemphasis_bandwidth"],
            ),
        )
        self.expander_worker_r.start()
        atexit.register(self.expander_worker_r.terminate)
        atexit.register(self.expander_worker_r.join)

        self.mix_to_stereo_worker_process = Process(
            target=PostProcessor.mix_to_stereo_worker,
            name="hifi_stereo_mix",
            args=(
                expander_worker_l_out_rx,
                expander_worker_r_out_rx,
                self.mix_to_stereo_worker_output,
                self.peak_gain,
                self.final_audio_rate,
            ),
        )
        self.mix_to_stereo_worker_process.start()
        atexit.register(self.mix_to_stereo_worker_process.terminate)
        atexit.register(self.mix_to_stereo_worker_process.join)

    @staticmethod
    @guvectorize(
        [(numba.types.float32, NumbaAudioArray, NumbaAudioArray)],
        "(),(n)->(n)",
        cache=True,
        fastmath=True,
        nopython=True,
    )
    def normalize(gain, _, audio):
        for i in range(len(audio)):
            audio[i] = audio[i] * gain

    @staticmethod
    def dc_block_worker(
        in_conn,
        out_conn,
        final_audio_rate
    ):
        setproctitle(current_process().name)
        dc_blocker = DCBlocker(
            final_audio_rate,
            8
        )

        while True:
            while True:
                try:
                    decoder_state, channel_num = in_conn.recv()
                    break
                except InterruptedError:
                    pass
                except EOFError:
                    return

            buffer = PostProcessorSharedMemory(decoder_state)
            if channel_num == 0:
                pre = buffer.get_pre_left()
            else:
                pre = buffer.get_pre_right()

            dc_blocker.process(pre)

            buffer.close()
            out_conn.send((decoder_state, channel_num))
        
    @staticmethod
    def spectral_noise_reduction_worker(
        in_conn,
        out_conn,
        spectral_nr_amount,
        final_audio_rate,
    ):
        setproctitle(current_process().name)
        spectral_nr = SpectralNoiseReduction(
            nr_reduction_amount=spectral_nr_amount,
            audio_rate=final_audio_rate,
        )

        while True:
            while True:
                try:
                    decoder_state, channel_num = in_conn.recv()
                    break
                except InterruptedError:
                    pass
                except EOFError:
                    return

            buffer = PostProcessorSharedMemory(decoder_state)
            if channel_num == 0:
                pre = buffer.get_pre_left()
                spectral_nr_out = buffer.get_post_left()
            else:
                pre = buffer.get_pre_right()
                spectral_nr_out = buffer.get_post_right()

            if spectral_nr_amount > 0:
                spectral_nr.spectral_nr(pre, spectral_nr_out)
            else:
                DecoderSharedMemory.copy_data_float32(
                    pre, spectral_nr_out, len(spectral_nr_out)
                )

            buffer.close()
            out_conn.send((decoder_state, channel_num))

    @staticmethod
    def expander_worker(
        in_conn,
        out_conn,
        enable_expander,
        enable_deemphasis,
        final_audio_rate,
        expander_gain,
        expander_ratio,
        expander_attack_tau,
        expander_release_tau,
        expander_weighting_low_tau,
        expander_weighting_high_tau,
        expander_weighting_db_per_octave,
        expander_weighting_bandwidth,
        deemphasis_low_tau,
        deemphasis_high_tau,
        deemphasis_db_per_octave,
        deemphasis_bandwidth
    ):
        setproctitle(current_process().name)
        deemphasis = Deemphasis(
            final_audio_rate,
            deemphasis_low_tau,
            deemphasis_high_tau,
            deemphasis_db_per_octave,
            deemphasis_bandwidth
        )

        expander = Expander(
            final_audio_rate,
            expander_gain,
            expander_ratio,
            expander_attack_tau,
            expander_release_tau,
            expander_weighting_low_tau,
            expander_weighting_high_tau,
            expander_weighting_db_per_octave,
            expander_weighting_bandwidth
        )

        while True:
            while True:
                try:
                    decoder_state, channel_num = in_conn.recv()
                    break
                except InterruptedError:
                    pass
                except EOFError:
                    return

            buffer = PostProcessorSharedMemory(decoder_state)
            if channel_num == 0:
                pre = buffer.get_pre_left()
                post = buffer.get_post_left()
            else:
                pre = buffer.get_pre_right()
                post = buffer.get_post_right()

            if enable_deemphasis:
                deemphasis.process(post)

            if enable_expander:
                if decoder_state.block_num == 0:
                    # prime the expander's gain if this is the first block
                    expander.process(pre, np.copy(post))
                expander.process(pre, post)

            buffer.close()
            out_conn.send(decoder_state)

    @staticmethod
    def mix_to_stereo_worker(
        expander_l_in_conn, expander_r_in_conn, out_conn, peak_gain, sample_rate
    ):
        setproctitle(current_process().name)
        while True:
            while True:
                try:
                    l_decoder_state = expander_l_in_conn.recv()
                    break
                except InterruptedError:
                    pass
                except EOFError:
                    return

            while True:
                try:
                    r_decoder_state = expander_r_in_conn.recv()
                    break
                except InterruptedError:
                    pass
                except EOFError:
                    return

            assert (
                l_decoder_state.block_num == r_decoder_state.block_num
            ), "Noise reduction processes are out of sync! Channels will be out of sync."

            decoder_state = l_decoder_state
            buffer = PostProcessorSharedMemory(decoder_state)
            l = buffer.get_post_left()
            r = buffer.get_post_right()
            stereo = buffer.get_stereo()

            max_gain = PostProcessor.stereo_interleave(
                l, r, stereo, sample_rate, decoder_state.block_num == 0
            )

            if peak_gain.value < max_gain:
                with peak_gain.get_lock():
                    peak_gain.value = max_gain

            buffer.close()
            out_conn.send(decoder_state)

    @staticmethod
    @njit(
        numba.types.float32(
            NumbaAudioArray,
            NumbaAudioArray,
            NumbaAudioArray,
            numba.types.int32,
            numba.types.bool_,
        ),
        cache=True,
        fastmath=True,
        nogil=True,
    )
    def stereo_interleave(
        audioL: np.array,
        audioR: np.array,
        stereo: np.array,
        sample_rate: int,
        is_first_block: bool,
    ) -> int:
        max_gain = 0
        start_sample = 0

        # mute the spike that occurs during noise reduction
        if is_first_block:
            trim_samples = int(0.0015 * sample_rate)
            start_sample = trim_samples
            for i in range(trim_samples):
                stereo[i * 2] = 0
                stereo[i * 2 + 1] = 0

        channel_length = len(audioL)
        for i in range(start_sample, channel_length):
            audioLSample = audioL[i]
            stereo[i * 2] = audioLSample
            gain = abs(audioLSample)
            if gain > max_gain:
                max_gain = gain

            audioRSample = audioR[i]
            stereo[i * 2 + 1] = audioRSample
            gain = abs(audioRSample)
            if gain > max_gain:
                max_gain = gain

        return max_gain

    @staticmethod
    def block_sorter_worker(
        decoder_out_queue,
        decoder_shared_memory_idle_queue,
        blocks_enqueued,
        post_processor_shared_memory_idle_queue,
        l_tx,
        r_tx,
    ):
        setproctitle(current_process().name)
        next_block = 0
        last_block_submitted = -1
        block_queue = []

        done = False
        while not done:
            while True:
                try:
                    in_decoder_state = decoder_out_queue.get()
                    break
                except InterruptedError:
                    pass
                except EOFError:
                    return

            buffer = DecoderSharedMemory(in_decoder_state)

            in_preL_buffer = buffer.get_pre_left()
            in_preR_buffer = buffer.get_pre_right()

            in_preL = np.empty(in_decoder_state.block_audio_final_len, dtype=REAL_DTYPE)
            in_preR = np.empty(in_decoder_state.block_audio_final_len, dtype=REAL_DTYPE)

            DecoderSharedMemory.copy_data_float32(
                in_preL_buffer, in_preL, len(in_preL)
            )
            DecoderSharedMemory.copy_data_float32(
                in_preR_buffer, in_preR, len(in_preR)
            )

            buffer.close()

            decoder_shared_memory_idle_queue.put(in_decoder_state.name)
            with blocks_enqueued.get_lock():
                blocks_enqueued.value -= 1

            # blocks are received from the decoder processes out of order
            # gather them into ordered chunk and process sequentially
            assert (
                last_block_submitted < in_decoder_state.block_num
            ), f"Warning, block was repeated, got {in_decoder_state.block_num}, already processed {last_block_submitted}"
            block_queue.append((in_decoder_state, in_preL, in_preR))

            if in_decoder_state.block_num == next_block:
                # process queued data in order of block number
                block_queue.sort(key=lambda x: x[0].block_num)

                # enqueue the blocks in order
                while len(block_queue) > 0 and (
                    block_queue[0][0].block_num <= next_block
                ):
                    while True:
                        try:
                            name = post_processor_shared_memory_idle_queue.get()
                            break
                        except InterruptedError:
                            pass
                        except EOFError:
                            return

                    decoder_state, preL, preR = block_queue.pop(0)

                    decoder_state.name = name
                    buffer = PostProcessorSharedMemory(decoder_state)

                    post_processor_preL = buffer.get_pre_left()
                    DecoderSharedMemory.copy_data_float32(
                        preL,
                        post_processor_preL,
                        len(post_processor_preL),
                    )
                    post_processor_preR = buffer.get_pre_right()
                    DecoderSharedMemory.copy_data_float32(
                        preR,
                        post_processor_preR,
                        len(post_processor_preR),
                    )

                    l_tx.send((decoder_state, 0))
                    r_tx.send((decoder_state, 1))

                    next_block += 1
                    last_block_submitted = decoder_state.block_num
                    done = decoder_state.is_last_block

    def close(self):
        cleanup_process(self.block_sorter_process)
        cleanup_process(self.dc_blocker_worker_l)
        cleanup_process(self.dc_blocker_worker_r)
        cleanup_process(self.spectral_nr_worker_l)
        cleanup_process(self.spectral_nr_worker_r)
        cleanup_process(self.expander_worker_l)
        cleanup_process(self.expander_worker_r)
        cleanup_process(self.mix_to_stereo_worker_process)


class AppWindow:
    def __init__(self, argv, decode_options):
        self._app, self._window = self.open_ui(argv, decode_options)

    def __del__(self):
        # self._window.close()
        self._app.quit()

    def open_ui(self, argv, decode_options):
        app = QApplication(argv)
        print("Opening hifi-ui...")
        if decode_options["input_file"] == "-":
            window = FileOutputDialogUI(decode_options_to_ui_parameters(decode_options))
        else:
            window = FileIODialogUI(decode_options_to_ui_parameters(decode_options))
        window.show()
        return app, window

    def run(self):
        self._app.exec_()

    @property
    def window(self):
        return self._window

    @property
    def app(self):
        return self._app


class SoundDeviceProcess:
    def __init__(self, sample_rate, stop_requested):
        self._sample_rate = sample_rate
        self._stop_requested = stop_requested

    def __enter__(self):
        self._play_parent_conn, self._play_child_conn = Pipe()
        self._process = Process(
            target=SoundDeviceProcess.play_worker,
            name="hifi_playback_worker",
            args=(self._play_child_conn, self._sample_rate, self._stop_requested),
        )
        self._process.start()
        return self

    def __exit__(self, exception_type, exception_value, exception_traceback):
        self._process.terminate()
        self._process.join()
        return self

    @staticmethod
    @njit(
        numba.types.void(
            numba.types.Array(numba.types.float32, 1, "C", readonly=True),
            numba.types.Array(numba.types.int16, 2, "C"),
        ),
        cache=True,
        fastmath=True,
        nogil=True,
    )
    def build_stereo(interleaved: np.array, stacked) -> np.array:
        for i in range(0, len(stacked)):
            stacked[i][0] = interleaved[i * 2] * 2**15
            stacked[i][1] = interleaved[i * 2 + 1] * 2**15

    @staticmethod
    def play_worker(conn, sample_rate, stop_requested):
        setproctitle(current_process().name)
        output_stream = None
        while True:
            while True:
                try:
                    with stop_requested.get_lock():
                        if stop_requested.value == STOP_IMMEDIATE_REQUESTED:
                            return

                    if conn.poll(1):
                        stereo = conn.recv_bytes()
                        break
                except InterruptedError:
                    pass
                except EOFError:
                    return

            if output_stream == None:
                output_stream = sd.OutputStream(
                    samplerate=sample_rate, channels=2, dtype="int16"
                )
                output_stream.start()

            interleaved_len = int(len(stereo) / np.dtype(REAL_DTYPE).itemsize)
            interleaved = np.ndarray(interleaved_len, dtype=REAL_DTYPE, buffer=stereo)
            stacked = np.empty((int(len(interleaved) / 2), 2), dtype=np.int16)

            SoundDeviceProcess.build_stereo(interleaved, stacked)
            output_stream.write(stacked)

    def play(self, stereo):
        self._play_parent_conn.send_bytes(stereo)


def write_soundfile_process_worker(
    post_processor_out_rx_conn,
    blocks_enqueued,
    post_processor_shared_memory_idle_queue,
    start_time,
    input_position,
    total_samples_decoded,
    decode_options,
    output_file: str,
    stop_requested,
    decode_done,
):
    setproctitle(current_process().name)
    audio_rate = decode_options["audio_rate"]
    input_rate = decode_options["input_rate"]
    preview_mode = decode_options["preview"]
    normalize = decode_options["normalize"]

    if preview_mode:
        player = SoundDeviceProcess(audio_rate, stop_requested)
    else:
        player = nullcontext()

    with player, as_outputfile(output_file, audio_rate, normalize) as w:
        done = False
        while not done:
            while True:
                try:
                    decoder_state = post_processor_out_rx_conn.recv()
                    break
                except InterruptedError:
                    pass
                except EOFError:
                    return

            buffer = PostProcessorSharedMemory(decoder_state)
            stereo = buffer.get_stereo()
            samples_decoded = len(stereo) / 2
            
            # pad the start of the audio due to beginning gap
            if decoder_state.block_num == 0:
                padding = round(decoder_state.block_audio_final_overlap / 2) * 2 * 4 # 2 channels, 4 bytes per channel
                w.buffer_write(bytes(padding), dtype="float32")

            w.buffer_write(stereo, dtype="float32")
            if preview_mode:
                if SOUNDDEVICE_AVAILABLE:
                    stereo_copy = np.empty_like(stereo)
                    DecoderSharedMemory.copy_data_float32(
                        stereo, stereo_copy, len(stereo_copy)
                    )
                    player.play(stereo_copy)
                else:
                    print("Import of sounddevice failed, preview is not available!")

            buffer.close()
            post_processor_shared_memory_idle_queue.put(decoder_state.name)
            with total_samples_decoded.get_lock():
                total_samples_decoded.value = int(
                    total_samples_decoded.value + samples_decoded
                )

            log_decode(
                start_time,
                input_position.value,
                total_samples_decoded.value,
                blocks_enqueued.value,
                input_rate,
                audio_rate,
            )

            done = decoder_state.is_last_block

        w.flush()
        decode_done.set()


async def decode_parallel(
    decode_options: dict,
    threads: int = 8,
    ui_t: Optional[AppWindow] = None,
):
    decoder = HiFiDecode(options=decode_options, is_main_process=True, bias_guess=decode_options["bias_guess"])
    # TODO: reprocess data read in this step
    if decode_options["bias_guess"]:
        guess_bias(decoder, decode_options["input_file"], int(decode_options["input_rate"]))

    input_file = decode_options["input_file"]
    output_file = decode_options["output_file"]

    block_size = decoder.initialBlockSize

    blocks_enqueued = Value("d", 0)
    input_position = Value("d", 0)
    total_samples_decoded = Value("d", 0)
    peak_gain = Value("d", 0)
    stop_requested = Value("d", STOP_NOT_REQUESTED)
    start_time = datetime.now()

    # HiFiDecode data flow diagram
    # All data is sent via SharedMemory
    # Each step below are separate processes connected together with queues
    # Each message on the queue contains the name of the SharedMemory buffer and any state that needs to persist as the data flow through
    #
    #                            [decoder_process_worker]
    #                                |->-decoder_1->-|
    #                                |->-decoder_2->-|                                                                                |-> [SoundDeviceProcess] -> audio out
    # data in ->- decoder_in_queue->-|->-decoder_3->-|->-decoder_out_queue-->--[post_processor]-->--[write_soundfile_process_worker]--|
    #                                |->-decoder_4->-|                           |                                                    |-> [SoundFileEncoder] ---> data out
    #                                |->-decoder_n->-|                           (see PostProcessor for details)

    # spin up shared memory
    # these blocks of memory are used to transfer the audio data throughout the various steps
    num_shared_memory_instances = int(threads + 2)
    num_decoders = threads

    shared_memory_instances = []
    shared_memory_idle_queue = SimpleQueue()
    for i in range(num_shared_memory_instances):
        buffer_instance = DecoderSharedMemory.get_shared_memory(
            decoder.initialBlockSize,
            decoder.blockOverlap,
            decoder.initialBlockFinalAudioSize,
            f"hifi_decoder_{i}",
        )
        shared_memory_instances.append(buffer_instance)
        shared_memory_idle_queue.put(buffer_instance.name)

        atexit.register(buffer_instance.close)
        atexit.register(buffer_instance.unlink)

    # spin up the decoders
    decoder_processes: list[Process] = []
    decoder_in_queue = SimpleQueue()
    decoder_out_queue = SimpleQueue()
    decode_done = Event()

    for i in range(num_decoders):
        decoder_process = Process(
            target=HiFiDecode.hifi_decode_worker,
            name=f"hifi_decode_worker_{i}",
            args=(
                decoder_in_queue,
                decoder_out_queue,
                decode_options,
                decoder.standard,
            ),
        )
        decoder_process.start()

        atexit.register(decoder_process.terminate)
        decoder_processes.append(decoder_process)

    # set up the post processor
    post_processor_out_rx_conn, post_processor_out_tx_conn = Pipe(duplex=False)
    post_processor_shared_memory_idle_queue = SimpleQueue()
    post_processor = PostProcessor(
        decode_options,
        decoder_out_queue,
        decoder.initialBlockFinalAudioSize + decoder.blockAudioFinalOverlap * 2,
        post_processor_shared_memory_idle_queue,
        shared_memory_idle_queue,
        blocks_enqueued,
        post_processor_out_tx_conn,
        peak_gain,
    )
    atexit.register(post_processor.close)

    # set up the output file process
    output_file_process = Process(
        target=write_soundfile_process_worker,
        name="hifi_output_encoder",
        args=(
            post_processor_out_rx_conn,
            blocks_enqueued,
            post_processor_shared_memory_idle_queue,
            start_time,
            input_position,
            total_samples_decoded,
            decode_options,
            output_file,
            stop_requested,
            decode_done,
        ),
    )
    output_file_process.start()
    atexit.register(output_file_process.terminate)
    atexit.register(output_file_process.join)

    def read_and_send_to_decoder(
        f,
        decoder,
        decoder_state,
        input_position,
        exit_requested,
        previous_overlap,
    ):
        buffer = DecoderSharedMemory(decoder_state)
        # read input data into the shared memory buffer
        block_in = buffer.get_block_in()
        frames_read = f.buffer_read_into(block_in, "int16")
        
        decoder_state.block_frames_read = frames_read
        decoder_state.is_last_block = frames_read < len(block_in) or exit_requested or stop_requested.value

        with input_position.get_lock():
            input_position.value += frames_read * 2

        if block_num == 0:
            # save the read data
            block_data_read = buffer.get_block_in().copy()
            buffer.close()

            # shift the actual data down by half so only the copied data is discarded
            start_overlap_end = (
                decoder_state.block_read_overlap - decoder_state.block_overlap
            )
            new_block_length = frames_read + start_overlap_end

            # create a new buffer with the updated offsets, and copy in the read data
            decoder_state = DecoderState(
                decoder,
                buffer.name,
                decoder_state.block_frames_read,
                new_block_length,
                decoder_state.block_num,
                decoder_state.is_last_block,
            )
            buffer = DecoderSharedMemory(decoder_state)
            block = buffer.get_block()
            # copy starting at half the normal read overlap
            DecoderSharedMemory.copy_data_dst_offset_int16(
                block_data_read, block, start_overlap_end, len(block_data_read)
            )

            # this is the first block, fill in the empty data before half the read overlap, this will be discarded
            DecoderSharedMemory.copy_data_int16(
                block_data_read, block, start_overlap_end
            )
        else:
            # copy the overlapping data from the previous read
            block_in_overlap = buffer.get_block_in_start_overlap()
            DecoderSharedMemory.copy_data_int16(
                previous_overlap, block_in_overlap, len(block_in_overlap)
            )

        if not decoder_state.is_last_block:
            # copy the the current overlap to use in the next iteration
            current_overlap = buffer.get_block_in_end_overlap()
            DecoderSharedMemory.copy_data_int16(
                current_overlap, previous_overlap, len(current_overlap)
            )

        buffer.close()

        # submit the block to the decoder
        # blocks should complete roughly in the order that they are submitted
        decoder_in_queue.put(decoder_state)

        return decoder_state.is_last_block

    print(f"Starting decode...")

    async def ui_task(stop_requested, ui_t):
        while True:
            previous_state = ui_t.window.transport_state
            ui_t.app.processEvents()

            if ui_t.window.transport_state == STOP_STATE:
                with stop_requested.get_lock():
                    stop_requested.value = STOP_REQUESTED

                    if previous_state == PREVIEW_STATE:
                        stop_requested.value = STOP_IMMEDIATE_REQUESTED

                break
            elif ui_t.window.transport_state == PAUSE_STATE:
                while ui_t.window.transport_state == PAUSE_STATE:
                    ui_t.app.processEvents()
                    await asyncio.sleep(0.01)

            await asyncio.sleep(0.01)

    if ui_t is not None:
        asyncio.create_task(ui_task(stop_requested, ui_t))

    with as_soundfile(input_file) as f:
        loop = asyncio.get_event_loop()
        previous_overlap = np.empty(0)
        progressB = TimeProgressBar(f.frames, f.frames)
        block_num = 0

        while True:
            # get the next available shared memory buffer
            while True:
                try:
                    buffer_name = await loop.run_in_executor(
                        None, shared_memory_idle_queue.get
                    )
                    break
                except InterruptedError:
                    pass
                except EOFError:
                    return

            decoder_state = DecoderState(
                decoder, buffer_name, 0, block_size, block_num, False
            )

            if len(previous_overlap) == 0:
                previous_overlap = np.empty(
                    decoder_state.block_read_overlap, dtype=np.int16
                )

            is_last_block = await loop.run_in_executor(
                None,
                read_and_send_to_decoder,
                f,
                decoder,
                decoder_state,
                input_position,
                exit_requested,
                previous_overlap,
            )
            
            with blocks_enqueued.get_lock():
                progressB.print(input_position.value / 2)
                blocks_enqueued.value += 1

            log_decode(
                start_time,
                input_position.value,
                total_samples_decoded.value,
                blocks_enqueued.value,
                decode_options["input_rate"],
                decode_options["audio_rate"],
            )

            if is_last_block:
                break

            block_num += 1

    print("")
    print("Decode finishing up. Emptying the queue")
    print("")
    
    with stop_requested.get_lock():
        if stop_requested.value != STOP_IMMEDIATE_REQUESTED:
            decode_done.wait()

    for p in decoder_processes:
        cleanup_process(p)
    post_processor.close()
    cleanup_process(output_file_process)

    for shared_memory in shared_memory_instances:
        shared_memory.close()
        shared_memory.unlink()
        atexit.unregister(shared_memory.close)
        atexit.unregister(shared_memory.unlink)
    
    with peak_gain.get_lock():
        print(f"\nPeak gain is {(peak_gain.value * 100):.2f}%.", end="")

        if decode_options["normalize"]:
            gain_adjust = (
                1 / peak_gain.value - np.finfo(np.float16).eps
            )  # subtract epsilon error to prevent appearance of "clipping" in editing tools
            print(f" Adjusting to {(gain_adjust * 100):.2f}%, please wait...")

            input_file_post_gain = get_normalize_filename(
                output_file, decode_options["audio_rate"]
            )
            output_file = decode_options["output_file"]
            audio_rate = decode_options["audio_rate"]

            try:
                total_frames_read = 0
                buffer = np.empty(2**20, dtype=np.float32)

                with sf.SoundFile(
                    input_file_post_gain,
                    "r",
                    samplerate=int(decode_options["audio_rate"]),
                    **normalize_parameters,
                ) as f, as_outputfile(output_file, audio_rate, False) as w:
                    progressB = TimeProgressBar(f.frames, f.frames)
                    done = False
                    while not done:
                        frames_read = f.buffer_read_into(buffer, dtype="float32")
                        samples_read = frames_read * 2

                        if samples_read < len(buffer):
                            buffer = buffer[0:samples_read]
                            done = True

                        PostProcessor.normalize(gain_adjust, buffer, buffer)
                        w.buffer_write(buffer, "float32")

                        total_frames_read += frames_read
                        progressB.print(total_frames_read, False)
                print("")
            finally:
                os.remove(input_file_post_gain)

    elapsed_time = datetime.now() - start_time
    dt_string = elapsed_time.total_seconds()
    print(f"\nDecode finished, seconds elapsed: {round(dt_string)}")


def guess_bias(decoder, input_file, block_size, blocks_limits=10):
    print("Measuring carrier bias ... ")
    blocks = list()

    with as_soundfile(input_file) as f:
        while f.tell() < f.frames and len(blocks) <= blocks_limits:
            block_buffer = np.empty(block_size, dtype=np.int16)
            f.buffer_read_into(block_buffer, "int16")
            blocks.append(block_buffer)

    decoder.guessBiases(blocks)
    print("\ndone!")


def run_decoder(args, decode_options, ui_t: Optional[AppWindow] = None):
    sample_freq = decode_options["input_rate"]

    if sample_freq is not None:
        # set_start_method("spawn")
        with ThreadPoolExecutor(args.threads) as async_executor:
            loop = asyncio.get_event_loop()
            loop.set_default_executor(async_executor)
            loop.run_until_complete(
                decode_parallel(decode_options, threads=args.threads, ui_t=ui_t)
            )
        print("Decode finished successfully")
        return 0
    else:
        print("No sample rate specified")
        return 0


def main() -> int:
    args = parser.parse_args()

    system = "PAL" if args.pal else "NTSC"
    sample_freq = args.inputfreq

    if not "UI" in args:
        if not test_input_file(args.infile):
            raise FileNotFoundError("Input file error")
        if not test_output_file(args.outfile):
            raise FileNotFoundError("Output file error")

    filename = args.infile
    outname = args.outfile

    if not args.UI and not args.overwrite:
        if os.path.isfile(outname):
            print(
                "Existing decode files found, remove them or run command with --overwrite"
            )
            print("\t", outname)
            return 1

    print("Initializing ...")

    # 8mm AFM uses a mono channel, or L-R/L+R rather than L/R channels
    # The spec defines a dual audio mode but not sure if it was ever used.
    default_mode = "s" if not args.format_8mm else "mpx"

    real_mode = default_mode if not args.mode else args.mode

    if (
        args.resampler_quality == "low"
        or args.resampler_quality == "medium"
        or args.resampler_quality == "high"
    ):
        resampler_quality = args.resampler_quality
    else:
        resampler_quality = DEFAULT_RESAMPLER_QUALITY

    if args.format_8mm:
        print("using 8mm")
        tape_format = "8mm"
        default_deemphasis_low_tau = DEFAULT_8MM_DEEMPHASIS_TAU_1
        default_deemphasis_high_tau = DEFAULT_8MM_DEEMPHASIS_TAU_2
        default_deemphasis_db_per_octave = DEFAULT_8MM_DEEMPHASIS_DB_PER_OCTAVE
        default_deemphasis_bandwidth = DEFAULT_8MM_DEEMPHASIS_BANDWIDTH

        default_expander_weighting_low_tau = DEFAULT_8MM_EXPANDER_WEIGHTING_TAU_1
        default_expander_weighting_high_tau = DEFAULT_8MM_EXPANDER_WEIGHTING_TAU_2
        default_expander_weighting_db_per_octave = DEFAULT_8MM_EXPANDER_WEIGHTING_DB_PER_OCTAVE
        default_expander_weighting_bandwidth = DEFAULT_8MM_EXPANDER_WEIGHTING_BANDWIDTH
    else:
        print("using vhs")
        tape_format = "vhs"
        default_deemphasis_low_tau = DEFAULT_VHS_DEEMPHASIS_TAU_1
        default_deemphasis_high_tau = DEFAULT_VHS_DEEMPHASIS_TAU_2
        default_deemphasis_db_per_octave = DEFAULT_VHS_DEEMPHASIS_DB_PER_OCTAVE
        default_deemphasis_bandwidth = DEFAULT_VHS_DEEMPHASIS_BANDWIDTH

        default_expander_weighting_low_tau = DEFAULT_VHS_EXPANDER_WEIGHTING_TAU_1
        default_expander_weighting_high_tau = DEFAULT_VHS_EXPANDER_WEIGHTING_TAU_2
        default_expander_weighting_db_per_octave = DEFAULT_VHS_EXPANDER_WEIGHTING_DB_PER_OCTAVE
        default_expander_weighting_bandwidth = DEFAULT_VHS_EXPANDER_WEIGHTING_BANDWIDTH

    decode_options = {
        "input_rate": sample_freq * 1e6,
        "standard": "p" if system == "PAL" else "n",
        "format": tape_format,
        "preview": args.preview,
        "preview_available": SOUNDDEVICE_AVAILABLE,
        "demod_type": args.demod_type,
        "afe_vco_deviation": args.afe_vco_deviation * 10e5,
        "afe_left_carrier": args.afe_left_carrier * 10e5,
        "afe_right_carrier": args.afe_right_carrier * 10e5,
        "resampler_quality": resampler_quality if not args.preview else "low",
        "spectral_nr_amount": args.spectral_nr_amount if not args.preview else 0,
        "head_switching_interpolation": args.head_switching_interpolation == "on",
        "muting": args.muting == "on",
        "enable_expander": args.enable_expander == "on",
        "enable_deemphasis": args.enable_deemphasis == "on",
        "auto_fine_tune": args.auto_fine_tune == "on" if not args.preview else False,
        "bias_guess": args.bias_guess,
        "normalize": args.normalize,
        "expander_gain": args.expander_gain,
        "expander_ratio": args.expander_ratio,
        "expander_attack_tau": args.expander_attack_tau,
        "expander_release_tau": args.expander_release_tau,
        "expander_weighting_low_tau": args.expander_weighting_low_tau or default_expander_weighting_low_tau,
        "expander_weighting_high_tau": args.expander_weighting_high_tau or default_expander_weighting_high_tau,
        "expander_weighting_db_per_octave": args.expander_weighting_db_per_octave or default_expander_weighting_db_per_octave,
        "expander_weighting_bandwidth": args.expander_weighting_bandwidth or default_expander_weighting_bandwidth,
        "deemphasis_low_tau": args.deemphasis_low_tau or default_deemphasis_low_tau,
        "deemphasis_high_tau": args.deemphasis_high_tau or default_deemphasis_high_tau,
        "deemphasis_db_per_octave": args.deemphasis_db_per_octave or default_deemphasis_db_per_octave,
        "deemphasis_bandwidth": args.deemphasis_bandwidth or default_deemphasis_bandwidth,
        "grc": args.GRC,
        "audio_rate": args.rate if not args.preview else 44100,
        "gain": args.gain,
        "input_file": filename,
        "output_file": outname,
        "mode": real_mode,
    }

    if args.UI and not HIFI_UI:
        print(
            (
                "PyQt5/PyQt6 is not installed, can not use graphical UI,"
                " falling back to command line interface.."
            )
        )

    if args.UI and HIFI_UI:
        ui_t = AppWindow(sys.argv, decode_options)
        decoder_state = 0
        try:
            while ui_t.window.isVisible():
                if (
                    ui_t.window.transport_state == PLAY_STATE
                    or ui_t.window.transport_state == PREVIEW_STATE
                ):
                    print("Starting decode...")
                    options = ui_parameters_to_decode_options(ui_t.window.getValues())
                    if ui_t.window.transport_state == PREVIEW_STATE:
                        options["preview"] = True
                    else:
                        options["preview"] = False

                    print("options", options)

                    # change to output file directory
                    if os.path.dirname(options["output_file"]) != "":
                        os.chdir(os.path.dirname(options["output_file"]))

                    # test input and output files
                    if test_input_file(options["input_file"]) and test_output_file(
                        options["output_file"]
                    ):
                        decoder_state = run_decoder(args, options, ui_t=ui_t)
                        previous_state = ui_t.window.transport_state
                        ui_t.window.transport_state = STOP_STATE

                        if previous_state == PLAY_STATE:
                            ui_t.window.on_decode_finished()
                    else:
                        message = None
                        if not test_input_file(options["input_file"]):
                            message = f"Input file '{options['input_file']}' not found"
                        elif not test_output_file(options["output_file"]):
                            message = f"Output file '{options['output_file']}' cannot be created nor overwritten"

                        ui_t.window.generic_message_box(
                            "I/O Error", message, QMessageBox.Icon.Critical
                        )
                        ui_t.window.on_stop_clicked()

                ui_t.app.processEvents()
                time.sleep(0.01)
            ui_t.window.transport_state = STOP_STATE
        except (KeyboardInterrupt, RuntimeError):
            pass

        return decoder_state
    else:
        if test_input_file(filename) and test_output_file(outname):
            if decode_options["format"] == "vhs":
                (
                    print(f"PAL VHS format selected, Audio mode is {real_mode}")
                    if system == "PAL"
                    else print(f"NTSC VHS format selected, Audio mode is {real_mode}")
                )
            else:
                if system == "PAL":
                    print(f"PAL 8mm format selected, Audio mode is {real_mode}")
                else:
                    print(f"NTSC 8mm format selected, Audio mode is {real_mode}")

            return run_decoder(args, decode_options)
        else:
            parser.print_help()
            print(
                "ERROR: input file not found"
                if not test_input_file(filename)
                else f"ERROR: output file '{outname}' cannot be created nor overwritten"
            )
            return 1


signal_count = 0
exit_requested = False
main_pid = os.getpid()
NUM_SIGINT_BEFORE_FORCE_EXIT = 1


def parent_signal_handler(sig, frame):
    global signal_count
    global main_pid
    global exit_requested

    exit_requested = True
    is_main_thread = main_pid == os.getpid()
    if signal_count >= NUM_SIGINT_BEFORE_FORCE_EXIT:
        if is_main_thread:
            # prevent reentrant calls https://stackoverflow.com/a/75368797
            os.write(
                sys.stdout.fileno(),
                b"\nCtrl-C was pressed again, stopping immediately...\n",
            )
        sys.exit(1)
    if signal_count == 0:
        if is_main_thread:
            os.write(sys.stdout.fileno(), b"\nCtrl-C was pressed, stopping decode...\n")
    signal_count += 1


def child_signal_handler(sig, frame):
    global signal_count
    global exit_requested

    exit_requested = True
    if signal_count >= NUM_SIGINT_BEFORE_FORCE_EXIT:
        sys.exit(1)
    signal_count += 1


if current_process().name == "MainProcess":
    signal.signal(signal.SIGINT, parent_signal_handler)
else:
    signal.signal(signal.SIGINT, child_signal_handler)

if __name__ == "__main__":
    freeze_support()
    sys.exit(main())
