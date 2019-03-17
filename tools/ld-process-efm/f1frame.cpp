/************************************************************************

    f1frame.cpp

    ld-process-efm - EFM data decoder
    Copyright (C) 2019 Simon Inns

    This file is part of ld-decode-tools.

    ld-process-efm is free software: you can redistribute it and/or
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

#include "f1frame.h"

// Note: Class for storing 'F1 frames' as defined by clause 16 of ECMA-130

F1Frame::F1Frame()
{
    dataSymbols.resize(2352);
    dataSymbols.fill(0);
}

void F1Frame::setData(QByteArray dataParam)
{
    // Perform descramble using look-up table
    uchar* dataIn = reinterpret_cast<uchar*>(dataParam.data());
    uchar* dataOut = reinterpret_cast<uchar*>(dataSymbols.data());

    for (qint32 i = 0; i < dataParam.size(); i++) {
        dataOut[i] = dataIn[i] ^ scrambleTable[i];
    }
}

// This method returns the 2352 data symbols for the F1 Frame
QByteArray F1Frame::getDataSymbols(void)
{
    return dataSymbols;
}

