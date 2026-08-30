"""Digital signal-processing primitives and small numeric helpers.

Split verbatim out of utils.py (see that module's compatibility shim).
"""

import math
from math import tau

import numpy as np
from numba import njit


# This runs a cubic scaler on a line.
# originally from https://www.paulinternet.nl/?page=bicubic
@njit(nogil=True, cache=True)
def scale(buf, begin, end, tgtlen, mult=1):
    linelen = end - begin
    sfactor = linelen / tgtlen

    output = np.zeros(tgtlen, dtype=buf.dtype)

    for i in range(0, tgtlen):
        coord = (i * sfactor) + begin
        start = int(coord) - 1
        p = buf[start : start + 4]
        x = coord - int(coord)

        output[i] = mult * (
            p[1]
            + 0.5
            * x
            * (
                p[2]
                - p[0]
                + x
                * (
                    2.0 * p[0]
                    - 5.0 * p[1]
                    + 4.0 * p[2]
                    - p[3]
                    + x * (3.0 * (p[1] - p[2]) + p[3] - p[0])
                )
            )
        )

    return output


# Kaiser Beta parameter controls trade-off between sharpness and ringing
# Small Beta = more sharpness / more ringing (narrow main lobe (more sharp), less side lobe cutoff
# (more ringing))
# Large Beta = less sharpness / less ringing (wide main lobe (less sharp), more side lobe cutoff
# (less ringing))
# kaiser_beta = 5
sinc_tap_count = 16  # must be multiple of 2
sinc_phase_count = 2**16

# @njit
# def sinc(x):
#     if x == 0.0:
#         return 1.0
#     x_pi = np.pi * x
#     return math.sin(x_pi) / x_pi


# def kaiser_window(x, a, beta, i0_beta):
#     r = x / a
#     if r < -1.0 or r > 1.0:
#         return 0.0
#
#     t = math.sqrt(1.0 - r * r)
#     return i0(beta * t) / i0_beta


# https://ccrma.stanford.edu/~jos/sasp/Kaiser_Windows_Transforms.html
# def build_kaiser_lut(beta, taps, phases):
#     a = taps // 2
#
#     offsets = np.arange(a - 1, -a - 1, -1)
#     offsets_len = len(offsets)
#
#     table = np.zeros((phases + 1, taps), dtype=np.float32)
#     weights = np.empty(offsets_len, dtype=np.float32)
#     i0_beta = i0(beta)
#
#     for i in range(phases):
#         phase = i / phases
#
#         s = 0.0
#         for j in range(offsets_len):
#             x = offsets[j] + phase
#             weight = sinc(x) * kaiser_window(x, a, beta, i0_beta)
#
#             weights[j] = weight
#             s += weight
#
#         table[i, :] = weights / s
#
#     # copy the last phase to avoid bounds checking later on when we do linear interpolation
#     table[phases] = table[phases - 1]
#
#     return table


@njit(nogil=True, cache=True, fastmath=True)
def scale_field(
    buf, dsout, interpolated_pixel_locs, wowfactors, sinc_lut, lineoffset, outwidth,
    wow_level_adjust_smoothing = 0, level_adjust_threshold = 15,
):
    # average out any unusual spikes in wow that happen on a per line basis
    # this indicates an hsync tbc error vs. being normal wow from playback speed variations
    # in this case for level adjusting we just want to fallback to the average wow to avoid a
    # bright or dark line
    median = np.median(wowfactors)
    mad = np.median(np.abs(wowfactors - median)) # median absolute deviation
    threshold = level_adjust_threshold * mad if mad > 0 else 0.001  # fallback for no variance

    level_adjusts = np.where(
        np.abs(wowfactors - median) > threshold,
        median,
        wowfactors
    )

    if wow_level_adjust_smoothing > 0:
        # removes oscillating brightness variations for video with lots of noise around the hsync
        # pulses, i.e. noisy line locations result in noisy wow calculations
        # applies a low pass filter that smooths any sudden brightness variations while still being
        # reactive enough to compensate for low frequency wow
        alpha = 1 / (wow_level_adjust_smoothing * outwidth)
        one_minus_alpha = 1 - alpha

        for i in range(1, len(level_adjusts)):
            level_adjusts[i] = alpha * level_adjusts[i] + one_minus_alpha * level_adjusts[i-1]

    half_taps_m1 = (sinc_tap_count // 2) - 1

    dsout_start = outwidth * (lineoffset + 1)
    dsout_end = len(dsout) + dsout_start
    for i in range(dsout_start, dsout_end):
        # compensates for the amplitude/frequency shift caused by FM demodulation under varying
        # playback speed.
        level_adjust = level_adjusts[i]

        # reconstructs the waveform at the proper fractional sample position, undoing wow-induced
        # timing variations
        coord = np.float32(interpolated_pixel_locs[i])
        coord_int = int(coord)

        # fractional phase
        frac = coord - coord_int

        # sinc_phase_count is 2**16, so the nearest tabulated phase is already
        # accurate far below float32 precision. Interpolating between two
        # adjacent phases would double LUT reads and add per-tap math in the
        # innermost loop of the decoder for no change in output.
        # If the LUT gets smaller, consider adding linear interpolation.
        phase = int(frac * sinc_phase_count + np.float32(0.5))
        w = sinc_lut[phase]

        start = coord_int - half_taps_m1

        result = 0.0
        for t in range(sinc_tap_count):
            result += buf[start + t] * w[t]

        dsout[i - dsout_start] = level_adjust * result


@njit(nogil=True, fastmath=True)
def scale_positions(buf, dsout, pixel_locs, wowfactors, sinc_lut,
                    samples_per_line, wow_level_adjust_smoothing=0,
                    level_adjust_threshold=15):
    """scale_field without the raster assumptions.

    Resamples buf at pixel_locs[i] into dsout[i] (equal-length arrays),
    applying the same wow level adjustment as scale_field.  Used by the
    CVBS output lattice, where output sample positions are not organised
    as fixed-width lines (PAL 4fsc is not line-locked).
    """
    median = np.median(wowfactors)
    mad = np.median(np.abs(wowfactors - median))
    threshold = level_adjust_threshold * mad if mad > 0 else 0.001

    level_adjusts = np.where(
        np.abs(wowfactors - median) > threshold,
        median,
        wowfactors
    )

    if wow_level_adjust_smoothing > 0:
        alpha = 1 / (wow_level_adjust_smoothing * samples_per_line)
        one_minus_alpha = 1 - alpha
        for i in range(1, len(level_adjusts)):
            level_adjusts[i] = alpha * level_adjusts[i] + one_minus_alpha * level_adjusts[i - 1]

    half_taps_m1 = (sinc_tap_count // 2) - 1

    for i in range(len(dsout)):
        coord = np.float32(pixel_locs[i])
        coord_int = int(coord)
        frac = coord - coord_int

        phase_pos = frac * sinc_phase_count
        phase_start = int(phase_pos)
        alpha2 = np.float32(phase_pos - phase_start)

        w_start = sinc_lut[phase_start]
        w_end = sinc_lut[phase_start + 1]

        start = coord_int - half_taps_m1

        result = 0.0
        for t in range(sinc_tap_count):
            ws = w_start[t]
            result += buf[start + t] * (ws + alpha2 * (w_end[t] - ws))

        dsout[i] = level_adjusts[i] * result


@njit(cache=True)
def genwave(rate, freq, initialphase=0):
    """ Generate an FM waveform from target frequency data """
    out = np.zeros(len(rate), dtype=np.double)

    angle = initialphase

    for i in range(0, len(rate)):
        out[i] = math.sin(angle)

        angle += math.pi * (rate[i] / freq)
        if angle > math.pi:
            angle -= tau

    return out


# slightly faster than np.std for short arrays
@njit(cache=True)
def rms(arr):
    return np.sqrt(np.mean(np.square(arr - np.mean(arr))))


# MTF calculations
def get_fmax(cavframe=0, laser=780, na=0.5, fps=30):
    loc = 0.055 + ((cavframe / 54000) * 0.090)
    return (2 * na / (laser / 1000)) * (2 * np.pi * fps) * loc


def compute_mtf(freq, cavframe=0, laser=780, na=0.52):
    fmax = get_fmax(cavframe, laser, na)

    freq_mhz = freq / 1000000

    if isinstance(freq_mhz, np.ndarray):
        freq_mhz[freq_mhz > fmax] = fmax
    elif freq_mhz > fmax:
        return 0

    # from Compact Disc Technology AvHeitarō Nakajima, Hiroshi Ogawa page 17
    return (2 / np.pi) * (
        np.arccos(freq_mhz / fmax)
        - ((freq_mhz / fmax) * np.sqrt(1 - ((freq_mhz / fmax) ** 2)))
    )


def roundfloat(fl, places=3):
    """ round float to (places) decimal places """
    r = 10 ** places
    return np.round(fl * r) / r


@njit(nogil=True, cache=True, fastmath=True)
def hz_to_output_array(input, ire0, hz_ire, outputZero, vsync_ire, out_scale):
    n = len(input)
    out = np.empty(n, dtype=np.uint16)

    scale = out_scale / hz_ire
    offset = outputZero - vsync_ire * out_scale - ire0 * scale

    for i in range(n):
        # +0.5 rounds to nearest, matching the scalar Field.hz_to_output path;
        # without it np.uint16() truncates and every output pixel is biased
        # roughly half an LSB low.
        out[i] = np.uint16(max(0, min(65535, input[i] * scale + offset + 0.5)))

    return out


def LRUupdate(lst, k):
    """ This turns a list into an LRU table.  When called it makes sure item 'k' is at the
        beginning,
        so the list is in descending order of previous use.
    """
    try:
        lst.remove(k)
    except Exception:
        pass

    lst.insert(0, k)


def concatenate_blocks(blocks):
    """Concatenate demodulator cache blocks, being sensitive to performance"""
    dtype = blocks[0].dtype
    if dtype.names is None:
        return np.concatenate(blocks)

    # np.concatenate does per-field/per-element copy on structured/record dtype.
    # ~30x slower than simple memcpy. We happen to know the blocks here share
    # the same dtype, so just copy the bytes.
    return np.concatenate([b.view(np.uint8) for b in blocks]).view(dtype)


# numba jit functions, used to numba-ify parts of more complex functions

@njit(cache=True, nogil=True)
def nb_median(m):
    return np.median(m)

@njit(cache=True,nogil=True)
def nb_round(m):
    return int(np.round(m))


@njit(cache=True, nogil=True)
def nb_mean(m):
    return np.mean(m)


@njit(cache=True, nogil=True)
def nb_min(m):
    return np.min(m)


@njit(cache=True, nogil=True)
def nb_max(m):
    return np.max(m)


@njit(cache=True, nogil=True)
def nb_abs(m):
    return np.abs(m)


@njit(cache=True, nogil=True)
def nb_absmax(m):
    return np.max(np.abs(m))


@njit(cache=True, nogil=True)
def nb_std(m):
    return np.std(m)


@njit(cache=True, nogil=True)
def nb_mul(x, y):
    return x * y


@njit(cache=True, nogil=True)
def n_orgt(a, x, y):
    a |= (x > y)


@njit(cache=True, nogil=True)
def n_ornotrange(a, x, y, z):
    a |= (x < y) | (x > z)


@njit(cache=True, nogil=True)
def n_ornotrange_scalar(a, x, lo, hi):
    for i in range(len(a)):
        if x[i] < lo or x[i] > hi:
            a[i] = True


@njit(cache=True, nogil=True)
def angular_mean_helper(x, cycle_len=1.0, zero_base=True):
    """ Compute the mean phase, assuming 0..1 is one phase cycle

        (Using this technique handles the 3.99, 5.01 issue
        where otherwise the phase average would be 0.5.  while a
        naive computation could be changed to rotate around 0.5,
        that breaks down when things are out of phase...)
    """
    x2 = x - x.astype(np.int32)  # not strictly necessary but slightly more precise

    # refer to https://en.wikipedia.org/wiki/Mean_of_circular_quantities
    angles = [np.e ** (1j * f * np.pi * 2 / cycle_len) for f in x2]

    return angles


@njit(cache=True)
def phase_distance(x, c=0.75):
    """ returns the shortest path between two phases (assuming x and c are in (0..1)) """
    d = (x - np.floor(x)) - c

    if d < -0.5:
        d += 1
    elif d > 0.5:
        d -= 1

    return d


# Used to help w/CX routines
@njit(cache=True)
def db_to_lev(db):
    return 10 ** (db / 20)


@njit(cache=True)
def lev_to_db(rlev):
    return 20 * np.log10(rlev)


@njit(cache=True)
def dsa_rescale_and_clip(infloat, fullscale=32767.0):
    """rescale input to output levels and clip to a signed `fullscale` range.

    fullscale is the positive full-scale code: 32767 for 16-bit, 8388607
    for genuine 24-bit.  The clip leaves one code of headroom either side
    (matching the historical +/-32766 16-bit behaviour)."""
    value = int(np.round(infloat * fullscale / 371081.0))
    lim = int(fullscale) - 1
    return min(max(value, -lim), lim)


@njit(cache=True)
def distance_from_round(x):
    # Yes, this was a hotspot.
    return np.round(x) - x


class FieldInfo:
    def __init__(self, field_history_size=3):
        self._field_history_size = field_history_size
        # store previous field references in a ring buffer
        self._fieldinfo = np.empty(field_history_size, dtype=object)
        self._len = 0

    def __len__(self):
        return self._len

    # called like a normal python list, where -1 is the last element, -2 the one before that, etc.
    # using [0] is not allowed since this only stores the end of the list
    def __getitem__(self, key):
        assert key < 0, "Attempted to get a field that has not been written"
        assert key > -self._field_history_size, "Attempted to get a field that is not buffered"
        return self._fieldinfo[(self._len + key) % self._field_history_size]

    def append(self, value):
        self._fieldinfo[self._len % self._field_history_size] = value
        self._len += 1


class StridedCollector:
    # This keeps a numpy buffer and outputs an fft block and keeps the overlap
    # for the next fft.
    def __init__(self, blocklen=32768, cut_begin=2048, cut_end=0):
        self.buffer = None
        self.blocklen = blocklen

        self.cut_begin = cut_begin
        self.cut_end = self.blocklen - cut_end
        self.stride = cut_begin + cut_end

    def add(self, data):
        if self.buffer is None:
            self.buffer = data
        else:
            self.buffer = np.concatenate([self.buffer, data])

        return self.have_block()

    def have_block(self):
        return (self.buffer is not None) and (len(self.buffer) >= self.blocklen)

    def cut(self, processed_data):
        # TODO: assert len(processed_data) == self.blocklen

        return processed_data[self.cut_begin : self.cut_end]

    def get_block(self):
        if self.have_block():
            rv = self.buffer[0 : self.blocklen]
            self.buffer = self.buffer[self.blocklen - self.stride :]

            return rv

        return None


@njit(cache=True, nogil=True)
def _calczc_findfirst(data, target, rising):
    if rising:
        for i in range(1, len(data)):
            if data[i - 1] < target and data[i] >= target:
                return i
    else:
        for i in range(1, len(data)):
            if data[i - 1] > target and data[i] <= target:
                return i
    return None


@njit(cache=True, nogil=True)
def _calczc_do(data, _start_offset, target, edge=0, count=16):
    start_offset = int(_start_offset)
    icount = int(count + 1)
    if edge == 0:
        if data[start_offset] < target:
            edge = 1
        else:
            edge = -1
    loc = _calczc_findfirst(
        data[start_offset : start_offset + icount], target, edge == 1
    )
    if loc is None:
        return None
    x = start_offset + loc
    a = data[x - 1] - target
    b = data[x] - target
    if b - a != 0:
        y = -a / (-a + b)
    else:
        y = 0
    return x - 1 + y


@njit(cache=True, nogil=True)
def compute_linelocs_kernel(
    p_start, p_type, p_valid, line0loc, lastlineloc, meanlinelen,
    linecount, proclines, skipdetected, hsync_tolerance, outlinecount, inlinelen,
):
    filled = np.full(proclines, -1.0)
    has = np.zeros(proclines, dtype=np.bool_)
    dist = np.zeros(proclines)

    n = p_start.shape[0]
    for k in range(n):
        ps = p_start[k]
        lineloc = (ps - line0loc) / meanlinelen
        rlineloc = nb_round(lineloc)
        lineloc_distance = abs(lineloc - rlineloc)

        if skipdetected:
            lineloc_end = linecount - ((lastlineloc - ps) / meanlinelen)
            rlineloc_end = nb_round(lineloc_end)
            lineloc_end_distance = abs(lineloc_end - rlineloc_end)

            if p_type[k] == 0 and rlineloc > 23 and lineloc_end_distance < lineloc_distance:
                lineloc = lineloc_end
                rlineloc = rlineloc_end
                lineloc_distance = lineloc_end_distance

        if rlineloc < 0 or rlineloc >= proclines:
            continue

        if lineloc_distance > hsync_tolerance or (
            has[rlineloc] and lineloc_distance > dist[rlineloc]
        ):
            continue

        if rlineloc > 0 and not p_valid[k]:
            if p_type[k] > 0 or (p_type[k] == 0 and rlineloc < 10):
                continue

        filled[rlineloc] = ps
        has[rlineloc] = True
        dist[rlineloc] = lineloc_distance

    linelocs0 = filled.copy()
    linelocs_filled = filled.copy()
    rv_err = np.zeros(proclines, dtype=np.bool_)

    if linelocs_filled[0] < 0:
        next_valid = -1
        for i in range(0, outlinecount + 1):
            if filled[i] > 0:
                next_valid = i
                break

        if next_valid == -1:
            return 1, linelocs0, linelocs_filled, rv_err

        linelocs_filled[0] = filled[next_valid] - (next_valid * meanlinelen)

        if linelocs_filled[0] < inlinelen:
            return 1, linelocs0, linelocs_filled, rv_err

    for l in range(1, proclines):
        if linelocs_filled[l] < 0:
            rv_err[l] = True

            prev_valid = -1
            next_valid = -1
            for i in range(l, -1, -1):
                if filled[i] > 0:
                    prev_valid = i
                    break
            for i in range(l, outlinecount + 1):
                if filled[i] > 0:
                    next_valid = i
                    break

            if prev_valid == -1:
                avglen = inlinelen
                linelocs_filled[l] = filled[next_valid] - (avglen * (next_valid - l))
            elif next_valid != -1:
                avglen = (filled[next_valid] - filled[prev_valid]) / (next_valid - prev_valid)
                linelocs_filled[l] = filled[prev_valid] + (avglen * (l - prev_valid))
            else:
                avglen = inlinelen
                linelocs_filled[l] = filled[prev_valid] + (avglen * (l - prev_valid))

    return 0, linelocs0, linelocs_filled, rv_err


@njit(cache=True, nogil=True)
def refine_hsync_zcs(
    demod_05, linelocs1, linebad, n, is_pal, freq,
    vsync_target, neg55, pos30,
):
    linelocs2 = linelocs1.copy()
    for i in range(n):
        if (3 <= i <= 6) or (is_pal and (1 <= i <= 2)):
            linebad[i] = True
            continue

        ll1 = linelocs1[i] - freq
        zc = _calczc_do(demod_05, ll1, vsync_target, 0, freq * 2)

        if zc is not None and not linebad[i]:
            linelocs2[i] = zc

            hsync_area = demod_05[int(zc - (freq * 0.75)) : int(zc + (freq * 8))]
            if np.min(hsync_area) < neg55 or np.max(hsync_area) > pos30:
                linebad[i] = True
                linelocs2[i] = linelocs1[i]
            else:
                porch_level = np.median(
                    demod_05[int(zc + (freq * 8)) : int(zc + (freq * 9))]
                )
                sync_level = np.median(
                    demod_05[int(zc + (freq * 1)) : int(zc + (freq * 2.5))]
                )

                zc2 = _calczc_do(demod_05, ll1, (porch_level + sync_level) / 2, 0, 400)

                if zc2 is not None and abs(zc2 - zc) < (freq / 2):
                    linelocs2[i] = zc2
                else:
                    linebad[i] = True
        else:
            linebad[i] = True

        if linebad[i]:
            linelocs2[i] = linelocs1[i]

    return linelocs2


@njit(cache=True, nogil=True)
def refine_pilot_zcs(demod_pilot, linelocs, n, length_px, freq, linelen, pilot_mhz):
    zcs = np.empty(n, dtype=np.float64)
    plen = np.empty(n, dtype=np.float64)
    prev = 0.0
    for l in range(n):
        adjfreq = freq
        if l > 1:
            adjfreq = freq / ((linelocs[l] - linelocs[l - 1]) / linelen)
        pl = (adjfreq / pilot_mhz) / 2
        plen[l] = pl

        begin = linelocs[l]
        start = int(begin)
        stop = int(begin + length_px + 1)
        lsoffset = begin - start

        pilots = demod_pilot[start:stop]

        peakloc = 0
        mx = -1.0
        for i in range(pilots.shape[0]):
            v = pilots[i]
            if v < 0:
                v = -v
            if v > mx:
                mx = v
                peakloc = i

        zc_base = _calczc_do(pilots, peakloc, 0.0, 0, 16)
        if zc_base is not None:
            zcs[l] = (zc_base - lsoffset) / pl
        else:
            zcs[l] = prev
        prev = zcs[l]

    return zcs, plen


if __name__ == "__main__":
    print("Nothing to see here, move along ;)")
