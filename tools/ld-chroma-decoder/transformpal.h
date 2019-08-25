/************************************************************************

    transformpal.h

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

#ifndef TRANSFORMPAL_H
#define TRANSFORMPAL_H

#include <QByteArray>
#include <QDebug>
#include <QObject>
#include <fftw3.h>

#include "lddecodemetadata.h"

#include "sourcefield.h"

class TransformPal {
public:
    TransformPal();
    ~TransformPal();

    // threshold is the similarity threshold for the filter (values from 0-1
    // are meaningful; 0.6 is pyctools-pal's default)
    void updateConfiguration(const LdDecodeMetaData::VideoParameters &videoParameters,
                             double threshold);

    // Filter an input field.
    // Returns a pointer to an array of the same size (owned by this object)
    // containing the chroma signal.
    const double *filterField(qint32 firstFieldLine, qint32 lastFieldLine, const SourceField &inputField);

private:
    // Apply the frequency-domain filter
    void applyFilter();

    // Configuration parameters
    bool configurationSet;
    LdDecodeMetaData::VideoParameters videoParameters;
    double threshold;

    // Maximum field size, based on PAL
    static constexpr qint32 MAX_WIDTH = 1135;

    // FFT input and output sizes.
    // The input field is divided into tiles of XTILE x YTILE, with adjacent
    // tiles overlapping by HALFXTILE/HALFYTILE.
    static constexpr qint32 YTILE = 16;
    static constexpr qint32 HALFYTILE = YTILE / 2;
    static constexpr qint32 XTILE = 32;
    static constexpr qint32 HALFXTILE = XTILE / 2;

    // Each tile is converted to the frequency domain using forwardPlan, which
    // gives a complex result of size XCOMPLEX x YCOMPLEX (roughly half the
    // size of the input, because the input data was real, i.e. contained no
    // negative frequencies).
    static constexpr qint32 YCOMPLEX = YTILE;
    static constexpr qint32 XCOMPLEX = (XTILE / 2) + 1;

    // Window function applied before the FFT
    double windowFunction[YTILE][XTILE];

    // FFT input/output buffers
    double *fftReal;
    fftw_complex *fftComplexIn;
    fftw_complex *fftComplexOut;

    // FFT plans
    fftw_plan forwardPlan, inversePlan;

    // The combined result of all the FFT processing.
    // Inverse-FFT results are accumulated into this buffer.
    QVector<double> chromaBuf;
};

#endif
