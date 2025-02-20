#!/usr/bin/env python3
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from multiprocessing import cpu_count, Pipe, Queue, SimpleQueue, Process, Value, freeze_support, current_process, Event, connection
from datetime import datetime, timedelta
import os
import sys
from typing import Optional
import signal
from numba import njit, prange
import numba
import atexit
import asyncio

import numpy as np
import soundfile as sf


from vhsdecode.hifi.utils import DecoderSharedMemory, DecoderState, PostProcessorSharedMemory, NumbaAudioArray, profile

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
    DEFAULT_RESAMPLER_QUALITY,
    DEFAULT_FINAL_AUDIO_RATE,
    REAL_DTYPE
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
    default=DEFAULT_FINAL_AUDIO_RATE,
    help=f"Output sample rate in Hz (default {DEFAULT_FINAL_AUDIO_RATE})",
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
    "--head_switching_interpolation",
    dest="head_switching_interpolation",
    type=str.lower,
    default="on",
    help=f"Enables head switching noise interpolation. (defaults to \"on\")."
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
            #compression_level=0.0
        )


def seconds_to_str(seconds: float) -> str:
    delta = timedelta(seconds=seconds)

    hours, remainder = divmod(delta.total_seconds(), 3600)
    minutes, seconds = divmod(remainder, 60)
    return '{:01}:{:02}:{:06.3f}'.format(int(hours), int(minutes), seconds)


def log_decode(start_time: datetime, frames: int, audio_samples: int, blocks_enqueued: int, input_rate: int, audio_rate: int):
    elapsed_time: timedelta = datetime.now() - start_time

    input_time: float = frames / (2 * input_rate)
    input_time_format: str = seconds_to_str(input_time)

    audio_time: float = audio_samples / audio_rate
    audio_time_format: str = seconds_to_str(audio_time)

    latency_time = max(0, input_time - audio_time)
    latency_format: str = seconds_to_str(latency_time)

    relative_speed: float = input_time / elapsed_time.total_seconds()
    elapsed_time_format: str = seconds_to_str(elapsed_time.total_seconds())

    print(
        f"- Decoding speed: {round(frames / (1e3 * elapsed_time.total_seconds()))} kFrames/s ({relative_speed:.2f}x), {blocks_enqueued} blocks enqueued\n"
        + f"- Input position: {input_time_format}\n"
        + f"- Audio position: {audio_time_format}\n"
        + f"- Latency:        {latency_format}\n"
        + f"- Wall time     : {elapsed_time_format}"
    )


class PostProcessor:
    def __init__(
        self,
        decode_options: dict,
        decoder_out_queue,
        channel_len,
        post_processor_shared_memory_idle_queue,
        decoder_shared_memory_idle_queue,
        out_conn,
    ):
        self.final_audio_rate = decode_options["audio_rate"]
        self.use_noise_reduction = decode_options["noise_reduction"]
        self.spectral_nr_amount = decode_options["spectral_nr_amount"]
        self.nr_side_gain = decode_options["nr_side_gain"]

        # create processes and wire up queues
        #
        #                                 (left channel)
        #                               spectral_noise_reduction_worker --> noise_reduction_worker 
        #                             /                                                            \
        # data in --[block_sorter]----                                                              --> mix_to_stereo_worker --> data out
        #                             \   (right channel)                                          /
        #                               spectral_noise_reduction_worker --> noise_reduction_worker 

        self.decoder_out_queue = decoder_out_queue
        self.mix_to_stereo_worker_output = out_conn
        self.decoder_shared_memory_idle_queue = decoder_shared_memory_idle_queue

        self.post_processor_shared_memory = []
        self.post_processor_shared_memory_idle_queue = post_processor_shared_memory_idle_queue
        self.post_processor_num_shared_memory = 16
        for i in range(self.post_processor_num_shared_memory):
            shared_memory = PostProcessorSharedMemory.get_shared_memory(channel_len, "HiFiDecode Post Processor Shared Memory")
            self.post_processor_shared_memory.append(shared_memory)
            self.post_processor_shared_memory_idle_queue.put(shared_memory.name)
            atexit.register(shared_memory.close)
            atexit.register(shared_memory.unlink)

        nr_worker_l_in_output, nr_worker_l_in_input = Pipe(duplex=False)
        nr_worker_r_in_output, nr_worker_r_in_input = Pipe(duplex=False)
        self.block_sorter_process = Process(target=PostProcessor.block_sorter_worker, name="HiFiDecode SpectralNoiseReduction L", args=(self.decoder_out_queue, self.decoder_shared_memory_idle_queue, self.post_processor_shared_memory_idle_queue, nr_worker_l_in_input, nr_worker_r_in_input))
        self.block_sorter_process.start()
        atexit.register(self.block_sorter_process.terminate)

        spectral_nr_worker_l_output, spectral_nr_worker_l_input = Pipe(duplex=False)
        self.spectral_nr_worker_l = Process(target=PostProcessor.spectral_noise_reduction_worker, name="HiFiDecode SpectralNoiseReduction L", args=(nr_worker_l_in_output, spectral_nr_worker_l_input, self.spectral_nr_amount, self.final_audio_rate))
        self.spectral_nr_worker_l.start()
        atexit.register(self.spectral_nr_worker_l.terminate)

        spectral_nr_worker_r_output, spectral_nr_worker_r_input = Pipe(duplex=False)
        self.spectral_nr_worker_r = Process(target=PostProcessor.spectral_noise_reduction_worker, name="HiFiDecode SpectralNoiseReduction R", args=(nr_worker_r_in_output, spectral_nr_worker_r_input, self.spectral_nr_amount, self.final_audio_rate))
        self.spectral_nr_worker_r.start()
        atexit.register(self.spectral_nr_worker_r.terminate)
        
        nr_worker_l_out_output, nr_worker_l_out_input = Pipe(duplex=False)
        self.nr_worker_l = Process(target=PostProcessor.noise_reduction_worker, name="HiFiDecode NoiseReduction L", args=(spectral_nr_worker_l_output, nr_worker_l_out_input, self.use_noise_reduction, self.nr_side_gain, self.final_audio_rate))
        self.nr_worker_l.start()
        atexit.register(self.nr_worker_l.terminate)

        nr_worker_r_out_output, nr_worker_r_out_input = Pipe(duplex=False)
        self.nr_worker_r = Process(target=PostProcessor.noise_reduction_worker, name="HiFiDecode NoiseReduction R", args=(spectral_nr_worker_r_output, nr_worker_r_out_input, self.use_noise_reduction, self.nr_side_gain, self.final_audio_rate))
        self.nr_worker_r.start()
        atexit.register(self.nr_worker_r.terminate)
        
        self.mix_to_stereo_worker_process = Process(target=PostProcessor.mix_to_stereo_worker, name="HiFiDecode Stereo Merge", args=(nr_worker_l_out_output, nr_worker_r_out_output, self.mix_to_stereo_worker_output, self.final_audio_rate))
        self.mix_to_stereo_worker_process.start()
        atexit.register(self.mix_to_stereo_worker_process.terminate)

    @staticmethod
    def spectral_noise_reduction_worker(
        in_conn,
        out_conn,
        spectral_nr_amount,
        final_audio_rate,
    ):
        spectral_nr = SpectralNoiseReduction(
            nr_reduction_amount=spectral_nr_amount,
            audio_rate=final_audio_rate,
        )

        while True:
            try:
                decoder_state, channel_num = in_conn.recv()
                buffer = PostProcessorSharedMemory(decoder_state)

                if channel_num == 0:
                    pre = buffer.get_pre_left()
                    spectral_nr_out = buffer.get_nr_left()
                else:
                    pre = buffer.get_pre_right()
                    spectral_nr_out = buffer.get_nr_right()

                if spectral_nr_amount > 0: 
                    spectral_nr.spectral_nr(pre, spectral_nr_out)
                else:
                    DecoderSharedMemory.copy_data_float32(pre, spectral_nr_out, decoder_state.post_audio_len)

                buffer.close()
                out_conn.send((decoder_state, channel_num))
            except InterruptedError:
                pass

    @staticmethod
    def noise_reduction_worker(
        in_conn,
        out_conn,
        use_noise_reduction,
        nr_side_gain,
        final_audio_rate,
    ):
        noise_reduction = NoiseReduction(
            nr_side_gain,
            audio_rate=final_audio_rate
        )

        while True:
            try:
                decoder_state, channel_num = in_conn.recv()
                buffer = PostProcessorSharedMemory(decoder_state)

                if channel_num == 0:
                    pre = buffer.get_pre_left()
                    nr_out = buffer.get_nr_left()
                else:
                    pre = buffer.get_pre_right()
                    nr_out = buffer.get_nr_right()

                if use_noise_reduction:
                    noise_reduction.noise_reduction(pre, nr_out)
                else:
                    DecoderSharedMemory.copy_data_float32(pre, nr_out, decoder_state.post_audio_len)

                buffer.close()
                out_conn.send(decoder_state)
            except InterruptedError:
                pass

    @staticmethod
    def mix_to_stereo_worker(nr_l_in_conn, nr_r_in_conn, out_conn, sample_rate):
        while True:
            while True:
                try:
                    l_decoder_state = nr_l_in_conn.recv()
                    break
                except InterruptedError:
                    pass
        
            while True:
                try:
                    r_decoder_state = nr_r_in_conn.recv()
                    break
                except InterruptedError:
                    pass

            assert l_decoder_state.block_num == r_decoder_state.block_num, "Noise reduction processes are out of sync! Channels will be out od sync."

            decoder_state = l_decoder_state
            buffer = PostProcessorSharedMemory(decoder_state)
            l = buffer.get_nr_left()
            r = buffer.get_nr_right()
            stereo = buffer.get_stereo()

            stereo_len = PostProcessor.stereo_interleave(l, r, stereo, decoder_state.post_audio_trimmed, sample_rate, decoder_state.block_num == 0)

            decoder_state.stereo_audio_trimmed = stereo_len
            buffer.close()
            out_conn.send(decoder_state)
            

    @staticmethod
    @njit(numba.types.int32(NumbaAudioArray, NumbaAudioArray, NumbaAudioArray, numba.types.int32, numba.types.int32, numba.types.bool_), cache=True, fastmath=True, nogil=True)
    def stereo_interleave(
        audioL: np.array,
        audioR: np.array,
        stereo: np.array,
        channel_length: int,
        sample_rate: int,
        is_first_block: bool
    ) -> int:
        for i in range(channel_length):
            stereo[(i * 2)] = audioL[i]
            stereo[(i * 2) + 1] = audioR[i]

        # mute the spike that occurs during noise reduction
        if is_first_block:
            trim_samples = int(0.0015 * sample_rate)
            for i in range(trim_samples):
                stereo[(i * 2)] = 0
                stereo[(i * 2) + 1] = 0
            
        stereo_len = channel_length * 2
        return stereo_len

    @staticmethod
    def block_sorter_worker(
        decoder_out_queue,
        decoder_shared_memory_idle_queue,
        post_processor_shared_memory_idle_queue,
        nr_worker_l_in_conn,
        nr_worker_r_in_conn,
    ):
        next_block = 0
        last_block_submitted = -1
        block_queue = []

        done = False
        while not done:
            in_decoder_state = decoder_out_queue.get()
            buffer = DecoderSharedMemory(in_decoder_state)

            in_preL_buffer = buffer.get_pre_left()
            in_preR_buffer = buffer.get_pre_right()

            in_preL = np.empty_like(in_preL_buffer)
            in_preR = np.empty_like(in_preR_buffer)

            DecoderSharedMemory.copy_data_float32(in_preL_buffer, in_preL, len(in_preL))
            DecoderSharedMemory.copy_data_float32(in_preR_buffer, in_preR, len(in_preR))

            buffer.close()

            decoder_shared_memory_idle_queue.put(in_decoder_state.name)

            # blocks are received from the decoder processes out of order
            # gather them into ordered chunk and process sequentially
            assert last_block_submitted < in_decoder_state.block_num, f"Warning, block was repeated, got {in_decoder_state.block_num}, already processed {last_block_submitted}"
            block_queue.append((in_decoder_state, in_preL, in_preR))
        
            if in_decoder_state.block_num == next_block:
                # process queued data in order of block number
                block_queue.sort(key=lambda x: x[0].block_num)
        
                # enqueue the blocks in order
                while len(block_queue) > 0 and (block_queue[0][0].block_num <= next_block):
                    name = post_processor_shared_memory_idle_queue.get()

                    decoder_state, preL, preR = block_queue.pop(0)
                    
                    decoder_state.name = name
                    buffer = PostProcessorSharedMemory(decoder_state)

                    DecoderSharedMemory.copy_data_float32(preL, buffer.get_pre_left(), decoder_state.pre_audio_trimmed)
                    DecoderSharedMemory.copy_data_float32(preR, buffer.get_pre_right(), decoder_state.pre_audio_trimmed)

                    nr_worker_l_in_conn.send((decoder_state, 0))
                    nr_worker_r_in_conn.send((decoder_state, 1))
        
                    next_block += 1
                    last_block_submitted = decoder_state.block_num
                    done = decoder_state.is_last_block

    def close(self):
        self.block_sorter_process.terminate()
        self.nr_worker_l.terminate()
        self.nr_worker_r.terminate()
        self.mix_to_stereo_worker_process.terminate()

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

class SoundDeviceProcess():
    def __init__(self, sample_rate):
        self._sample_rate = sample_rate

    def __enter__(self):
        self._play_parent_conn, self._play_child_conn = Pipe()
        self._thread_executor = ThreadPoolExecutor(1)
        self._process = Process(target=SoundDeviceProcess.play_worker, args=(self._play_child_conn, self._sample_rate))
        self._process.start()
        return self

    def __exit__(self, exception_type, exception_value, exception_traceback):
        self._process.terminate()
        self._thread_executor.shutdown(False)
        return self

    @staticmethod
    @njit(numba.types.void(numba.types.Array(numba.types.float32, 1, "C", readonly=True), numba.types.Array(numba.types.int16, 2, "C")), cache=True, fastmath=True, nogil=True)
    def build_stereo(interleaved: np.array, stacked) -> np.array:
        for i in range(0, len(stacked)):
            stacked[i][0] = interleaved[i*2] * 2**15
            stacked[i][1] = interleaved[i*2+1] * 2**15

    @staticmethod
    def play_worker(conn, sample_rate):
        output_stream = None
        while True:
            try:
                stereo = conn.recv_bytes()
                if output_stream == None:
                    output_stream = sd.OutputStream(
                        samplerate=sample_rate,
                        channels=2,
                        dtype="int16"
                    )
                    output_stream.start()
    
                interleaved_len = int(len(stereo) / np.dtype(REAL_DTYPE).itemsize)
                interleaved = np.ndarray(interleaved_len, dtype=REAL_DTYPE, buffer=stereo)
                stacked = np.empty((int(len(interleaved)/2), 2), dtype=np.int16)

                SoundDeviceProcess.build_stereo(interleaved, stacked)
                output_stream.write(stacked)
            except InterruptedError:
                pass
    
    def play(self, stereo):
        self._thread_executor.submit(self._play_parent_conn.send_bytes, stereo)
    

def write_soundfile_process_worker(
    post_processor_out_output_conn,
    max_shared_memory_size,
    shared_memory_idle_queue,
    post_processor_shared_memory_idle_queue,
    start_time,
    input_position,
    total_samples_decoded,
    decode_options,
    output_file: str,
    decode_done,
):
    audio_rate = decode_options["audio_rate"]
    input_rate = decode_options["input_rate"]
    preview_mode = decode_options["preview"]

    with SoundDeviceProcess(audio_rate) as player:
        with as_outputfile(output_file, audio_rate) as w:
            done = False
            while not done:
                try:
                    decoder_state = post_processor_out_output_conn.recv()
                    buffer = PostProcessorSharedMemory(decoder_state)
                    stereo = buffer.get_stereo()

                    w.buffer_write(stereo, dtype="float32")
                    if preview_mode:
                        if SOUNDDEVICE_AVAILABLE:
                            stereo_copy = np.empty_like(stereo)
                            DecoderSharedMemory.copy_data_float32(stereo, stereo_copy, len(stereo_copy))
                            player.play(stereo_copy)
                        else:
                            print(
                                "Import of sounddevice failed, preview is not available!"
                            )

                    buffer.close()
                    post_processor_shared_memory_idle_queue.put(decoder_state.name)
                    with total_samples_decoded.get_lock():
                        total_samples_decoded.value = int(total_samples_decoded.value + decoder_state.stereo_audio_trimmed / 2)
                    
                    blocks_enqueued = max_shared_memory_size - shared_memory_idle_queue.qsize()
                    log_decode(start_time, input_position.value, total_samples_decoded.value, blocks_enqueued, input_rate, audio_rate)

                    done = decoder_state.is_last_block
                except InterruptedError:
                    pass

            w.flush()
            decode_done.set()

async def decode_parallel(
    decode_options: dict,
    bias_guess,
    threads: int = 8,
    ui_t: Optional[AppWindow] = None,
):
    decoder = HiFiDecode(options=decode_options)
    # TODO: reprocess data read in this step
    if bias_guess:
        LCRef, RCRef = guess_bias(decoder, decode_options["input_file"], int(decode_options["input_rate"]))
        decoder.updateAFE(LCRef, RCRef)
        
    input_file = decode_options["input_file"]
    output_file = decode_options["output_file"]

    block_size = decoder.blockSize
    block_resampled_size = decoder.blockResampledSize
    block_audio_size = decoder.blockAudioSize

    read_overlap = decoder.readOverlap
    input_position = Value('d', 0)
    total_samples_decoded = Value('d', 0)
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
    num_shared_memory_instances = int(threads * 1.5)
    num_decoders = threads

    shared_memory_instances = []
    shared_memory_idle_queue = Queue()
    for i in range(num_shared_memory_instances):
        buffer_instance = DecoderSharedMemory.get_shared_memory(block_size, read_overlap, block_resampled_size, block_audio_size, f"HiFiDecode Shared Memory {i}")
        shared_memory_instances.append(buffer_instance)
        decoder_idx = i % num_decoders
        shared_memory_idle_queue.put(buffer_instance.name)

        atexit.register(buffer_instance.close)
        atexit.register(buffer_instance.unlink)

    # spin up the decoders
    decoder_processes: list[Process] = []
    decoder_in_queue = SimpleQueue()
    decoder_out_queue = SimpleQueue()
    decode_done = Event()

    for i in range(num_decoders):
        decoder_process = Process(target=HiFiDecode.hifi_decode_worker, args=(decoder_in_queue, decoder_out_queue, decode_options, decoder.standard))
        decoder_process.start()

        atexit.register(decoder_process.terminate)
        decoder_processes.append(decoder)

    # set up the post processor
    post_processor_out_output_conn, post_processor_out_input_conn = Pipe(duplex=False)
    post_processor_shared_memory_idle_queue = Queue()
    post_processor = PostProcessor(
        decode_options,
        decoder_out_queue,
        decoder.blockFinalAudioSize,
        post_processor_shared_memory_idle_queue,
        shared_memory_idle_queue,
        post_processor_out_input_conn
    )
    atexit.register(post_processor.close)

    # set up the output file process
    output_file_process = Process(
        target=write_soundfile_process_worker, 
        name="HiFiDecode Soundfile Encoder", 
        args=(
            post_processor_out_output_conn, 
            num_shared_memory_instances, 
            shared_memory_idle_queue,
            post_processor_shared_memory_idle_queue,
            start_time, 
            input_position, 
            total_samples_decoded, 
            decode_options, 
            output_file, 
            decode_done
    ))
    output_file_process.start()
    atexit.register(output_file_process.terminate)

    def handle_ui_events():
        stop_requested = False
        if ui_t is not None:
            ui_t.app.processEvents()
            if ui_t.window.transport_state == 0:
                stop_requested = True
            elif ui_t.window.transport_state == 2:
                while ui_t.window.transport_state == 2:
                    ui_t.app.processEvents()
                    time.sleep(0.01)
        
        return stop_requested
    
    def read_and_send_to_decoder(
        f,
        decoder,
        decoder_state,
        input_position,
        exit_requested,
        previous_overlap
    ):
        buffer = DecoderSharedMemory(decoder_state)
        # read input data into the shared memory buffer
        block_in = buffer.get_block_in()
        frames_read = f.buffer_read_into(block_in, "int16")

        with input_position.get_lock():
            input_position.value += frames_read * 2

        # handle stop and last block
        stop_requested = handle_ui_events()
        is_last_block = frames_read < len(block_in) or exit_requested or stop_requested
        if is_last_block:
            # save the read data
            block_data_read = buffer.get_block_in().copy()
            buffer.close()

            # create a new buffer with the updated offsets, and copy in the read data
            decoder_state = DecoderState(decoder, buffer.name, frames_read, decoder_state.block_num, is_last_block)
            buffer = DecoderSharedMemory(decoder_state)
            new_block_in = buffer.get_block_in()
            DecoderSharedMemory.copy_data_int16(block_data_read, new_block_in, len(new_block_in))

        # copy the overlapping data from the previous read
        block_in_overlap = buffer.get_block_in_start_overlap()
        if block_num == 0:
            # this is the first block, fill in some data since there is no overlap
            DecoderSharedMemory.copy_data_int16(block_in, block_in_overlap, len(block_in_overlap))
        else:
            DecoderSharedMemory.copy_data_int16(previous_overlap, block_in_overlap, len(block_in_overlap))

        # copy the the current overlap to use in the next iteration
        current_overlap = buffer.get_block_in_end_overlap()
        DecoderSharedMemory.copy_data_int16(current_overlap, previous_overlap, len(current_overlap))
        
        buffer.close()

        # submit the block to the decoder
        # blocks should complete roughly in the order that they are submitted
        decoder_in_queue.put(decoder_state)

        return decoder_state, is_last_block
            
    print(f"Starting decode...")

    with as_soundfile(input_file) as f:
        loop = asyncio.get_event_loop()        
        previous_overlap = np.empty(0)
        progressB = TimeProgressBar(f.frames, f.frames)
        block_num = 0

        while True:
            # get the next available shared memory buffer
            buffer_name = await loop.run_in_executor(None, shared_memory_idle_queue.get)
            decoder_state = DecoderState(decoder, buffer_name, decoder.blockSize, block_num, False)

            if (len(previous_overlap) == 0):
                previous_overlap = np.empty(decoder_state.block_overlap, dtype=np.int16)

            decoder_state, is_last_block = await loop.run_in_executor(None, read_and_send_to_decoder, 
                f,
                decoder,
                decoder_state,
                input_position,
                exit_requested,
                previous_overlap
            )

            progressB.print(input_position.value / 2)

            blocks_enqueued = num_shared_memory_instances - shared_memory_idle_queue.qsize()
            log_decode(start_time, input_position.value, total_samples_decoded.value, blocks_enqueued, decode_options["input_rate"], decode_options["audio_rate"])

            if is_last_block:
                 break

            block_num += 1

    print("")
    print("Decode finishing up. Emptying the queue")
    print("")

    decode_done.wait()
    post_processor.close()

    for shared_memory in shared_memory_instances:
        shared_memory.close()
        shared_memory.unlink()
        atexit.unregister(shared_memory.close)
        atexit.unregister(shared_memory.unlink)
    
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

    LCRef, RCRef = decoder.guessBiases(blocks)
    print("done!")
    print(
        "L carrier found at %.02f MHz, R carrier found at %.02f MHz"
        % (LCRef / 1e6, RCRef / 1e6)
    )
    return LCRef, RCRef


def run_decoder(args, decode_options, ui_t: Optional[AppWindow] = None):
    sample_freq = decode_options["input_rate"]

    if sample_freq is not None:
        # set_start_method("spawn")
        with ThreadPoolExecutor(args.threads) as async_executor:
            loop = asyncio.get_event_loop()
            loop.set_default_executor(async_executor)
            loop.run_until_complete(decode_parallel(decode_options, args.BG, threads=args.threads, ui_t=ui_t))
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
        "head_switching_interpolation": args.head_switching_interpolation == "on",
        "noise_reduction": args.noise_reduction == "on",
        "auto_fine_tune": args.auto_fine_tune == "on" if not args.preview else False,
        "nr_side_gain": args.NR_side_gain,
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
            os.write(sys.stdout.fileno(), b"\nCtrl-C was pressed again, stopping immediately...\n")
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

if current_process().name == 'MainProcess':
    signal.signal(signal.SIGINT, parent_signal_handler)
else:
    signal.signal(signal.SIGINT, child_signal_handler)

if __name__ == "__main__":
    freeze_support()
    sys.exit(main())
