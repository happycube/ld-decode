"""File loaders, ffmpeg/ldf readers and output pipes.

Originally split out of utils.py, which now only re-exports it.
"""

import logging
import os
import shlex
import subprocess
import threading

import numpy as np
from numba import njit

# Try to make sure ffmpeg is available
try:
    import static_ffmpeg
    # weak: only download the static binaries when no ffmpeg is on PATH
    static_ffmpeg.add_paths(weak=True)
except ImportError:
    pass

from .ldf_reader import packed_s16_bytes
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


def make_loader(filename, inputfreq=None, decode_threads=1):
    """Return an appropriate loader function object for filename.

    If inputfreq is specified, it gives the sample rate in MHz of the source
    file, and the loader will resample from that rate to 40 MHz. Any sample
    rate specified by the source file's metadata will be ignored, as some
    formats can't represent typical RF sample rates accurately.

    decode_threads is how many threads may decode a compressed (.ldf/FLAC)
    input; it does not affect the samples returned."""

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
    elif filename.endswith(".s16") or filename.endswith(".raw"):
        # .raw is signed 16-bit, same as the resampling path above treats it
        return load_unpacked_data_s16
    elif filename.endswith(".r16") or filename.endswith(".u16"):
        return load_unpacked_data_u16
    elif filename.endswith(".s8"):
        return load_unpacked_data_s8
    elif filename.endswith(".r8") or filename.endswith(".u8"):
        return load_unpacked_data_u8
    elif (
        filename.endswith("raw.oga")
        or filename.endswith(".ldf")
        or filename.endswith(".wav")
        or filename.endswith(".flac")
        or filename.endswith(".vhs")
    ):
        return LoadLDF(filename, decode_threads=decode_threads)

    # Fallback to LoadFFmpeg for other formats (with stdin input)
    return LoadFFmpeg()


#: The fixed-width raw captures, and the sample layout each one holds.
#: The read-time TBC path reads a capture at arbitrary positions, which only
#: a fixed-width file can serve: a packed (.lds) or compressed (.ldf, .raw.oga, .flac)
#: capture cannot be read at an arbitrary offset.
RAW_LAYOUTS = {
    ".s16": ("int16", 2),
    ".raw": ("int16", 2),
    ".r16": ("uint16", 2),
    ".u16": ("uint16", 2),
    ".r8": ("uint8", 1),
    ".u8": ("uint8", 1),
    ".s8": ("int8", 1),
    ".rf": ("float32", 4),
}


def raw_layout(filename):
    """The (sample dtype, bytes per sample) of a fixed-width raw capture.

    Returns None for a capture that is not fixed-width (a packed .lds, a
    compressed .ldf or .flac), which cannot be read at arbitrary positions.
    """
    name = filename.lower()
    for ext, layout in RAW_LAYOUTS.items():
        if name.endswith(ext):
            return layout
    return None


class RawCapture:
    """A fixed-width raw capture, read at absolute sample positions.

    The samples come back in the same units the matching loader returns
    (signed 16-bit, unsigned 16-bit centred on 32768, unsigned 8-bit, signed
    8-bit scaled up to the 16-bit range, or 32-bit float scaled by 32768), so
    a decode reads the same scale whether it takes one capture or a stack.

    This is the reader the stacking source injects: it asks for a range of
    samples and gets an array of floats, whatever the file's own dtype.
    """

    def __init__(self, filename):
        """Open filename; raises ValueError when it is not a fixed-width raw capture."""
        layout = raw_layout(filename)
        if layout is None:
            raise ValueError(
                f"{filename} is not a fixed-width raw capture "
                "(s16, raw, r16, u16, r8, u8, s8, rf)"
            )
        self.filename = filename
        self.dtype, self.width = layout
        self._file = open(filename, "rb")
        self._length = os.path.getsize(filename) // self.width

    @property
    def length(self):
        """The capture's length in samples."""
        return self._length

    def read(self, start, count):
        """The samples [start, start + count) as float64.

        Samples before the file and past its end read as zero, so a caller
        may ask for a range that overhangs either end.  Returns a new array;
        it does not share memory with the file.
        """
        out = np.zeros(count, dtype=np.float64)
        lo = max(0, int(start))
        hi = min(self._length, int(start) + int(count))
        if hi <= lo:
            return out
        self._file.seek(lo * self.width)
        data = np.fromfile(self._file, dtype=self.dtype, count=hi - lo)
        if self.dtype == "float32":
            data = data * 32768.0
        elif self.dtype == "int8":
            # The same scale-up the .s8 loader applies, so the two paths
            # decode identically.
            data = data.astype(np.float64) * 256.0
        out[lo - int(start) : lo - int(start) + len(data)] = data
        return out

    def close(self):
        """Close the file."""
        if self._file is not None:
            self._file.close()
            self._file = None


#: The packed captures: samples and bytes per group.
PACKED_LAYOUTS = {".lds": (4, 5), ".r30": (3, 4)}

#: The compressed captures, decoded by PyAV (LoadLDF): every suffix
#: make_loader sends to LoadLDF, so a capture the decoder reads as a stream
#: can also be read at positions.
COMPRESSED_EXTENSIONS = ("raw.oga", ".ldf", ".wav", ".flac", ".vhs")


class PackedCapture:
    """A packed capture (.lds: four 10-bit samples in five bytes; .r30:
    three in a 32-bit word), read at absolute sample positions with the
    loaders the decoder reads them with (load_packed_data_4_40 and
    load_packed_data_3_32), so the samples are the same."""

    def __init__(self, filename):
        ext = os.path.splitext(filename)[1].lower()
        if ext not in PACKED_LAYOUTS:
            raise ValueError(f"{filename} is not a packed capture (lds, r30)")
        per_group, group_bytes = PACKED_LAYOUTS[ext]
        self.filename = filename
        self._load = load_packed_data_4_40 if ext == ".lds" else load_packed_data_3_32
        self._file = open(filename, "rb")
        self._length = os.path.getsize(filename) // group_bytes * per_group

    @property
    def length(self):
        return self._length

    def read(self, start, count):
        """The samples [start, start + count) as float64, zero outside the
        capture (as RawCapture.read)."""
        out = np.zeros(count, dtype=np.float64)
        lo = max(0, int(start))
        hi = min(self._length, int(start) + int(count))
        if hi <= lo:
            return out
        data = self._load(self._file, lo, hi - lo)
        n = min(len(data), hi - lo)
        out[lo - int(start) : lo - int(start) + n] = data[:n]
        return out

    def close(self):
        if self._file is not None:
            self._file.close()
            self._file = None


def compressed_length(filename):
    """The number of samples in a compressed (.ldf/.flac) capture.

    The header's count is where the search starts, not the answer: a FLAC
    whose header could not be rewritten once encoded (written through a
    pipe) can carry a count that is not the stream's - one 28 GB capture
    says 16.8 s of a 20-minute stream.  The decoder reads such a file to its
    end, so the end is found in the stream itself: a seek, then the first
    frame decoded there and its position, doubling past the header's count
    while the stream goes on, halving back, and the last stretch decoded to
    the end.  (The decoder's own reader cannot be asked one sample at a
    time near the end: it answers from what it holds.)
    """
    import av

    with av.open(filename) as container:
        stream = container.streams.audio[0]
        scale = stream.time_base * stream.sample_rate

        def frame_at(sample):
            """The frame a seek to `sample` lands on: (first sample, count),
            or None past the end."""
            try:
                container.seek(int(sample / scale), stream=stream, any_frame=False, backward=True)
            except av.error.FFmpegError:
                return None
            for frame in container.decode(stream):
                if frame.pts is None:
                    return None
                return int(frame.pts * scale), frame.samples
            return None

        def inside(sample):
            found = frame_at(sample)
            return found is not None and found[0] + found[1] > sample

        claimed = int(stream.duration * scale) if stream.duration is not None else 0
        lo, guess = 0, max(claimed, 1 << 20)
        if inside(guess):
            lo, step = guess, guess
            while inside(lo + step):
                lo += step
                step *= 2
            hi = lo + step
        else:
            hi = guess
        while hi - lo > 1 << 16:
            mid = (lo + hi) // 2
            if inside(mid):
                lo = mid
            else:
                hi = mid
        found = frame_at(lo)
        if found is None:
            return 0
        container.seek(int(found[0] / scale), stream=stream, any_frame=False, backward=True)
        end = found[0]
        for frame in container.decode(stream):
            if frame.pts is not None:
                end = int(frame.pts * scale)
            end += frame.samples
        return end


class CompressedCapture:
    """A compressed capture (.ldf, .raw.oga, .flac, .wav, .vhs), read at
    absolute sample positions through the decoder's own FLAC reader
    (LoadLDF), which seeks in the container and decodes from there."""

    def __init__(self, filename):
        self.filename = filename
        self._loader = LoadLDF(filename)
        self._length = compressed_length(filename)

    @property
    def length(self):
        return self._length

    def read(self, start, count):
        """The samples [start, start + count) as float64, zero outside the
        capture (as RawCapture.read)."""
        out = np.zeros(count, dtype=np.float64)
        lo = max(0, int(start))
        hi = min(self._length, int(start) + int(count))
        if hi <= lo:
            return out
        data = self._loader.read(None, lo, hi - lo)
        if data is None:
            raise IOError(f"{self.filename}: the stream ends before sample {hi}"
                          + (f" ({self._loader.failed})" if self._loader.failed else ""))
        out[lo - int(start) : hi - int(start)] = data
        return out

    def close(self):
        if self._loader is not None:
            self._loader._close()
            self._loader = None


def open_capture(filename):
    """A capture read at absolute sample positions, whatever its format:
    raw (RawCapture), packed (PackedCapture) or compressed
    (CompressedCapture).  Raises ValueError for another format."""
    if raw_layout(filename) is not None:
        return RawCapture(filename)
    ext = os.path.splitext(filename)[1].lower()
    if ext in PACKED_LAYOUTS:
        return PackedCapture(filename)
    # Matched on the name's end, not on splitext: ".raw.oga" has two dots.
    if filename.lower().endswith(COMPRESSED_EXTENSIONS):
        return CompressedCapture(filename)
    raise ValueError(
        f"{filename}: a capture read at positions is raw (s16, raw, r16, u16, "
        "r8, u8, s8, rf), packed (lds, r30) or compressed (ldf, raw.oga, "
        "flac, wav, vhs)")


def open_capture_reader(filename):
    """open_capture(filename).read: module-level, so that
    ``functools.partial(open_capture_reader, filename)`` can be sent to
    another process (the stacked source's pass 0)."""
    return open_capture(filename).read


def capture_dtype(filename):
    """The sample type of a capture's samples, as RAW_LAYOUTS names it (the
    packed and compressed captures read as signed 16-bit)."""
    layout = raw_layout(filename)
    return layout[0] if layout is not None else "int16"


def spool_stdin():
    """Buffer what stdin carries to a temporary 16-bit file, for a decode
    that reads its input at positions; returns its name.  ffmpeg decodes it
    as the decoder's stdin loader (LoadFFmpeg) does, and the samples keep
    their own rate.  The caller removes the file."""
    import sys
    import tempfile

    fd, path = tempfile.mkstemp(prefix="ld-decode-stdin-", suffix=".s16")
    os.close(fd)
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", "-",
               "-c:a", "pcm_s16le", "-f", "s16le", path]
    try:
        code = subprocess.run(command, stdin=sys.stdin.buffer).returncode
        if code != 0:
            raise IOError(f"stdin: ffmpeg exited with status {code} while buffering it")
    except BaseException:
        os.remove(path)
        raise
    return path


#: The rate a capture is taken to be at when nothing says otherwise (Hz):
#: the decoder's own default, and the Domesday Duplicator's rate.
DEFAULT_CAPTURE_RATE_HZ = 40.0e6


def open_raw_reader(filename):
    """A reader of the fixed-width raw capture ``filename``: ``read(start, count)``.

    Module-level, so ``functools.partial(open_raw_reader, filename)`` can be
    sent to another process, which opens the capture itself (the stacked
    source's pass 0 does).  The file stays open for the process's life.
    """
    return RawCapture(filename).read


def sidecar_sample_rate(lines):
    """The sample rate (Hz) a Domesday Duplicator sidecar gives, or None.

    ``lines`` is the sidecar's text, line by line.  The rate is the
    ``sample_rate_hz`` key, in hertz, which the Domesday Duplicator writes
    quoted (``"sample_rate_hz": 75000000``, under ``"capture"``); a bare
    key is read as well.  A trailing comment is ignored.
    """
    for line in lines:
        key, sep, value = line.partition(":")
        if sep and key.strip().strip("\"'") == "sample_rate_hz":
            try:
                rate = float(value.split("#")[0].strip().strip("\"'"))
            except ValueError:
                return None
            return rate if rate > 0 else None
    return None


def capture_sample_rate(filename, inputfreq=None):
    """The capture's own sample rate in Hz.

    inputfreq is the rate the user gave (in MHz); when it is None the rate
    is read from the Domesday Duplicator sidecar that sits next to the
    capture (a .yaml file, see sidecar_sample_rate), and failing that it is
    DEFAULT_CAPTURE_RATE_HZ, as for any other decode.  Returns None only
    when the sidecar exists but its rate cannot be read.
    """
    if inputfreq is not None:
        return float(inputfreq) * 1e6
    sidecar = os.path.splitext(filename)[0] + ".yaml"
    if not os.path.isfile(sidecar):
        return DEFAULT_CAPTURE_RATE_HZ
    try:
        with open(sidecar, "r", encoding="utf-8", errors="replace") as f:
            return sidecar_sample_rate(f)
    except OSError:
        return None


def load_unpacked_data(infile, sample, readlen, sampletype):
    # this is run for unpacked data:
    # 1 is for 8-bit cxadc data, 2 for 16bit DD, 3 for 16bit cxadc,
    # 4 for 32-bit float, 5 for signed 8-bit
    #
    # sampletype is not the sample width, so the two are mapped explicitly.
    samplelength = {1: 1, 2: 2, 3: 2, 4: 4, 5: 1}[sampletype]

    infile.seek(sample * samplelength, 0)
    inbuf = infile.read(readlen * samplelength)

    if sampletype == 4:
        indata = np.frombuffer(inbuf, "float32", len(inbuf) // 4) * 32768
    elif sampletype == 3:
        indata = np.frombuffer(inbuf, "uint16", len(inbuf) // 2)
    elif sampletype == 2:
        indata = np.frombuffer(inbuf, "int16", len(inbuf) // 2)
    elif sampletype == 5:
        # Scale up to the 16-bit range, so that a given .s8 file decodes
        # identically whether it reaches us through this loader or through
        # the ffmpeg path (which converts s8 to pcm_s16le the same way).
        indata = np.frombuffer(inbuf, "int8", len(inbuf)).astype(np.int16) * 256
    else:
        # NOTE(oln): Can probably use frombuffer for other variants too but
        # didn't have any samples to test with.
        indata = np.frombuffer(inbuf, "uint8", len(inbuf))

    if len(indata) < readlen:
        return None

    return indata


def samples_to_s16(data):
    """Convert loader output to signed 16-bit samples, as a new array.

    The .u8 and .u16 loaders return unsigned samples centred on 128 and
    32768; casting those straight to int16 wraps (u16) or leaves an 8-bit
    signal in the bottom of the range (u8).  Convert them the way ffmpeg's
    u8/u16le -> pcm_s16le conversion does, so a cut or test .ldf matches
    what the resampling path would have produced.  Float input (the .rf
    loader's, already scaled by 32768) is rounded and limited to the int16
    range as ffmpeg's f32 -> s16 conversion does
    (av_clip_int16(lrintf(x * 32768))): a full-scale +1.0 sample is 32768,
    which a plain cast wraps to -32768.  Signed integer input is cast
    unchanged.
    """
    data = np.asarray(data)
    if data.dtype == np.uint8:
        return ((data.astype(np.int16) - 128) * 256).astype(np.int16)
    if data.dtype == np.uint16:
        return (data.astype(np.int32) - 32768).astype(np.int16)
    if np.issubdtype(data.dtype, np.floating):
        return np.clip(np.rint(data), -32768, 32767).astype(np.int16)
    return data.astype(np.int16)


def load_unpacked_data_u8(infile, sample, readlen):
    return load_unpacked_data(infile, sample, readlen, 1)


def load_unpacked_data_s8(infile, sample, readlen):
    return load_unpacked_data(infile, sample, readlen, 5)


def load_unpacked_data_s16(infile, sample, readlen):
    return load_unpacked_data(infile, sample, readlen, 2)


def load_unpacked_data_u16(infile, sample, readlen):
    return load_unpacked_data(infile, sample, readlen, 3)


def load_unpacked_data_float32(infile, sample, readlen):
    return load_unpacked_data(infile, sample, readlen, 4)


# This is for the .r30 format I did in ddpack/unpack.c.  Deprecated but I still have samples in it.
def load_packed_data_3_32(infile, sample, readlen):
    """Load data from packed .r30 format (3 x 10-bits in each 32-bit LE word).

    Returns the raw 10-bit values (0..1023) as int16, like the cxadc
    unsigned-raw loaders.  (The original version of this loader computed
    its byte count with the samples-per-byte ratio inverted and then
    compared a word count against that byte count, so it returned None
    for every read - .r30 input had never actually worked.)"""
    start = (sample // 3) * 4
    offset = sample % 3

    infile.seek(start)

    # 3 samples per 32-bit word; the first `offset` samples of the first
    # word are before the requested range
    words = (offset + readlen + 2) // 3
    inbuf = infile.read(words * 4)
    indata = np.frombuffer(inbuf, "<u4", len(inbuf) // 4)

    if len(indata) < words:
        # EOF
        return None

    unpacked = np.zeros(len(indata) * 3, dtype=np.int16)
    unpacked[0::3] = indata & 0x3FF
    unpacked[1::3] = (indata >> 10) & 0x3FF
    unpacked[2::3] = (indata >> 20) & 0x3FF

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

    # Whole 5-byte groups only: unpack_data_4_40's strided views require
    # len(indata) to be a multiple of 5 (and its output a multiple of 4),
    # with one slack group so any offset/readlen combination fits.  The
    # previous byte count (readlen * 5 // 4 + 5) satisfied that only for
    # the block-multiple readlens the decoder happens to use, and demanded
    # bytes past EOF even when every requested sample was on disk, so a
    # read up to the exact end of a .lds file always failed.
    groups = (offset + readlen + 3) // 4 + 1
    needed = groups * 5

    inbuf = infile.read(needed)
    indata = np.frombuffer(inbuf, "uint8", (len(inbuf) // 5) * 5)

    if (len(indata) // 5) * 4 < offset + readlen:
        return None  # EOF: the requested samples are not all on disk

    if len(indata) < needed:
        # Only the slack group ran past EOF; pad it (the pad lands beyond
        # the requested range).
        indata = np.concatenate(
            [indata, np.zeros(needed - len(indata), dtype=np.uint8)]
        )

    return unpack_data_4_40(indata, groups * 4 - 4, offset)[:readlen]


class LoadFFmpeg:
    """Load samples from a wide variety of formats using ffmpeg.

    A read that runs out of samples returns None, as at end of input.
    `failed` tells the two apart afterwards: None when ffmpeg reached the
    end of its input and exited cleanly, otherwise a description of how it
    stopped.
    """

    # How long to wait for ffmpeg to exit once its output has ended (s)
    EXIT_TIMEOUT = 10

    def __init__(self, input_args=[], output_args=[]):
        self.input_args = input_args
        self.output_args = output_args

        # ffmpeg subprocess
        self.ffmpeg = None

        self.failed = None

        # The number of the next byte ffmpeg will return
        self.position = 0

        # Keep a buffer of recently-read data, to allow seeking backwards by
        # small amounts. The last byte returned by ffmpeg is at the end of
        # this buffer.
        self.rewind_size = 16 * 1024 * 1024
        self.rewind_buf = bytearray()

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

        if len(data) < count:
            self._check_exit()

        self.rewind_buf += data
        if len(self.rewind_buf) > 2 * self.rewind_size:
            del self.rewind_buf[: len(self.rewind_buf) - self.rewind_size]

        return data

    def _check_exit(self):
        """ffmpeg's output has ended: record whether it ended cleanly."""
        if self.failed is not None:
            return
        try:
            code = self.ffmpeg.wait(timeout=self.EXIT_TIMEOUT)
        except subprocess.TimeoutExpired:
            self.failed = "ffmpeg stopped producing samples but did not exit"
            return
        if code != 0:
            self.failed = f"ffmpeg exited with status {code}"

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
            buf_data = bytes(self.rewind_buf[start:end])
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


class SampleRing:
    """Fixed-capacity byte ring between the FLAC decode thread and its reader.

    The producer appends decoded bytes at a write cursor; the consumer takes
    them in order at a read cursor and may seek backwards over the recent
    past.  Nothing moves as the buffer fills: a byte is copied in once and
    out once, where a growing `bytearray` re-seats the whole buffer every
    time it is extended near its cap.

    Capacity is `readahead + history`.  Holding the producer to `readahead`
    bytes ahead of the consumer is therefore the same condition as keeping
    the ring from overwriting itself, and it leaves `history` bytes behind
    the read cursor intact for a backward seek.

    Cursors are absolute byte counts since the ring was made, so they say
    where the consumer is in the run as well as where it is in the ring.
    """

    def __init__(self, readahead, history):
        self.readahead = int(readahead)
        self.history = int(history)
        self.capacity = self.readahead + self.history
        self._buf = bytearray(self.capacity)
        self._view = memoryview(self._buf)
        self.wpos = 0
        self.rpos = 0

    @property
    def available(self):
        """Bytes written but not yet read."""
        return self.wpos - self.rpos

    @property
    def writable(self):
        """Bytes the producer may write without overrunning the consumer."""
        return self.readahead - self.available

    @property
    def rewindable(self):
        """Bytes behind the read cursor that are still intact."""
        return min(self.rpos, self.capacity - self.available)

    def write(self, data):
        """Copy `data` in at the write cursor.  The caller must have checked
        `writable` first; writing more than that corrupts unread bytes."""
        n = len(data)
        if n > self.writable:
            raise ValueError("SampleRing.write of %d bytes over %d writable"
                             % (n, self.writable))
        start = self.wpos % self.capacity
        end = start + n
        if end <= self.capacity:
            self._view[start:end] = data
        else:
            split = self.capacity - start
            self._view[start:] = data[:split]
            self._view[: n - split] = data[split:]
        self.wpos += n

    def read_into(self, out):
        """Copy up to len(out) available bytes into `out`, advancing the read
        cursor.  Returns the number copied (short only when the ring is
        empty of unread bytes)."""
        n = min(len(out), self.available)
        if n:
            start = self.rpos % self.capacity
            end = start + n
            if end <= self.capacity:
                out[:n] = self._view[start:end]
            else:
                split = self.capacity - start
                out[:split] = self._view[start:]
                out[split:n] = self._view[: n - split]
            self.rpos += n
        return n

    def skip(self, count):
        """Advance the read cursor over `count` available bytes without
        copying them.  Returns the number skipped."""
        n = min(count, self.available)
        self.rpos += n
        return n

    def rewind(self, count):
        """Move the read cursor back over `count` retained bytes.  Returns
        the number moved, which is short if the history does not reach."""
        n = min(count, self.rewindable)
        self.rpos -= n
        return n


class LoadLDF:
    """Load samples from an .ldf file using PyAV (FFmpeg) for in-process FLAC decode.

    Uses a background thread to decode FLAC frames and fill a buffer.
    Eliminates the subprocess and pipe overhead of the previous design.

    ``decode_threads`` > 1 lets libavcodec decode FLAC frames on that many
    threads.  A single decode thread is what bounds a threaded decode: at
    ``-t 8`` it runs ~87% busy at half its standalone rate, and the field
    dispatcher spends most of its time waiting on it for raw samples.

    A FLAC decode error ends the input, as end of file does: reads past it
    return None.  `failed` tells the two apart afterwards: None at a clean
    end of file, otherwise a description of the error.
    """

    def __init__(self, filename, decode_threads=1):
        try:
            import av  # noqa: F401
        except ImportError:
            raise ImportError(
                "PyAV library required for .ldf/.flac files. Install with: pip install av"
            )

        self.filename = filename
        self.decode_threads = int(decode_threads)

        self.position = 0
        self.rewind_size = 2 * 1024 * 1024

        # Forward seeks farther than this (in bytes) restart the decoder with a
        # container seek instead of reading and discarding samples one by one.
        self.seek_threshold = 40 * 1024 * 1024

        # How far the decode thread may run ahead of the reader, to bound
        # memory use.  A single read larger than this cannot be served out of
        # the ring, so _ensure_readahead raises it (restarting the decoder) if
        # one ever arrives; at a field per read it never does.
        self._readahead = 64 * 1024 * 1024

        self._container = None
        self._ring = None
        self._cv = threading.Condition()
        self._eof = False
        self._reader_thread = None
        self._stop_event = None

        self.failed = None

    def _start_decoder(self, sample):
        """Start/reset the decoder so the next sample returned is `sample`."""
        import av

        self._stop_decoder()

        container = av.open(self.filename)
        try:
            stream = container.streams.audio[0]
            if self.decode_threads > 1:
                # libavcodec's FLAC frame threading.  Lossless, so the
                # samples are the same whatever the thread count.
                stream.thread_type = "FRAME"
                stream.codec_context.thread_count = self.decode_threads
            resampler = av.audio.resampler.AudioResampler(format="s16", layout="mono")

            if sample > 0:
                # The FLAC stores RF samples 1:1 (labeled 40kHz, actually 40MHz).
                # frame.pts and seek offsets are in stream time_base (1/40000)
                # units, which equal the FLAC sample index = RF sample index.
                seek_sample = max(0, sample - stream.sample_rate)
                container.seek(seek_sample, stream=stream, any_frame=True)

            decode_iter = container.decode(audio=0)
        except Exception:
            container.close()
            raise

        # All per-run state (buffer, stop flag, container, decode iterator,
        # resampler) is captured here and passed to the reader thread, so a
        # reader left over from a previous decoder can never touch the current
        # run's state.  Once started, the reader thread OWNS the container and
        # is the only thing that closes it: closing it from another thread
        # while the reader is inside a libav demux call frees the AVIOContext
        # under it and segfaults (NULL URLContext in ffurl_seek2).
        ring = SampleRing(self._readahead, self.rewind_size)
        stop_event = threading.Event()
        with self._cv:
            self._ring = ring
            self._eof = False
        self._stop_event = stop_event
        self._container = container

        self.position = sample * 2

        self._reader_thread = threading.Thread(
            target=self._reader_loop,
            args=(stop_event, ring, sample, container, decode_iter, resampler),
            daemon=True,
        )
        self._reader_thread.start()

    def _reader_loop(self, stop_event, ring, target_sample, container,
                     decode_iter, resampler):
        """Background thread: decode FLAC frames into `ring`.

        Discards any samples decoded before `target_sample` (the lead-in that
        results from seeking to a frame before the requested position).

        This thread owns `container` and closes it on the way out -- whether
        it stops on request, hits EOF, or errors."""
        try:
            skip_samples = None
            for frame in decode_iter:
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

                for rf in resampler.resample(frame):
                    if stop_event.is_set():
                        return
                    data = packed_s16_bytes(rf)

                    if skip_samples > 0:
                        skip_bytes = min(skip_samples * 2, len(data))
                        data = data[skip_bytes:]
                        skip_samples -= skip_bytes // 2
                        if not data:
                            continue

                    with self._cv:
                        # Backpressure: pause until the ring has room for this
                        # frame without overwriting bytes the reader has yet to
                        # take, or the recent past it may still seek back over.
                        while ring.writable < len(data) and not stop_event.is_set():
                            self._cv.wait()
                        if stop_event.is_set():
                            return
                        ring.write(data)
                        self._cv.notify_all()
        except Exception as error:
            # Ends the input like end of file, but logged, and recorded in
            # `failed` so the caller can report the output as incomplete
            # rather than finished.
            logging.getLogger("lddecode").error(
                "FLAC decode failed; treating as end of input", exc_info=True)
            with self._cv:
                if self._ring is ring and not stop_event.is_set():
                    self.failed = f"FLAC decode failed: {error!r}"
        finally:
            try:
                container.close()
            except Exception:
                pass
            with self._cv:
                if self._ring is ring:
                    # Still the current run; a stale thread from a superseded
                    # run must not inject EOF into its successor's state.
                    self._eof = True
                self._cv.notify_all()

    def _stop_decoder(self):
        if self._stop_event is not None:
            self._stop_event.set()

        thread = self._reader_thread
        if thread is not None and thread.is_alive():
            with self._cv:
                # Wake the reader if it is parked on backpressure.
                self._cv.notify_all()
            thread.join(timeout=2)
            # If the join timed out the reader is still inside a decode call;
            # it will close the container itself when that call returns.  Do
            # NOT close it here -- that is a use-after-close for the reader.

        self._reader_thread = None
        self._stop_event = None
        self._container = None

    def _consume(self, count, out=None):
        """Take `count` decoded bytes, blocking until they are there or the
        decoder reaches EOF (so a short return means EOF).  With `out` the
        bytes are copied into it, otherwise they are discarded; either way the
        ring keeps them behind the read cursor for a later backward seek.

        Returns the number of bytes taken."""
        with self._cv:
            while self._ring.available < count and not self._eof:
                self._cv.wait()
            if out is None:
                got = self._ring.skip(count)
            else:
                got = self._ring.read_into(out[:count])
            self._cv.notify_all()

        self.position += got
        return got

    def _ensure_readahead(self, count):
        """Make sure a single read of `count` bytes can be served.  The ring
        holds the decode thread `readahead` bytes ahead of the reader, so a
        larger read would wait for bytes the producer is not allowed to write.
        Raising the bound restarts the decoder, which at one field per read
        never happens."""
        if count <= self._readahead:
            return
        self._readahead = count + self.rewind_size
        if self._container is not None:
            self._start_decoder(self.position // 2)

    def _close(self):
        self._stop_decoder()

    def __del__(self):
        self._close()

    def read(self, infile, sample, readlen):
        sample_bytes = sample * 2
        readlen_bytes = readlen * 2
        self._ensure_readahead(readlen_bytes)

        # (Re)start the decoder if it isn't running, or if the target is far
        # enough ahead that seeking beats reading and discarding.
        if self._container is None or (sample_bytes - self.position) > self.seek_threshold:
            self._start_decoder(sample)

        if sample_bytes < self.position:
            # Seeking backwards - the ring keeps the recent past behind the
            # read cursor, so this is a cursor move if it reaches back far
            # enough, and a reseek if it does not.
            back = self.position - sample_bytes
            with self._cv:
                moved = self._ring.rewind(back)
                self._cv.notify_all()
            self.position -= moved
            if moved < back:
                self._start_decoder(sample)

        while sample_bytes > self.position:
            # Seeking forwards within range - decode and discard samples.
            count = min(sample_bytes - self.position, self.rewind_size)
            if self._consume(count) == 0:
                return None

        out = np.empty(readlen, "<i2")
        if readlen_bytes > 0:
            got = self._consume(readlen_bytes, out.view(np.uint8))
            if got < readlen_bytes:
                return None
        return out

    def __call__(self, infile, sample, readlen):
        return self.read(infile, sample, readlen)


def ffmpeg_command(outname: str, opts: str):
    """The ffmpeg argv that encodes s16le samples on stdin into outname.

    `opts` are extra output options as one shell-style string: split with
    shell quoting rules (so a quoted value may hold spaces, and runs of
    spaces separate nothing), but never run through a shell.
    """
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "quiet",
           "-f", "s16le", "-ar", "40k", "-ac", "1", "-i", "-"]
    if opts:
        cmd += shlex.split(opts)
    return [*cmd, outname]


def ffmpeg_pipe(outname: str, opts: str):
    process = subprocess.Popen(
        ffmpeg_command(outname, opts),
        stdin=subprocess.PIPE,
    )

    return process, process.stdin


def ldf_pipe(outname: str, compression_level: int = 6):
    return ffmpeg_pipe(outname, f"-acodec flac -f ogg -compression_level {compression_level}")
