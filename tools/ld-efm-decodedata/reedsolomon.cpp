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
template < size_t SYMBOLS, size_t PAYLOAD > struct C1RS;
template < size_t PAYLOAD > struct C1RS<255, PAYLOAD> : public __RS(C1RS, uint8_t, 255, PAYLOAD, 0x11d, 0,  1);

template < size_t SYMBOLS, size_t PAYLOAD > struct C2RS;
template < size_t PAYLOAD > struct C2RS<255, PAYLOAD> : public __RS(C2RS, uint8_t, 255, PAYLOAD, 0x11d, 0,  1);

ReedSolomon::ReedSolomon()
{
    c1Passed = 0;
    c1Corrected = 0;
    c1Failed = 0;

    c2Passed = 0;
    c2Corrected = 0;
    c2Failed = 0;
}

// Perform a C1 level error check and correction
bool ReedSolomon::decodeC1(unsigned char *inData)
{
    // Copy the ingress data into a vector
    std::vector<uint8_t> data;
    data.resize(32);
    for (size_t byteC = 0; byteC < 32; byteC++) data[byteC] = inData[byteC];

    // Initialise the error corrector
    C1RS<255,255-4> rs; // Up to 251 symbols data load with 4 symbols parity RS(32,28)

    // Perform decode
    int fixed = rs.decode(data);

    // Did C1 pass?
    if (fixed == 0) c1Passed++;
    if (fixed > 0)  c1Corrected++;
    if (fixed >= 0) {
        // Copy back the corrected data
        for (size_t byteC = 0; byteC < 32; byteC++) inData[byteC] = data[byteC];

        return true;
    }

    // C1 failed
    c1Failed++;
    return false;
}

// Perform a C2 level error check and correction
// To-Do: handle erasures correctly
bool ReedSolomon::decodeC2(uchar *inData, bool *inErasures)
{
    // Copy the ingress data into a vector
    std::vector<uint8_t> data;
    std::vector<int> erasures;
    data.resize(28);
    for (size_t byteC = 0; byteC < 28; byteC++) {
        data[byteC] = inData[byteC];
        if (inErasures[byteC]) erasures.push_back(static_cast<int>(byteC));
    }

    // Up to 4 erasures can be fixed
    int fixed = -1;
    if (erasures.size() < 5) {
        // Initialise the error corrector
        C2RS<255,255-4> rs; // Up to 251 symbols data load with 4 symbols parity RS(28,24)

        // Perform decode
        std::vector<int> position;
        fixed = rs.decode(data, erasures, &position);

        // Copy back the corrected data
        for (size_t byteC = 0; byteC < 28; byteC++) inData[byteC] = data[byteC];
    } else {
        qDebug() << "ReedSolomon::decodeC2(): Too many erasures, C2 invalid" << erasures.size();
    }

    // Did C2 pass?
    if (fixed == 0) c2Passed++;
    if (fixed > 0)  c2Corrected++;
    if (fixed >= 0) {
        return true;
    }

    // C2 failed
    c2Failed++;
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
