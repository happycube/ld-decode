import cython

import numpy as np
from math import pi, tau


def unwrap_hilbert(hilbert, cython.float freq_hz):
    tangles = np.angle(hilbert)
    dangles = np.ediff1d(tangles, to_begin=0)

    # make sure unwapping goes the right way
    if dangles[0] < -pi:
        dangles[0] += tau

    tdangles2 = np.unwrap(dangles)
    # With extremely bad data, the unwrapped angles can jump.
    while np.min(tdangles2) < 0:
        tdangles2[tdangles2 < 0] += tau
    while np.max(tdangles2) > tau:
        tdangles2[tdangles2 > tau] -= tau
    return tdangles2 * (freq_hz / tau)
