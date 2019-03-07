/************************************************************************

    f3frame.cpp

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

#include "f3frame.h"

F3Frame::F3Frame()
{
    isSync0 = false;
    isSync1 = false;
    subcodeSymbol = -1;
    firstAfterSync = false;

    dataSymbols.resize(32);
    errorSymbols.resize(32);

    dataSymbols.fill(0);
    errorSymbols.fill(0);
}

// This method sets the T-values for the F3 Frame
void F3Frame::setTValues(QVector<qint32> tValuesIn)
{
    // Does tValuesIn contain values?
    if (tValuesIn.isEmpty()) {
        qDebug() << "F3Frame::setTValues(): T values array is empty!";
        return;
    }

    // Range check the incoming T Values
    for (qint32 i = 0; i < tValuesIn.size(); i++) {
        if (tValuesIn[i] < 3) {
            qDebug() << "F3Frame::setTValues(): Incoming T value is <T3";
            tValuesIn[i] = 3;
        }

        if (tValuesIn[i] > 11) {
            qDebug() << "F3Frame::setTValues(): Incoming T value is >T11";
            tValuesIn[i] = 11;
        }
    }

    // Now perform the conversion
    // Step 1:

    // Convert the T values into a bit stream
    // Should produce 588 channel bits which is 73.5 bytes of data
    uchar rawFrameData[74];
    qint32 bitPosition = 7;
    qint32 bytePosition = 0;
    uchar byteData = 0;

    for (qint32 tPosition = 0; tPosition < tValuesIn.size(); tPosition++) {
        for (qint32 bitCount = 0; bitCount < tValuesIn[tPosition]; bitCount++) {
            if (bitCount == 0) byteData |= (1 << bitPosition);
            bitPosition--;

            if (bitPosition < 0) {
                rawFrameData[bytePosition] = byteData;
                byteData = 0;
                bitPosition = 7;
                bytePosition++;

                // Check for overflow (due to errors in the T values)
                if (bytePosition == 74) {
                    qDebug() << "F3Frame::setTValues(): 14-bit EFM frame length exceeded 74 bytes";
                    break;
                }
            }
        }
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

    qint32 efmValues[33];
    qint32 currentBit = 0;

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
        subcodeSymbol = -1;
        isSync0 = true;
    } else if (efmValues[0] == 0x012) {
        // Sync 1
        subcodeSymbol = -1;
        isSync1 = true;
    } else {
        // Normal subcode symbol
        subcodeSymbol = translateEfm(efmValues[0]);
    }

    // Step 4:

    // Decode the data symbols
    for (qint32 i = 0; i < 32; i++) {
        qint32 value = translateEfm(efmValues[i + 1]);
        if (value != -1) {
            // Translated to a valid value
            dataSymbols[i] = static_cast<char>(value);
            errorSymbols[i] = 0;
        } else {
            // Translation was invalid, mark as error
            dataSymbols[i] = 0;
            errorSymbols[i] = 1;
        }
    }

    //qDebug().noquote() << "F3Frame::setTValues(): F3 Frame data symbols =" << dataToString(dataSymbols);
}

// This method returns the 32 data symbols for the F3 Frame
QByteArray F3Frame::getDataSymbols(void)
{
    return dataSymbols;
}

// This method returns the 32 error symbols for the F3 Frame
QByteArray F3Frame::getErrorSymbols(void)
{
    return errorSymbols;
}

// This method returns the subcode symbol for the F3 frame
// Note: Returns -1 if the subcode symbol is a SYNC0 or SYNC1
qint32 F3Frame::getSubcodeSymbol(void)
{
    return subcodeSymbol;
}

// This method returns true if the subcode symbol is a SYNC0 pattern
bool F3Frame::isSubcodeSync0(void)
{
    return isSync0;
}

// This method returns true if the subcode symbol is a SYNC1 pattern
bool F3Frame::isSubcodeSync1(void)
{
    return isSync1;
}

// Set flag to indicate if the F3 frame is the first after the
// initial sync (true) or a continuation of a frame sequence
void F3Frame::setFirstAfterSync(bool parameter)
{
    firstAfterSync = parameter;
}

// Get first after sync flag
bool F3Frame::getFirstAfterSync(void)
{
    return firstAfterSync;
}

// Private methods ----------------------------------------------------------------------------------------------------

// Method to translate 14-bit EFM value into 8-bit byte
// Returns -1 if the EFM value is invalid
qint32 F3Frame::translateEfm(qint32 efmValue)
{
    qint32 result = -1;

    for (qint32 lutPos = 0; lutPos < 256; lutPos++) {
        if (efm2numberLUT[lutPos] == efmValue) {
            result = static_cast<uchar>(lutPos);
            break;
        }
    }

    return result;
}

// Method to get 'width' bits (max 31) from a byte array starting from bit 'bitIndex'
qint32 F3Frame::getBits(uchar *rawData, qint32 bitIndex, qint32 width)
{
    qint32 byteIndex = bitIndex / 8;
    qint32 bitInByteIndex = 7 - (bitIndex % 8);

    qint32 result = 0;
    for (qint32 nBits = width - 1; nBits > -1; nBits--) {
        if (rawData[byteIndex] & (1 << bitInByteIndex)) result += (1 << nBits);

        bitInByteIndex--;
        if (bitInByteIndex < 0) {
            bitInByteIndex = 7;
            byteIndex++;
        }
    }

    return result;
}

// This method is for debug and outputs an array of 8-bit unsigned data as a hex string
QString F3Frame::dataToString(QByteArray data)
{
    QString output;

    for (qint32 count = 0; count < data.length(); count++) {
        output += QString("%1").arg(static_cast<uchar>(data[count]), 2, 16, QChar('0'));
    }

    return output;
}
