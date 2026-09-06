"""Unit tests for the shared-memory filter segment.

The segment exists so that one copy of the invariant filter bank serves
a whole pool of worker processes instead of one copy per process.  It
changes where the numbers live, never what they are, so these tests are
about the round trip being exact, the views being read-only, a malformed
descriptor being refused, and demodblock producing the same block
whether the filters it reads are private arrays or views.

Everything runs through an injected bytearray-backed factory, so nothing
here touches /dev/shm or spawns a process.
"""

import threading
import time

import numpy as np
import pytest
from numpy.testing import assert_array_equal

from lddecode import shared_filter_bank as sfb
from lddecode.rfdecode import RFDecode

pytestmark = [pytest.mark.unit, pytest.mark.parallel]


# --- a segment factory that never leaves the process ---------------------


class FakeSegment:
    """A bytearray with the two attributes publish/attach use.

    Names are unique for the life of the test session, as the real
    factory's are: publish() and attach() key their registries by name,
    so a factory that recycled them would let one test attach to
    another's segment.
    """

    _store = {}
    _serial = 0

    def __init__(self, name=None, size=0):
        if name is None:
            FakeSegment._serial += 1
            name = "fake-%d" % FakeSegment._serial
            self._store[name] = bytearray(size)
        elif name not in self._store:
            raise FileNotFoundError(name)
        self.name = name
        self.buf = memoryview(self._store[name])

    def close(self):
        self.buf.release()

    def unlink(self):
        self._store.pop(self.name, None)


@pytest.fixture
def factory():
    """The stand-in factory, with the module's own registries cleared
    around each test so no segment outlives the test that made it."""
    sfb._published.clear()
    sfb._attached.clear()
    FakeSegment._store = {}
    yield FakeSegment
    sfb._published.clear()
    sfb._attached.clear()
    FakeSegment._store = {}


def round_trip(arrays, factory, slots=None):
    descriptor = sfb.publish(arrays, slots=slots, segment_factory=factory)
    return descriptor, sfb.attach(descriptor, segment_factory=factory)


# --- the per-block read sets ---------------------------------------------


@pytest.fixture(scope="module", params=["PAL", "NTSC"])
def decoder(request):
    """A real bank, because the point of the segment is the real one:
    PAL carries an audio-carrier notch and real-valued RF and MTF halves
    where NTSC carries complex ones, and a packer that only ever saw one
    of those would not be tested at all."""
    return RFDecode(
        inputfreq=40,
        system=request.param,
        decode_analog_audio=44100,
        decode_digital_audio=True,
        has_analog_audio=True,
    )


def test_the_per_block_read_set_round_trips_exactly(decoder, factory):
    spec = decoder.shared_filter_spec()
    _, views = round_trip(spec["arrays"], factory)

    assert set(views.arrays) == set(spec["arrays"])
    for name, original in spec["arrays"].items():
        assert_array_equal(views.arrays[name], original)
        assert views.arrays[name].dtype == original.dtype


def test_the_read_set_is_the_filters_a_block_is_demodulated_against(decoder):
    """The names published are the ones demodblock actually reads, and
    the PAL-only notch is absent on NTSC rather than published empty."""
    names = set(decoder.shared_filter_spec()["arrays"])

    assert {"RFVideo_half", "Frfhpf_half", "Fefm_half", "MTF_half"} <= names
    assert {"audio:left:filt1", "audio:right:filt1"} <= names
    assert ("FcutPAL_half" in names) == (decoder.system == "PAL")


def test_views_are_read_only(decoder, factory):
    _, views = round_trip(decoder.shared_filter_spec()["arrays"], factory)

    for name, view in views.arrays.items():
        assert not view.flags.writeable, name
        with pytest.raises(ValueError):
            view[0] = 0


def test_entries_are_aligned_for_the_vector_loads_that_read_them(decoder,
                                                                 factory):
    descriptor = sfb.publish(decoder.shared_filter_spec()["arrays"],
                             segment_factory=factory)

    for name, entry in descriptor["arrays"].items():
        assert entry["offset"] % sfb.ALIGNMENT == 0, name


def test_one_segment_holds_the_whole_set(decoder, factory):
    descriptor = sfb.publish(decoder.shared_filter_spec()["arrays"],
                             segment_factory=factory)

    assert len(FakeSegment._store) == 1
    total = sum(a.nbytes for a in
                decoder.shared_filter_spec()["arrays"].values())
    assert descriptor["size"] >= total


# --- descriptors are decoded into a pointer and a length, so checked -----


def base_descriptor(factory):
    return sfb.publish({"a": np.arange(8, dtype=np.float64)},
                       segment_factory=factory)


def test_an_unusable_dtype_raises(factory):
    descriptor = base_descriptor(factory)
    descriptor["arrays"]["a"]["dtype"] = "not-a-dtype"

    with pytest.raises(ValueError, match="unusable dtype"):
        sfb.attach(descriptor, segment_factory=factory)


def test_an_object_dtype_raises(factory):
    descriptor = base_descriptor(factory)
    descriptor["arrays"]["a"]["dtype"] = np.dtype(object).str

    with pytest.raises(ValueError, match="cannot live in shared memory"):
        sfb.attach(descriptor, segment_factory=factory)


def test_an_offset_that_overruns_the_segment_raises(factory):
    descriptor = base_descriptor(factory)
    descriptor["arrays"]["a"]["offset"] = descriptor["size"] - 8

    with pytest.raises(ValueError, match="overrun"):
        sfb.attach(descriptor, segment_factory=factory)


def test_a_shape_that_overruns_the_segment_raises(factory):
    descriptor = base_descriptor(factory)
    descriptor["arrays"]["a"]["shape"] = [descriptor["size"]]

    with pytest.raises(ValueError, match="overrun"):
        sfb.attach(descriptor, segment_factory=factory)


def test_a_negative_extent_raises(factory):
    descriptor = base_descriptor(factory)
    descriptor["arrays"]["a"]["shape"] = [-1]

    with pytest.raises(ValueError, match="negative extent"):
        sfb.attach(descriptor, segment_factory=factory)


def test_a_misaligned_offset_raises(factory):
    descriptor = base_descriptor(factory)
    descriptor["arrays"]["a"]["offset"] = 3

    with pytest.raises(ValueError, match="not a valid"):
        sfb.attach(descriptor, segment_factory=factory)


# --- slots ---------------------------------------------------------------


def slot_spec(depth=2, n=8):
    return {"video": (depth, {"stack": np.zeros(n, dtype=np.complex64)})}


def test_a_slot_reads_back_nothing_until_it_is_written(factory):
    descriptor, views = round_trip({}, factory, slots=slot_spec())

    assert views.slots["video"][0].pubid == sfb.UNPUBLISHED
    assert views.slot("video", 0, 1) is None


def test_a_slot_reads_back_only_under_the_id_it_was_stamped_with(factory):
    descriptor, views = round_trip({}, factory, slots=slot_spec())
    value = np.arange(8, dtype=np.complex64)

    sfb.write_slot(descriptor, "video", 0, {"stack": value}, pubid=7)

    assert_array_equal(views.slot("video", 0, 7)["stack"], value)
    assert views.slot("video", 0, 6) is None
    assert views.slot("video", 0, sfb.UNPUBLISHED) is None


def test_a_rewritten_slot_stops_answering_to_the_old_id(factory):
    descriptor, views = round_trip({}, factory, slots=slot_spec())
    sfb.write_slot(descriptor, "video", 0,
                   {"stack": np.arange(8, dtype=np.complex64)}, pubid=7)
    sfb.write_slot(descriptor, "video", 0,
                   {"stack": np.ones(8, dtype=np.complex64)}, pubid=8)

    assert views.slot("video", 0, 7) is None
    assert_array_equal(views.slot("video", 0, 8)["stack"],
                       np.ones(8, dtype=np.complex64))


def test_slots_of_a_family_are_independent(factory):
    descriptor, views = round_trip({}, factory, slots=slot_spec())
    sfb.write_slot(descriptor, "video", 0,
                   {"stack": np.zeros(8, dtype=np.complex64)}, pubid=1)
    sfb.write_slot(descriptor, "video", 1,
                   {"stack": np.ones(8, dtype=np.complex64)}, pubid=2)

    assert_array_equal(views.slot("video", 0, 1)["stack"],
                       np.zeros(8, dtype=np.complex64))
    assert_array_equal(views.slot("video", 1, 2)["stack"],
                       np.ones(8, dtype=np.complex64))


def test_slot_views_are_read_only(factory):
    descriptor, views = round_trip({}, factory, slots=slot_spec())
    sfb.write_slot(descriptor, "video", 0,
                   {"stack": np.arange(8, dtype=np.complex64)}, pubid=1)

    view = views.slot("video", 0, 1)["stack"]
    assert not view.flags.writeable
    with pytest.raises(ValueError):
        view[0] = 0


def test_a_slot_write_that_does_not_fit_raises(factory):
    descriptor, _ = round_trip({}, factory, slots=slot_spec())

    with pytest.raises(ValueError, match="does not fit"):
        sfb.write_slot(descriptor, "video", 0,
                       {"stack": np.zeros(4, dtype=np.complex64)}, pubid=1)


def test_a_slot_cannot_be_stamped_unpublished(factory):
    descriptor, _ = round_trip({}, factory, slots=slot_spec())

    with pytest.raises(ValueError, match="non-zero"):
        sfb.write_slot(descriptor, "video", 0,
                       {"stack": np.zeros(8, dtype=np.complex64)},
                       pubid=sfb.UNPUBLISHED)


def test_an_out_of_range_slot_index_reads_as_a_miss(factory):
    descriptor, views = round_trip({}, factory, slots=slot_spec())

    assert views.slot("video", 5, 1) is None
    assert views.slot("mtf", 0, 1) is None


def test_unlink_releases_the_segment(factory):
    descriptor = sfb.publish({"a": np.arange(4.0)}, segment_factory=factory)
    assert FakeSegment._store

    sfb.unlink(descriptor)
    assert not FakeSegment._store
    # A descriptor this process did not publish is simply not its
    # business; unlinking one twice must not raise on the way out.
    sfb.unlink(descriptor)


# --- the registry, which a thread pool reaches from several threads ------


def test_attach_maps_under_the_registry_lock(factory):
    """The mapping happens inside the lock, not merely the bookkeeping.

    This is the invariant a concurrent test can only sample: if the
    segment were created outside the lock and only recorded inside it,
    two threads could both miss, both map, and the registry would keep
    one of the two mappings while the other thread read through the
    orphan.  Asserted directly, so it cannot regress into a race that
    the timing-based test below happens not to catch.
    """
    descriptor = sfb.publish({"a": np.arange(8.0)}, segment_factory=factory)

    observed = []

    def probing_factory(name=None, size=0):
        observed.append(sfb._registry_lock.locked())
        return FakeSegment(name=name, size=size)

    sfb.attach(descriptor, segment_factory=probing_factory)

    assert observed == [True], (
        "attach() mapped the segment outside the registry lock")


def test_concurrent_attach_maps_the_segment_once(factory):
    """Several threads attaching at once get one mapping between them.

    The process engine only ever attaches once per worker process, so
    this is unobservable there; a pool that ran its workers as threads
    reaches attach() from several at once.
    """
    descriptor = sfb.publish({"a": np.arange(8.0)}, segment_factory=factory)

    created = []

    def slow_factory(name=None, size=0):
        # Widens the window a check-then-set would race in.  With the
        # map inside the lock this cannot fail; without it, it nearly
        # always does.
        time.sleep(0.01)
        segment = FakeSegment(name=name, size=size)
        created.append(segment)
        return segment

    views = []
    errors = []

    def worker():
        try:
            views.append(sfb.attach(descriptor, segment_factory=slow_factory))
        except Exception as exc:            # pragma: no cover - reported below
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
        assert not t.is_alive(), "attach() deadlocked"

    assert not errors, errors
    assert len(created) == 1, (
        "the segment was mapped %d times; attach() raced" % len(created))
    assert len(views) == 8
    # Every thread must be reading the one mapping the registry kept.
    assert all(v.segment is created[0] for v in views)
    for v in views:
        assert_array_equal(v.arrays["a"], np.arange(8.0))


def test_unlink_keeps_this_process_s_own_attachment(factory):
    """unlink() releases the publication and never the mapping.

    ``SharedMemory`` unmaps in ``close()`` and again in ``__del__``
    without raising, even while NumPy views still point into the
    mapping, so releasing an attachment here - or dropping the last
    reference to it - would turn every live view into a segmentation
    fault.  Only the publisher's own segment is released, and the
    attachment is held for the life of the process.
    """
    descriptor = sfb.publish({"a": np.arange(4.0)}, segment_factory=factory)
    views = sfb.attach(descriptor, segment_factory=factory)
    name = descriptor["name"]
    assert name in sfb._attached

    sfb.unlink(descriptor)

    assert name not in sfb._published, "the publication should be released"
    assert name in sfb._attached, (
        "the mapping must be retained; releasing it segfaults live views")
    assert sfb._attached[name] is views.segment
    assert_array_equal(views.arrays["a"], np.arange(4.0))
