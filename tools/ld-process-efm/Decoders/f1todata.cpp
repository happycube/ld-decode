/************************************************************************

    f1todata.cpp

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

#include "f1todata.h"

F1ToData::F1ToData()
{
    debugOn = false;
    reset();
}

// Public methods -----------------------------------------------------------------------------------------------------

// Method to feed the sector processing state-machine with F1 frames
QByteArray F1ToData::process(QVector<F1Frame> f1FramesIn, bool debugState)
{
    debugOn = debugState;

    // Clear the output buffer
    dataOutputBuffer.clear();

    if (f1FramesIn.isEmpty()) return dataOutputBuffer;

    // Append input data to the processing buffer
    f1FrameBuffer.append(f1FramesIn);

    waitingForData = false;
    while (!waitingForData) {
        currentState = nextState;

        switch (currentState) {
        case state_initial:
            nextState = sm_state_initial();
            break;
        case state_getSync:
            nextState = sm_state_getSync();
            break;
        case state_processFrame:
            nextState = sm_state_processFrame();
            break;
        }
    }

    return dataOutputBuffer;
}

// Get method - retrieve statistics
F1ToData::Statistics F1ToData::getStatistics()
{
    return statistics;
}

// Method to report decoding statistics to qInfo
void F1ToData::reportStatistics()
{
    qInfo()           << "";
    qInfo()           << "F1 Frames to Data:";
    qInfo()           << "       Valid sectors:" << statistics.validSectors;
    qInfo()           << "     Invalid sectors:" << statistics.invalidSectors;
    qInfo()           << "       Total sectors:" << statistics.totalSectors;
    qInfo()           << "";
    qInfo().noquote() << "       Start address:" << statistics.startAddress.getTimeAsQString();
    qInfo().noquote() << "     Current address:" << statistics.currentAddress.getTimeAsQString();
}

// Reset the object
void F1ToData::reset()
{
    f1FrameBuffer.clear();
    dataOutputBuffer.clear();
    waitingForData = false;

    clearStatistics();
}

// Private methods ----------------------------------------------------------------------------------------------------

// Method to clear the statistics counters
void F1ToData::clearStatistics()
{
    statistics.validSectors = 0;
    statistics.invalidSectors = 0;
    statistics.totalSectors = 0;

    statistics.startAddress.setTime(0, 0, 0);
    statistics.currentAddress.setTime(0, 0, 0);
}

// State-machine methods ----------------------------------------------------------------------------------------------

F1ToData::StateMachine F1ToData::sm_state_initial()
{
    if (debugOn) qDebug() << "F1ToData::sm_state_initial(): Called";

    // Set initial disc time to 00:00.00
    statistics.startAddress.setTime(0, 0, 0);

    return state_processFrame;
}

// Find the next sector sync pattern
F1ToData::StateMachine F1ToData::sm_state_getSync()
{
    f1FrameBuffer.clear();
    waitingForData = true;
    return state_getSync;
}

// Process a sector into data
F1ToData::StateMachine F1ToData::sm_state_processFrame()
{
    return state_processFrame;
}
