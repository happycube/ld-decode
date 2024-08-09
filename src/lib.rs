mod ported;

use std::f64::consts;

use numpy::ndarray::{Array1, ArrayView1, ArrayViewMut1, Zip};
use numpy::{Complex64, IntoPyArray, PyArray1, PyReadonlyArray1, PyReadwriteArray1};
use pyo3::prelude::*;

use ported::{unwrap_angles_impl, unwrap_angles_in_place};

fn complex_angle(input_array: ArrayView1<'_, Complex64>) -> Array1<f64> {
    // Replicate the np.angle function for 1-dimensional input
    // it's possible we could use SIMD in some way to speed this up but that might be complicated.
    let mut output_array = Array1::<f64>::zeros(input_array.len());
    Zip::from(&mut output_array)
        .and(&input_array)
        .for_each(|i, &j| {
            *i = j.im.atan2(j.re);
        });
    output_array
}

fn diff_forward_in_place_impl(mut input_array: ArrayViewMut1<'_, f64>) {
    // output the difference of the output in place, putting 0 in the first element.
    // equivialent to calling np.ediff1d(input_array, to_begin=0)
    for i in (2..input_array.len()).rev() {
        input_array[i] -= input_array[i - 1];
    }
    input_array[1] -= input_array[0];
    input_array[0] = 0.0;
}

fn remove_jumps_and_scale(data: ArrayViewMut1<'_, f64>, freq: f64) {
    for i in data {
        // Further constrain values so they lie within 0..TAU as was done in the
        // original impl
        // TODO: could maybe do this in a more efficient way.
        while *i < 0.0 {
            *i += consts::TAU;
        }
        while *i > consts::TAU {
            *i -= consts::TAU;
        }
        // Scale the output so the demodulated output values corresponds to the specified frequencies.
        *i *= freq / consts::TAU;
    }
}

fn unwrap_hilbert_impl(input_array: ArrayView1<'_, Complex64>, freq: f64) -> Array1<f64> {
    // Demodulate complex luminance data that has had the hilbert transofm done to it to output
    // scaled to the set frequency range.

    // We compute the instantaneous angle of the input data
    let mut tangles = complex_angle(input_array);
    // and then find the difference between these angles to get the instantaneous frequency
    diff_forward_in_place_impl(tangles.view_mut());
    // Ensure unwrapping goes the right way
    // Not needed since this is always set to 0 by the diff function.
    /* if tangles[0] < -std::f64::consts::PI {
        tangles[0] += std::f64::consts::TAU;
    }*/

    // We then unwrap the resulting angles to get a coherent signal.
    unwrap_angles_in_place(tangles.view_mut());
    // Finally remove outliers and scale the signal.
    remove_jumps_and_scale(tangles.view_mut(), freq);

    tangles
}

#[pyfunction]
fn complex_angle_py<'py>(
    py: Python<'py>,
    input_array: PyReadonlyArray1<'py, Complex64>,
) -> Bound<'py, PyArray1<f64>> {
    let input_array = input_array.as_array();
    let output_array = py.allow_threads(|| complex_angle(input_array));
    output_array.into_pyarray_bound(py)
}

#[pyfunction]
fn unwrap_angles<'py>(
    py: Python<'py>,
    input_array: PyReadonlyArray1<'py, f64>,
) -> Bound<'py, PyArray1<f64>> {
    let input_array = input_array.as_array();
    let output_array = py.allow_threads(|| unwrap_angles_impl(input_array));
    output_array.into_pyarray_bound(py)
}

#[pyfunction]
fn diff_forward_in_place<'py>(py: Python<'py>, mut input_array: PyReadwriteArray1<'py, f64>) {
    let input_array = input_array.as_array_mut();
    py.allow_threads(|| diff_forward_in_place_impl(input_array));
}

#[pyfunction]
fn unwrap_hilbert<'py>(
    py: Python<'py>,
    input_array: PyReadonlyArray1<'py, Complex64>,
    freq: f64,
) -> Bound<'py, PyArray1<f64>> {
    let input_array = input_array.as_array();
    let output_array = py.allow_threads(|| unwrap_hilbert_impl(input_array, freq));
    output_array.into_pyarray_bound(py)
}

/// A Python module implemented in Rust. The name of this function must match
/// the `lib.name` setting in the `Cargo.toml`, else Python will not be able to
/// import the module.
#[pymodule]
fn vhsd_rust(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(complex_angle_py, m)?)?;
    m.add_function(wrap_pyfunction!(unwrap_angles, m)?)?;
    m.add_function(wrap_pyfunction!(diff_forward_in_place, m)?)?;
    m.add_function(wrap_pyfunction!(unwrap_hilbert, m)?)?;
    Ok(())
}
