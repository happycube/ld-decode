"""
test_cvbs_frame_encoding - quantisation of CVBS frames to file bytes

SPDX-License-Identifier: GPL-3.0-or-later
SPDX-FileCopyrightText: 2026 ld-decode contributors

Covers lddecode.cvbs.encode_cvbs_frame(), the writer's sample quantisation.
The property that matters is that CVBS_U10_4FSC and CVBS_U16_4FSC carry the
same sample values for the same decode: ld-decode picks the encoding by
system, so a difference between them would show up as a level difference
between PAL and NTSC measurements that no disc actually has.

The writer's input domain is the 10-bit sample value scaled by 64.
"""

import numpy as np
import pytest

from lddecode.cvbs import (
    CVBS_CLAMP_HI10,
    CVBS_CLAMP_LO10,
    CVBS_U10_CONTAINER_MAX,
    CVBS_U10_CONTAINER_MIN,
    encode_cvbs_frame,
)

pytestmark = [pytest.mark.unit, pytest.mark.format]

U10 = "CVBS_U10_4FSC"
U16 = "CVBS_U16_4FSC"


def working_domain(values_10bit):
    """The writer's internal domain: the 10-bit value scaled by 64."""
    return np.asarray(values_10bit, dtype=np.float64) * 64.0


def decode(payload, encoding):
    """Read a payload back as 10-bit sample values."""
    if encoding == U10:
        return np.frombuffer(payload, dtype="<i2").astype(np.int32)
    return np.frombuffer(payload, dtype="<u2").astype(np.int32) >> 6


# --- the two encodings agree ---------------------------------------------


def test_both_encodings_store_the_same_sample_values():
    # The regression this pins: the u16 path used to mask the low six bits
    # off a 16-bit rounding, which floors instead of rounding and put every
    # sample up to one code (about 0.17 IRE) below the u10 path.
    frame = working_domain(np.arange(CVBS_CLAMP_LO10, CVBS_CLAMP_HI10 + 1))
    a = decode(encode_cvbs_frame(frame, U10)[0], U10)
    b = decode(encode_cvbs_frame(frame, U16)[0], U16)
    np.testing.assert_array_equal(a, b)


def test_both_encodings_agree_on_fractional_inputs():
    # Real frames are floats: the working domain is a scaled measurement, not
    # an integer grid, so the halfway and near-halfway cases are the ones that
    # separate rounding from flooring.
    rng = np.random.default_rng(12345)
    frame = rng.uniform(CVBS_CLAMP_LO10, CVBS_CLAMP_HI10, 4096) * 64.0
    a = decode(encode_cvbs_frame(frame, U10)[0], U10)
    b = decode(encode_cvbs_frame(frame, U16)[0], U16)
    np.testing.assert_array_equal(a, b)


@pytest.mark.parametrize("frac", [0.0, 0.25, 0.5, 0.75, 0.9999])
def test_a_fractional_code_rounds_the_same_way_in_both_encodings(frac):
    frame = working_domain(np.full(64, 500.0) + frac)
    a = decode(encode_cvbs_frame(frame, U10)[0], U10)
    b = decode(encode_cvbs_frame(frame, U16)[0], U16)
    np.testing.assert_array_equal(a, b)
    # Nearest-code quantisation, not truncation towards the lower code.
    np.testing.assert_array_equal(a, np.round(500.0 + frac))


# --- container formats ----------------------------------------------------


def test_u16_payload_has_zero_low_bits():
    # CVBS file format specification - sample-encoding-presets:
    # u16 = value_10bit * 64, so the low six bits are scale, never data.
    payload, _ = encode_cvbs_frame(working_domain([4, 511, 1019]), U16)
    words = np.frombuffer(payload, dtype="<u2")
    assert np.all((words & 0x3F) == 0)
    np.testing.assert_array_equal(words >> 6, [4, 511, 1019])


def test_each_encoding_writes_two_bytes_per_sample():
    frame = working_domain(np.full(100, 256))
    for encoding in (U10, U16):
        payload, _ = encode_cvbs_frame(frame, encoding)
        assert len(payload) == 200


def test_u10_payload_is_signed_and_u16_payload_is_unsigned():
    payload, _ = encode_cvbs_frame(working_domain([256]), U10)
    assert np.frombuffer(payload, dtype="<i2")[0] == 256
    payload, _ = encode_cvbs_frame(working_domain([256]), U16)
    assert np.frombuffer(payload, dtype="<u2")[0] == 256 * 64


# --- clamping -------------------------------------------------------------


@pytest.mark.parametrize("encoding", [U10, U16])
def test_samples_outside_the_permitted_range_are_clamped_and_counted(encoding):
    frame = working_domain([-50, 0, 3, 4, 1019, 1020, 2000])
    payload, n_clamped = encode_cvbs_frame(frame, encoding)
    out = decode(payload, encoding)
    assert out.min() >= CVBS_CLAMP_LO10
    assert out.max() <= CVBS_CLAMP_HI10
    # -50, 0, 3, 1020 and 2000 all sit outside [4, 1019].
    assert n_clamped == 5


@pytest.mark.parametrize("encoding", [U10, U16])
def test_a_conformant_frame_reports_nothing_clamped(encoding):
    frame = working_domain(np.arange(CVBS_CLAMP_LO10, CVBS_CLAMP_HI10 + 1))
    _, n_clamped = encode_cvbs_frame(frame, encoding)
    assert n_clamped == 0


@pytest.mark.parametrize("encoding", [U10, U16])
def test_reserved_codes_are_never_written(encoding):
    # CVBS file format specification - sample-encoding-presets: 0-3 and
    # 1020-1023 are protected, and cvbs_verify.py fails a file containing them.
    frame = working_domain(np.linspace(-500, 1500, 8192))
    out = decode(encode_cvbs_frame(frame, encoding)[0], encoding)
    assert not np.any((out >= 0) & (out <= 3))
    assert not np.any((out >= 1020) & (out <= 1023))


# --- CVBS_U10_4FSC signed headroom ---------------------------------------


def test_u10_keeps_excursions_when_the_decode_has_nonstandard_values():
    # This is the reason the u10 encoding exists: a decode carrying PAL pilot
    # burst residue or chroma overshoot keeps it instead of being clipped to
    # the reserved-code bounds.
    frame = working_domain([-2000, -1, 0, 1023, 1024, 5000])
    payload, n_clamped = encode_cvbs_frame(frame, U10, has_nonstandard_values=True)
    np.testing.assert_array_equal(
        decode(payload, U10), [-2000, -1, 0, 1023, 1024, 5000])
    assert n_clamped == 0


def test_u10_headroom_is_bounded_by_the_signed_container():
    frame = working_domain([CVBS_U10_CONTAINER_MIN - 10,
                            CVBS_U10_CONTAINER_MAX + 10])
    payload, n_clamped = encode_cvbs_frame(frame, U10, has_nonstandard_values=True)
    np.testing.assert_array_equal(
        decode(payload, U10), [CVBS_U10_CONTAINER_MIN, CVBS_U10_CONTAINER_MAX])
    assert n_clamped == 2


def test_headroom_is_not_offered_by_the_unsigned_encoding():
    # A u16 container cannot represent a negative sample, so the same frame
    # is clamped whatever the caller asks for; ld-decode selects u10 for such
    # a decode rather than losing the excursions here.
    frame = working_domain([-2000, 5000])
    out = decode(
        encode_cvbs_frame(frame, U16, has_nonstandard_values=True)[0], U16)
    np.testing.assert_array_equal(out, [CVBS_CLAMP_LO10, CVBS_CLAMP_HI10])


def test_u10_without_nonstandard_values_clamps_to_the_reserved_bounds():
    frame = working_domain([-2000, 5000])
    payload, n_clamped = encode_cvbs_frame(frame, U10, has_nonstandard_values=False)
    np.testing.assert_array_equal(
        decode(payload, U10), [CVBS_CLAMP_LO10, CVBS_CLAMP_HI10])
    assert n_clamped == 2


# --- purity ---------------------------------------------------------------


def test_the_input_frame_is_not_modified():
    # _write_frame hands in the frame it also uses for burst-lock bookkeeping,
    # so quantisation must not write through it.
    frame = working_domain([-50, 500, 2000])
    before = frame.copy()
    encode_cvbs_frame(frame, U10)
    encode_cvbs_frame(frame, U16)
    np.testing.assert_array_equal(frame, before)
