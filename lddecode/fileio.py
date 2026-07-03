"""File loaders, ffmpeg/ldf readers and output pipes.

Split verbatim out of utils.py (see that module's compatibility shim).
"""

import subprocess
import threading
import traceback

import numpy as np
from numba import njit

# Try to make sure ffmpeg is available
try:
    import static_ffmpeg
    static_ffmpeg.add_paths()  # adds static ffmpeg/ffprobe binaries to PATH
except ImportError:
    pass

from .profiling import profile


frequency_suffixes = [
    ("ghz", 1.0e9),
    ("mhz", 1.0e6),
    ("khz", 1.0e3),
    ("hz", 1.0),
    ("fsc", 315.0e6 / 88.0),
    ("fscpal", (283.75 * 15625) + 25),
]


def parse_frequency(string):
    """Parse an argument string, returning a float frequency in MHz."""
    multiplier = 1.0e6
    for suffix, mult in frequency_suffixes:
        if string.lower().endswith(suffix):
            multiplier = mult
            string = string[: -len(suffix)]
            break
    return (multiplier * float(string)) / 1.0e6


"""

For this part of the loader phase I found myself going to function objects that implement this
sample API:

```
infile: standard readable/seekable python binary file
sample: starting sample #
readlen: # of samples
```
Returns data if successful, or None or an upstream exception if not (including if not enough data
is available)
"""


def make_loader(filename, inputfreq=None):
    """Return an appropriate loader function object for filename.

    If inputfreq is specified, it gives the sample rate in MHz of the source
    file, and the loader will resample from that rate to 40 MHz. Any sample
    rate specified by the source file's metadata will be ignored, as some
    formats can't represent typical RF sample rates accurately."""

    if inputfreq is not None:
        # We're resampling, so we have to use ffmpeg.

        if filename.endswith(".s16") or filename.endswith(".raw"):
            input_args = ["-f", "s16le"]
        elif filename.endswith(".r16") or filename.endswith(".u16") or filename.endswith(".tbc"):
            input_args = ["-f", "u16le"]
        elif filename.endswith(".rf"):
            input_args = ["-f", "f32le"]
        elif filename.endswith(".s8"):
            input_args = ["-f", "s8"]
        elif filename.endswith(".r8") or filename.endswith(".u8"):
            input_args = ["-f", "u8"]
        elif filename.endswith(".lds") or filename.endswith(".r30"):
            raise ValueError("File format not supported when resampling: " + filename)
        else:
            # Assume ffmpeg will recognise this format itself.
            input_args = []

        output_args = []

        if inputfreq != 40:
            # Use asetrate first to override the input file's sample rate.
            output_args = [
                "-filter:a",
                "asetrate=" + str(inputfreq * 1e6) + ",aresample=" + str(40e6),
            ]

        return LoadFFmpeg(input_args=input_args, output_args=output_args)

    elif filename.endswith(".lds"):
        return load_packed_data_4_40
    elif filename.endswith(".r30"):
        return load_packed_data_3_32
    elif filename.endswith(".rf"):
        return load_unpacked_data_float32
    elif filename.endswith(".s16"):
        return load_unpacked_data_s16
    elif filename.endswith(".r16") or filename.endswith(".u16"):
        return load_unpacked_data_u16
    elif filename.endswith(".r8") or filename.endswith(".u8"):
        return load_unpacked_data_u8
    elif (
        filename.endswith("raw.oga")
        or filename.endswith(".ldf")
        or filename.endswith(".wav")
        or filename.endswith(".flac")
        or filename.endswith(".vhs")
    ):
        return LoadLDF(filename)

    # Fallback to LoadFFmpeg for other formats (with stdin input)
    return LoadFFmpeg()


def load_unpacked_data(infile, sample, readlen, sampletype):
    # this is run for unpacked data:
    # 1 is for 8-bit cxadc data, 2 for 16bit DD, 3 for 16bit cxadc

    samplelength = 2 if sampletype == 3 else sampletype

    infile.seek(sample * samplelength, 0)
    inbuf = infile.read(readlen * samplelength)

    if sampletype == 4:
        indata = np.frombuffer(inbuf, "float32", len(inbuf) // 4) * 32768
    elif sampletype == 3:
        indata = np.frombuffer(inbuf, "uint16", len(inbuf) // 2)
    elif sampletype == 2:
        indata = np.frombuffer(inbuf, "int16", len(inbuf) // 2)
    else:
        # NOTE(oln): Can probably use frombuffer for other variants too but
        # didn't have any samples to test with.
        indata = np.frombuffer(inbuf, "uint8", len(inbuf))

    if len(indata) < readlen:
        return None

    return indata


def load_unpacked_data_u8(infile, sample, readlen):
    return load_unpacked_data(infile, sample, readlen, 1)


def load_unpacked_data_s16(infile, sample, readlen):
    return load_unpacked_data(infile, sample, readlen, 2)


def load_unpacked_data_u16(infile, sample, readlen):
    return load_unpacked_data(infile, sample, readlen, 3)


def load_unpacked_data_float32(infile, sample, readlen):
    return load_unpacked_data(infile, sample, readlen, 4)


# This is for the .r30 format I did in ddpack/unpack.c.  Deprecated but I still have samples in it.
def load_packed_data_3_32(infile, sample, readlen):
    start = (sample // 3) * 4
    offset = sample % 3

    infile.seek(start)

    # we need another word in case offset != 0
    needed = int(np.ceil(readlen * 3 / 4) * 4) + 4

    inbuf = infile.read(needed)
    indata = np.frombuffer(inbuf, "uint32", len(inbuf) // 4)

    if len(indata) < needed:
        return None

    unpacked = np.zeros(len(indata) * 3, dtype=np.int16)

    # By using strides the unpacked data can be loaded with no additional copies
    np.bitwise_and(indata, 0x3FF, out=unpacked[0::3])
    # hold the shifted bits in it's own array to avoid an allocation
    tmp = np.right_shift(indata, 10)
    np.bitwise_and(tmp, 0x3FF, out=unpacked[1::3])
    np.right_shift(indata, 20, out=tmp)
    np.bitwise_and(tmp, 0x3FF, out=unpacked[2::3])

    return unpacked[offset : offset + readlen]


# The 10-bit samples from the Duplicator...
# """
# From Simon's code:

# // Original
# // 0: xxxx xx00 0000 0000
# // 1: xxxx xx11 1111 1111
# // 2: xxxx xx22 2222 2222
# // 3: xxxx xx33 3333 3333
# //
# // Packed:
# // 0: 0000 0000 0011 1111
# // 2: 1111 2222 2222 2233
# // 4: 3333 3333
# """

@njit(cache=True, nogil=True)
def unpack_data_4_40(indata, readlen, offset):
    """Inner unpacking function, split off to allow numba optimisation."""
    unpacked = np.zeros(readlen + 4, dtype=np.uint16)

    # Data needs to be in uint16 for the shift to do the right thing
    # Could've used dtype argument to right_shift but numba didn't like that.
    #
    indatai16 = indata.astype(np.uint16)

    unpacked[0::4] = ( indatai16[0::5] << 2)         | ((indata[1::5] >> 6) & 0x03)
    unpacked[1::4] = ((indatai16[1::5] & 0x3F) << 4) | ((indata[2::5] >> 4) & 0x0F)
    unpacked[2::4] = ((indatai16[2::5] & 0x0F) << 6) | ((indata[3::5] >> 2) & 0x3F)
    unpacked[3::4] = ((indatai16[3::5] & 0x03) << 8) | indata[4::5]

    # convert back to original DdD 16-bit format (signed 16-bit, left shifted)
    rv_unsigned = unpacked[offset : offset + readlen]
    rv_signed   = np.left_shift(rv_unsigned - 512, 6).astype(np.int16)

    return rv_signed


@profile
def load_packed_data_4_40(infile, sample, readlen):
    """Load data from packed DdD format (4 x 10-bits packed in 5 bytes)"""
    start = (sample // 4) * 5
    offset = sample % 4

    infile.seek(start)

    # we need another word in case offset != 0
    needed = int(np.ceil(readlen * 5 // 4)) + 5

    inbuf = infile.read(needed)
    indata = np.frombuffer(inbuf, "uint8", len(inbuf))

    if len(indata) < needed:
        return None

    return unpack_data_4_40(indata, readlen, offset)


class LoadFFmpeg:
    """Load samples from a wide variety of formats using ffmpeg."""

    def __init__(self, input_args=[], output_args=[]):
        self.input_args = input_args
        self.output_args = output_args

        # ffmpeg subprocess
        self.ffmpeg = None

        # The number of the next byte ffmpeg will return
        self.position = 0

        # Keep a buffer of recently-read data, to allow seeking backwards by
        # small amounts. The last byte returned by ffmpeg is at the end of
        # this buffer.
        self.rewind_size = 16 * 1024 * 1024
        self.rewind_buf = b""

    def _close(self):
        if self.ffmpeg is not None:
            self.ffmpeg.kill()
            self.ffmpeg.wait()

    def __del__(self):
        self._close()

    def _read_data(self, count):
        """Read data as bytes from ffmpeg, append it to the rewind buffer, and
        return it. May return less than count bytes if EOF is reached."""

        data = self.ffmpeg.stdout.read(count)
        self.position += len(data)

        self.rewind_buf += data
        self.rewind_buf = self.rewind_buf[-self.rewind_size :]

        return data

    def read(self, infile, sample, readlen):
        sample_bytes = sample * 2
        readlen_bytes = readlen * 2

        if self.ffmpeg is None:
            command = ["ffmpeg", "-hide_banner", "-loglevel", "quiet"]
            command += self.input_args
            command += ["-i", "-"]
            command += self.output_args
            command += ["-c:a", "pcm_s16le", "-f", "s16le", "-"]
            self.ffmpeg = subprocess.Popen(
                command, stdin=infile, stdout=subprocess.PIPE
            )

        if sample_bytes < self.position:
            # Seeking backwards - use data from rewind_buf
            start = len(self.rewind_buf) - (self.position - sample_bytes)
            end = min(start + readlen_bytes, len(self.rewind_buf))
            if start < 0:
                raise IOError("Seeking too far backwards with ffmpeg")
            buf_data = self.rewind_buf[start:end]
            sample_bytes += len(buf_data)
            readlen_bytes -= len(buf_data)
        else:
            buf_data = b""

        while sample_bytes > self.position:
            # Seeking forwards - read and discard samples
            count = min(sample_bytes - self.position, self.rewind_size)
            data = self._read_data(count)
            if len(data) == 0:
                # EOF
                return None

        if readlen_bytes > 0:
            # Read some new data from ffmpeg
            read_data = self._read_data(readlen_bytes)
            if len(read_data) < readlen_bytes:
                # Short read - end of file
                return None
        else:
            read_data = b""

        data = buf_data + read_data
        assert len(data) == readlen * 2
        return np.frombuffer(data, "<i2")

    def __call__(self, infile, sample, readlen):
        return self.read(infile, sample, readlen)


class LoadLDF:
    """Load samples from an .ldf file using PyAV (FFmpeg) for in-process FLAC decode.

    Uses a background thread to decode FLAC frames and fill a buffer.
    Eliminates the subprocess and pipe overhead of the previous design.
    """

    def __init__(self, filename):
        try:
            import av  # noqa: F401
        except ImportError:
            raise ImportError(
                "PyAV library required for .ldf/.flac files. Install with: pip install av"
            )

        self.filename = filename

        self.position = 0
        self.rewind_size = 2 * 1024 * 1024
        self.rewind_buf = b""

        # Forward seeks farther than this (in bytes) restart the decoder with a
        # container seek instead of reading and discarding samples one by one.
        self.seek_threshold = 40 * 1024 * 1024

        # Soft cap on the decode buffer, to bound memory use.  The reader thread
        # pauses once the buffer grows past this -- unless a single read needs
        # more than this many bytes (see _read_data), to avoid a deadlock.
        self._max_buffer = 64 * 1024 * 1024

        self._container = None
        self._stream = None
        self._resampler = None
        self._decode_iter = None
        self._buffer = bytearray()
        self._want = 0
        self._cv = threading.Condition()
        self._eof = False
        self._reader_thread = None
        self._stop_event = None

    def _start_decoder(self, sample):
        """Start/reset the decoder so the next sample returned is `sample`."""
        import av

        self._stop_decoder()

        self._container = av.open(self.filename)
        self._stream = self._container.streams.audio[0]
        self._resampler = av.audio.resampler.AudioResampler(format="s16", layout="mono")

        if sample > 0:
            # The FLAC stores RF samples 1:1 (labeled 40kHz, actually 40MHz).
            # frame.pts and seek offsets are in stream time_base (1/40000)
            # units, which equal the FLAC sample index = RF sample index.
            seek_sample = max(0, sample - self._stream.sample_rate)
            self._container.seek(seek_sample, stream=self._stream, any_frame=True)

        self._decode_iter = self._container.decode(audio=0)

        # Capture the buffer and stop flag per run so a reader thread left over
        # from a previous decoder can never touch the current buffer.
        buf = bytearray()
        stop_event = threading.Event()
        with self._cv:
            self._buffer = buf
            self._want = 0
            self._eof = False
        self._stop_event = stop_event

        self.position = sample * 2
        self.rewind_buf = b""

        self._reader_thread = threading.Thread(
            target=self._reader_loop,
            args=(stop_event, buf, sample),
            daemon=True,
        )
        self._reader_thread.start()

    def _reader_loop(self, stop_event, buf, target_sample):
        """Background thread: decode FLAC frames into `buf`.

        Discards any samples decoded before `target_sample` (the lead-in that
        results from seeking to a frame before the requested position)."""
        try:
            skip_samples = None
            for frame in self._decode_iter:
                if stop_event.is_set():
                    return
                if frame is None:
                    continue

                if skip_samples is None:
                    # The first decoded frame tells us where decoding actually
                    # resumed after the seek, via its presentation timestamp.
                    if frame.pts is not None:
                        base_sample = frame.pts
                    else:
                        base_sample = target_sample
                    skip_samples = max(0, target_sample - base_sample)

                for rf in self._resampler.resample(frame):
                    if stop_event.is_set():
                        return
                    data = bytes(rf.planes[0])

                    if skip_samples > 0:
                        skip_bytes = min(skip_samples * 2, len(data))
                        data = data[skip_bytes:]
                        skip_samples -= skip_bytes // 2
                        if not data:
                            continue

                    with self._cv:
                        # Backpressure: pause while the buffer is over the cap,
                        # but keep filling if a pending read needs even more.
                        while (
                            len(buf) >= self._max_buffer
                            and len(buf) >= self._want
                            and not stop_event.is_set()
                        ):
                            self._cv.wait()
                        if stop_event.is_set():
                            return
                        buf.extend(data)
                        self._cv.notify_all()
        except Exception:
            traceback.print_exc()
        finally:
            with self._cv:
                self._eof = True
                self._cv.notify_all()

    def _stop_decoder(self):
        if self._stop_event is not None:
            self._stop_event.set()

        if self._reader_thread is not None and self._reader_thread.is_alive():
            with self._cv:
                # Wake the reader if it is parked on backpressure.
                self._cv.notify_all()
            self._reader_thread.join(timeout=2)

        if self._container is not None:
            try:
                self._container.close()
            except Exception:
                pass
            self._container = None

        self._reader_thread = None
        self._stop_event = None
        self._decode_iter = None

    def _read_data(self, count):
        """Read up to `count` bytes from the decoded buffer, blocking until they
        are available or the decoder reaches EOF (so a short read means EOF)."""
        with self._cv:
            self._want = count
            self._cv.notify_all()
            while len(self._buffer) < count and not self._eof:
                self._cv.wait()

            available = min(count, len(self._buffer))
            data = bytes(self._buffer[:available])
            del self._buffer[:available]
            self._want = 0
            self._cv.notify_all()

        self.position += len(data)

        self.rewind_buf += data
        self.rewind_buf = self.rewind_buf[-self.rewind_size:]

        return data

    def _close(self):
        self._stop_decoder()

    def __del__(self):
        self._close()

    def read(self, infile, sample, readlen):
        sample_bytes = sample * 2
        readlen_bytes = readlen * 2

        # (Re)start the decoder if it isn't running, or if the target is far
        # enough ahead that seeking beats reading and discarding.
        if self._container is None or (sample_bytes - self.position) > self.seek_threshold:
            self._start_decoder(sample)

        if sample_bytes < self.position:
            # Seeking backwards - serve from rewind_buf if it reaches back far
            # enough, otherwise reseek.
            start = len(self.rewind_buf) - (self.position - sample_bytes)
            end = min(start + readlen_bytes, len(self.rewind_buf))
            if start < 0:
                self._start_decoder(sample)
                buf_data = b""
            else:
                buf_data = self.rewind_buf[start:end]
                sample_bytes += len(buf_data)
                readlen_bytes -= len(buf_data)
        else:
            buf_data = b""

        while sample_bytes > self.position:
            # Seeking forwards within range - read and discard samples.
            count = min(sample_bytes - self.position, self.rewind_size)
            data = self._read_data(count)
            if len(data) == 0:
                return None

        if readlen_bytes > 0:
            read_data = self._read_data(readlen_bytes)
            if len(read_data) < readlen_bytes:
                return None
        else:
            read_data = b""

        data = buf_data + read_data
        assert len(data) == readlen * 2
        return np.frombuffer(data, "<i2")

    def __call__(self, infile, sample, readlen):
        return self.read(infile, sample, readlen)


def ffmpeg_pipe(outname: str, opts: str):
    cmd = "ffmpeg -y -hide_banner -loglevel quiet -f s16le -ar 40k -ac 1 -i -"
    if opts and len(opts):
        cmd += f" {opts}"

    cmd = cmd.split(' ')

    process = subprocess.Popen(
        [*cmd, outname],
        stdin=subprocess.PIPE,
    )

    return process, process.stdin


def ldf_pipe(outname: str, compression_level: int = 6):
    return ffmpeg_pipe(outname, f"-acodec flac -f ogg -compression_level {compression_level}")


def ac3_pipe(outname: str):
    processes = []

    cmd1 = (
        "sox -r 40000000 -b 8 -c 1 -e signed -t raw - -b 8 -r 46080000 "
        "-e unsigned -c 1 -t raw -"
    ).split()
    cmd2 = "ld-ac3-demodulate -v 3 - -".split()
    cmd3 = ["ld-ac3-decode", "-", outname]

    logfp = open(outname + '.log', 'w')

    # This is done in reverse order to allow for pipe building
    processes.append(subprocess.Popen(cmd3,
                                      stdin=subprocess.PIPE,
                                      stdout=logfp,
                                      stderr=subprocess.STDOUT))

    processes.append(subprocess.Popen(cmd2,
                                      stdin=subprocess.PIPE,
                                      stdout=processes[-1].stdin))

    processes.append(subprocess.Popen(cmd1,
                                      stdin=subprocess.PIPE,
                                      stdout=processes[-1].stdin))

    return processes, processes[-1].stdin
