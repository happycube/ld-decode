"""Unit tests for the packet amplitudes measure_vits_multiburst reports.

SPDX-License-Identifier: GPL-3.0-or-later
SPDX-FileCopyrightText: 2026 ld-decode contributors

The multiburst EQ servo and the inverse-MTF ceiling read these amplitudes
against the ~1 MHz reference packet.  On NTSC's FCC multiburst the packets
above 2 MHz are about 4 us long with 1.5 us gaps between them; the fit used
to run over the scan's accepted windows, which hang past a packet's end, and
to chain the 3.58 and 4.1 MHz packets into one across their gap, reading
those packets 0.7 to 2 dB low.  The lines here have the FCC and NTC-7
layouts with known packet amplitudes; NTC-7's three-level chrominance at the
subcarrier frequency follows its 4.2 MHz packet, and must not be taken for
the 3.58 MHz packet.
"""

import types

import numpy as np
import pytest

from lddecode.metrics import measure_vits_multiburst

pytestmark = [pytest.mark.unit, pytest.mark.decode]

OUTFREQ = 315.0 / 88.0 * 4.0        # NTSC 4fsc, MHz
LINELEN = 910
LINE = 22

#: (start us, end us, MHz, p-p IRE): the FCC multiburst as GGV records it,
#: each packet a different level so a reading taken from the wrong span or
#: the wrong packet shows.
PACKETS = [
    (27.6, 33.5, 1.25, 52.0),
    (35.9, 40.3, 2.0, 58.0),
    (41.8, 46.0, 3.0, 48.0),
    (47.6, 52.0, 3.58, 56.0),
    (54.0, 58.0, 4.1, 70.0),
]


def tone_line(packets, pedestal, noise_ire=0.0, seed=1):
    t = np.arange(LINELEN) / OUTFREQ
    y = np.full(LINELEN, pedestal)
    for t0, t1, f, pp in packets:
        inside = (t >= t0) & (t < t1)
        # 0.15 us raised-cosine ends, as a band-limited packet has
        ramp = np.clip(np.minimum(t - t0, t1 - t) / 0.15, 0.0, 1.0)
        env = np.where(inside, 0.5 - 0.5 * np.cos(np.pi * ramp), 0.0)
        y += env * (pp / 2.0) * np.sin(2 * np.pi * f * (t - t0))
    rng = np.random.default_rng(seed)
    return y + rng.normal(0.0, noise_ire, LINELEN)


def fcc_line(noise_ire=0.0, seed=1):
    return tone_line(PACKETS, 40.0, noise_ire, seed)


def field_with(line_ire, line=LINE, first_field=True):
    picture = np.zeros(LINELEN * 30)
    picture[LINELEN * (line - 1):LINELEN * line] = line_ire

    class Field:
        rf = types.SimpleNamespace(system="NTSC",
                                   SysParams={"outfreq": OUTFREQ})
        dspicture = picture
        isFirstField = first_field

        def lineslice_tbc(self, line, begin, length):
            start = LINELEN * (line - 1) + int(begin * OUTFREQ)
            return slice(start, start + int(length * OUTFREQ))

        def output_to_ire(self, output):
            return output

    return Field()


@pytest.mark.parametrize("noise_ire", [0.0, 1.0])
def test_every_fcc_packet_reads_its_own_amplitude(noise_ire):
    result = measure_vits_multiburst(field_with(fcc_line(noise_ire)))
    assert result is not None
    packets, line = result
    assert line == LINE
    for _, _, f, pp in PACKETS:
        near = [a for fr, a in packets if abs(fr / 1e6 - f) < 0.1]
        assert len(near) == 1, (f, packets)
        assert 20 * np.log10(near[0] / pp) == pytest.approx(0.0, abs=0.15), f


def test_adjacent_packets_are_not_merged():
    """3.58 and 4.1 MHz sit 0.52 MHz and a 2 us gap apart: two packets."""
    packets, _ = measure_vits_multiburst(field_with(fcc_line()))
    freqs = sorted(fr / 1e6 for fr, _ in packets)
    assert any(abs(f - 3.58) < 0.05 for f in freqs)
    assert any(abs(f - 4.1) < 0.05 for f in freqs)


#: NTC-7 combination, second fields: ~3 us packets on a 50 IRE pedestal,
#: then the three-level chrominance at the subcarrier frequency.
NTC7_PACKETS = [
    (24.5, 27.5, 1.0, 50.0),
    (28.5, 31.5, 2.0, 46.0),
    (32.5, 35.5, 3.0, 54.0),
    (36.5, 39.5, 3.58, 48.0),
    (40.5, 43.5, 4.2, 56.0),
]
NTC7_CHROMA = [(46.0, 50.0, 3.579545, 20.0), (50.0, 54.0, 3.579545, 40.0),
               (54.0, 58.0, 3.579545, 80.0)]


def test_the_ntc7_multiburst_is_read_on_second_fields():
    line = tone_line(NTC7_PACKETS + NTC7_CHROMA, 50.0)
    result = measure_vits_multiburst(field_with(line, 20, first_field=False))
    assert result is not None
    packets, at = result
    assert at == 20
    for _, _, f, pp in NTC7_PACKETS:
        near = [a for fr, a in packets if abs(fr / 1e6 - f) < 0.1]
        assert len(near) == 1, (f, packets)
        # the subcarrier packet, not the 80 IRE chrominance bar after it
        assert 20 * np.log10(near[0] / pp) == pytest.approx(0.0, abs=0.25), f


def test_first_fields_look_only_for_the_fcc_line():
    line = tone_line(NTC7_PACKETS + NTC7_CHROMA, 50.0)
    assert measure_vits_multiburst(field_with(line, 20, first_field=True)) is None
