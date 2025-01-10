from vhsd_rust import sosfiltfilt, sosfiltfilt_f32
import numpy as np
import scipy.signal as sps


def sos_filter_as_array_and_order(filter):
    """Convert the sos filter to a array derive the filter order for use inside
    rust code with sci_rs
    We do this here rather than in rust for now for easier interop."""
    filter_view = filter.ravel()
    assert (
        len(filter_view) % 6 == 0
    ), "filter length is not divideable by 6, there is a bug somewhere!"
    return int(len(filter_view) / 6), filter_view


def sosfiltfilt_rust(sos, input):
    assert input.dtype != np.complex128
    order, filter = sos_filter_as_array_and_order(sos)
    if input.dtype == np.complex128:
        input = abs(input)

    if input.dtype == np.float64:
        return sosfiltfilt(order, filter, input)
    # if input.dtype == np.float32:
    #    return sosfiltfilt_f32(order, filter, input)
    else:
        return sosfiltfilt_f32(order, filter, input.astype(np.float32))
