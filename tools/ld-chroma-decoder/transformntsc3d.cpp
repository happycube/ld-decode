/************************************************************************

    transformntsc3d.cpp

    ld-chroma-decoder - Colourisation filter for ld-decode
    Copyright (C) 2019-2021 Adam Sampson

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

#include "transformntsc3d.h"

#include <QtMath>
#include <cassert>
#include <cmath>
#include <cstring>

#include "framecanvas.h"

/*!
    \class TransformNtsc3D

    3D Transform PAL filter, based on Jim Easterbrook's implementation in
    pyctools-pal. Given a composite signal, this extracts a chroma signal from
    it using frequency-domain processing.

    For a description of the algorithm with examples, see the Transform PAL web
    site (http://www.jim-easterbrook.me.uk/pal/).
 */

void TransformNtsc3D::filterFields(const QVector<SourceField> &inputFields, qint32 startIndex, qint32 endIndex,
                                   QVector<const double *> &outputFields)
{
    assert(configurationSet);

    // Check we have a valid vector of input fields, and a matching output vector
    assert((inputFields.size() % 2) == 0);
    for (qint32 i = 0; i < inputFields.size(); i++) {
        assert(!inputFields[i].data.empty());
    }
    assert(outputFields.size() == (endIndex - startIndex));

    // Check that we've been given enough surrounding fields to compute FFTs
    // that overlap the fields we're actually interested in by half a tile
    assert(startIndex >= HALFZTILE);
    assert((inputFields.size() - endIndex) >= HALFZTILE);

    // Allocate and clear output buffers
    chromaBuf.resize(endIndex - startIndex);
    for (qint32 i = 0; i < chromaBuf.size(); i++) {
        chromaBuf[i].resize(videoParameters.fieldWidth * videoParameters.fieldHeight);
        chromaBuf[i].fill(0.0);

        outputFields[i] = chromaBuf[i].data();
    }

    // Iterate through the overlapping tile positions, covering the active area.
    // (See TransformPal3D member variable documentation for how the tiling works;
    // if you change the Z tiling here, also review getLookBehind/getLookAhead above.)
    for (qint32 tileZ = startIndex - HALFZTILE; tileZ < endIndex; tileZ += HALFZTILE) {
        for (qint32 tileY = videoParameters.firstActiveFrameLine - HALFYTILE; tileY < videoParameters.lastActiveFrameLine; tileY += HALFYTILE) {
            for (qint32 tileX = videoParameters.activeVideoStart - HALFXTILE; tileX < videoParameters.activeVideoEnd; tileX += HALFXTILE) {
                // Compute the forward FFT
                forwardFFTTile(tileX, tileY, tileZ, inputFields);

                // Apply the frequency-domain filter in the appropriate mode
                if (mode == levelMode) {
                    applyFilter<levelMode>();
                } else {
                    applyFilter<thresholdMode>();
                }

                // Compute the inverse FFT
                inverseFFTTile(tileX, tileY, tileZ, startIndex, endIndex);
            }
        }
    }
}

// Return the absolute value squared of an fftw_complex
static inline double fftwAbsSq(const fftw_complex &value)
{
    return (value[0] * value[0]) + (value[1] * value[1]);
}

static inline double dist_sq(const double x, const double y, const double z)
{
    return x*x + y*y + z*z;
}

// Apply the frequency-domain filter.
// (Templated so that the inner loop gets specialised for each mode.)
template <TransformPal::TransformMode MODE>
void TransformNtsc3D::applyFilter()
{
    // Get pointer to squared threshold values
    const double *thresholdsPtr = thresholds.data();

    // Clear fftComplexOut. We discard values by default; the filter only
    // copies values that look like chroma.
    for (qint32 i = 0; i < ZCOMPLEX * YCOMPLEX * XCOMPLEX; i++) {
        fftComplexOut[i][0] = 0.0;
        fftComplexOut[i][1] = 0.0;
    }

    // This is a direct translation of transform_filter from pyctools-pal, with
    // an extra loop added to extend it to 3D. The main simplification is that
    // we don't need to worry about conjugates, because FFTW only returns half
    // the result in the first place.
    //
    // The general idea is that a real modulated chroma signal will be
    // approximately symmetrical around the subcarrier, which is at
    // fSC Hz, 120 c/aph, 15 Hz. We look at every bin that might be a
    // chroma signal, and only keep it if it's sufficiently
    // symmetrical with its reflection. Note that this is less exact
    // than the PAL case: we rely on the fact that it is "unlikely"
    // that I and Q have the amplitude/phase relationship that causes
    // one of the two frequency amplitudes to vanish.
    //
    // In addition, compare with the corresponding luma frequency: it
    // is "unlikely" that there is chroma but no corresponding luma.
    // 
    //  0----------0  Here we can illustrate the effect of interlacing
    //  |    /\    |  in yz frequency space:
    //-z|   /  \   |   (y,z) and (y+YTILE/2,z+ZTILE/2) are equivalent.
    //  |  /    c  |  Thus, every point inside the diamond is
    //  | /      \ |  equivalent to a point outside the diamond.
    //  |/    0   \|  - The origin is at the corners+center.
    //  |\        /|  - The subcarrier is at the two 'c' points.
    //  | \      / |  - The origin is symmetric around the subcarrier,
    //  |  c    /  |    so if x=fSC then the reflection comparison
    //  |   \  /   |    tells us nothing.
    //+z|    \/    |  - The midpoints of the sides are also equivalent
    //  0----------0    and symmetric around the subcarrier. (This
    //    +y   -y       corresponds to fine details appearing in
    //                  different fields.)
    //
    // The Z axis covers 0 to 60 Hz;      15 Hz     is 1/4 * ZTILE.
    // The Y axis covers 0 to 480 c/aph;  120 c/aph is 1/4 * YTILE.
    // The X axis covers 0 to 4fSC Hz;    fSC HZ    is 1/4 * XTILE.

    for (qint32 z = 0; z < ZTILE; z++) {
        // Reflect around 15 Hz temporally.
        const qint32 z_ref = ((ZTILE / 2) + ZTILE - z) % ZTILE;
        // subtract 15 Hz
        const qint32 z_lumaref = (z - ZTILE / 4 + ZTILE) % ZTILE;
        const qint32 z_lumaref_neg = (ZTILE - z_lumaref) % ZTILE;
        const double kz0 = static_cast<double>(z) / static_cast<double>(ZTILE);

        for (qint32 y = 0; y < YTILE; y++) {
            // Reflect around 120 c/aph vertically.
            const qint32 y_ref = ((YTILE / 2) + YTILE - y) % YTILE;
            // subtract 120 c/aph
            const qint32 y_lumaref = (y - YTILE / 4 + YTILE) % YTILE;
            const qint32 y_lumaref_neg = (YTILE - y_lumaref) % YTILE;
            const double ky0 = static_cast<double>(y) / static_cast<double>(YTILE);
            double ky,kz;
            // map to central "diamond"
            if (kz0 + ky0 < 0.5) {
                kz = kz0 + 0.5;
                ky = ky0 + 0.5;
            } else if (kz0 + ky0 > 1.5) {
                kz = kz0 - 0.5;
                ky = ky0 - 0.5;
            } else if (kz0 - ky0 > 0.5) {
                kz = kz0 - 0.5;
                ky = ky0 + 0.5;
            } else if (ky0 - kz0 > 0.5) {
                kz = kz0 + 0.5;
                ky = ky0 - 0.5;
            } else {
                kz = kz0;
                ky = ky0;
            }
            // bring to lower-left half of diamond
            if (kz + ky > 1.0) {
                kz = 1.0 - kz;
                ky = 1.0 - ky;
            }

            // Input data for this line and its reflection
            const fftw_complex *bi = fftComplexIn + (((z * YCOMPLEX) + y) * XCOMPLEX);
            const fftw_complex *bi_ref = fftComplexIn + (((z_ref * YCOMPLEX) + y_ref) * XCOMPLEX);
            const fftw_complex *bi_lumaref = fftComplexIn + (((z_lumaref * YCOMPLEX) + y_lumaref) * XCOMPLEX);
            const fftw_complex *bi_lumaref_neg = fftComplexIn + (((z_lumaref_neg * YCOMPLEX) + y_lumaref_neg) * XCOMPLEX);

            // Output data for this line and its reflection
            fftw_complex *bo = fftComplexOut + (((z * YCOMPLEX) + y) * XCOMPLEX);
            fftw_complex *bo_ref = fftComplexOut + (((z_ref * YCOMPLEX) + y_ref) * XCOMPLEX);

            // We only need to look at horizontal frequencies that might be chroma (0.5fSC to 1.5fSC).
            for (qint32 x = XTILE / 8; x <= XTILE / 4; x++) {
                // Reflect around fSC horizontally
                const qint32 x_ref = (XTILE / 2) - x;
                // subtract fSC
                qint32 x_lumaref = x - XTILE / 4;
                const double kx = static_cast<double>(x) / static_cast<double>(XTILE);
                // if x < 0 then we have to negate (x,y,z)_lumaref
                const fftw_complex *lumaref_val;
                if (x_lumaref >= 0)
                  lumaref_val = &bi_lumaref[x_lumaref];
                else
                  lumaref_val = &bi_lumaref_neg[-x_lumaref];

                // Get the threshold for this bin
                const double threshold0_sq = *thresholdsPtr++;

                const fftw_complex &in_val = bi[x];
                const fftw_complex &ref_val = bi_ref[x_ref];

                if (x == x_ref &&
                    ( (y == YTILE/4 && z == ZTILE/4)
                   || (y == 3*YTILE/4 && z == 3*ZTILE/4)
                    ) ) {
                    // This bin is its own reflection (i.e. it's a carrier). Keep it!
                    bo[x][0] = in_val[0];
                    bo[x][1] = in_val[1];
                    continue;
                }
                if (x == x_ref &&
                    ( ( (y == 0 || y == YTILE/2) && (z == 0 || z == ZTILE/2) )
                   || (y == YTILE/4 && z == 3*ZTILE/4)
                   || (y == 3*YTILE/4 && z == ZTILE/4)
                    ) ){
                    // This bin is its own reflection (but not a carrier). Discard it!
                    continue;
                }

                // Adjust the threshold based on distance to uniform luma vs uniform chroma.
                // This breaks functionality based on reading in frequency-dependent thresholds.
                const double k_sq_luma = dist_sq(kz-0.5, ky-0.5, kx);
                const double k_sq_chroma = dist_sq(kz-0.25, ky-0.25, kx-0.25);
                const double threshold_sq = pow(k_sq_chroma / ( k_sq_luma + k_sq_chroma ), 10.0*threshold0_sq);

                // Get the squares of the magnitudes (to minimise the number of sqrts)
                const double m_in_sq = fftwAbsSq(in_val);
                const double m_ref_sq = fftwAbsSq(ref_val);
                const double m_lumaref_sq = fftwAbsSq(*lumaref_val);

                if (MODE == levelMode) {
                    // Compare the magnitudes of the two values, and scale the
                    // larger one down so its magnitude is the same as the
                    // smaller one.
                    const double factor = sqrt(m_in_sq / m_ref_sq);
                    if (std::max(m_in_sq,m_ref_sq) > 10 * m_lumaref_sq) {
                        // no corresponding luma signal -> discard bin
                        ;
                    } else if (m_in_sq > 10 * m_ref_sq) {
                        // Reduce in_val, keep ref_val as is
                        bo[x][0] = in_val[0] / factor;
                        bo[x][1] = in_val[1] / factor;
                        bo_ref[x_ref][0] = ref_val[0];
                        bo_ref[x_ref][1] = ref_val[1];
                    } else if (m_ref_sq > 10 * m_in_sq) {
                        // Reduce ref_val, keep in_val as is
                        bo[x][0] = in_val[0];
                        bo[x][1] = in_val[1];
                        bo_ref[x_ref][0] = ref_val[0] * factor;
                        bo_ref[x_ref][1] = ref_val[1] * factor;
                    } else {
                        // keep both
                        bo[x][0] = in_val[0];
                        bo[x][1] = in_val[1];
                        bo_ref[x_ref][0] = ref_val[0];
                        bo_ref[x_ref][1] = ref_val[1];
                    }
                } else {
                    // Compare the magnitudes of the two values, and discard
                    // both if they are more different than the threshold for
                    // this bin.
                    double threshold2_sq = threshold_sq;
                    if (m_lumaref_sq < std::max(m_in_sq,m_ref_sq) * threshold_sq) {
                        // no corresponding luma signal -> tighten threshold
                        threshold2_sq = 0.5 * ( 1.0 + threshold2_sq );
                    }
                    if (m_in_sq < m_ref_sq * threshold2_sq || m_ref_sq < m_in_sq * threshold2_sq) {
                        // Probably not a chroma signal; throw it away.
                    } else {
                        // They're similar. Keep it!
                        bo[x][0] = in_val[0];
                        bo[x][1] = in_val[1];
                        bo_ref[x_ref][0] = ref_val[0];
                        bo_ref[x_ref][1] = ref_val[1];
                    }
                }
            }
        }
    }

    assert(thresholdsPtr == thresholds.data() + thresholds.size());
}

void TransformNtsc3D::overlayFFTFrame(qint32 positionX, qint32 positionY,
                                     const QVector<SourceField> &inputFields, qint32 fieldIndex,
                                     ComponentFrame &componentFrame)
{
    // Do nothing if the tile isn't within the frame
    if (positionX < 0 || positionX + XTILE > videoParameters.fieldWidth
        || positionY < 0 || positionY + YTILE > (2 * videoParameters.fieldHeight) + 1) {
        return;
    }

    // Compute the forward FFT
    forwardFFTTile(positionX, positionY, fieldIndex, inputFields);

    // Apply the frequency-domain filter in the appropriate mode
    if (mode == levelMode) {
        applyFilter<levelMode>();
    } else {
        applyFilter<thresholdMode>();
    }

    // Create a canvas
    FrameCanvas canvas(componentFrame, videoParameters);

    // Outline the selected tile
    const auto green = canvas.rgb(0, 0xFFFF, 0);
    canvas.drawRectangle(positionX - 1, positionY - 1, XTILE + 1, YTILE + 1, green);

    // Draw the arrays
    overlayFFTArrays(fftComplexIn, fftComplexOut, canvas);
}
