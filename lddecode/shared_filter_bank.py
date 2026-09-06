"""One shared-memory segment holding the filters every worker reads.

Each field-decode worker holds its own RFDecode, and so its own copy of
the filter bank.  About 1.2 MiB of that bank - the positive-frequency
halves demodblock multiplies against, the EFM front end, the two audio
stage-1 filters - is identical in every process and never changes once
the decoder is calibrated.  Four workers therefore keep four copies of
the same numbers in four sets of pages, and every block demodulation
pulls its own copy through L3.  Publishing them once and mapping that
segment into each worker leaves one copy.

Two kinds of entry live here:

- **Arrays**, written by :func:`publish` and read-only for the rest of
  the segment's life.  These are the filters that do not depend on
  anything a job carries.
- **Slots**, fixed-size holders the publisher rewrites as a parameter
  moves: the video output stack when the inverse-MTF strength or the
  dynamic EQ changes, the MTF response when the level does.  Each slot
  carries a publication id in its header, and a reader that was told
  which id to expect uses the slot only while the header still matches.

Thread-safety and lifetime:

- Views handed out by :func:`attach` are read-only (``flags.writeable``
  is False), so no reader can disturb another process's filters.
- The segment lives as long as its publisher: :func:`unlink` removes the
  name, and POSIX keeps the mapping alive in every process that already
  attached until that process exits.  Readers never unlink, and an
  attached reader is unaffected by an unlink mid-flight (which is what
  a worker-pool restart does).
- An attachment is never released, only registered.  ``SharedMemory``
  unmaps in ``close()`` *and* in ``__del__`` without raising, even while
  NumPy views still point into the mapping, so letting go of one - by
  closing it or by dropping the last reference - segfaults every view
  that outlives it.  Holding it is the whole job of ``_attached``.
- The two registries below are guarded by a lock, because a process
  that runs its workers as threads reaches :func:`attach` from several
  of them at once and the check-then-set would otherwise map the same
  segment twice.  Nothing else here locks: rewriting a slot is only safe
  because the publisher rewrites one no reader can still be using, and
  the publication id is the reader's check on that discipline, not a
  substitute for it.
- ``segment_factory`` is injected so tests can back a segment with a
  bytearray and never touch /dev/shm.

The module has no intra-package imports: NumPy and, for the default
factory, ``multiprocessing.shared_memory``.
"""

import threading

import numpy as np

#: Every entry starts on a 64-byte boundary.  These arrays are FFT
#: operands read straight into vector registers, and an unaligned one
#: costs a split load on every cache line it crosses.
ALIGNMENT = 64

#: One unsigned 64-bit publication id ahead of each slot's arrays.
HEADER_DTYPE = np.dtype("<u8")

#: Slot ids start at 1 so that zero means "nothing published here".
UNPUBLISHED = 0

# Segments this process created (publish) and mapped (attach).  Both are
# held because a SharedMemory that is garbage-collected closes its
# mapping, and the views handed out point into it.
_published = {}
_attached = {}

#: Guards _published and _attached.  Held across attach()'s
#: check-then-set, which has to map under it, and otherwise only across
#: the dictionary operations themselves.
_registry_lock = threading.Lock()


def shared_memory_segment(name=None, size=0):
    """The default factory: a POSIX shared-memory segment.

    Called with a size to create one, with a name to map an existing
    one.  The object it returns needs a ``name`` and a writable ``buf``,
    which is all :func:`publish` and :func:`attach` use.
    """
    from multiprocessing import shared_memory

    if name is None:
        return shared_memory.SharedMemory(create=True, size=size)
    return shared_memory.SharedMemory(name=name)


def _align(offset):
    return -(-offset // ALIGNMENT) * ALIGNMENT


def _describe(array, offset):
    return {
        "offset": int(offset),
        "shape": [int(d) for d in array.shape],
        "dtype": array.dtype.str,
    }


def _checked(entry, capacity, what):
    """(shape, dtype, offset) for a descriptor entry, or ValueError.

    A descriptor is built by this module and travels only as a pool
    initializer's argument, but it is still decoded into a raw pointer
    and a length: check it rather than trust it.
    """
    try:
        dtype = np.dtype(entry["dtype"])
    except (KeyError, TypeError) as exc:
        raise ValueError(
            "%s: unusable dtype %r" % (what, entry.get("dtype"))
        ) from exc
    if dtype.hasobject:
        raise ValueError("%s: dtype %s cannot live in shared memory"
                         % (what, dtype))

    shape = tuple(int(d) for d in entry["shape"])
    if any(d < 0 for d in shape):
        raise ValueError("%s: negative extent in shape %r" % (what, shape))

    nbytes = dtype.itemsize
    for d in shape:
        nbytes *= d

    offset = int(entry["offset"])
    if offset < 0 or offset % dtype.itemsize:
        raise ValueError("%s: offset %d is not a valid %s boundary"
                         % (what, offset, dtype))
    if offset + nbytes > capacity:
        raise ValueError(
            "%s: bytes %d..%d overrun the %d-byte segment"
            % (what, offset, offset + nbytes, capacity)
        )
    return shape, dtype, offset


def _map(buf, entry, capacity, what, writable):
    shape, dtype, offset = _checked(entry, capacity, what)
    view = np.ndarray(shape, dtype=dtype, buffer=buf, offset=offset)
    if not writable:
        view.flags.writeable = False
    return view


class SlotView:
    """One publisher-rewritable holder, as a reader sees it.

    ``read(pubid)`` is the whole interface: it returns the slot's arrays
    if the slot still holds that publication id, and None otherwise, so
    a reader that has been handed a stale id falls back rather than
    using filters that have moved under it.
    """

    __slots__ = ("_header", "_arrays")

    def __init__(self, header, arrays):
        self._header = header
        self._arrays = arrays

    @property
    def pubid(self):
        return int(self._header[0])

    def read(self, pubid):
        if pubid and int(self._header[0]) == int(pubid):
            return self._arrays
        return None


class SharedFilterViews:
    """What a worker gets back from :func:`attach`."""

    __slots__ = ("arrays", "slots", "segment")

    def __init__(self, arrays, slots, segment):
        self.arrays = arrays        # name -> read-only ndarray
        self.slots = slots          # family -> [SlotView, ...]
        self.segment = segment

    def slot(self, family, index, pubid):
        """The arrays of one slot if it still holds pubid, else None."""
        entries = self.slots.get(family)
        if not entries or not 0 <= index < len(entries):
            return None
        return entries[index].read(pubid)


def publish(arrays, slots=None, segment_factory=None):
    """Pack ``arrays`` - and empty slots - into one segment.

    ``arrays`` maps a name to the array whose contents are copied in.
    ``slots`` maps a family name to ``(count, {name: template})``, where
    the template supplies shape and dtype only: a slot's contents are
    undefined until :func:`write_slot` fills it, and its header reads
    ``UNPUBLISHED`` until then.

    Returns a descriptor of plain ints and strings, so it travels in a
    pool initializer's arguments.  The publisher keeps the segment
    alive until :func:`unlink`.
    """
    if segment_factory is None:
        segment_factory = shared_memory_segment

    offset = 0
    layout = {}
    pending = []
    for name in sorted(arrays):
        array = np.ascontiguousarray(arrays[name])
        offset = _align(offset)
        layout[name] = _describe(array, offset)
        pending.append((offset, array))
        offset += array.nbytes

    slot_layout = {}
    for family in sorted(slots or {}):
        count, templates = slots[family]
        entries = []
        for _ in range(int(count)):
            offset = _align(offset)
            header = offset
            offset += HEADER_DTYPE.itemsize
            members = {}
            for name in sorted(templates):
                template = np.asarray(templates[name])
                offset = _align(offset)
                members[name] = _describe(template, offset)
                offset += template.nbytes
            entries.append({"header": header, "arrays": members})
        slot_layout[family] = entries

    size = max(_align(offset), ALIGNMENT)
    segment = segment_factory(size=size)
    descriptor = {
        "name": segment.name,
        "size": size,
        "arrays": layout,
        "slots": slot_layout,
    }

    buf = segment.buf
    for at, array in pending:
        target = np.ndarray(array.shape, dtype=array.dtype,
                            buffer=buf, offset=at)
        target[...] = array
        del target
    for entries in slot_layout.values():
        for entry in entries:
            header = np.ndarray((1,), dtype=HEADER_DTYPE, buffer=buf,
                                offset=entry["header"])
            header[0] = UNPUBLISHED
            del header
    del buf

    with _registry_lock:
        _published[descriptor["name"]] = segment
    return descriptor


def write_slot(descriptor, family, index, arrays, pubid):
    """Fill one slot and stamp it with ``pubid``.

    The header is cleared first and stamped last, so a reader can never
    see the id of a value whose arrays are still being written.  That
    ordering is a guard, not a protocol: the caller is responsible for
    only rewriting a slot no reader can still be using.
    """
    if not pubid:
        raise ValueError("a slot's publication id must be non-zero")

    with _registry_lock:
        segment = _published.get(descriptor["name"])
    if segment is None:
        raise LookupError("segment %r was not published by this process"
                          % (descriptor["name"],))

    entry = descriptor["slots"][family][index]
    capacity = min(int(descriptor["size"]), len(segment.buf))

    buf = segment.buf
    header = np.ndarray((1,), dtype=HEADER_DTYPE, buffer=buf,
                        offset=entry["header"])
    header[0] = UNPUBLISHED
    for name, member in entry["arrays"].items():
        what = "%s slot %d/%s" % (family, index, name)
        source = np.ascontiguousarray(arrays[name])
        target = _map(buf, member, capacity, what, writable=True)
        if source.shape != target.shape or source.dtype != target.dtype:
            raise ValueError(
                "%s: %s %s does not fit the slot's %s %s"
                % (what, source.dtype, source.shape,
                   target.dtype, target.shape)
            )
        target[...] = source
        del target
    header[0] = int(pubid)
    del header
    del buf


def attach(descriptor, segment_factory=None):
    """Map a published segment and return read-only views of it.

    The reader holds the mapping for the life of the process; the views
    stay valid even if the publisher unlinks the name (POSIX keeps the
    mapping until the last process using it goes away).
    """
    if segment_factory is None:
        segment_factory = shared_memory_segment

    name = descriptor["name"]
    with _registry_lock:
        segment = _attached.get(name)
        if segment is None:
            # Mapped under the lock, not merely recorded under it: two
            # worker threads attaching at once would otherwise both miss
            # and map the same segment twice, and the registry would keep
            # only one of the two mappings.
            segment = segment_factory(name=name)
            _attached[name] = segment

    buf = segment.buf
    capacity = min(int(descriptor["size"]), len(buf))

    arrays = {
        key: _map(buf, entry, capacity, key, writable=False)
        for key, entry in descriptor["arrays"].items()
    }

    slots = {}
    for family, entries in descriptor.get("slots", {}).items():
        views = []
        for index, entry in enumerate(entries):
            what = "%s slot %d" % (family, index)
            header = _map(buf, {"offset": entry["header"], "shape": [1],
                                "dtype": HEADER_DTYPE.str},
                          capacity, what + " header", writable=False)
            members = {
                name: _map(buf, member, capacity, what + "/" + name,
                           writable=False)
                for name, member in entry["arrays"].items()
            }
            views.append(SlotView(header, members))
        slots[family] = views

    return SharedFilterViews(arrays, slots, segment)


def unlink(descriptor):
    """Release a segment this process published.

    Safe while readers are still attached, and a no-op for a descriptor
    this process did not publish.

    A mapping this process took with :func:`attach` is deliberately *not*
    released here, and must not be: ``SharedMemory.close()`` unmaps the
    segment without raising even when NumPy views still point into it,
    and so does its ``__del__``, so releasing the mapping - or merely
    dropping the last reference to it - turns every live view into a
    segmentation fault.  An attachment is held for the life of the
    process, which is what the registry above is for.
    """
    with _registry_lock:
        segment = _published.pop(descriptor["name"], None)
    if segment is None:
        return
    for release in ("close", "unlink"):
        method = getattr(segment, release, None)
        if method is None:
            continue
        try:
            method()
        except (OSError, BufferError, FileNotFoundError):
            # An already-removed name, or a mapping a reader in this
            # process still holds: neither is worth failing a shutdown
            # over, and the segment goes with the process either way.
            pass
