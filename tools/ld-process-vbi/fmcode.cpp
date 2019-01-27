/************************************************************************

    fmcode.cpp

    ld-process-vbi - VBI and IEC NTSC specific processor for ld-decode
    Copyright (C) 2018 Simon Inns

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

#include "fmcode.h"

FmCode::FmCode(QObject *parent) : QObject(parent)
{

}

// Public method to read a 40-bit FM coded signal from a field line
FmCode::FmDecode FmCode::fmDecoder(QByteArray lineData, LdDecodeMetaData::VideoParameters videoParameters)
{
    FmDecode fmDecode;
    fmDecode.receiverClockSyncBits = 0;
    fmDecode.videoFieldIndicator = 0;
    fmDecode.leadingDataRecognitionBits = 0;
    fmDecode.data = 0;
    fmDecode.dataParityBit = 0;
    fmDecode.trailingDataRecognitionBits = 0;

    quint64 decodedBytes = 0;

    // Determine the 16-bit zero-crossing point
    qint32 zcPoint = videoParameters.white16bIre - videoParameters.black16bIre;

    QVector<bool> fmData = getTransitionMap(lineData, zcPoint);

    // Get the number of samples for 0.75us
    qreal fSamples = (videoParameters.sampleRate / 1000000) * 0.75;
    qint32 samples = static_cast<qint32>(fSamples);

    // Keep track of the number of bits decoded
    qint32 decodeCount = 0;

    // Find the first transition
    qint32 x = 0;
    while (x < fmData.size() && fmData[x] == false) {
        x++;
    }

    if (x < fmData.size()) {
        qint32 lastTransistionX = x;
        bool lastState = fmData[x];

        // Find the rest of the bits
        while (x < fmData.size() && decodeCount < 40) {
            // Find the next transition
            while (x < fmData.size() && fmData[x] == lastState)
            {
                x++;
            }

            lastState = fmData[x];

            // Was the transition in the middle of the cell?
            if (x - lastTransistionX < samples) {
                decodedBytes = (decodedBytes << 1) + 1;
                lastTransistionX = x;
                decodeCount++;

                // Find the end of the cell
                while (x < fmData.size() && fmData[x] == lastState)
                {
                    x++;
                }
                if (x >= fmData.size()) break; // Check for overflow
                lastState = fmData[x];
                lastTransistionX = x;
            } else {
                decodedBytes = (decodedBytes << 1);
                lastTransistionX = x;
                decodeCount++;
            }

            // Next x
            x = x + 1;
        }
    }

    // We must have 40-bits if the decode was successful
    if (decodeCount != 40) {
        if (decodeCount == 0) qDebug() << "FmCode::fmDecoder(): No FM code data found in the field line";
        else qDebug() << "FmCode::fmDecoder(): FM decode failed!  Only got" << decodeCount << "bits";
        decodedBytes = 0;
    } else {
        // Show the 40-bit FM coded data as hexadecimal
        qDebug() << "FmCode::fmDecoder(): 40-bit FM code is" << QString::number(decodedBytes, 16);

        // Split the result into the required fields
        bool isValid = true;

        fmDecode.receiverClockSyncBits = (decodedBytes & 0xF000000000) >> 36;
        fmDecode.videoFieldIndicator = (decodedBytes & 0x0800000000) >> 35;
        fmDecode.leadingDataRecognitionBits = (decodedBytes & 0x07F0000000) >> 28;
        fmDecode.data = (decodedBytes & 0x000FFFFF00) >>  8;
        fmDecode.dataParityBit = (decodedBytes & 0x0000000080) >> 7;
        fmDecode.trailingDataRecognitionBits = (decodedBytes & 0x000000007F);

        qDebug() << "FmCode::fmDecoder(): receiverClockSyncBits =" << fmDecode.receiverClockSyncBits;
        qDebug() << "FmCode::fmDecoder(): videoFieldIndicator =" << fmDecode.videoFieldIndicator;
        qDebug() << "FmCode::fmDecoder(): leadingDataRecognitionBits =" << fmDecode.leadingDataRecognitionBits;
        qDebug() << "FmCode::fmDecoder(): data =" << fmDecode.data;
        qDebug() << "FmCode::fmDecoder(): dataParityBit =" << fmDecode.dataParityBit;
        qDebug() << "FmCode::fmDecoder(): trailingDataRecognitionBits =" << fmDecode.trailingDataRecognitionBits;

        // Sanity check the data
        if (fmDecode.receiverClockSyncBits != 3 || fmDecode.leadingDataRecognitionBits != 114 || fmDecode.trailingDataRecognitionBits != 13) {
            qWarning() << "FM code does not appear sane";
            isValid = false;
        }

        // Check parity (dataParityBit = 1 = odd parity)
        if (fmDecode.dataParityBit == 1 && !isEvenParity(fmDecode.data)) {
            qWarning() << "Data fails parity check (expected even, got odd)";
            isValid = false;
        }

        if (fmDecode.dataParityBit == 0 && isEvenParity(fmDecode.data)) {
            qWarning() << "Data fails parity check (expected odd, got even)";
            isValid = false;
        }

        // If the result isn't valid, clear all the fields
        if (!isValid) {
            fmDecode.receiverClockSyncBits = 0;
            fmDecode.videoFieldIndicator = 0;
            fmDecode.leadingDataRecognitionBits = 0;
            fmDecode.data = 0;
            fmDecode.dataParityBit = 0;
            fmDecode.trailingDataRecognitionBits = 0;
        }
    }

    return fmDecode;
}

// Private method to check data for even parity
bool FmCode::isEvenParity(quint64 data)
{
    quint64 count = 0, b = 1;

    for(quint64 i = 0; i < 64; i++) {
        if (data & (b << i)) {
            count++;
        }
    }

    if (count % 2) {
        return false;
    }

    return true;
}

// Private method to get the map of transitions across the sample and reject noise
QVector<bool> FmCode::getTransitionMap(QByteArray lineData, qint32 zcPoint)
{
    // First read the data into a boolean array using debounce to remove transition noise
    bool previousState = false;
    bool currentState = false;
    qint32 debounce = 0;
    QVector<bool> fmData;

    qint32 fmPointer = 0;
    for (qint32 xPoint = 0; xPoint < lineData.size(); xPoint += 2) {
        qint32 pixelValue = (static_cast<uchar>(lineData[xPoint + 1]) * 256) + static_cast<uchar>(lineData[xPoint]);
        if (pixelValue > zcPoint) currentState = true; else currentState = false;

        if (currentState != previousState) debounce++;

        if (debounce > 3) {
            debounce = 0;
            previousState = currentState;
        }

        fmData.append(previousState);
        fmPointer++;
    }

    return fmData;
}
