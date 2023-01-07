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
#include "vbiutilities.h"

// Public method to read CEA-608 Closed Captioning data.
// Return true if CC data was decoded successfully, false otherwise.
bool ClosedCaption::decodeLine(const SourceVideo::Data& lineData,
                               const LdDecodeMetaData::VideoParameters& videoParameters,
                               LdDecodeMetaData::Field& fieldMetadata)
{
    // Reset data to invalid
    fieldMetadata.closedCaption.inUse = false;
    fieldMetadata.closedCaption.data0 = -1;
    fieldMetadata.closedCaption.data1 = -1;

    // Determine the 16-bit zero-crossing point
    qint32 zcPoint = ((videoParameters.white16bIre - videoParameters.black16bIre) / 4) + videoParameters.black16bIre;

    // Get the transition map for the line
    QVector<bool> transitionMap = getTransitionMap(lineData, zcPoint);

    // Set the number of samples to the expected start of the start bit transition
    qint32 expectedStart = videoParameters.activeVideoStart + 262;

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
        return false;
    } else {
        qDebug() << "ClosedCaption::getData(): Found start bit transition at" << x << "(expected" << expectedStart << ")";
    }

    // Skip the the start bit and move to the centre of the first payload bit
    x += samplesPerBit + (samplesPerBit / 2);

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
    } else {
        fieldMetadata.closedCaption.data0 = byte0;
        fieldMetadata.closedCaption.inUse = true;
    }

    if (isEvenParity(byte1) && byte1Parity != 1) {
        qDebug() << "ClosedCaption::getData(): Second byte failed parity check!";
    } else {
        fieldMetadata.closedCaption.data1 = byte1;
        fieldMetadata.closedCaption.inUse = true;
    }

    return true;
}
