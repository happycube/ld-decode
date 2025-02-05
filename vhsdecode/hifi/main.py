#!/usr/bin/env python3
import subprocess
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from multiprocessing import cpu_count, Pipe, Queue, Process, Manager
from datetime import datetime, timedelta
import os
import sys
from typing import List, Optional
import signal
from numba import njit, prange

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
    DEFAULT_RESAMPLER_QUALITY,
    DEFAULT_FINAL_AUDIO_RATE
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
        if is_main_thread:
            # prevent reentrant calls https://stackoverflow.com/a/75368797
            os.write(sys.stdout.fileno(), b"\nCtrl-C was pressed again, stopping immediately...\n")
        sys.exit(1)
    if signal_count == 0:
        if is_main_thread:
            os.write(sys.stdout.fileno(), b"\nCtrl-C was pressed, stopping decode...\n")
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
    
    @staticmethod
    @njit(cache=True, fastmath=True, nogil=True)
    def _handle_overlap(
        data,
        overlap_data: np.array,
        overlap_size: int,
        out_dtype: np.number
    ) -> tuple[np.array,np.array]:
        out_int16 = np.frombuffer(data, dtype=np.int16)
        
        #out = np.asarray(out_int16, dtype=out_dtype)
        #new_overlap = out[-overlap_size:]
        #new_overlap = new_overlap.astype(np.int16)
        #
        #if np.size(overlap_data) == 0:
        #    overlap_data = new_overlap
        #
        #return (np.concatenate((overlap_data, out)), new_overlap)

        # offset array copying logic implemented without numpy seems a bit faster
        out_int16_len = np.size(out_int16)
        overlap_size = min(overlap_size, out_int16_len)
        new_overlap = np.empty(overlap_size, dtype=np.int16)
        result = np.empty(overlap_size + out_int16_len, dtype=np.float64)
        
        # copy the overlapping data into result
        overlap_offset = out_int16_len - overlap_size
        if np.size(overlap_data) == 0:
            for i in range(overlap_size):
                overlap_value = out_int16[i + overlap_offset]
                
                new_overlap[i] = overlap_value
                result[i] = overlap_value
        else:
            for i in range(overlap_size):
                new_overlap[i] = out_int16[i + overlap_offset]
                result[i] = overlap_data[i]

        # copy the remaining data
        for i in range(out_int16_len):
            result[i+overlap_size] = out_int16[i]

        return result, new_overlap

    def _read_next_chunk(self, blocksize, overlap, dtype) -> np.array:
        data = self.file_path.read(blocksize - overlap)
        assert len(data) % 2 == 0, "data is misaligned"

        result, self._overlap = UnseekableSoundFile._handle_overlap(data, self._overlap, overlap, dtype)
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
        current_block = self._read_next_chunk(blocksize, overlap, np.dtype(dtype))
        while True:
            next_block = self._read_next_chunk(blocksize, overlap, np.dtype(dtype))
            is_last_block = len(next_block) == 0

            yield (current_block, is_last_block)

            current_block = next_block


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
        )


def seconds_to_str(seconds: float) -> str:
    return str(timedelta(seconds=seconds))


def log_decode(start_time: datetime, frames: int, audio_samples: int, decode_options: dict):
    elapsed_time: timedelta = datetime.now() - start_time

    input_time: float = frames / (2 * decode_options["input_rate"])
    input_time_format: str = seconds_to_str(input_time)

    audio_time: float = audio_samples / decode_options["audio_rate"]
    audio_time_format: str = seconds_to_str(audio_time)

    relative_speed: float = input_time / elapsed_time.total_seconds()
    elapsed_time_format: str = seconds_to_str(elapsed_time.total_seconds())

    print(
        f"- Decoding speed: {round(frames / (1e3 * elapsed_time.total_seconds()))} kFrames/s ({relative_speed:.2f}x)\n"
        + f"- Input position: {str(input_time_format)[:-3]}\n"
        + f"- Audio position: {str(audio_time_format)[:-3]}\n"
        + f"- Wall time     : {str(elapsed_time_format)[:-3]}"
    )


class PostProcessor:
    def __init__(
        self,
        decode_options: dict,
        max_queued_messages,
        decoder: HiFiDecode,
    ):
        self.submit_thread_executor_queue = list()
        self.submit_thread_executor = ThreadPoolExecutor(1) # must only be one thread to enforce sequential processing
        self.next_block = 0
        self.block_queue = []
        self.max_queued_messages = max_queued_messages

        self.final_audio_rate = decode_options["audio_rate"]
        self.decoder_audio_rate = decoder.audioRate
        self.decoder_audio_block_size = decoder.blockAudioSize
        self.use_noise_reduction = decode_options["noise_reduction"]
        self.decoder_audio_discard_size = decoder.audioDiscard
        self.spectral_nr_amount = decode_options["spectral_nr_amount"]
        self.nr_side_gain = decode_options["nr_side_gain"]
        
        manager = Manager()
        self.nr_worker_l_in = manager.Queue()
        self.nr_worker_l_out = manager.Queue()
        self.nr_worker_l = Process(target=PostProcessor.noise_reduction_worker, name="HiFiDecode NoiseReduction L", args=(self.nr_worker_l_in, self.nr_worker_l_out, self.spectral_nr_amount, self.use_noise_reduction, self.nr_side_gain, self.final_audio_rate))
        self.nr_worker_l.start()

        self.nr_worker_r_in = manager.Queue()
        self.nr_worker_r_out = manager.Queue()
        self.nr_worker_r = Process(target=PostProcessor.noise_reduction_worker, name="HiFiDecode NoiseReduction R", args=(self.nr_worker_r_in, self.nr_worker_r_out, self.spectral_nr_amount, self.use_noise_reduction, self.nr_side_gain, self.final_audio_rate))
        self.nr_worker_r.start()

        self.discard_merge_worker_in = manager.Queue()
        self.discard_merge_worker_out_parent, discard_merge_worker_out_child = Pipe()
        self.discard_merge_worker_process = Process(target=PostProcessor.discard_merge_worker, name="HiFiDecode Stereo Merge", args=(self.discard_merge_worker_in, discard_merge_worker_out_child, self.final_audio_rate, self.decoder_audio_rate, self.decoder_audio_block_size, self.decoder_audio_discard_size))
        self.discard_merge_worker_process.start()

    @staticmethod
    def noise_reduction_worker(
        in_queue,
        out_queue,
        spectral_nr_amount,
        use_noise_reduction,
        nr_side_gain,
        final_audio_rate,
    ):
        spectral_nr = SpectralNoiseReduction(
            audio_rate=final_audio_rate,
            nr_reduction_amount=spectral_nr_amount
        )
        noise_reduction = NoiseReduction(
            nr_side_gain,
            audio_rate=final_audio_rate
        )

        while True:
            blocknum, pre = in_queue.get()

            audio = (
                spectral_nr.spectral_nr(pre)
                if spectral_nr_amount > 0 else
                pre
            )

            if use_noise_reduction:
                audio = noise_reduction.noise_reduction(pre, audio)

            out_queue.put_nowait((blocknum, audio))

    @staticmethod
    def discard_merge_worker(in_queue, out_conn, audio_rate, decoder_audio_rate, decoder_audio_block_size, decoder_audio_discard_size):
        with ThreadPoolExecutor(1) as executor:
            while True:
                l, r, is_last_block = in_queue.get()

                overlap_start, overlap_end = PostProcessor.get_overlap(len(l), is_last_block, audio_rate, decoder_audio_rate, decoder_audio_block_size, decoder_audio_discard_size)
                stereo = PostProcessor.stereo_interleave(l, r, overlap_start, overlap_end)

                executor.submit(out_conn.send_bytes, stereo)

    @staticmethod
    @njit(cache=True, fastmath=True, nogil=True)
    def get_overlap(
        audio_len: int,
        is_last_block: bool,
        audio_rate: int,
        decoder_audio_rate: int,
        decoder_audio_block_size: int,
        decoder_audio_discard_size: int
    ) -> tuple[int, int]:
        # discard overlapped audio, and account for samples lost during sinc resampling
        sample_rate_ratio = audio_rate / decoder_audio_rate
        audio_block_size = decoder_audio_block_size * sample_rate_ratio
    
        total_overlap = round(audio_len - audio_block_size + decoder_audio_discard_size)
        overlap_start = total_overlap - round(total_overlap / 20)
        overlap_end = overlap_start - total_overlap + audio_len
        
        if is_last_block:
            # don't trim the end when at the last block
            overlap_end = audio_len

        return overlap_start, overlap_end

    @staticmethod
    @njit(cache=True, fastmath=True, nogil=True, parallel=True)
    def stereo_interleave(
        audioL: np.array,
        audioR: np.array,
        overlap_start: int,
        overlap_end: int
    ) -> bytes:
        audio_len = (overlap_end - overlap_start)
        stereo = np.empty(audio_len*2, dtype=np.float32)

        for i in prange(int(audio_len)):
            stereo[(i * 2)] = audioL[i + overlap_start]
            stereo[(i * 2) + 1] = audioR[i + overlap_start]
            
        return stereo
    
    def process_audio_worker(
        self,
        block_num_in: int,
        l_in: np.array,
        r_in: np.array,
        is_last_block: bool
    ) -> np.array:
        # needs to happen sequentially and in a thread since the noise reduction classes are stateful
        self.nr_worker_l_in.put_nowait((block_num_in, l_in))
        self.nr_worker_r_in.put_nowait((block_num_in, r_in))

        l_block_num, l = self.nr_worker_l_out.get()
        r_block_num, r = self.nr_worker_r_out.get()
        assert l_block_num == r_block_num, "Noise reduction processes are out of sync!"

        self.discard_merge_worker_in.put_nowait((l, r, is_last_block))
        stereo = self.discard_merge_worker_out_parent.recv_bytes()

        return stereo
    
    def submit(
        self,
        block_num_in: int,
        l_in: np.array,
        r_in: np.array,
        is_last_block: bool
    ):
        self.block_queue.append((block_num_in, l_in, r_in))

        # process noise reduction in order
        if block_num_in == self.next_block:
            # process queued data in order of block number
            self.block_queue.sort(key=lambda x: x[0])

            # enqueue the blocks in order
            while len(self.block_queue) > 0 and self.block_queue[0][0] <= self.next_block:
                (block_num, l, r) = self.block_queue.pop(0)

                future = self.submit_thread_executor.submit(self.process_audio_worker, block_num, l, r, is_last_block)
                self.submit_thread_executor_queue.append(future)
                self.next_block += 1

    def read(self):
        while len(self.submit_thread_executor_queue) >= self.max_queued_messages or (len(self.submit_thread_executor_queue) > 0 and self.submit_thread_executor_queue[0].done()):
            stereo_future = self.submit_thread_executor_queue.pop(0)
            yield stereo_future.result()

    def flush(self):
        while len(self.submit_thread_executor_queue) > 0:
            stereo_future = self.submit_thread_executor_queue.pop(0)
            yield stereo_future.result()

        self.nr_worker_l.terminate()
        self.nr_worker_r.terminate()
        self.discard_merge_worker_process.terminate()

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
    start_time =  datetime.now()
    stereo_play_buffer = list()
    total_samples_decoded = 0

    post_processor = PostProcessor(
        decode_options,
        1,
        decoder
    )
    with as_outputfile(output_file, decode_options["audio_rate"]) as w:
        with as_soundfile(input_file) as f:
            progressB = TimeProgressBar(f.frames, f.frames)
            current_block = 0
            try:
                print(f"Starting decode...")
                for block, is_last_block in f.blocks(
                    blocksize=decoder.blockSize, overlap=decoder.readOverlap
                ):
                    if exit_requested:
                        break

                    progressB.print(f.tell())
    
                    l, r = decoder.block_decode(block)
    
                    if decode_options["auto_fine_tune"]:
                        log_bias(decoder)
    
                    post_processor.submit(current_block, l, r, is_last_block)

                    current_block += 1
                    for stereo in post_processor.read():
                        try:
                            w.buffer_write(stereo, dtype='float32')

                            total_samples_decoded += len(stereo) / 8
                            log_decode(start_time, f.tell(), total_samples_decoded, decode_options)

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

                    if is_last_block:
                        break
            except KeyboardInterrupt:
                pass
                print("Emptying the decode queue ...")
            for stereo in post_processor.flush():
                try:
                    w.buffer_write(stereo, dtype='float32')

                    total_samples_decoded += len(stereo) / 8
                    log_decode(start_time, f.tell(), total_samples_decoded, decode_options)
                except ValueError:
                    pass
            elapsed_time = datetime.now() - start_time
        dt_string = elapsed_time.total_seconds()
        print(f"\nDecode finished, seconds elapsed: {round(dt_string)}")


def decoder_process_worker(in_queue, out_queue, decoder_id, decoder, auto_fine_tune):
    while True:
        data = in_queue.get()
        if isinstance(data, int):
            out_queue.put_nowait(decoder_id)
            break

        block_num, block = data

        l, r = decoder.block_decode(np.asarray(block))
        if auto_fine_tune:
            log_bias(decoder)

        out_queue.put_nowait((block_num, l, r))

def write_soundfile_process_worker(conn, output_file, audio_rate):
    with ThreadPoolExecutor(1) as write_executor:
        with as_outputfile(output_file, audio_rate) as w:
            while True:
                stereo = conn.recv_bytes()
                if len(stereo) == 0:
                    write_executor.submit(w.flush)
                    write_executor.shutdown(wait=True)
                    break

                write_executor.submit(w.buffer_write, stereo, dtype='float32')

def decode_parallel(
    decoders: List[HiFiDecode],
    decode_options: dict,
    threads: int = 8,
    ui_t: Optional[AppWindow] = None,
):
    input_file = decode_options["input_file"]
    output_file = decode_options["output_file"]
    start_time =  datetime.now()
    block_size = decoders[0].blockSize
    read_overlap = decoders[0].readOverlap
    current_block = 0
    stereo_play_buffer = list()
    total_samples_decoded = 0

    # spin up the decoders
    decoder_processes = []
    decoder_in_queue = Queue()
    decoder_out_queue = Queue()

    for i in range(len(decoders)):
        decoder = decoders[i]
        decoder_process = Process(target=decoder_process_worker, name=f"HiFiDecode Decoder Thread {i}", args=(decoder_in_queue, decoder_out_queue, i, decoder, decode_options["auto_fine_tune"]))
        decoder_process.start()
        decoder_processes.append(decoder_process)

    output_parent_conn, output_child_conn = Pipe()
    output_file_process = Process(target=write_soundfile_process_worker, name="HiFiDecode Soundfile Encoder", args=(output_child_conn, output_file, decode_options["audio_rate"]))
    output_file_process.start()

    post_processor = PostProcessor(
        decode_options,
        threads,
        decoders[0]
    )
    decoders_queued = 0
    with as_soundfile(input_file) as f:
        progressB = TimeProgressBar(f.frames, f.frames)
        try:
            print(f"Starting decode...")
            for block, is_last_block in f.blocks(blocksize=block_size, overlap=read_overlap):
                if exit_requested:
                    break

                # read completed data from decoders pool
                # keep queues saturated but don't overfill
                while decoders_queued > threads * 1.5 or not decoder_out_queue.empty():
                    decoders_queued -= 1
                    block_num, l, r = decoder_out_queue.get()
                    post_processor.submit(block_num, l, r, is_last_block)

                decoder_in_queue.put_nowait((current_block, block))
                decoders_queued += 1
                current_block += 1

                # send to post processor
                for stereo in post_processor.read():
                    try:
                        output_parent_conn.send_bytes(stereo)
                        total_samples_decoded += len(stereo) / 8

                        log_decode(start_time, f.tell(), total_samples_decoded, decode_options)

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
                progressB.print(f.tell())
                  
                if is_last_block:
                    break
        except KeyboardInterrupt:
            pass
        print("")
        print("Decode finishing up. Emptying the queue")
        print("")

    # signal the decoders to shutdown
    decoders_running = set()
    for i in range(len(decoder_processes)):
        decoder_in_queue.put_nowait(i)
        decoders_running.add(i)

    while len(decoders_running) > 0 or not decoder_out_queue.empty():
        data = decoder_out_queue.get()
        if isinstance(data, int):
            decoders_running.remove(data)
            continue

        block_num, l, r = data
        post_processor.submit(block_num, l, r, block_num == current_block - 1)

        for stereo in post_processor.read():
            output_parent_conn.send_bytes(stereo)
            total_samples_decoded += len(stereo) / 8

            log_decode(start_time, f.tell(), total_samples_decoded, decode_options)       

    for stereo in post_processor.flush():
        try:
            output_parent_conn.send_bytes(stereo)
            total_samples_decoded += len(stereo) / 8

            log_decode(start_time, f.tell(), total_samples_decoded, decode_options)
        except ValueError:
            pass

    for i in range(threads):
        process = decoder_processes[i]
        process.terminate()
        output_parent_conn.send_bytes(b"")

    output_file_process.join()

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
