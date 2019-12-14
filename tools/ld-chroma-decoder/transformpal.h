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
#include <QVector>
#include <fftw3.h>

#include "lddecodemetadata.h"

#include "framecanvas.h"
#include "sourcefield.h"

// Abstract base class for Transform PAL filters.
class TransformPal {
public:
    TransformPal(qint32 xComplex, qint32 yComplex, qint32 zComplex);
    virtual ~TransformPal();

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
                             qint32 firstActiveLine, qint32 lastActiveLine,
                             TransformMode mode, double threshold,
                             const QVector<double> &thresholds);

    // Filter input fields.
    //
    // For each input frame between startFieldIndex and endFieldIndex, a
    // pointer will be placed in outputFields to an array of the same size
    // (owned by this object) containing the chroma signal.
    virtual void filterFields(const QVector<SourceField> &inputFields, qint32 startIndex, qint32 endIndex,
                              QVector<const double *> &outputFields) = 0;

    // Draw a visualisation of the FFT over RGB output frames.
    //
    // The FFT is computed for each field, so this visualises only the first
    // field in each frame. positionX/Y specify the location to visualise in
    // frame coordinates.
    void overlayFFT(qint32 positionX, qint32 positionY,
                    const QVector<SourceField> &inputFields, qint32 startIndex, qint32 endIndex,
                    QVector<QByteArray> &rgbFrames);

protected:
    // Overlay a visualisation of one field's FFT.
    // Calls back to overlayFFTArrays to draw the arrays.
    virtual void overlayFFTFrame(qint32 positionX, qint32 positionY,
                                 const QVector<SourceField> &inputFields, qint32 fieldIndex,
                                 QByteArray &rgbFrame) = 0;

    void overlayFFTArrays(const fftw_complex *fftIn, const fftw_complex *fftOut,
                          FrameCanvas &canvas);

    // FFT size
    qint32 xComplex;
    qint32 yComplex;
    qint32 zComplex;

    // Configuration parameters
    bool configurationSet;
    LdDecodeMetaData::VideoParameters videoParameters;
    qint32 firstActiveLine;
    qint32 lastActiveLine;
    QVector<double> thresholds;
    TransformMode mode;
};

#endif
