"""Adopting the shared filter segment into an RFDecode bank.

A worker process builds the whole filter bank, then hands the invariant
part of it back and reads the parent's copy instead.  What that must not
change is any number: these tests pin the swap to exactly the published
names, and demodblock's output on a seeded block to the byte whether the
filters it multiplies against are the worker's own arrays or views into
another process's memory.

The segment itself is exercised through the bytearray-backed factory in
test_shared_filter_bank.
"""

import numpy as np
import pytest
from numpy.testing import assert_array_equal

from lddecode import shared_filter_bank as sfb
from lddecode.rfdecode import RFDecode

pytestmark = [pytest.mark.unit, pytest.mark.parallel]

SYSTEMS = ["PAL", "NTSC"]
parametrize_system = pytest.mark.parametrize("system", SYSTEMS)


class FakeSegment:
    """A bytearray standing in for a POSIX shared-memory segment."""

    _store = {}
    _serial = 0

    def __init__(self, name=None, size=0):
        if name is None:
            FakeSegment._serial += 1
            name = "adopt-%d" % FakeSegment._serial
            self._store[name] = bytearray(size)
        self.name = name
        self.buf = memoryview(self._store[name])

    def close(self):
        self.buf.release()

    def unlink(self):
        self._store.pop(self.name, None)


@pytest.fixture(autouse=True)
def clean_registries():
    sfb._published.clear()
    sfb._attached.clear()
    yield
    sfb._published.clear()
    sfb._attached.clear()
    FakeSegment._store = {}


def make_rf(system):
    """A bank with every optional path built, so the published set is the
    whole one: analog audio adds the stage-1 filters and EFM the front
    end, and PAL adds the audio-carrier notch."""
    return RFDecode(
        inputfreq=40,
        system=system,
        decode_analog_audio=44100,
        decode_digital_audio=True,
        has_analog_audio=True,
    )


def publish_for(rf):
    spec = rf.shared_filter_spec()
    descriptor = sfb.publish(spec["arrays"], slots=spec["slots"],
                             segment_factory=FakeSegment)
    return descriptor, sfb.attach(descriptor, segment_factory=FakeSegment)


def block(rf, seed=12345):
    rng = np.random.default_rng(seed)
    return rng.integers(0, 16384, rf.blocklen).astype(np.float64)


def demod_bytes(result):
    """Every channel of a demodblock result, flattened for comparison."""
    out = {}
    for key, value in result.items():
        if value is None:
            out[key] = None
        elif getattr(value, "dtype", None) is not None and value.dtype.names:
            for name in value.dtype.names:
                out["%s.%s" % (key, name)] = np.asarray(value[name])
        else:
            out[key] = np.asarray(value)
    return out


# --- what adoption touches -----------------------------------------------


@parametrize_system
def test_adoption_replaces_exactly_the_published_entries(system):
    rf = make_rf(system)
    _, views = publish_for(rf)
    published = set(views.arrays)

    before = {name: id(value) for name, value in rf.Filters.items()}
    adopted = rf.adopt_shared_filters(views.arrays)

    filter_names = {n for n in published if not n.startswith("audio:")}
    assert set(adopted) == published
    moved = {name for name, value in rf.Filters.items()
             if before.get(name) != id(value)}
    assert moved == filter_names
    assert set(before) == set(rf.Filters)


@parametrize_system
def test_the_adopted_entries_are_the_segment_views(system):
    rf = make_rf(system)
    _, views = publish_for(rf)
    rf.adopt_shared_filters(views.arrays)

    for name, view in views.arrays.items():
        if name.startswith("audio:"):
            _, channel, attribute = name.split(":", 2)
            held = getattr(rf.audio[channel], attribute)
        else:
            held = rf.Filters[name]
        assert held is view
        assert not held.flags.writeable


@parametrize_system
def test_adoption_refuses_a_filter_that_does_not_line_up(system):
    rf = make_rf(system)
    _, views = publish_for(rf)
    wrong = dict(views.arrays)
    wrong["MTF_half"] = np.zeros(4, dtype=np.float64)

    with pytest.raises(ValueError, match="MTF_half"):
        rf.adopt_shared_filters(wrong)


@parametrize_system
def test_adoption_refuses_a_name_this_bank_does_not_have(system):
    rf = make_rf(system)

    with pytest.raises(KeyError):
        rf.adopt_shared_filters({"Fnonesuch": np.zeros(4)})


# --- and what it must not change -----------------------------------------


@parametrize_system
def test_demodblock_is_unchanged_by_adoption(system):
    rf = make_rf(system)
    data = block(rf)
    before = demod_bytes(rf.demodblock(data=data, mtf_level=0.7, cut=True))

    _, views = publish_for(rf)
    rf.adopt_shared_filters(views.arrays)
    after = demod_bytes(rf.demodblock(data=data, mtf_level=0.7, cut=True))

    assert set(before) == set(after)
    for name, expected in before.items():
        if expected is None:
            assert after[name] is None
        else:
            assert_array_equal(after[name], expected, err_msg=name)


# --- the per-job slot sources --------------------------------------------


@parametrize_system
def test_the_mtf_slot_carries_what_mtf_response_would_build(system):
    rf = make_rf(system)

    for level in (0.0, 0.62, 1.13):
        arrays = rf.slot_filter_arrays("mtf", level)
        assert_array_equal(arrays["MTF_response"], rf.mtf_response(level))


@parametrize_system
def test_the_video_slot_carries_the_bank_at_its_own_key(system):
    rf = make_rf(system)
    key = (rf.DecoderParams.get("inverse_mtf_strength", 0.0), None)

    arrays = rf.slot_filter_arrays("video", key)

    assert set(arrays) == set(RFDecode.SLOT_FILTERS["video"])
    for name, value in arrays.items():
        assert value is rf.Filters[name]


@parametrize_system
def test_the_video_slot_is_refused_for_a_key_the_bank_is_not_at(system):
    """The decoder writes the parameter and rebuilds the filters in two
    steps; a publication taken between them would stamp the old filter
    with the new key."""
    rf = make_rf(system)
    held = rf.DecoderParams.get("inverse_mtf_strength", 0.0)

    assert rf.slot_filter_arrays("video", (held + 0.5, None)) is None
    assert rf.slot_filter_arrays("video", (held, ((1e6, 1.0),))) is None


@parametrize_system
def test_the_video_slot_follows_the_bank_through_a_rebuild(system):
    rf = make_rf(system)
    rf.DecoderParams["inverse_mtf_strength"] = 0.4
    rf.recompute_fvideo()

    arrays = rf.slot_filter_arrays("video", (0.4, None))

    assert arrays is not None
    assert_array_equal(arrays["FVideo_rfft32"], rf.Filters["FVideo_rfft32"])
    assert_array_equal(arrays["FVideo_rfft_dc"], rf.Filters["FVideo_rfft_dc"])


def test_an_unknown_slot_family_has_no_source():
    rf = make_rf("PAL")
    assert rf.slot_filter_arrays("nonesuch", 0) is None
