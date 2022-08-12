/************************************************************************

    f3frame.cpp

    ld-process-efm - EFM data decoder
    Copyright (C) 2019-2022 Simon Inns

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

#include "f3frame.h"

// Note: Class for storing 'F3 frames' as defined by clause 18 of ECMA-130
//
// Each frame consists of 1 byte of subcode data and 32 bytes of payload
//
// Data is represented as data symbols (the actual payload) and error symbols
// that flag if a data symbol was detected as invalid during translation from EFM

F3Frame::F3Frame()
{
    validEfmSymbols = 0;
    invalidEfmSymbols = 0;
    correctedEfmSymbols = 0;

    isSync0 = false;
    isSync1 = false;
    subcodeSymbol = 0;

    for (qint32 i = 0; i < 32; i++) {
        dataSymbols[i] = 0;
        errorSymbols[i] = 0;
    }
}

F3Frame::F3Frame(uchar *tValuesIn, qint32 tLength)
{
    validEfmSymbols = 0;
    invalidEfmSymbols = 0;
    correctedEfmSymbols = 0;

    isSync0 = false;
    isSync1 = false;
    subcodeSymbol = 0;

    setTValues(tValuesIn, tLength);
}

// This method sets the T-values for the F3 Frame
void F3Frame::setTValues(uchar* tValuesIn, qint32 tLength)
{
    // Does tValuesIn contain values?
    if (tLength == 0) {
        qDebug() << "F3Frame::setTValues(): T values array is empty!";
        return;
    }

    // Now perform the conversion
    // Step 1:

    // Convert the T values into a bit stream
    // Should produce 588 channel bits which is 73.5 bytes of data
    uchar rawFrameData[75];
    qint32 bitPosition = 7;
    qint32 bytePosition = 0;
    uchar byteData = 0;

    bool finished = false;
    for (qint32 tPosition = 0; tPosition < tLength; tPosition++) {
        uchar tValuesIn_tPosition = tValuesIn[tPosition];
        for (qint32 bitCount = 0; bitCount < tValuesIn_tPosition; bitCount++) {
            if (bitCount == 0) byteData |= (1 << bitPosition);
            bitPosition--;

            if (bitPosition < 0) {
                rawFrameData[bytePosition] = byteData;
                byteData = 0;
                bitPosition = 7;
                bytePosition++;

                // Check for overflow (due to errors in the T values) and stop processing to prevent crashes
                if (bytePosition > 73) {
                    finished = true;
                    break;
                }
            }

            if (finished) break;
        }

        if (finished) break;
    }

    // Add in the last nybble to get from 73.5 to 74 bytes
    if (bytePosition < 74) rawFrameData[bytePosition] = byteData;

    // Step 2:

    // Take the bit stream and extract just the EFM values it contains
    // There are 33 EFM values per F3 frame (1 Subcode symbol and 32 data symbols)

    // Composition of an EFM packet is as follows:
    //
    //  1 * (24 + 3) bits sync pattern         =  27
    //  1 * (14 + 3) bits control and display  =  17
    // 32 * (14 + 3) data+parity               = 544
    //                                   total = 588 bits

    qint16 efmValues[33];
    qint16 currentBit = 0;

    // Ignore the sync pattern (which is 24 bits plus 3 merging bits)
    currentBit += 24 + 3;

    // Get the 33 x 14-bit sync/EFM values
    for (qint32 counter = 0; counter < 33; counter++) {
        efmValues[counter] = getBits(rawFrameData, currentBit, 14);
        currentBit += 14 + 3; // the value plus 3 merging bits
    }

    // Step 3:

    // Decode the subcode symbol
    if (efmValues[0] == 0x801) {
        // Sync 0
        subcodeSymbol = 0;
        isSync0 = true;
    } else if (efmValues[0] == 0x012) {
        // Sync 1
        subcodeSymbol = 0;
        isSync1 = true;
    } else {
        // Normal subcode symbol
        subcodeSymbol = static_cast<uchar>(translateEfm(efmValues[0]));
    }

    // Step 4:

    // Decode the data symbols
    for (qint32 i = 0; i < 32; i++) {
        qint32 value = translateEfm(efmValues[i + 1]);
        if (value != -1) {
            // Translated to a valid value
            dataSymbols[i] = static_cast<uchar>(value);
            errorSymbols[i] = 0;
        } else {
            // Translation was invalid, mark as error
            dataSymbols[i] = 0;
            errorSymbols[i] = 1;
        }
    }
}

// Return the number of valid EFM symbols in the frame
qint64 F3Frame::getNumberOfValidEfmSymbols()
{
    return validEfmSymbols;
}

// Return the number of invalid EFM symbols in the frame
qint64 F3Frame::getNumberOfInvalidEfmSymbols()
{
    return invalidEfmSymbols;
}

// Return the number of corrected EFM symbols in the frame
qint64 F3Frame::getNumberOfCorrectedEfmSymbols()
{
    return correctedEfmSymbols;
}

// This method returns the 32 data symbols for the F3 Frame
uchar *F3Frame::getDataSymbols()
{
    return dataSymbols;
}

// This method returns the 32 error symbols for the F3 Frame
uchar *F3Frame::getErrorSymbols()
{
    return errorSymbols;
}

// This method returns the subcode symbol for the F3 frame
uchar F3Frame::getSubcodeSymbol()
{
    return subcodeSymbol;
}

// This method returns true if the subcode symbol is a SYNC0 pattern
bool F3Frame::isSubcodeSync0()
{
    return isSync0;
}

// This method returns true if the subcode symbol is a SYNC1 pattern
bool F3Frame::isSubcodeSync1()
{
    return isSync1;
}

// Private methods ----------------------------------------------------------------------------------------------------

// Method to translate 14-bit EFM value into 8-bit byte
// Returns -1 if the EFM value is could not be converted
qint16 F3Frame::translateEfm(qint16 efmValue)
{
    for (qint16 lutPos = 0; lutPos < 256; lutPos++) {
        if (efm2numberLUT[lutPos] == efmValue) {
            // Symbol was valid
            validEfmSymbols++;
            return lutPos;
        }
    }

    // Symbol was invalid
    invalidEfmSymbols++;

    // Attempt to recover symbol using cosine similarity lookup
    for (qint16 lutPos = 0; lutPos < 16384; lutPos++) {
        if (efmerr2positionLUT[lutPos] == efmValue) {
            // Found -- get the translated value from the second LUT
            correctedEfmSymbols++;
            return efmerr2valueLUT[lutPos];
        }
    }

    // Not found
    return -1;
}

// Method to get 'width' bits (max 15) from a byte array starting from bit 'bitIndex'
inline qint16 F3Frame::getBits(uchar *rawData, qint16 bitIndex, qint16 width)
{
    qint16 byteIndex = bitIndex / 8;
    qint16 bitInByteIndex = 7 - (bitIndex % 8);

    qint16 result = 0;
    for (qint16 nBits = width - 1; nBits > -1; nBits--) {
        if (rawData[byteIndex] & (1 << bitInByteIndex)) result += (1 << nBits);

        bitInByteIndex--;
        if (bitInByteIndex < 0) {
            bitInByteIndex = 7;
            byteIndex++;
        }
    }

    return result;
}

