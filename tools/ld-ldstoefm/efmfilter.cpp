/************************************************************************

    efmfilter.cpp

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

#include "efmfilter.h"

EfmFilter::EfmFilter()
{

}

// Note: The EFM filter is a 71 tap FIR bandpass filter designed to extract
// the EFM signal from the original ADC signal of the Domesday Duplicator
// It is an Inverse Chebyshev with slight asymmetry around the bandpass
// based on the EFM filter in the Pioneer LD-V4300D LaserDisc player.

void EfmFilter::process(QByteArray &inputData)
{
    qint16 *input = reinterpret_cast<qint16 *>(inputData.data());

    for (qint32 i = 0; i < (inputData.size() / 2); i++) {
        input[i] = static_cast<qint16>(feed(static_cast<qreal>(input[i])));
    }
}


qreal EfmFilter::feed(qreal inputSample)
{
    qreal sum; qint32 i;
    for (i = 0; i < ceNZeros; i++) ceXv[i] = ceXv[i+1];
    ceXv[ceNZeros] = inputSample * ceGain;
    sum = 0.0;
    for (i = 0; i <= ceNZeros; i++) sum += (ceXcoeffs[i] * ceXv[i]);
    return sum;
}
