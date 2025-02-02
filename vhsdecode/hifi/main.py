#!/usr/bin/env python3
import subprocess
import time
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import cpu_count
from datetime import datetime, timedelta
import os
import sys
from typing import List, Optional
import signal

import numpy as np
import soundfile as sf
from vhsdecode.addons.chromasep import samplerate_resample

from vhsdecode.cmdcommons import (
    common_parser_cli,
    select_sample_freq,
    select_system,
    get_basics,
    test_input_file,
    test_output_file,
)
from vhsdecode.hifi.HiFiDecode import (
    HiFiDecode,
    SpectralNoiseReduction,
    NoiseReduction,
    DEFAULT_NR_ENVELOPE_GAIN,
    DEFAULT_SPECTRAL_NR_AMOUNT,
    DEFAULT_RESAMPLER_QUALITY
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


parser, _ = common_parser_cli(
    "Extracts audio from RAW HiFi FM RF captures",
    default_threads=round(cpu_count() / 2),
)

parser.add_argument(
    "--ar",
    "--audio_rate",
    dest="rate",
    type=int,
    default=48000,
    help="Output sample rate in Hz (default 48000)",
)

parser.add_argument(
    "--bg",
    "--bias_guess",
    dest="BG",
    action="store_true",
    default=False,
    help="Do carrier bias guess",
)

parser.add_argument(
    "--preview",
    dest="preview",
    action="store_true",
    default=False,
    help="Use preview quality (faster and noisier)",
)

parser.add_argument(
    "--original",
    dest="original",
    action="store_true",
    default=False,
    help="Use the same FM demod as vhs-decode",
)

parser.add_argument(
    "--noise_reduction",
    dest="noise_reduction",
    type=str.lower,
    default="on",
    help="Set noise reduction block (deemphasis and expansion) on/off",
)

parser.add_argument(
    "--auto_fine_tune",
    dest="auto_fine_tune",
    type=str.lower,
    default="on",
    help="Set auto tuning of the analog front end on/off",
)

parser.add_argument(
    "--NR_sidechain_gain",
    dest="NR_side_gain",
    type=float,
    default=DEFAULT_NR_ENVELOPE_GAIN,
    help=f"Sets the noise reduction expander sidechain gain (default is {DEFAULT_NR_ENVELOPE_GAIN}). "
    f"Range (20~100): Higher values increase the effect of the expander",
)

parser.add_argument(
    "--NR_spectral_amount",
    dest="spectral_nr_amount",
    type=float,
    default=DEFAULT_SPECTRAL_NR_AMOUNT,
    help=f"Sets the amount of broadband spectral noise reduction to apply. (default is {DEFAULT_SPECTRAL_NR_AMOUNT}). "
    f"Range (0~1): 0 being off, 1 being full spectral noise reduction",
)

parser.add_argument(
    "--resampler_quality",
    dest="resampler_quality",
    type=str,
    default=DEFAULT_RESAMPLER_QUALITY,
    help=f"Sets quality of resampling to use in the audio chain. (default is {DEFAULT_RESAMPLER_QUALITY}). "
    f"Range (low, medium, high): low being faster, and high having best quality",
)

parser.add_argument(
    "--gain",
    dest="gain",
    type=float,
    default=1.0,
    help="Sets the gain/volume of the output audio (default is 1.0)",
)

parser.add_argument(
    "--8mm",
    dest="format_8mm",
    action="store_true",
    default=False,
    help="Use settings for Video8 and Hi8 tape formats.",
)

parser.add_argument(
    "--gnuradio",
    dest="GRC",
    action="store_true",
    default=False,
    help="Opens ZMQ REP pipe to gnuradio at port 5555",
)

parser.add_argument(
    "--gui",
    dest="UI",
    action="store_true",
    default=False,
    help="Opens hifi-decode GUI graphical user interface",
)

parser.add_argument(
    "--audio_mode",
    dest="mode",
    type=str,
    help=(
        "Audio mode (s: stereo, mpx: stereo with mpx, l: left channel, r: right channel, sum: mono sum) - "
        "defaults to s other than on 8mm which defaults to mpx."
        " 8mm mono is not auto detected currently so has to be manually specified as l."
    ),
)

signal_count = 0
exit_requested = False
main_pid = os.getpid()
def signal_handler(sig, frame):
    global signal_count
    global main_pid
    global exit_requested

    exit_requested = True
    is_main_thread = main_pid == os.getpid()
    if signal_count >= 1:
        if is_main_thread: print("Ctrl-C was pressed again, stopping immediately...")
        sys.exit(1)
    if signal_count == 0:
        if is_main_thread: print("Ctrl-C was pressed, stopping decode...")
    signal_count += 1

signal.signal(signal.SIGINT, signal_handler)

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
        print(
            "WARN: ffmpeg not installed (or not in PATH), please install it to speed up file reading"
        )
        return False


class BufferedInputStream(io.RawIOBase):
    def __init__(self, buffer):
        self.buffer = buffer
        self._pos: int = 0

    def read(self, size=-1):
        data = self.buffer.read(size * 2)
        if not data:
            return b""

        self._pos += len(data)
        return data

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


# executes ffmpeg and reads stdout as a file
class FfmpegFileReader(BufferedInputStream):
    def __init__(self, file_path):
        shell_command = ["ffmpeg", "-i", file_path, "-f", "s16le", "pipe:1"]
        p = subprocess.Popen(
            shell_command,
            shell=False,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
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

    def read(
        self,
        samples,
        frames=-1,
        dtype="float64",
        always_2d=False,
        fill_value=None,
        out=None,
    ):
        data = self.file_path.read(samples)
        if not data:
            return b""
        assert len(data) % 2 == 0, "data is misaligned"
        out = np.asarray(np.frombuffer(data, dtype=np.int16), dtype=dtype)
        return out

    def _read_next_chunk(self, blocksize, overlap, dtype) -> np.array:
        data = self.file_path.read(blocksize - overlap)
        assert len(data) % 2 == 0, "data is misaligned"
        out = np.asarray(np.frombuffer(data, dtype=np.int16), dtype=dtype)
        self._overlap = (
            np.copy(out[-overlap:]) if np.size(self._overlap) == 0 else self._overlap
        )
        result = np.concatenate((self._overlap, out))
        self._overlap = np.copy(out[-overlap:])
        return result

    # yields infinite generator for _read_next_chunk
    def blocks(
        self,
        blocksize=None,
        overlap=0,
        frames=-1,
        dtype="float64",
        always_2d=False,
        fill_value=None,
        out=None,
    ):
        while True:
            yield self._read_next_chunk(blocksize, overlap, dtype)


class UnSigned16BitFileReader(io.RawIOBase):
    def __init__(self, file_path):
        self.file_path = file_path
        self.file = open(file_path, "rb")

    def read(self, size=-1):
        data = self.file.read(size)
        if not data:
            return b""

        # Converts unsigned 16-bit to signed 16-bit
        samples = np.frombuffer(data, dtype=np.uint16)
        signed_samples = samples.astype(np.int16) - 32768

        return signed_samples.tobytes()

    def readable(self):
        return True

    def close(self):
        self.file.close()


# This part is what opens the file
# The samplerate here could be anything
def as_soundfile(pathR, sample_rate=48000):
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
        return sf.SoundFile(
            UnSigned16BitFileReader(pathR),
            "r",
            channels=1,
            samplerate=int(sample_rate),
            format="RAW",
            subtype="PCM_16",
            endian="LITTLE",
        )
    elif "flac" == extension or "ldf" == extension or "hifi" == extension:
        return sf.SoundFile(
            pathR,
            "r",
        )
    elif "-" == path:
        return UnseekableSoundFile(
            BufferedInputStream(sys.stdin.buffer),
            "r",
            channels=1,
            samplerate=int(sample_rate),
            format="RAW",
            subtype="PCM_16",
            endian="LITTLE",
        )
    else:
        if test_if_ffmpeg_is_installed():
            return UnseekableSoundFile(
                FfmpegFileReader(pathR),
                "r",
                channels=1,
                samplerate=int(sample_rate),
                format="RAW",
                subtype="PCM_16",
                endian="LITTLE",
            )
        return sf.SoundFile(pathR, "r")


def as_outputfile(path, sample_rate):
    if ".wav" in path.lower():
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
        )


def seconds_to_str(seconds: float) -> str:
    return str(timedelta(seconds=seconds))


def log_decode(start_time: datetime, frames: int, decode_options: dict):
    elapsed_time: timedelta = datetime.now() - start_time
    audio_time: float = frames / (2 * decode_options["input_rate"])
    relative_speed: float = audio_time / elapsed_time.total_seconds()
    elapsed_time_format: str = seconds_to_str(elapsed_time.total_seconds())
    audio_time_format: str = seconds_to_str(audio_time)

    print(
        f"- Decoding speed: {round(frames / (1e3 * elapsed_time.total_seconds()))} kFrames/s ({relative_speed:.2f}x)\n"
        + f"- Audio position: {str(audio_time_format)[:-3]}\n"
        + f"- Wall time     : {str(elapsed_time_format)[:-3]}"
    )


class PostProcessor:
    def __init__(
        self,
        executor: ProcessPoolExecutor,
        decode_options: dict,
        decoder: HiFiDecode,
    ):
        self.executor_queue = list()
        self.executor = executor

        self.spectral_nr_l = SpectralNoiseReduction(
            audio_rate=decode_options["audio_rate"],
            nr_reduction_amount=decode_options["spectral_nr_amount"]
        )
        self.spectral_nr_r = SpectralNoiseReduction(
            audio_rate=decode_options["audio_rate"],
            nr_reduction_amount=decode_options["spectral_nr_amount"]
        )

        self.noise_reduction_l = NoiseReduction(
            decoder.notchFreq,
            decode_options["nr_side_gain"],
            audio_rate=decode_options["audio_rate"]
        )
        self.noise_reduction_r = NoiseReduction(
            decoder.notchFreq,
            decode_options["nr_side_gain"],
            audio_rate=decode_options["audio_rate"]
        )

        if decode_options["resampler_quality"] == "high":
            self.resampler_converter_type = "sinc_best"
        elif decode_options["resampler_quality"] == "medium":
            self.resampler_converter_type = "sinc_medium"
        else: # low
            self.resampler_converter_type = "sinc_fastest"

        common_params = {
            "resample_audio_rate": decode_options["audio_rate"],
            "decoder_audio_rate": decoder.audioRate,
            "resampler_converter_type": self.resampler_converter_type,
            "gain": decode_options["gain"],
            "use_noise_reduction": decode_options["noise_reduction"],
            "decoder_audio_block_size": decoder.blockAudioSize,
            "decoder_audio_discard_size": decoder.audioDiscard,
            "decode_mode": decode_options["mode"],
            "spectral_nr_amount": decode_options["spectral_nr_amount"]
        }

        self.l_params = common_params.copy()
        self.l_params["noise_reduction"] = self.noise_reduction_l
        self.l_params["spectral_nr"] = self.spectral_nr_l

        self.r_params = common_params.copy()
        self.r_params["noise_reduction"] = self.noise_reduction_r
        self.r_params["spectral_nr"] = self.spectral_nr_r

    @staticmethod
    def mix_for_mode_stereo(
        l_raw: np.array,
        r_raw: np.array,
        params
    ) -> tuple[np.array, np.array]:
        if params["decode_mode"] == "mpx":
            l = np.multiply(np.add(l_raw, r_raw), 0.5)
            r = np.multiply(np.subtract(l_raw, r_raw), 0.5)
        elif params["decode_mode"] == "l":
            l = l_raw
            r = l_raw
        elif params["decode_mode"] == "r":
            l = r_raw
            r = r_raw
        elif params["decode_mode"] == "sum":
            l = np.multiply(np.add(l_raw, r_raw), 0.5)
            r = np.multiply(np.add(l_raw, r_raw), 0.5)
        else:
            l = l_raw
            r = r_raw
    
        return l, r
        
    @staticmethod
    def adjust_gain(
        audio: np.array,
        params: dict
    ) -> tuple[np.array, np.array]:
        if params["gain"] != 1:
            return np.multiply(audio, params["gain"])
        else:
            return audio
    
    @staticmethod
    def resample_to_audio_rate(
        audio: np.array,
        params: dict
    ) -> tuple[np.array, np.array]:
        if params["resample_audio_rate"] != params["decoder_audio_rate"]: 
            return samplerate_resample(audio, params["resample_audio_rate"], params["decoder_audio_rate"], params["resampler_converter_type"])
        else:
            return audio

    @staticmethod
    def apply_spectral_noise_reduction(
        audio: np.array,
        params: dict,
    ) -> tuple[np.array, np.array]:
        if params["spectral_nr_amount"] > 0:
            return params["spectral_nr"].spectral_nr(audio)
        else:
            return audio

    @staticmethod
    def apply_noise_reduction(
        pre: np.array,
        de_noise: np.array,
        params: dict,
    ) -> tuple[np.array, np.array]:
        if params["use_noise_reduction"]:
            return params["noise_reduction"].noise_reduction(pre, de_noise)
        else:
            return de_noise

    @staticmethod
    def discard_overlap(
        audio: np.array,
        is_last_block: bool,
        params: dict
    ) -> np.array:
        # discard overlapped audio, and account for samples lost during sinc resampling
        sample_rate_ratio = params["resample_audio_rate"] / params["decoder_audio_rate"]
        audio_block_size = params["decoder_audio_block_size"] * sample_rate_ratio
    
        total_overlap = round(len(audio) - audio_block_size + params["decoder_audio_discard_size"])
        overlap_start = total_overlap - round(total_overlap / 20)
        overlap_end = overlap_start - total_overlap + len(audio)
        
        if is_last_block:
            # don't trim the end when at the last block
            overlap_end = len(audio)

        return audio[overlap_start:overlap_end]

    @staticmethod
    def merge_to_stereo(audioL: np.array, audioR: np.array) -> np.array:
        return list(
            map(
                list,
                zip(
                    audioL,
                    audioR
                ),
            )
        )

    @staticmethod
    def work(
        audio: np.array,
        params: dict,
    ) -> tuple[np.array, np.array]:
        audio = PostProcessor.resample_to_audio_rate(audio, params)
        audio = PostProcessor.adjust_gain(audio, params)
        spectral_nr = PostProcessor.apply_spectral_noise_reduction(audio, params)

        return audio, spectral_nr
    
    def apply_expander_mix_to_stereo(
        self,
        l_pre: np.array,
        l_de_noise: np.array,
        r_pre: np.array,
        r_de_noise: np.array,
        is_last_block: bool
    ) -> np.array:
        l = PostProcessor.apply_noise_reduction(l_pre, l_de_noise, self.l_params)
        r = PostProcessor.apply_noise_reduction(r_pre, r_de_noise, self.r_params)
        l = PostProcessor.discard_overlap(l, is_last_block, self.l_params)
        r = PostProcessor.discard_overlap(r, is_last_block, self.r_params)

        return PostProcessor.merge_to_stereo(l, r)

    def _pop_from_executor(self):
        l_future, r_future = self.executor_queue.pop(0)
        l_pre, l_de_noise = l_future.result()
        r_pre, r_de_noise = r_future.result()

        return l_pre, l_de_noise, r_pre, r_de_noise

    def submit(
        self,
        l: np.array,
        r: np.array,
    ): 
        l, r = PostProcessor.mix_for_mode_stereo(l, r, self.l_params)

        self.executor_queue.append((
            self.executor.submit(PostProcessor.work, l, self.l_params),
            self.executor.submit(PostProcessor.work, r, self.r_params),
        ))
           
    def read(self):
        while len(self.executor_queue) > 0:
            if self.executor_queue[0][0].done() and self.executor_queue[0][1].done():
                l_pre, l_de_noise, r_pre, r_de_noise = self._pop_from_executor()

                yield self.apply_expander_mix_to_stereo(
                    l_pre, l_de_noise,
                    r_pre, r_de_noise,
                    False
                )
            else:
                break     

    def flush(self):
        while len(self.executor_queue) > 0:
            l_pre, l_de_noise, r_pre, r_de_noise = self._pop_from_executor()

            yield self.apply_expander_mix_to_stereo(
                l_pre, l_de_noise,
                r_pre, r_de_noise,
                len(self.executor_queue) == 0
            )

class AppWindow:
    def __init__(self, argv, decode_options):
        self._app, self._window = self.open_ui(argv, decode_options)

    def __del__(self):
        self._window.close()
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


def decode(decoder, decode_options, ui_t: Optional[AppWindow] = None):
    input_file = decode_options["input_file"]
    output_file = decode_options["output_file"]
    start_time = datetime.now()
    stereo_play_buffer = list()

    with ProcessPoolExecutor(1) as executor:
        post_processor = PostProcessor(
            executor,
            decode_options,
            decoder
        )
        with as_outputfile(output_file, decode_options["audio_rate"]) as w:
            with as_soundfile(input_file) as f:
                progressB = TimeProgressBar(f.frames, f.frames)
                current_block = 0
                try:
                    print(f"Starting decode...")
                    for block in f.blocks(
                        blocksize=decoder.blockSize, overlap=decoder.readOverlap
                    ):
                        if exit_requested:
                            break

                        progressB.print(f.tell())
        
                        current_block, l, r = decoder.block_decode(
                            block, block_count=current_block
                        )
        
                        if decode_options["auto_fine_tune"]:
                            log_bias(decoder)
        
                        post_processor.submit(l, r, current_block)

                        current_block += 1
                        for stereo in post_processor.read():
                            log_decode(start_time, f.tell(), decode_options)
                            try:
                                w.write(stereo)
                                if decode_options["preview"]:
                                    if SOUNDDEVICE_AVAILABLE:
                                        if (
                                            len(stereo_play_buffer)
                                            > decode_options["audio_rate"] * 5
                                        ):
                                            sd.wait()
                                            sd.play(
                                                stereo_play_buffer,
                                                decode_options["audio_rate"],
                                                blocking=False,
                                            )
                                            stereo_play_buffer = list()
                                        stereo_play_buffer += stereo
                                    else:
                                        print(
                                            "Import of sounddevice failed, preview is not available!"
                                        )
                            except ValueError:
                                pass
                            if ui_t is not None:
                                ui_t.app.processEvents()
                                if ui_t.window.transport_state == 0:
                                    break
                                elif ui_t.window.transport_state == 2:
                                    while ui_t.window.transport_state == 2:
                                        ui_t.app.processEvents()
                                        time.sleep(0.01)
                except KeyboardInterrupt:
                    pass
    
                print("Emptying the decode queue ...")
                for stereo in post_processor.flush():
                    try:
                        w.write(stereo)
                    except ValueError:
                        pass
    
            elapsed_time = datetime.now() - start_time
            dt_string = elapsed_time.total_seconds()
            print(f"\nDecode finished, seconds elapsed: {round(dt_string)}")

def decode_parallel(
    decoders: List[HiFiDecode],
    decode_options: dict,
    threads: int = 8,
    ui_t: Optional[AppWindow] = None,
):
    input_file = decode_options["input_file"]
    output_file = decode_options["output_file"]
    start_time = datetime.now()
    block_size = decoders[0].blockSize
    read_overlap = decoders[0].readOverlap
    futures_queue = list()
    current_block = 0
    stereo_play_buffer = list()

    with ProcessPoolExecutor(threads) as executor:
        post_processor = PostProcessor(
            executor,
            decode_options,
            decoders[0]
        )
        with as_outputfile(output_file, decode_options["audio_rate"]) as w:
            with as_soundfile(input_file) as f:
                progressB = TimeProgressBar(f.frames, f.frames)
                try:
                    print(f"Starting decode...")
                    for block in f.blocks(blocksize=block_size, overlap=read_overlap):
                        if exit_requested:
                            break
                        
                        decoder = decoders[current_block % threads]
                        if len(block) > 0:
                            futures_queue.append(
                                executor.submit(HiFiDecode.block_decode_worker, decoder, block, current_block)
                            )
                        else:
                            break
        
                        if decode_options["auto_fine_tune"]:
                            log_bias(decoder)
        
                        current_block += 1
                        progressB.print(f.tell())
        
                        while len(futures_queue) > threads:
                            future = futures_queue.pop(0)
                            blocknum, l, r = future.result()
        
                            post_processor.submit(l, r)
                            for stereo in post_processor.read():
                                log_decode(start_time, f.tell(), decode_options)
        
                                try:
                                    w.write(stereo)
                                    if decode_options["preview"]:
                                        if SOUNDDEVICE_AVAILABLE:
                                            if (
                                                len(stereo_play_buffer)
                                                > decode_options["audio_rate"] * 5
                                            ):
                                                sd.wait()
                                                sd.play(
                                                    stereo_play_buffer,
                                                    decode_options["audio_rate"],
                                                    blocking=False,
                                                )
                                                stereo_play_buffer = list()
                                            stereo_play_buffer += stereo
                                        else:
                                            print(
                                                "Import of sounddevice failed, preview is not available!"
                                            )
                                except ValueError:
                                    pass
        
                        if ui_t is not None:
                            ui_t.app.processEvents()
                            if ui_t.window.transport_state == 0:
                                break
                            elif ui_t.window.transport_state == 2:
                                while ui_t.window.transport_state == 2:
                                    ui_t.app.processEvents()
                                    time.sleep(0.01)
                except KeyboardInterrupt:
                    pass
    
                print("Emptying the decode queue ...")
                while len(futures_queue) > 0:
                    future = futures_queue.pop(0)
                    blocknum, l, r = future.result()
                    post_processor.submit(l, r)
    
                for stereo in post_processor.flush():
                    try:
                        w.write(stereo)
                    except ValueError:
                        pass
    
            elapsed_time = datetime.now() - start_time
            dt_string = elapsed_time.total_seconds()
            print(f"\nDecode finished, seconds elapsed: {round(dt_string)}")


def guess_bias(decoder, input_file, block_size, blocks_limits=10):
    print("Measuring carrier bias ... ")
    blocks = list()

    with as_soundfile(input_file) as f:
        while f.tell() < f.frames and len(blocks) <= blocks_limits:
            blocks.append(f.read(block_size))

    LCRef, RCRef = decoder.guessBiases(blocks)
    print("done!")
    print(
        "L carrier found at %.02f MHz, R carrier found at %.02f MHz"
        % (LCRef / 1e6, RCRef / 1e6)
    )
    return LCRef, RCRef


def log_bias(decoder: HiFiDecode):
    devL = (decoder.standard.LCarrierRef - decoder.afe_params.LCarrierRef) / 1e3
    devR = (decoder.standard.RCarrierRef - decoder.afe_params.RCarrierRef) / 1e3
    print("Bias L %.02f kHz, R %.02f kHz" % (devL, devR), end=" ")
    if abs(devL) < 9 and abs(devR) < 9:
        print("(good player/recorder calibration)")
    elif 9 <= abs(devL) < 10 or 9 <= abs(devR) < 10:
        print("(maybe marginal player/recorder calibration)")
    else:
        print(
            "\nWARN: the player or the recorder may be uncalibrated and/or\n"
            "the standard and/or the sample rate specified are wrong"
        )


def run_decoder(args, decode_options, ui_t: Optional[AppWindow] = None):
    sample_freq = decode_options["input_rate"]
    filename = decode_options["input_file"]

    if sample_freq is not None:
        decoder = HiFiDecode(decode_options)
        LCRef, RCRef = decoder.standard.LCarrierRef, decoder.standard.RCarrierRef
        if args.BG:
            LCRef, RCRef = guess_bias(decoder, filename, int(decoder.sample_rate))
            decoder.updateAFE(LCRef, RCRef)

        if args.threads > 1 and not args.GRC:
            decoders = list()
            for i in range(0, args.threads):
                decoders.append(HiFiDecode(decode_options))
                decoders[i].updateAFE(LCRef, RCRef)
            decode_parallel(decoders, decode_options, threads=args.threads, ui_t=ui_t)
        else:
            decode(decoder, decode_options, ui_t=ui_t)
        print("Decode finished successfully")
        return 0
    else:
        print("No sample rate specified")
        return 0


def main() -> int:
    args = parser.parse_args()

    system = select_system(args)
    sample_freq = select_sample_freq(args)

    filename, outname, _, _ = get_basics(args)
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
        args.resampler_quality == "low" or 
        args.resampler_quality == "medium" or 
        args.resampler_quality == "high"
    ):
        resampler_quality = args.resampler_quality
    else:
        resampler_quality = DEFAULT_RESAMPLER_QUALITY

    decode_options = {
        "input_rate": sample_freq * 1e6,
        "standard": "p" if system == "PAL" else "n",
        "format": "vhs" if not args.format_8mm else "8mm",
        "preview": args.preview,
        "preview_available": SOUNDDEVICE_AVAILABLE,
        "original": args.original,
        "resampler_quality": resampler_quality if not args.preview else "low",
        "spectral_nr_amount": args.spectral_nr_amount if not args.preview else 0,
        "noise_reduction": args.noise_reduction == "on",
        "auto_fine_tune": args.auto_fine_tune == "on" if not args.preview else False,
        "nr_side_gain": args.NR_side_gain,
        "grc": args.GRC,
        "audio_rate": args.rate,
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
                if ui_t.window.transport_state == 1:
                    print("Starting decode...")
                    options = ui_parameters_to_decode_options(ui_t.window.getValues())

                    print("options", options)

                    # change to output file directory
                    if os.path.dirname(options["output_file"]) != "":
                        os.chdir(os.path.dirname(options["output_file"]))

                    # test input and output files
                    if test_input_file(options["input_file"]) and test_output_file(
                        options["output_file"]
                    ):
                        decoder_state = run_decoder(args, options, ui_t=ui_t)
                        ui_t.window.transport_state = 0
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
            ui_t.window.transport_state = 0
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
                    print(f"PAL Hi8 format selected, Audio mode is {real_mode}")
                else:
                    print(f"NTSC Hi8 format selected, Audio mode is {real_mode}")

            return run_decoder(args, decode_options)
        else:
            parser.print_help()
            print(
                "ERROR: input file not found"
                if not test_input_file(filename)
                else f"ERROR: output file '{outname}' cannot be created nor overwritten"
            )
            return 1


if __name__ == "__main__":
    sys.exit(main())
