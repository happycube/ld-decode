/************************************************************************

    isifilter.cpp

    ld-ldstoefm - LDS sample to EFM data processing
    Copyright (C) 2019 Simon Inns

    This file is part of ld-decode-tools.

    ld-ldstoefm is free software: you can redistribute it and/or
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

#include "isifilter.h"

IsiFilter::IsiFilter()
{
    // Test code - converts floating-point coeffs to fixed point
    // with 15 bit scaling
//    QString coeff;
//    for (qint32 i = 0; i < (ceNZeros+1); i++) {
//        qreal scale = ceXcoeffs[i] * 32768.0;
//        coeff += QString::number(static_cast<qint16>(scale)) + ", ";
//    }
//    qDebug() << "FP coeff:" << coeff;

    // Initialise the fixed-point filter
    offset = 0;
}

// Method to feed the ISI FIR filter
void IsiFilter::floatIsiProcess(QByteArray &inputSample)
{
    qint16 *input = reinterpret_cast<qint16*>(inputSample.data());

    for (qint32 sample = 0; sample < (inputSample.size() / 2); sample++) {
        input[sample] = static_cast<qint16>(floatIsiFilter(static_cast<qreal>(input[sample])));
    }
}

// ISI FIR filter (floating-point implementation)
qreal IsiFilter::floatIsiFilter(qreal inputSample)
{
    qreal sum; qint32 i;
    for (i = 0; i < ceNZeros; i++) ceXv[i] = ceXv[i+1];
    ceXv[ceNZeros] = inputSample / ceGain;
    sum = 0.0;
    for (i = 0; i <= ceNZeros; i++) sum += (ceXcoeffs[i] * ceXv[i]);
    return sum;
}

// Method to feed the ISI FIR filter (fixed-point implementation)
void IsiFilter::fixedIsiProcess(QByteArray &inputSample)
{
    qint16 *input = reinterpret_cast<qint16*>(inputSample.data());

    for (qint32 sample = 0; sample < (inputSample.size() / 2); sample++) {
        input[sample] = fixedIsiFilter(input[sample]);
    }
}

// ISI FIR filter (fixed-point implementation)
qint16 IsiFilter::fixedIsiFilter(qint16 inputSample)
{
    qint16 *coeff     = fpCoeff;
    qint16 *coeff_end = fpCoeff + fpTaps;

    qint16 *buf_val = fpXv + offset;

    *buf_val = inputSample >> 4; // Gain is /8
    qint32 output_ = 0;

    while(buf_val >= fpXv)
        output_ += *buf_val-- * *coeff++;

    buf_val = fpXv + fpTaps-1;

    while(coeff < coeff_end)
        output_ += *buf_val-- * *coeff++;

    if(++offset >= fpTaps)
        offset = 0;

    return static_cast<qint16>(output_ >> 15);
}
