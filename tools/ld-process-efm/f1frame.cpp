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
    dataSymbols.resize(2340);
    dataSymbols.fill(0);
}

void F1Frame::setData(QByteArray dataParam)
{
    // Descramble the input data according to ECMA-130 Annex B
    // and store as an F1 frame
    quint16 shiftRegister = 0x0001; // 15-bits wide (0x0001 is the preset value)
    for (qint32 byteC = 12; byteC < dataParam.size(); byteC++) {
        uchar inputByte = static_cast<uchar>(dataParam[byteC]);
        uchar outputByte = 0;

        for (qint32 bitC = 0; bitC < 8; bitC++) {
            // Get the input bit
            uchar inputBit = ((inputByte) & (1 << bitC)) ? 1 : 0;

            // Get the 1st and 2nd LSBs from the shift register
            uchar s0 = ((shiftRegister) & (1 << 0)) ? 1 : 0;
            uchar s1 = ((shiftRegister) & (1 << 1)) ? 1 : 0;

            // Perform the two XOR operations
            uchar xor1Result = s0 ^ s1;
            uchar outputBit = inputBit ^ s0;

            // Shift the register right by 1 bit
            shiftRegister >>= 1;

            // Push the XOR result into the MSB of the shift register
            if (xor1Result != 0) shiftRegister += 16384; // Set bit 15

            // Set the bit in the output byte
            outputByte |= (outputBit << bitC);
        }
        // Store the output byte in the F1 frame data
        dataSymbols[byteC - 12] = static_cast<char>(outputByte);
    }

    // Set the mode and the address for the F1 frame
    sectorMode = dataSymbols[3];
    sectorAddress.setTime(bcdToInteger(static_cast<uchar>(dataSymbols[0])),
            bcdToInteger(static_cast<uchar>(dataSymbols[1])),
            bcdToInteger(static_cast<uchar>(dataSymbols[2])));
}

// This method returns the 2340 data symbols for the F1 Frame
QByteArray F1Frame::getDataSymbols(void)
{
    return dataSymbols;
}

// Method to return the sector mode of the F1 frame
qint32 F1Frame::getMode(void)
{
    return sectorMode;
}

// Method to return the sector address of the F1 frame
TrackTime F1Frame::getAddress(void)
{
    return sectorAddress;
}

// Method to convert 2 digit BCD byte to an integer
qint32 F1Frame::bcdToInteger(uchar bcd)
{
   return (((bcd>>4)*10) + (bcd & 0xF));
}
