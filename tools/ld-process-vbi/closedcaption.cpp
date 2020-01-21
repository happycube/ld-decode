/************************************************************************

    closedcaption.cpp

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

#include "closedcaption.h"

// Public method to read CEA-608 Closed Captioning data (NTSC only)
ClosedCaption::CcData ClosedCaption::getData(const SourceVideo::Data &lineData, LdDecodeMetaData::VideoParameters videoParameters)
{
    CcData ccData;
    ccData.byte0 = 0;
    ccData.byte1 = 0;
    ccData.isValid = false;

    // Determine the 16-bit zero-crossing point
    qint32 zcPoint = ((videoParameters.white16bIre - videoParameters.black16bIre) / 4) + videoParameters.black16bIre;

    // Get the transition map for the line
    QVector<bool> transitionMap = getTransitionMap(lineData, zcPoint);

    // Set the number of samples to the expected start of the start bit transition
    qint32 expectedStart = 262;

    // Set the width of 1 bit
    qint32 samplesPerBit = 28;

    // Find the first transition
    qint32 x = expectedStart - samplesPerBit;
    while (x < transitionMap.size() && transitionMap[x] == false) {
        x++;
    }

    // Check that the first transition is where it should be
    if (abs(x - expectedStart) > 16) {
        qDebug() << "ClosedCaption::getData(): Expected" << expectedStart << "but got" << x << "- invalid CC line";
        return ccData;
    } else {
        qDebug() << "ClosedCaption::getData(): Found start bit transition at" << x << "(expected" << expectedStart << ")";
    }

    // Skip the the start bit and move to the centre of the first payload bit
    x = x + samplesPerBit + (samplesPerBit / 2);

    // Get the first 7 bit code
    uchar byte0 = 0;
    for (qint32 i = 0; i < 7; i++)
    {
        byte0 >>= 1;
        if (transitionMap[x]) byte0 += 64;
        x += samplesPerBit;
    }

    // Get the first 7 bit parity
    uchar byte0Parity = 0;
    if (transitionMap[x]) byte0Parity = 1;
    x += samplesPerBit;

    // Get the second byte
    uchar byte1 = 0;
    for (qint32 i = 0; i < 7; i++)
    {
        byte1 >>= 1;
        if (transitionMap[x]) byte1 += 64;
        x += samplesPerBit;
    }

    // Get the second 7 bit parity
    uchar byte1Parity = 0;
    if (transitionMap[x]) byte1Parity = 1;
    x += samplesPerBit;

    qDebug().nospace() << "ClosedCaption::getData(): Bytes are: " << byte0 << " (" << byte0Parity << ") - "
                       << byte1 << " (" << byte1Parity << ")";

    if (isEvenParity(byte0) && byte0Parity != 1) {
        qDebug() << "ClosedCaption::getData(): First byte failed parity check!";
        byte0 = 0;
    }

    if (isEvenParity(byte1) && byte1Parity != 1) {
        qDebug() << "ClosedCaption::getData(): Second byte failed parity check!";
        byte1 = 0;
    }

    ccData.byte0 = byte0;
    ccData.byte1 = byte1;
    ccData.isValid = true;

    return ccData;
}

// Private method to check data for even parity
bool ClosedCaption::isEvenParity(uchar data)
{
    qint32 count = 0, b = 1;

    for(qint32 i = 0; i < 7; i++) {
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
QVector<bool> ClosedCaption::getTransitionMap(const SourceVideo::Data &lineData, qint32 zcPoint)
{
    // First read the data into a boolean array using debounce to remove transition noise
    bool previousState = false;
    bool currentState = false;
    qint32 debounce = 0;
    QVector<bool> transitionMap;

    // Each value is 2 bytes (16-bit greyscale data)
    for (qint32 xPoint = 0; xPoint < lineData.size(); xPoint++) {
        if (lineData[xPoint] > zcPoint) currentState = true; else currentState = false;

        if (currentState != previousState) debounce++;

        if (debounce > 3) {
            debounce = 0;
            previousState = currentState;
        }

        transitionMap.append(previousState);
    }

    return transitionMap;
}
