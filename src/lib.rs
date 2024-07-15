mod ported;

use numpy::ndarray::{Array1, ArrayView1, ArrayViewMut1, Zip};
use numpy::{Complex64, IntoPyArray, PyArray1, PyReadonlyArray1, PyReadwriteArray1};
use pyo3::prelude::*;

use ported::unwrap_angles_impl;

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

/// A Python module implemented in Rust. The name of this function must match
/// the `lib.name` setting in the `Cargo.toml`, else Python will not be able to
/// import the module.
#[pymodule]
fn vhsd_rust(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(complex_angle_py, m)?)?;
    m.add_function(wrap_pyfunction!(unwrap_angles, m)?)?;
    m.add_function(wrap_pyfunction!(diff_forward_in_place, m)?)?;
    Ok(())
}
