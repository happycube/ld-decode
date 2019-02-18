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
// of 8-bit decoded data (33 bytes per F3 frame)
void EfmDecoder::convertTvaluesToData(QVector<qint32> frameT, uchar* outputData)
{
    // Firstly we have to make a bit-stream of the 588 channel bits including
    // all of the sync pattern and merge bits
    uchar rawFrameData[74];
    for (qint32 byteC = 0; byteC < 74; byteC++) rawFrameData[byteC] = 0;

    qint32 bitPosition = 0;
    qint32 bytePosition = 0;
    uchar byteData = 0;

    for (qint32 tPosition = 0; tPosition < frameT.size(); tPosition++) {
        for (qint32 bitCount = 0; bitCount < frameT[tPosition]; bitCount++) {

            if (bitCount == 0) byteData += 1; else byteData += 0;

            bitPosition++;
            if (bitPosition > 7) {
                rawFrameData[bytePosition] = byteData;
                byteData = 0;
                bitPosition = 0;
                bytePosition++;
            } else {
                byteData = static_cast<uchar>(byteData << 1);
            }
        }
    }

    // Process the last nibble (to make 73.5 bytes into 74)
    byteData = static_cast<uchar>(byteData << (7 - bitPosition));
    rawFrameData[bytePosition] = byteData;

    // Secondly, we take the bit stream and extract just the EFM values it contains
    // There are 33 EFM values per F3 frame

    // Composition of an EFM packet is as follows:
    //
    //  1 * (24 + 3) bits sync pattern         =  27
    //  1 * (14 + 3) bits control and display  =  17
    // 32 * (14 + 3) data+parity               = 544
    //                                   total = 588 bits

    // Which demodulates to and F3 frame of:
    //
    // Sync Pattern (discarded)
    //  1 byte control
    // 32 bytes data+parity
    //
    // Total of 33 bytes

    QVector<quint32> efmValues;
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

    // Note: Each output F3 frame consists of 34 bytes.  1 byte of sync data and
    // 33 bytes of actual F3 data.  We add the additional 1 byte so F3 frame
    // sync can be performed later (it's not a real F3 data byte, but otherwise
    // the SYNC0 and SYNC1 would be lost as they cannot be converted as EFM values)
    outputData[0] = 0; // No sync
    if (efmValues[0] == 0x801) outputData[0] = 0x01; // SYNC0
    if (efmValues[0] == 0x012) outputData[0] = 0x02; // SYNC1

    for (qint32 counter = 1; counter < 34; counter++) {
        qint32 result = -1;

        if (counter == 1 && (efmValues[0] == 0x801 || efmValues[0] == 0x012)) {
            // Sync bit, can't translate, so set data to 0
            outputData[counter] = 0;
        } else {
            // Normal EFM - translate to 8-bit value
            for (quint32 lutPos = 0; lutPos < 256; lutPos++) {
                if (efm2numberLUT[lutPos] == efmValues[counter - 1]) {
                    outputData[counter] = static_cast<uchar>(lutPos);
                    result = 1;
                    break;
                }
            }
        }

        if (result == -1) {
            // To-Do: count the EFM decode failures for debug
            qDebug() << "EfmDecoder::convertTvaluesToData(): 14-bit EFM value" << efmValues[counter -1] << "not found in translation look-up table";
            badDecodes++;
            outputData[counter] = 0;
        } else goodDecodes++;
    }
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
quint32 EfmDecoder::getBits(uchar *rawData, qint32 bitIndex, qint32 width)
{

    qint32 byteIndex = bitIndex / 8;
    qint32 bitInByteIndex = 7 - (bitIndex % 8);

    quint32 result = 0;
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

void EfmDecoder::hexDump(QString title, uchar *data, qint32 length)
{
    QString output;

    output += title;

    for (qint32 count = 0; count < length; count++) {
        output += QString("%1").arg(data[count], 2, 16, QChar('0'));
    }

    qDebug().noquote() << output;
}
