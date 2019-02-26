/************************************************************************

    filter.cpp

    ld-efm-sampletodata - EFM sample to data processor for ld-decode
    Copyright (C) 2019 Simon Inns

    This file is part of ld-decode-tools.

    ld-efm-sampletodata is free software: you can redistribute it and/or
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

#include "filter.h"

Filter::Filter()
{
    // Initialise DC blocker filter
    acc = 0;
    previousInputSample = 0;
    previousOutputSample = 0;
}

// This method is based on the public domain code available from:
// https://dspguru.com/dsp/tricks/fixed-point-dc-blocking-filter-with-noise-shaping/
QVector<qint16> Filter::dcBlocker(QVector<qint16> inputSample)
{
    // let's say sizeof(short) = 2 (16 bits) and sizeof(long) = 4 (32 bits)
    QVector<qint16> outputSample;
    outputSample.resize(inputSample.size());

    qreal pole = 0.9999;
    qint32 A = static_cast<qint32>(32768.0 * (1.0 - pole));

    for (qint32 sampleNo = 0; sampleNo < inputSample.size(); sampleNo++) {
        acc -= previousInputSample;
        previousInputSample = static_cast<qint32>(inputSample[sampleNo]) << 15;
        acc += previousInputSample;
        acc -= A * previousOutputSample;
        previousOutputSample = acc >> 15; // Quantization happens here
        outputSample[sampleNo] = static_cast<qint16>(previousOutputSample);
        // acc has y[n] in upper 17 bits and -e[n] in lower 15 bits
    }

    return outputSample;
}

// Method to feed the channelEqualizer FIR filter
QVector<qint16> Filter::channelEqualizer(QVector<qint16> inputSample)
{
    QVector<qint16> outputSample;
    outputSample.resize(inputSample.size());

    for (qint32 sample = 0; sample < inputSample.size(); sample++) {
        outputSample[sample] = static_cast<qint16>(channelEqualizerFir(static_cast<qreal>(inputSample[sample])));
    }

    return outputSample;
}

// Channel Equalizer FIR filter
qreal Filter::channelEqualizerFir(qreal inputSample)
{
    qreal sum; qint32 i;
    for (i = 0; i < ceNZeros; i++) ceXv[i] = ceXv[i+1];
    ceXv[ceNZeros] = inputSample / ceGain;
    sum = 0.0;
    for (i = 0; i <= ceNZeros; i++) sum += (ceXcoeffs[i] * ceXv[i]);
    return sum;
}
