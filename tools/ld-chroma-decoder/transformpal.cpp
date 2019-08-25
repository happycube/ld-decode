/************************************************************************

    transformpal.cpp

    ld-chroma-decoder - Colourisation filter for ld-decode
    Copyright (C) 2019 Adam Sampson

    Reusing code from pyctools-pal, which is:
    Copyright (C) 2014 Jim Easterbrook

    This file is part of ld-decode-tools.

    ld-chroma-decoder is free software: you can redistribute it and/or
    modify it under the terms of the GNU General Public License as
    published by the Free Software Foundation, either version 3 of the
    License, or (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program.  If not, see <http://www.gnu.org/licenses/>.

************************************************************************/

#include "transformpal.h"

#include <QtMath>
#include <cassert>
#include <cmath>

/*!
    \class TransformPal

    Transform PAL filter, based on Jim Easterbrook's implementation in
    pyctools-pal. Given a composite signal, this extracts a chroma signal from
    it using frequency-domain processing.

    For a description of the algorithm with examples, see the Transform PAL web
    site (http://www.jim-easterbrook.me.uk/pal/).

    Note that this is only a 2D implementation at the moment, which limits the
    quality of the output; it would be possible to extend it to 3D given access
    to multiple fields.
 */

// Compute one value of the window function, applied to the data blocks before
// the FFT to reduce edge effects. This is a symmetrical raised-cosine
// function, which means that the overlapping inverse-FFT blocks can be summed
// directly without needing an inverse window function.
static double computeWindow(qint32 element, qint32 limit)
{
    return 0.5 - (0.5 * cos((2 * M_PI * (element + 0.5)) / limit));
}

TransformPal::TransformPal()
    : configurationSet(false)
{
    // Compute the window function.
    for (qint32 y = 0; y < YTILE; y++) {
        const double windowY = computeWindow(y, YTILE);
        for (qint32 x = 0; x < XTILE; x++) {
            const double windowX = computeWindow(x, XTILE);
            windowFunction[y][x] = windowY * windowX;
        }
    }

    // Allocate buffers for FFTW. These must be allocated using FFTW's own
    // functions so they're properly aligned for SIMD operations.
    fftReal = fftw_alloc_real(YTILE * XTILE);
    fftComplexIn = fftw_alloc_complex(YCOMPLEX * XCOMPLEX);
    fftComplexOut = fftw_alloc_complex(YCOMPLEX * XCOMPLEX);

    // Plan FFTW operations
    forwardPlan = fftw_plan_dft_r2c_2d(YTILE, XTILE, fftReal, fftComplexIn, FFTW_MEASURE);
    inversePlan = fftw_plan_dft_c2r_2d(YTILE, XTILE, fftComplexOut, fftReal, FFTW_MEASURE);
}

TransformPal::~TransformPal()
{
    // Free FFTW plans and buffers
    fftw_destroy_plan(forwardPlan);
    fftw_destroy_plan(inversePlan);
    fftw_free(fftReal);
    fftw_free(fftComplexIn);
    fftw_free(fftComplexOut);
}

void TransformPal::updateConfiguration(const LdDecodeMetaData::VideoParameters &_videoParameters,
                                       double _threshold)
{
    videoParameters = _videoParameters;
    threshold = _threshold;

    // Resize the chroma buffer
    chromaBuf.resize(videoParameters.fieldWidth * videoParameters.fieldHeight);

    configurationSet = true;
}

const double *TransformPal::filterField(qint32 firstFieldLine, qint32 lastFieldLine, const SourceField &inputField)
{
    assert(configurationSet);

    // Check we have a valid input field
    assert(!inputField.data.isNull());

    // Check that there is enough horizontal space around the active region to
    // overlap safely by half a tile. (We can't do this vertically because we'd
    // run into the VBI data, so we have to pad with black lines on the Y
    // axis.)
    assert((videoParameters.activeVideoStart - videoParameters.colourBurstEnd) >= HALFXTILE);
    assert((videoParameters.fieldWidth - videoParameters.activeVideoEnd) >= HALFXTILE);

    // Clear chromaBuf
    chromaBuf.fill(0.0);

    // Iterate through the overlapping tile positions, covering the active area.
    // (See TransformThread member variable documentation for how the tiling works.)
    for (qint32 tileY = firstFieldLine - HALFYTILE; tileY < lastFieldLine; tileY += HALFYTILE) {
        for (qint32 tileX = videoParameters.activeVideoStart - HALFXTILE; tileX < videoParameters.activeVideoEnd; tileX += HALFXTILE) {
            // Compute the forward FFT
            forwardFFTTile(tileX, tileY, inputField, firstFieldLine, lastFieldLine);

            // Apply the frequency-domain filter
            applyFilter();

            // Compute the inverse FFT
            inverseFFTTile(tileX, tileY, firstFieldLine, lastFieldLine);
        }
    }

    return chromaBuf.data();
}

// Apply the forward FFT to an input tile, populating fftComplexIn
void TransformPal::forwardFFTTile(qint32 tileX, qint32 tileY, const SourceField &inputField, qint32 firstFieldLine, qint32 lastFieldLine)
{
    // Work out which lines of this tile are within the active region
    const qint32 startY = qMax(firstFieldLine - tileY, 0);
    const qint32 endY = qMin(lastFieldLine - tileY, YTILE);

    // Copy the input signal into fftReal, applying the window function
    const quint16 *inputPtr = reinterpret_cast<const quint16 *>(inputField.data.data());
    for (qint32 y = 0; y < YTILE; y++) {
        // If this frame line is above/below the active region, fill it with
        // black instead.
        if (y < startY || y >= endY) {
            for (qint32 x = 0; x < XTILE; x++) {
                fftReal[(y * XTILE) + x] = videoParameters.black16bIre * windowFunction[y][x];
            }
            continue;
        }

        const quint16 *b = inputPtr + ((tileY + y) * videoParameters.fieldWidth);
        for (qint32 x = 0; x < XTILE; x++) {
            fftReal[(y * XTILE) + x] = b[tileX + x] * windowFunction[y][x];
        }
    }

    // Convert time domain in fftReal to frequency domain in fftComplexIn
    fftw_execute(forwardPlan);
}

// Apply the inverse FFT to fftComplexOut, overlaying the result into chromaBuf
void TransformPal::inverseFFTTile(qint32 tileX, qint32 tileY, qint32 firstFieldLine, qint32 lastFieldLine)
{
    // Work out what portion of this tile is inside the active area
    const qint32 startX = qMax(videoParameters.activeVideoStart - tileX, 0);
    const qint32 endX = qMin(videoParameters.activeVideoEnd - tileX, XTILE);
    const qint32 startY = qMax(firstFieldLine - tileY, 0);
    const qint32 endY = qMin(lastFieldLine - tileY, YTILE);

    // Convert frequency domain in fftComplexOut back to time domain in fftReal
    fftw_execute(inversePlan);

    // Overlay the result, normalising the FFTW output, into chromaBuf
    double *outputPtr = chromaBuf.data();
    for (qint32 y = startY; y < endY; y++) {
        double *b = outputPtr + ((tileY + y) * videoParameters.fieldWidth);
        for (qint32 x = startX; x < endX; x++) {
            b[tileX + x] += fftReal[(y * XTILE) + x] / (YTILE * XTILE);
        }
    }
}

// Return the absolute value squared of an fftw_complex
static inline double fftwAbsSq(const fftw_complex &value)
{
    return (value[0] * value[0]) + (value[1] * value[1]);
}

// Apply the frequency-domain filter
void TransformPal::applyFilter()
{
    // Clear fftComplexOut. We discard values by default; the filter only
    // copies values that look like chroma.
    for (qint32 i = 0; i < XCOMPLEX * YCOMPLEX; i++) {
        fftComplexOut[i][0] = 0.0;
        fftComplexOut[i][1] = 0.0;
    }

    // This is a direct translation of transform_filter from pyctools-pal.
    // The main simplification is that we don't need to worry about
    // conjugates, because FFTW only returns half the result in the first
    // place. We've also only implemented "threshold" mode for now.
    //
    // The general idea is that a real modulated chroma signal will be
    // symmetrical around the U carrier, which is at fSC Hz and 72 c/aph -- and
    // because we're sampling at 4fSC, this is handily equivalent to being
    // symmetrical around the V carrier owing to wraparound. We look at every
    // point that might be a chroma signal, and only keep it if it's
    // sufficiently symmetrical with its reflection.
    //
    // The Y axis covers 0 to 288 c/aph;  72 c/aph is 1/4 * YTILE.
    // The X axis covers 0 to 4fSC Hz;    fSC HZ   is 1/4 * XTILE.

    const double threshold_sq = threshold * threshold;

    for (qint32 y = 0; y < YTILE; y++) {
        // Reflect around 72 c/aph vertically.
        const qint32 y_ref = ((YTILE / 2) + YTILE - y) % YTILE;

        // Input data for this line and its reflection
        const fftw_complex *bi = fftComplexIn + (y * XCOMPLEX);
        const fftw_complex *bi_ref = fftComplexIn + (y_ref * XCOMPLEX);

        // Output data for this line and its reflection
        fftw_complex *bo = fftComplexOut + (y * XCOMPLEX);
        fftw_complex *bo_ref = fftComplexOut + (y_ref * XCOMPLEX);

        // We only need to look at horizontal frequencies that might be chroma (0.5fSC to 1.5fSC).
        for (qint32 x = XTILE / 8; x <= XTILE / 4; x++) {
            // Reflect around fSC Hz horizontally.
            const qint32 x_ref = (XTILE / 2) - x;

            const fftw_complex &in_val = bi[x];
            const fftw_complex &ref_val = bi_ref[x_ref];

            if (x == x_ref && y == y_ref) {
                // This point is its own reflection (i.e. it's a carrier). Keep it!
                bo[x][0] = in_val[0];
                bo[x][1] = in_val[1];
                continue;
            }

            // Compare the magnitudes of the two values.
            // (In fact, we compute the square of the magnitude, and square
            // both sides of the comparison below; this saves an expensive sqrt
            // operation.)
            // XXX Implement other comparison modes
            const double m_in_sq = fftwAbsSq(in_val);
            const double m_ref_sq = fftwAbsSq(ref_val);
            if (m_in_sq < m_ref_sq * threshold_sq || m_ref_sq < m_in_sq * threshold_sq) {
                // They're different. Probably not a chroma signal; throw it away.
                continue;
            }

            // They're similar. Keep it!
            bo[x][0] = in_val[0];
            bo[x][1] = in_val[1];
            bo_ref[x_ref][0] = ref_val[0];
            bo_ref[x_ref][1] = ref_val[1];
        }
    }
}
