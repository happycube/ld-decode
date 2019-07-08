/************************************************************************

    f2frame.cpp

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

#include "f2frame.h"

// Note: Class for storing 'F2 frames' as defined by clause 17 of ECMA-130

F2Frame::F2Frame()
{
    dataSymbols.resize(24);
    dataSymbols.fill(0, 24);

    discTime.setTime(0, 0, 0);
    trackTime.setTime(0, 0, 0);
    trackNumber = 0;
}

void F2Frame::setData(QByteArray dataParam, QByteArray erasuresParam)
{
    if (dataParam.size() != 24 || erasuresParam.size() != 24) {
        qCritical() << "F2Frame::setData(): Parameter size is incorrect!";
        return;
    }

    errorState = false;

    // Add the F2 frame data to the F2 data buffer and swap the byte
    // order (see ECMA-130 clause 16)
    for (qint32 j = 0; j < 24; j += 2) {
        dataSymbols[j] = dataParam[j+1];
        dataSymbols[j+1] = dataParam[j];

        if (erasuresParam[j] != static_cast<char>(0)) errorState = true;
        if (erasuresParam[j+1] != static_cast<char>(0)) errorState = true;
    }

    // Note: According the ECMA-130 audio data doesn't require byte swapping
    // however, since the required PCM sample format is little-endian (on a PC)
    // it is required.  Therefore we do it to the F2 frame data to save having
    // to perform the swapping twice (in the audio and data processing)
}

// This method returns the 24 data symbols for the F2 Frame
QByteArray F2Frame::getDataSymbols(void)
{
    return dataSymbols;
}

// This method returns true if the data in the F2 Frame
// is marked with erasures (i.e. it's corrupt)
bool F2Frame::isFrameCorrupt(void)
{
    return errorState;
}

// Time markers (not really part of an F2, but used to track the location of the F2 when processing audio)

void F2Frame::setDiscTime(TrackTime _discTime)
{
    discTime = _discTime;
}

void F2Frame::setTrackTime(TrackTime _trackTime)
{
    trackTime = _trackTime;
}

TrackTime F2Frame::getDiscTime(void)
{
    return discTime;
}

TrackTime F2Frame::getTrackTime(void)
{
    return trackTime;
}

void F2Frame::setTrackNumber(qint32 _trackNumber)
{
    trackNumber = _trackNumber;
}

qint32 F2Frame::getTrackNumber(void)
{
    return trackNumber;
}

void F2Frame::setIsEncoderRunning(bool _isEncoderRunning)
{
    isEncoderRunning = _isEncoderRunning;
}

bool F2Frame::getIsEncoderRunning(void)
{
    return isEncoderRunning;
}

