# NTSC Burst Phase Offset Investigation (2026-06-20)

## Problem

Median burst phase across all TBC output lines consistently measured ~139° instead of the ideal ~147° (NTSC standard burst phase). Consistent across different source discs — a decoder-side systematic bias.

## Root Cause

The `shift33` constant in `FieldNTSC.process()` (core.py ~line 3034). The old code:

```python
shift33 = 83 * (np.pi / 180)
self.linelocs = self.apply_offsets(self.linelocs4, -shift33 - 0)
```

had a unit mismatch: `apply_offsets` treats `phaseoffset` as output samples (converting via `* freq / outfreq`), but `shift33` was passed in radians. Each degree of the constant produced ~pi/2 degrees of actual subcarrier shift, not 1:1. The comment "This should be 33 but this is what makes it line up" acknowledged the confusion.

## Fix Applied

Replaced with a clean formula using degrees of subcarrier directly:

```python
fsc_phase_deg = 122.5
shift_samples = (fsc_phase_deg / 360) / self.rf.SysParams["fsc_mhz"] * self.rf.freq
self.linelocs = np.array(self.linelocs4) - shift_samples
```

The constant 122.5° is the actual subcarrier phase offset, equivalent to the old `shift33 = 78 * pi/180` (78 * pi/2 = 122.52°). Measured median burst phase after fix: ~147.5°.

## Calibration Math

- Old constant 83 → measured 139.6°
- Each degree of the old constant shifted subcarrier by pi/2 ≈ 1.5708°
- To correct by +7.8°: delta = 7.8 / (pi/2) ≈ 5
- New old-style constant = 83 - 5 = 78
- In clean units: 78 * pi/2 = 122.5° of subcarrier

**Direction:** Increasing the phase shift constant moves burst phase DOWN (tested: 83→88 dropped 139→131). Decreasing moves it UP (83→78 raised 139→147.5).

## What Was Investigated and Ruled Out

These are all potential sources of phase offset that were checked and found NOT to contribute:

### 1. `outlinelen` rounding
Exactly 910 samples = 227.5 * 4, zero fractional error. No contribution. (core.py `calclinelen`, SysParams_NTSC)

### 2. IIR filter phase at fSC
The `Fvideo_lpf` and `Fdeemp` filters have significant phase response at fSC (~155° combined), but this affects both `demod_burst` (used for burst locking) and `demod` (used for output) equally, so it cancels out. Would only matter if burst locking used a different signal path than the output.

### 3. FIR burst filter compensation
The 81-tap FIR with delay 40 samples is correctly compensated via a frequency-domain shift (core.py ~line 719). No residual offset.

### 4. 1D comb filter in CombNTSC
At fSC with 4*fSC sampling, `(data[n-2] + data[n+2])/2 - data[n]` has gain = -2 and phase = exactly 180°. This is a property of the symmetric ±2 tap structure at quarter-cycle spacing. No fractional phase contribution. (metrics.py `buildCBuffer`)

### 5. Sinc interpolation in `scale_field`
16-tap symmetric kernel, centered at tap index 7. No half-sample offset that could introduce phase. (core.py `scale_field`)

### 6. `computewow_scaled`
Output pixel 0 of each line maps exactly to `linelocs[line]`, no additional bias introduced.

### 7. Burst locking half-correction damping
The `/2` damping factor in `refine_linelocs_burst` (~line 2933) is compensated by feeding the full value back via `phase_adjust_median`. No systematic bias — just convergence rate.

### 8. `getlinephase` correctness
The NTSC 4-field color phase sequence logic in metrics.py correctly models the relationship between fieldPhaseID, line parity, and I/Q sign patterns.

## Key Takeaway

When debugging phase issues in the NTSC pipeline, start at the `fsc_phase_deg` constant and the burst locking path (`refine_linelocs_burst`). The filter chain, comb filter, and resampling are phase-neutral by design/verification.
