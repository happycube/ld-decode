use numpy::ndarray::{Array1, ArrayView1};
use sci_rs::signal::filter::design::Sos;
use sci_rs::signal::filter::sosfiltfilt_dyn;

pub fn sos_filtfilt(
    sos_order: u32,
    sos_filter: ArrayView1<'_, f64>,
    input_array: ArrayView1<'_, f64>,
) -> Array1<f64> {
    let sos_filter_vec = sos_filter.to_vec();
    let sos = Sos::from_scipy_dyn(sos_order as usize, sos_filter_vec);
    let ret = sosfiltfilt_dyn(input_array.iter(), &sos);
    Array1::from_vec(ret)
}

pub fn sos_filtfilt_f32(
    sos_order: u32,
    sos_filter: ArrayView1<'_, f64>,
    input_array: ArrayView1<'_, f32>,
) -> Array1<f32> {
    let sos_filter_vec: Vec<f32> = sos_filter.iter().map(|&value| value as f32).collect();
    let sos = Sos::from_scipy_dyn(sos_order as usize, sos_filter_vec);
    let ret = sosfiltfilt_dyn(input_array.iter(), &sos);
    Array1::from_vec(ret)
}
