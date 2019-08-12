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

#include <cassert>
#include <complex>

/*!
    \class TransformPal

    Transform PAL filter, based on Jim Easterbrook's implementation in
    pyctools-pal. Given a composite signal, this extracts a chroma signal from
    it using frequency-domain processing.

    For a description of the algorithm with examples, see Transform PAL web
    site (http://www.jim-easterbrook.me.uk/pal/).

    Note that this is only a 2D implementation at the moment, which limits the
    quality of the output; it would be possible to extend it to 3D given access
    to multiple fields.
 */

TransformPal::TransformPal()
    : configurationSet(false)
{
    // Compute the window function applied to the data blocks before the FFT to
    // reduce edge effects. This function is chosen so that the overlapping
    // inverse-FFT blocks can be summed directly.
    // XXX This is wasteful because the edges are 0... use raised cosine instead?
    for (qint32 y = 0; y < YTILE; y++) {
        const double windowY = ((y < HALFYTILE) ? y : (YTILE - 1 - y)) / (HALFYTILE - 1.0);
        for (qint32 x = 0; x < XTILE; x++) {
            const double windowX = ((x < HALFXTILE) ? x : (XTILE - 1 - x)) / (HALFXTILE - 1.0);
            windowFunction[y][x] = windowY * windowX;
        }
    }

    // Allocate buffers for FFTW. These must be allocated using FFTW's own
    // functions so they're properly aligned for SIMD operations.
    fftReal = fftw_alloc_real(YTILE * XTILE);
    fftComplexIn = fftw_alloc_complex(YCOMPLEX * XCOMPLEX);
    fftComplexOut = fftw_alloc_complex(YCOMPLEX * XCOMPLEX);

    // Plan FFTW operations
    // XXX FFTW_ESTIMATE is quick but potentially produces a slower plan...
    forwardPlan = fftw_plan_dft_r2c_2d(YTILE, XTILE, fftReal, fftComplexIn, FFTW_ESTIMATE);
    inversePlan = fftw_plan_dft_c2r_2d(YTILE, XTILE, fftComplexOut, fftReal, FFTW_ESTIMATE);
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

void TransformPal::updateConfiguration(LdDecodeMetaData::VideoParameters _videoParameters,
                                       qint32 _firstActiveLine, qint32 _lastActiveLine,
                                       double _threshold)
{
    videoParameters = _videoParameters;
    firstActiveLine = _firstActiveLine;
    lastActiveLine = _lastActiveLine;
    threshold = _threshold;

    // Resize the chroma buffer
    chromaBuf.resize(videoParameters.fieldWidth * videoParameters.fieldHeight);

    configurationSet = true;
}

const double *TransformPal::filterField(qint32 fieldNumber, const QByteArray &fieldData)
{
    assert(configurationSet);
    assert(fieldNumber == 0 || fieldNumber == 1);
    assert(!fieldData.isNull());

    // Work out the active lines to be decoded within this field.
    // If firstActiveLine or lastActiveLine is odd, we can end up with
    // different ranges for the two fields, so we need to be careful
    // about how this is rounded.
    const qint32 firstFieldLine = (firstActiveLine + 1 - fieldNumber) / 2;
    const qint32 lastFieldLine = (lastActiveLine + 1 - fieldNumber) / 2;

    // Pointers to the input and output data
    const quint16 *inputPtr = reinterpret_cast<const quint16 *>(fieldData.data());
    double *outputPtr = chromaBuf.data();

    // Clear chromaBuf
    chromaBuf.fill(0.0);

    // Iterate through the overlapping tile positions, covering the active area.
    // (See TransformThread member variable documentation for how the tiling works.)
    for (qint32 tileY = firstFieldLine - HALFYTILE; tileY < lastFieldLine; tileY += HALFYTILE) {
        for (qint32 tileX = videoParameters.activeVideoStart - HALFXTILE; tileX < videoParameters.activeVideoEnd; tileX += HALFXTILE) {
            // Work out what portion of this tile is inside the active area
            const qint32 startX = qMax(videoParameters.activeVideoStart - tileX, 0);
            const qint32 endX = qMin(videoParameters.activeVideoEnd - tileX, XTILE);
            const qint32 startY = qMax(firstFieldLine - tileY, 0);
            const qint32 endY = qMin(lastFieldLine - tileY, YTILE);

            // If we aren't going to fill in the whole tile, zero it first
            if (startX != 0 || endX != XTILE || startY != 0 || endY != YTILE) {
                for (qint32 i = 0; i < YTILE * XTILE; i++) {
                    fftReal[i] = 0.0;
                }
            }

            // Copy the input signal into fftReal, applying the window function
            for (qint32 y = startY; y < endY; y++) {
                const quint16 *b = inputPtr + ((tileY + y) * videoParameters.fieldWidth);
                for (qint32 x = startX; x < endX; x++) {
                    fftReal[(y * XTILE) + x] = b[tileX + x] * windowFunction[y][x];
                }
            }

            // Convert time domain in fftReal to frequency domain in fftComplexIn
            fftw_execute(forwardPlan);

            // Apply the frequency-domain filter
            applyFilter();

            // Convert frequency domain in fftComplexOut back to time domain in fftReal
            fftw_execute(inversePlan);

            // Overlay the result, normalising the FFTW output, into chromaBuf
            for (qint32 y = startY; y < endY; y++) {
                double *b = outputPtr + ((tileY + y) * videoParameters.fieldWidth);
                for (qint32 x = startX; x < endX; x++) {
                    b[tileX + x] += fftReal[(y * XTILE) + x] / (YTILE * XTILE);
                }
            }
        }
    }

    return chromaBuf.data();
}

// Return the absolute value of an fftw_complex
static inline double fftwAbs(const fftw_complex &value) {
    return std::abs(std::complex<double>(value[0], value[1]));
}

void TransformPal::applyFilter() {
    // Clear fftComplexOut. We discard values by default; the filter only
    // copies values that look like chroma.
    for (int i = 0; i < XCOMPLEX * YCOMPLEX; i++) {
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

    for (int y = 0; y < YTILE; y++) {
        // Reflect around 72 c/aph vertically.
        const int y_ref = ((YTILE / 2) + YTILE - y) % YTILE;

        // Input data for this line and its reflection
        const fftw_complex *bi = fftComplexIn + (y * XCOMPLEX);
        const fftw_complex *bi_ref = fftComplexIn + (y_ref * XCOMPLEX);

        // Output data for this line and its reflection
        fftw_complex *bo = fftComplexOut + (y * XCOMPLEX);
        fftw_complex *bo_ref = fftComplexOut + (y_ref * XCOMPLEX);

        // We only need to look at horizontal frequencies that might be chroma (0.5fSC to 2fSC).
        for (int x = XTILE / 8; x <= XTILE / 4; x++) {
            // Reflect around 4fSC Hz horizontally.
            const int x_ref = (XTILE / 2) - x;

            const fftw_complex &in_val = bi[x];
            const fftw_complex &ref_val = bi_ref[x_ref];

            if (x == x_ref && y == y_ref) {
                // This point is its own reflection (i.e. it's a carrier). Keep it!
                bo[x][0] = in_val[0];
                bo[x][1] = in_val[1];
                continue;
            }

            // Compare the magnitudes of the two values.
            // XXX This does a sqrt which we don't strictly need for the comparison below
            // XXX Implement other comparison modes
            const double m_in = fftwAbs(in_val);
            const double m_ref = fftwAbs(ref_val);
            if (m_in < m_ref * threshold || m_ref < m_in * threshold) {
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
