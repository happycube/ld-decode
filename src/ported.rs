/*** Copyright (c) 2005-2024, NumPy Developers.
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are
met:

    * Redistributions of source code must retain the above copyright
       notice, this list of conditions and the following disclaimer.

    * Redistributions in binary form must reproduce the above
       copyright notice, this list of conditions and the following
       disclaimer in the documentation and/or other materials provided
       with the distribution.

    * Neither the name of the NumPy Developers nor the names of any
       contributors may be used to endorse or promote products derived
       from this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
"AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
(INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
***/

// Ported from numpy code hence copyright notice/BSD license

use numpy::ndarray::{Array1, ArrayView1, ArrayViewMut1};

pub fn unwrap_angles_impl(input_array: ArrayView1<'_, f64>) -> Array1<f64> {
    let mut output_array = input_array.to_owned();
    unwrap_angles_in_place(output_array.view_mut());
    output_array
}

pub fn unwrap_angles_in_place(mut output_array: ArrayViewMut1<'_, f64>) {
    // Port of numpy unwrap function using default parameters and a 1d double precision floating point array
    let discont = std::f64::consts::PI; // period / 2
    let period = std::f64::consts::TAU;
    let interval_high = discont; // period / 2
    let interval_low = -discont; // period / 2

    assert!(!output_array.is_empty());

    // TODO: performance seems to be a tad slower than numpy even though we're doing this in one pass
    // while numpy does several loops and array copies.
    // Will need to see if it can get auto-vectorized properly which it might not be yet - so may need some rework to optimize better.
    // NOTE: Skipping first element here - since we know it's going to be 0 anyway we don't bother putting in extra code for it
    // simplifying the code.
    for i in 1..output_array.len() {
        let diff = output_array[i] - output_array[i - 1];
        // Note - rem_euclid has diff behavoiur to python mod if both args are negative but
        // period should always be positive so that should be fine.
        let mut diff_mod = ((diff - interval_low).rem_euclid(period)) + interval_low;

        if (diff_mod == interval_low) && (diff > 0.0) {
            diff_mod = interval_high;
        }

        let mut correct = diff_mod - diff;
        if diff.abs() < discont {
            correct = 0.0;
        }

        output_array[i] += correct;
    }
}
