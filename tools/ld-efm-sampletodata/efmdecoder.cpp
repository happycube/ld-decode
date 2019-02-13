/************************************************************************

    efmdecoder.cpp

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

#include "efmdecoder.h"

EfmDecoder::EfmDecoder()
{
    goodDecodes = 0;
    badDecodes = 0;
}

// This method takes a vector of T values and returns a byte array
// of 8-bit decoded data (33 bytes per frame)
QByteArray EfmDecoder::convertTvaluesToData(QVector<qint32> frameT)
{
    // Firstly we have to make a bit-stream of the 588 channel bits including
    // all of the sync pattern and merge bits

    QByteArray rawFrameData;
    rawFrameData.resize(74); // 588 bits is actually 73.5 bytes

    qint32 bitPosition = 0;
    qint32 bytePosition = 0;
    qint32 byteData = 0;

    for (qint32 tPosition = 0; tPosition < frameT.size(); tPosition++) {
        for (qint32 bitCount = 0; bitCount < frameT[tPosition]; bitCount++) {

            if (bitCount == 0) byteData += 1; else byteData += 0;

            bitPosition++;
            if (bitPosition > 7) {
                rawFrameData[bytePosition] = static_cast<char>(byteData);
                byteData = 0;
                bitPosition = 0;
                bytePosition++;
            } else {
                byteData = byteData << 1;
            }
        }
    }

    // Process the last nibble (to make 73.5 bytes into 74)
    byteData = byteData << (7 - bitPosition);
    rawFrameData[bytePosition + 1] = static_cast<char>(byteData);

    // Secondly, we take the bit stream and extract just the EFM values it contains
    // There are 33 EFM values per frame

    // Composition of an EFM packet is as follows:
    //
    //  1 * (24 + 3) bits sync pattern         =  27
    //  1 * (14 + 3) bits control and display  =  17
    // 16 * (14 + 3) Q data+parity             = 272
    // 16 * (14 + 3) P data+parity             = 272
    //                                   total = 588 bits

    // Which demodulates to:
    //
    // Sync Pattern (discarded)
    //  1 byte control
    // 16 bytes Q data+parity
    // 16 bytes P data+parity
    //
    // Total of 33 bytes

    QVector<qint32> efmValues;
    efmValues.resize(33);
    qint32 currentBit = 0;

    // Ignore the sync pattern (which is 24 bits plus 3 merging bits)
    // To-do: check the sync pattern; could be useful debug
    currentBit += 24 + 3;

    // Get the 33 x 14-bit EFM values
    for (qint32 counter = 0; counter < 33; counter++) {
        efmValues[counter] = getBits(rawFrameData, currentBit, 14);
        currentBit += 14 + 3; // the value plus 3 merging bits
    }

    // Thirdly we take each EFM value, look it up and replace it with the
    // 8-bit value it represents
    QByteArray outputData;
    outputData.resize(33);
    for (qint32 counter = 0; counter < 33; counter++) {
        qint32 result = -1;

        for (qint32 lutPos = 0; lutPos < 256; lutPos++) {
            if (efm2numberLUT[lutPos] == efmValues[counter]) {
                outputData[counter] = static_cast<char>(lutPos);
                result = 1;
                break;
            }
        }

        if (result == -1) {
            // To-Do: count the EFM decode failures for debug
            badDecodes++;
            outputData[counter] = 0;
        } else goodDecodes++;
    }

    return outputData;
}

// Return the number of successfull EFM to 8-bit data decodes
qint32 EfmDecoder::getGoodDecodes(void)
{
    return goodDecodes;
}

// Return the number of unsuccessful EFM to 8-bit data decodes
qint32 EfmDecoder::getBadDecodes(void)
{
    return badDecodes;
}

// Method to get 'width' bits (max 32) from a byte array starting from
// bit 'bitIndex'
qint32 EfmDecoder::getBits(QByteArray rawData, qint32 bitIndex, qint32 width)
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
