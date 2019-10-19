/************************************************************************

    isifilter.cpp

    cd-decode - Compact Disc RF to EFM converter
    Copyright (C) 2019 Simon Inns

    This file is part of ld-decode-tools.

    cd-decode is free software: you can redistribute it and/or
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

