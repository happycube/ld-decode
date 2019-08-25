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
#include <QVector>
#include <fftw3.h>

#include "lddecodemetadata.h"

#include "sourcefield.h"

class TransformPal {
public:
    TransformPal();
    ~TransformPal();

    // Specify what the frequency-domain filter should do to each pair of
    // frequencies that should be symmetrical around the carriers.
    enum TransformMode {
        // Adjust the amplitudes of the two points to be equal
        levelMode = 0,
        // If the amplitudes aren't within a threshold of each other, zero both points
        thresholdMode
    };

    // Configure TransformPal.
    //
    // mode selects an operation mode for the filter.
    //
    // threshold is the similarity threshold for the filter in thresholdMode.
    // Values from 0-1 are meaningful, with higher values requiring signals to
    // be more similar to be considered chroma. 0.6 is pyctools-pal's default.
    void updateConfiguration(const LdDecodeMetaData::VideoParameters &videoParameters,
                             TransformMode mode, double threshold);

    // Filter input fields.
    //
    // For each input frame between startFieldIndex and endFieldIndex, a
    // pointer will be placed in outputFields to an array of the same size
    // (owned by this object) containing the chroma signal.
    void filterFields(qint32 firstFieldFirstLine, qint32 firstFieldLastLine,
                      qint32 secondFieldFirstLine, qint32 secondFieldLastLine,
                      const QVector<SourceField> &inputFields, qint32 startIndex, qint32 endIndex,
                      QVector<const double *> &outputFields);

private:
    void filterField(const SourceField& inputField, qint32 firstFieldLine, qint32 lastFieldLine, qint32 outputIndex);
    void forwardFFTTile(qint32 tileX, qint32 tileY, const SourceField &inputField, qint32 firstFieldLine, qint32 lastFieldLine);
    void inverseFFTTile(qint32 tileX, qint32 tileY, qint32 firstFieldLine, qint32 lastFieldLine, qint32 outputIndex);
    template <TransformMode MODE>
    void applyFilter();

    // Configuration parameters
    bool configurationSet;
    LdDecodeMetaData::VideoParameters videoParameters;
    double threshold;
    TransformMode mode;

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

    // The combined result of all the FFT processing for each input field.
    // Inverse-FFT results are accumulated into these buffers.
    QVector<QVector<double>> chromaBuf;
};

#endif
