"""
test_cvbs_sample_decoding - CVBS sample encoding presets in the analysis loaders

SPDX-License-Identifier: GPL-3.0-or-later
SPDX-FileCopyrightText: 2026 ld-decode contributors

Covers video_common.decode_cvbs_samples() and the level presets that go with it.
ld-decode writes CVBS_U10_4FSC by default for PAL and CVBS_U16_4FSC for NTSC,
so both have to measure the same; the property under test is that the two
containers decode to one common 10-bit domain, with CVBS_U10_4FSC's signed
headroom surviving intact rather than wrapping.

Everything here is built from byte strings in the test.  No file is opened, so
the suite runs with the testdata submodule absent.
"""

import numpy as np
import pytest

from video_common import (
    CVBS_GEOMETRY,
    CVBS_PROTECTED_10BIT,
    CVBS_SAMPLE_ENCODINGS,
    CaptureParams,
    VideoField,
    cvbs_container_dtype,
    decode_cvbs_samples,
)

pytestmark = [pytest.mark.unit, pytest.mark.format]


def u10_bytes(values):
    """Encode 10-bit domain values as a CVBS_U10_4FSC buffer (s16le)."""
    return np.asarray(values, dtype="<i2").tobytes()


def u16_bytes(values):
    """Encode 10-bit domain values as a CVBS_U16_4FSC buffer (u16le, <<6)."""
    return (np.asarray(values, dtype=np.int32) * 64).astype("<u2").tobytes()


# --- container dtypes -----------------------------------------------------


def test_u10_container_is_signed_and_u16_container_is_unsigned():
    # The signedness is the whole difference: it is what lets CVBS_U10_4FSC
    # carry excursions below blanking that CVBS_U16_4FSC cannot represent.
    assert cvbs_container_dtype("CVBS_U10_4FSC") == np.dtype("<i2")
    assert cvbs_container_dtype("CVBS_U16_4FSC") == np.dtype("<u2")


def test_both_containers_are_two_bytes_per_sample():
    # Frame sizing in the geometry table is in samples, and CVBS file
    # conformance checks file size against it, so a container that was not
    # two bytes wide would silently change every frame offset.
    for encoding in CVBS_SAMPLE_ENCODINGS:
        assert cvbs_container_dtype(encoding).itemsize == 2


# --- round trips ----------------------------------------------------------


def test_u10_round_trips_the_ten_bit_domain_exactly():
    values = [4, 64, 240, 256, 512, 800, 844, 1019]
    out = decode_cvbs_samples(u10_bytes(values), "CVBS_U10_4FSC")
    np.testing.assert_array_equal(out, values)


def test_u16_round_trips_the_ten_bit_domain_exactly():
    values = [4, 64, 240, 256, 512, 800, 844, 1019]
    out = decode_cvbs_samples(u16_bytes(values), "CVBS_U16_4FSC")
    np.testing.assert_array_equal(out, values)


def test_the_two_encodings_decode_the_same_values_identically():
    # This is what makes a PAL decode and an NTSC decode comparable, and what
    # lets a capture be re-encoded without changing any measurement.
    values = np.arange(4, 1020, 7)
    u10 = decode_cvbs_samples(u10_bytes(values), "CVBS_U10_4FSC")
    u16 = decode_cvbs_samples(u16_bytes(values), "CVBS_U16_4FSC")
    np.testing.assert_array_equal(u10, u16)


def test_u16_low_six_bits_are_the_scale_factor_not_data():
    # The preset stores value_10bit * 64, so a value and its container word
    # differ by exactly six bit positions.
    out = decode_cvbs_samples(u16_bytes([1, 2, 1019]), "CVBS_U16_4FSC")
    np.testing.assert_array_equal(out, [1, 2, 1019])
    assert np.all((np.frombuffer(u16_bytes([1, 2, 1019]), dtype="<u2") & 0x3F) == 0)


def test_decoded_samples_are_signed_int32():
    # int32 rather than the container width: the headroom below 0 has to be
    # representable, and downstream arithmetic subtracts blanking from it.
    for encoding, buf in (("CVBS_U10_4FSC", u10_bytes([256])),
                          ("CVBS_U16_4FSC", u16_bytes([256]))):
        assert decode_cvbs_samples(buf, encoding).dtype == np.int32


# --- CVBS_U10_4FSC signed headroom ---------------------------------------


def test_u10_negative_excursions_keep_their_sign():
    # An unsigned container would read -300 back as 65236.  PAL pilot-burst
    # residue and chroma undershoot land here on real captures, which is why
    # ld-decode picks this encoding when a decode carries them.
    values = [-1, -300, -32768]
    out = decode_cvbs_samples(u10_bytes(values), "CVBS_U10_4FSC")
    np.testing.assert_array_equal(out, values)
    assert out.min() == -32768


def test_u10_excursions_above_the_ten_bit_range_are_preserved():
    values = [1023, 1024, 5000, 32767]
    out = decode_cvbs_samples(u10_bytes(values), "CVBS_U10_4FSC")
    np.testing.assert_array_equal(out, values)


def test_u10_headroom_survives_a_full_excursion_sweep():
    values = np.arange(-2000, 3000, 13)
    out = decode_cvbs_samples(u10_bytes(values), "CVBS_U10_4FSC")
    np.testing.assert_array_equal(out, values)


# --- reserved codes -------------------------------------------------------


def test_protected_code_ranges_match_the_specification():
    # CVBS file format specification - sample-encoding-presets: protected
    # values 0-3 and 1020-1023.
    assert CVBS_PROTECTED_10BIT == ((0, 3), (1020, 1023))


def test_reserved_codes_decode_unchanged():
    # Decoding reports what the file holds; conformance is cvbs_verify.py's
    # job.  A loader that silently clamped here would hide a real defect.
    reserved = [0, 1, 2, 3, 1020, 1021, 1022, 1023]
    for encoding, buf in (("CVBS_U10_4FSC", u10_bytes(reserved)),
                          ("CVBS_U16_4FSC", u16_bytes(reserved))):
        np.testing.assert_array_equal(
            decode_cvbs_samples(buf, encoding), reserved)


# --- rejected inputs ------------------------------------------------------


@pytest.mark.parametrize(
    "encoding", ["RAW_S16_28M", "RAW_S16_40M", "CVBS_TPG21_4FSC", "", "u10"]
)
def test_an_unmeasurable_encoding_is_refused_by_name(encoding):
    # The raw-capture presets are unscaled ADC output with no level mapping,
    # so they cannot be measured against the video standard tables.  The
    # error has to name what it found, or a mis-set preset is a silent skip.
    with pytest.raises(ValueError, match=encoding or "Unsupported"):
        decode_cvbs_samples(b"\x00\x00", encoding)
    with pytest.raises(ValueError, match=encoding or "Unsupported"):
        cvbs_container_dtype(encoding)


def test_an_array_in_the_wrong_container_dtype_is_refused():
    # Reinterpreting a u16 buffer as s16 would turn every high sample
    # negative, so the mismatch is refused rather than viewed.
    wrong = np.array([256, 512], dtype="<u2")
    with pytest.raises(ValueError, match="CVBS_U10_4FSC"):
        decode_cvbs_samples(wrong, "CVBS_U10_4FSC")


def test_an_array_already_in_the_container_dtype_is_accepted():
    arr = np.array([4, 256, 1019], dtype="<i2")
    out = decode_cvbs_samples(arr, "CVBS_U10_4FSC")
    np.testing.assert_array_equal(out, [4, 256, 1019])
    # A copy, not a view: the caller's mmap must not be written through.
    assert out.base is None


# --- level presets --------------------------------------------------------


@pytest.mark.parametrize("system", ["NTSC", "PAL"])
def test_cvbs_params_carry_ten_bit_levels(system):
    # decode_cvbs_samples returns the 10-bit domain, so the levels compared
    # against it must be in that domain and not the .tbc file's 16-bit one.
    params = CaptureParams.for_cvbs(system)
    levels = CVBS_GEOMETRY[system]["levels"]
    assert params.blanking_16b_ire == levels["blanking"]
    assert params.white_16b_ire == levels["white"]
    assert params.black_16b_ire == levels["black"]
    assert params.white_16b_ire <= 1023


@pytest.mark.parametrize("system", ["NTSC", "PAL"])
def test_blanking_reads_as_zero_ire_and_white_as_one_hundred(system):
    params = CaptureParams.for_cvbs(system)
    field = VideoField(
        np.zeros(params.field_samples, dtype=np.int32), 0, params,
        {"field_phase_id": 1, "is_first_field": True, "field_id": 0},
    )
    ire = field.output_to_ire(
        np.array([params.blanking_16b_ire, params.white_16b_ire]))
    np.testing.assert_allclose(ire, [0.0, 100.0], rtol=0, atol=1e-9)


@pytest.mark.parametrize("system", ["NTSC", "PAL"])
def test_ire_is_identical_whichever_encoding_the_file_used(system):
    # The domain cancels in output_to_ire, which is why a U10 and a U16 file
    # of the same decode measure the same.
    values = np.arange(4, 1020, 11)
    fields = []
    for encoding, buf in (("CVBS_U10_4FSC", u10_bytes(values)),
                          ("CVBS_U16_4FSC", u16_bytes(values))):
        params = CaptureParams.for_cvbs(system, sample_encoding=encoding)
        samples = decode_cvbs_samples(buf, encoding)
        field = VideoField(
            np.zeros(params.field_samples, dtype=np.int32), 0, params,
            {"field_phase_id": 1, "is_first_field": True, "field_id": 0},
        )
        fields.append(field.output_to_ire(samples))
    np.testing.assert_array_equal(fields[0], fields[1])


def test_black_level_from_metadata_is_taken_as_a_ten_bit_value():
    # The .meta cvbs_file record stores black_level in the 10-bit domain;
    # scaling it here as if it were 16-bit put NTSC setup out by a factor of
    # 64 relative to the samples it is compared against.
    params = CaptureParams.for_cvbs("NTSC", black_level=300)
    assert params.black_16b_ire == 300
    setup_ire = (params.black_16b_ire - params.blanking_16b_ire) / params.out_scale
    np.testing.assert_allclose(setup_ire, 60 / 5.6, rtol=0, atol=1e-9)


@pytest.mark.parametrize("encoding", sorted(CVBS_SAMPLE_ENCODINGS))
def test_params_carry_the_encoding_the_file_was_written_in(encoding):
    # _cvbs_extract_field reads this to decode each row, and consumers branch
    # on it to report which sample domain they are working in, so it has to
    # be the file's encoding rather than the default.
    assert CaptureParams.for_cvbs("PAL", sample_encoding=encoding).sample_encoding == (
        encoding
    )


def test_the_default_cvbs_encoding_is_the_normative_production_one():
    # CVBS file format specification - index: CVBS_U10_4FSC is the normative
    # production output, and ld-decode's default for PAL.
    assert CaptureParams.for_cvbs("PAL").sample_encoding == "CVBS_U10_4FSC"
