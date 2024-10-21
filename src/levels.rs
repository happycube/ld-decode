use pyo3::prelude::*;
use numpy::ndarray::{ArrayView1, s};
use pyo3::types::{PyList, PyTuple};

const PULSE_START: usize = 0;
const PULSE_LEN: usize = 1;

pub fn _hz_to_ire(sys_params_hz_ire: i64, sys_params_ire0: i64, hz: i64, ire0: Option<i64>) -> i64 {
    let ire0 = ire0.unwrap_or(sys_params_ire0);
    (hz - ire0) / sys_params_hz_ire
}

pub const fn _ire_to_hz(sys_params_ire0: i64, sys_params_hz_ire: i64, ire: i64) -> i64 {
    sys_params_ire0 + (sys_params_hz_ire * ire)
}

pub fn fallback_vsync_loc_means_impl<'a>(py: Python<'a>, demod_05: ArrayView1<'_, f64>, pulses: Bound<'a, PyList>, sample_freq_mhz: f64, min_len: f64, max_len: f64) -> (Bound<'a, PyList>, Bound<'a, PyList>) {
    let vsync_locs = PyList::empty_bound(py);
    let vsync_means = PyList::empty_bound(py);
    
    let mean_pos_offset = sample_freq_mhz;
    
    
    let list_iter = pulses.iter().enumerate();
    
    for (i, p) in list_iter {
        let pulse: &Bound<'a, PyTuple> = p.downcast().unwrap();
        let pulse_start = pulse.get_item(PULSE_START).unwrap().extract::<i64>().unwrap();
        let pulse_len = pulse.get_item(PULSE_LEN).unwrap().extract::<i64>().unwrap();
        if (pulse_len as f64) > min_len && (pulse_len as f64) < max_len {
            vsync_locs.append(i).unwrap();
            let a = (pulse_start + (mean_pos_offset as i64)) as usize;
            let b = (pulse_start + pulse_len - (mean_pos_offset as i64)) as usize;
            let s_mean = demod_05.slice(s![a..b]).mean().unwrap();
            vsync_means.append(s_mean).unwrap();
        }
    }
    
    (vsync_locs, vsync_means)
}