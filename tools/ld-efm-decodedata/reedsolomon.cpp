/************************************************************************

    reedsolomon.cpp

    ld-efm-decodedata - EFM data decoder for ld-decode
    Copyright (C) 2019 Simon Inns

    This file is part of ld-decode-tools.

    ld-efm-decodedata is free software: you can redistribute it and/or
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

#include "reedsolomon.h"

#include <ezpwd/rs>
#include <ezpwd/corrector>
#include <ezpwd/output>
#include <ezpwd/definitions>

// CD-ROM specific CIRC configuration for Reed-Solomon forward error correction
template < size_t SYMBOLS, size_t PAYLOAD > struct CDRS;
template < size_t PAYLOAD > struct CDRS<255, PAYLOAD> : public __RS(CDRS, uint8_t, 255, PAYLOAD, 0x11d, 0,  1);

ReedSolomon::ReedSolomon()
{
    c1Passed = 0;
    c1Corrected = 0;
    c1Failed = 0;
}

bool ReedSolomon::decodeC1(unsigned char *inData)
{
    // Copy the ingress data into a vector
    std::vector<uint8_t> data;
    data.resize(32);
    for (size_t byteC = 0; byteC < 32; byteC++) data[byteC] = inData[byteC];

    // Initialise the error corrector
    CDRS<255,255-4> rs; // Up to 251 symbols data load; adds 4 symbols parity RS(32,28)

    // Perform decode
    int fixed = rs.decode(data);

    // Did C1 pass?
    if (fixed == 0) c1Passed++;
    if (fixed > 0)  c1Corrected++;
    if (fixed >= 0) return true;

    // C1 failed
    c1Failed++;
    return false;
}

// This method is for debug and outputs an array of 8-bit unsigned data as a hex string
QString ReedSolomon::dataToString(std::vector<uint8_t> data)
{
    QString output;

    for (size_t count = 0; count < data.size(); count++) {
        output += QString("%1").arg(data[count], 2, 16, QChar('0'));
    }

    return output;
}
