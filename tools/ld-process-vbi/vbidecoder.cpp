/************************************************************************

    vbidecoder.cpp

    ld-process-vbi - VBI and IEC NTSC specific processor for ld-decode
    Copyright (C) 2018-2019 Simon Inns

    This file is part of ld-decode-tools.

    ld-process-vbi is free software: you can redistribute it and/or
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

#include "vbidecoder.h"
#include "decoderpool.h"

VbiDecoder::VbiDecoder(QAtomicInt& _abort, DecoderPool& _decoderPool, QObject *parent)
    : QThread(parent), abort(_abort), decoderPool(_decoderPool)
{

}

// Thread main processing method
void VbiDecoder::run()
{
    qint32 fieldNumber;

    // Input data buffers
    QByteArray sourceFieldData;
    LdDecodeMetaData::Field fieldMetadata;
    LdDecodeMetaData::VideoParameters videoParameters;

    while(!abort) {
        // Get the next field to process from the input file
        if (!decoderPool.getInputField(fieldNumber, sourceFieldData, fieldMetadata, videoParameters)) {
            // No more input fields -- exit
            break;
        }

        FmCode fmCode;
        FmCode::FmDecode fmDecode;

        bool isWhiteFlag = false;
        WhiteFlag whiteFlag;

        ClosedCaption closedCaption;
        ClosedCaption::CcData ccData;

        if (fieldMetadata.isFirstField) qDebug() << "VbiDecoder::process(): Getting metadata for field" << fieldNumber << "(first)";
        else  qDebug() << "VbiDecoder::process(): Getting metadata for field" << fieldNumber << "(second)";

        // Determine the 16-bit zero-crossing point
        qint32 zcPoint = videoParameters.white16bIre - videoParameters.black16bIre;

        // Get the VBI data from the field lines (we only read field lines 10-21, so the real field line number is -9)
        qDebug() << "VbiDecoder::process(): Getting field-lines for field" << fieldNumber;
        fieldMetadata.vbi.vbiData[0] = manchesterDecoder(getActiveVideoLine(&sourceFieldData, 16 - 9, videoParameters), zcPoint, videoParameters);
        fieldMetadata.vbi.vbiData[1] = manchesterDecoder(getActiveVideoLine(&sourceFieldData, 17 - 9, videoParameters), zcPoint, videoParameters);
        fieldMetadata.vbi.vbiData[2] = manchesterDecoder(getActiveVideoLine(&sourceFieldData, 18 - 9, videoParameters), zcPoint, videoParameters);

        // Show the VBI data as hexadecimal (for every 1000th field)
        if (fieldNumber % 1000 == 0) {
            qInfo() << "Processing field" << fieldNumber;
        }

        // Process NTSC specific data if source type is NTSC
        if (!videoParameters.isSourcePal) {
            // Get the 40-bit FM coded data from the field lines
            fmDecode = fmCode.fmDecoder(getActiveVideoLine(&sourceFieldData, 10 - 9, videoParameters), videoParameters);

            // Get the white flag from the field lines
            isWhiteFlag = whiteFlag.getWhiteFlag(getActiveVideoLine(&sourceFieldData, 11 - 9, videoParameters), videoParameters);

            // Get the closed captioning from field line 21
            ccData = closedCaption.getData(getActiveVideoLine(&sourceFieldData, 21 - 9, videoParameters), videoParameters);

            // Update the metadata
            if (fmDecode.receiverClockSyncBits != 0) {
                fieldMetadata.ntsc.isFmCodeDataValid = true;
                fieldMetadata.ntsc.fmCodeData = static_cast<qint32>(fmDecode.data);
                if (fmDecode.videoFieldIndicator == 1) fieldMetadata.ntsc.fieldFlag = true;
                else fieldMetadata.ntsc.fieldFlag = false;
            } else {
                fieldMetadata.ntsc.isFmCodeDataValid = false;
                fieldMetadata.ntsc.fmCodeData = -1;
                fieldMetadata.ntsc.fieldFlag = false;
            }

            fieldMetadata.ntsc.whiteFlag = isWhiteFlag;
            fieldMetadata.ntsc.inUse = true;

            if (ccData.isValid) {
                fieldMetadata.ntsc.ccData0 = ccData.byte0;
                fieldMetadata.ntsc.ccData1 = ccData.byte1;
            } else {
                fieldMetadata.ntsc.ccData0 = -1;
                fieldMetadata.ntsc.ccData1 = -1;
            }
        }

        // Update the metadata for the field
        fieldMetadata.vbi.inUse = true;

        // Write the result to the output metadata
        if (!decoderPool.setOutputField(fieldNumber, fieldMetadata)) {
            abort = true;
            break;
        }
    }
}

// Private method to get a single scanline of greyscale data
QByteArray VbiDecoder::getActiveVideoLine(QByteArray *sourceField, qint32 fieldLine,
                                        LdDecodeMetaData::VideoParameters videoParameters)
{
    // Range-check the scan line
    if (fieldLine > videoParameters.fieldHeight || fieldLine < 1) {
        qWarning() << "Cannot generate field-line data, line number is out of bounds! Scan line =" << fieldLine;
        return QByteArray();
    }

    qint32 startPointer = ((fieldLine - 1) * videoParameters.fieldWidth * 2) + (videoParameters.activeVideoStart * 2);
    qint32 length = (videoParameters.activeVideoEnd - videoParameters.activeVideoStart) * 2;

    return sourceField->mid(startPointer, length);
}

// Private method to read a 24-bit biphase coded signal (manchester code) from a field line
qint32 VbiDecoder::manchesterDecoder(QByteArray lineData, qint32 zcPoint,
                                     LdDecodeMetaData::VideoParameters videoParameters)
{
    qint32 result = 0;
    QVector<bool> manchesterData = getTransitionMap(lineData, zcPoint);

    // Get the number of samples for 1.5us
    qreal fJumpSamples = (videoParameters.sampleRate / 1000000) * 1.5;
    qint32 jumpSamples = static_cast<qint32>(fJumpSamples);

    // Keep track of the number of bits decoded
    qint32 decodeCount = 0;

    // Find the first transition
    qint32 x = 0;
    while (x < manchesterData.size() && manchesterData[x] == false) {
        x++;
    }

    if (x < manchesterData.size()) {
        // Plot the first transition (which is always 01)
        result += 1;
        decodeCount++;

        // Find the rest of the transitions based on the expected clock rate of 2us per cell window
        while (x < manchesterData.size()) {
            x = x + jumpSamples;

            // Ensure we don't go out of bounds
            if (x >= manchesterData.size()) break;

            bool startState = manchesterData[x];
            while (x < manchesterData.size() && manchesterData[x] == startState)
            {
                x++;
            }

            if (x < manchesterData.size()) {
                if (manchesterData[x - 1] == false && manchesterData[x] == true) {
                    // 01 transition
                    result = (result << 1) + 1;
                }
                if (manchesterData[x - 1] == true && manchesterData[x] == false) {
                    // 10 transition
                    result = result << 1;
                }
                decodeCount++;
            }
        }
    }

    // We must have 24-bits if the decode was successful
    if (decodeCount != 24) {
        if (decodeCount == 0) qDebug() << "VbiDecoder::manchesterDecoder(): No VBI data found in the field line";
        else qDebug() << "VbiDecoder::manchesterDecoder(): Manchester decode failed!  Only got" << decodeCount << "bits";
        result = 0;
    }

    return result;
}

// Private method to get the map of transitions across the sample and reject noise
QVector<bool> VbiDecoder::getTransitionMap(QByteArray lineData, qint32 zcPoint)
{
    // First read the data into a boolean array using debounce to remove transition noise
    bool previousState = false;
    bool currentState = false;
    qint32 debounce = 0;
    QVector<bool> manchesterData;

    for (qint32 xPoint = 0; xPoint < lineData.size(); xPoint += 2) {
        qint32 pixelValue = (static_cast<uchar>(lineData[xPoint + 1]) * 256) + static_cast<uchar>(lineData[xPoint]);
        if (pixelValue > zcPoint) currentState = true; else currentState = false;

        if (currentState != previousState) debounce++;

        if (debounce > 3) {
            debounce = 0;
            previousState = currentState;
        }

        manchesterData.append(previousState);
    }

    return manchesterData;
}
