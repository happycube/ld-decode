"""Shared .lds test vectors.

The packing tests (tests/unit/) and the writer/CLI tests (tests/functional/)
exercise the same converter from either side of the hermetic boundary, so the
sample data they drive it with is generated here rather than duplicated.

Both generators are seeded: the same bytes come out on every run and on every
machine, which is what makes a byte-exact failure mean a real change in the
converter rather than a different draw.
"""

import random

import numpy as np


def packed_bytes():
    """A .lds byte stream: every field boundary in the 5-byte group, then noise.

    The hand-built prefix walks each bit field of the 4-samples-in-5-bytes
    layout to its limits; the seeded tail covers the ordinary case in bulk.
    """
    rng = random.Random(1234)
    edge = bytearray()
    for pattern in (0x00, 0x01, 0x02, 0x03, 0x3F, 0x40, 0x7F, 0x80, 0xC0, 0xFE, 0xFF):
        edge.extend([pattern] * 5)
    for a in (0x00, 0xFF, 0x80, 0x7F):
        for b in (0x00, 0xFF, 0x3F, 0xC0):
            edge.extend([a, b, a, b, a])
    return bytes(edge) + bytes(rng.randrange(256) for _ in range(5 * 5000))


def sample_array():
    """20,000 seeded int16 samples spanning the full 16-bit range."""
    rng = random.Random(5678)
    return np.array(
        [rng.randrange(-32768, 32768) for _ in range(4 * 5000)], dtype=np.int16
    )
