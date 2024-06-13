import cython


import numpy as np
cimport numpy as np
#from math import pi, tau
import math


cpdef complex[:] diff_center(complex[:] input_array):
    """Center diff of array"""
    assert len(input_array) > 4
    cdef complex[:] output_array = np.zeros_like(input_array)
    output_array[0] = input_array[1] * 0.5
    output_array[-1] = -input_array[-2] * 0.5
    for i in range(1, len(input_array) - 1):
        output_array[i] = -(0.5 * input_array[i - 1]) + (0.5 * input_array[i + 1])

    return output_array


cdef double[:] diff_forward_inplace(double[:] input_array):
    """Return the forward diff on the input array in place"""
    cdef int i = 0
    assert len(input_array) > 4
    for i in range(len(input_array) - 1, 1, -1):
        input_array[i] = input_array[i] - input_array[i - 1]

    input_array[1] = input_array[1] - input_array[0]
    input_array[0] = 0


    return input_array

cdef double[:] diff_forward(double[:] input_array):
    """Return the forward diff on the input array - not used currently"""
    assert len(input_array) > 4
    cdef double[:] output_array = np.zeros_like(input_array)
    cdef int i = 0
    output_array[0] = 0
    output_array[2] = input_array[1] - input_array[0]
    #output_array[-1] = input_array[-2] - input_array[-1]
    #output_array[-1] = -input_array[-2] * 0.5
    #for i in range(1, len(input_array) - 1):
    #    output_array[i] = (-0.5*input_array[i + 1]) + (2 * input_array[i]) + (-1.5 * input_array[i - 1])

    #
    #for i in range(2, len(input_array) - 1):
    #    output_array[i] = (1.5*input_array[i]) - (2 * input_array[i - 1]) + (0.5 * input_array[i - 2])

    for i in range(1, len(input_array)):
        output_array[i] = input_array[i] - input_array[i - 1]


    return output_array

# 
def unwrap_hilbert(double complex[:] hilbert, cython.double freq_hz):
    cdef cython.double pi = math.pi
    cdef cython.double tau = math.tau
    cdef double[:] tangles = np.angle(hilbert)
    # np.ediff1d(tangles, to_begin=0)
    tangles = diff_forward_inplace(tangles)
    cdef np.ndarray tdangles2
    # make sure unwapping goes the right way
    if tangles[0] < -pi:
        tangles[0] += tau

    tdangles2 = np.unwrap(tangles)
    #del dangles
    # With extremely bad data, the unwrapped angles can jump.
    while np.min(tdangles2) < 0:
        tdangles2[tdangles2 < 0] += tau
    while np.max(tdangles2) > tau:
        tdangles2[tdangles2 > tau] -= tau
    tdangles2 *= (freq_hz / tau)
    return tdangles2
