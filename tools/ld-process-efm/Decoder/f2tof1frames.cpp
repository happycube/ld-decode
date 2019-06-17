/************************************************************************

    f2tof1frames.cpp

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

#include "f2tof1frames.h"
#include "logging.h"

F2ToF1Frames::F2ToF1Frames()
{
    // Create the 12 byte F1 frame sync pattern
    syncPattern.append(static_cast<char>(0x00));
    syncPattern.append(static_cast<char>(0xFF));
    syncPattern.append(static_cast<char>(0xFF));
    syncPattern.append(static_cast<char>(0xFF));
    syncPattern.append(static_cast<char>(0xFF));
    syncPattern.append(static_cast<char>(0xFF));
    syncPattern.append(static_cast<char>(0xFF));
    syncPattern.append(static_cast<char>(0xFF));
    syncPattern.append(static_cast<char>(0xFF));
    syncPattern.append(static_cast<char>(0xFF));
    syncPattern.append(static_cast<char>(0xFF));
    syncPattern.append(static_cast<char>(0x00));

    reset();
}

// Method to reset and flush all buffers
void F2ToF1Frames::reset(void)
{
    // Initialise the state machine
    currentState = state_initial;
    nextState = currentState;
    waitingForF2frames = false;

    missedF1SyncCount = 0;
    F1SyncLost = 0;
    poorSyncs = 0;
    totalF1Frames = 0;

    f1FrameBuffer.clear();
    f2DataBuffer.clear();
    f2ErrorBuffer.clear();

    resetStatistics();
}

// Reset the statistics
void F2ToF1Frames::resetStatistics(void)
{
    missedF1SyncCount = 0;
    F1SyncLost = 0;
    totalF1Frames = 0;
    poorSyncs = 0;
}

// Method to write status information to qCInfo
void F2ToF1Frames::reportStatus(void)
{
    qInfo() << "F2 to F1 converter:";
    qInfo() << "  Total number of F1 frames =" << totalF1Frames;
    qInfo() << "  Number of F1 frames with sync missing =" << missedF1SyncCount;
    qInfo() << "  Lost F1 sync" << F1SyncLost << "times";
}

QVector<F1Frame> F2ToF1Frames::convert(QVector<F2Frame> f2FramesIn)
{
    // Clear the F1 frame buffer
    f1FrameBuffer.clear();

    // Add the F2 frame data to the F2 data buffer
    for (qint32 i = 0; i < f2FramesIn.size(); i++) {
        f2DataBuffer.append(f2FramesIn[i].getDataSymbols());
        f2ErrorBuffer.append(f2FramesIn[i].getErrorSymbols());
    }

    // Since we have a new F2 frames, clear the waiting flag
    waitingForF2frames = false;

    // Process the state machine until more F2 frames are required
    while (!waitingForF2frames) {
        currentState = nextState;

        switch (currentState) {
        case state_initial:
            nextState = sm_state_initial();
            break;
        case state_getInitialSync:
            nextState = sm_state_getInitialSync();
            break;
        case state_getInitialF1Frame:
            nextState = sm_state_getInitialF1Frame();
            break;
        case state_getNextF1Frame:
            nextState = sm_state_getNextF1Frame();
            break;
        case state_syncLost:
            nextState = sm_state_syncLost();
            break;
        }
    }

    return f1FrameBuffer;
}

F2ToF1Frames::StateMachine F2ToF1Frames::sm_state_initial(void)
{
    return state_getInitialSync;
}

F2ToF1Frames::StateMachine F2ToF1Frames::sm_state_getInitialSync(void)
{
    // Look for the F1 sync pattern in the F2 data buffer
    qint32 syncPosition = f2DataBuffer.indexOf(syncPattern);

    if (syncPosition == -1) {
        // Sync pattern was not found, discard buffer and request
        // more F2 data
        f2DataBuffer.clear();
        f2ErrorBuffer.clear();
        waitingForF2frames = true;

        return state_getInitialSync;
    }

    qDebug() << "F2ToF1Frames::sm_state_getInitialSync(): F1 Sync position:" << syncPosition;

    // Sync found, discard all F2 data up to the start of the sync pattern
    removeF2Data(syncPosition);

    return state_getInitialF1Frame;
}

F2ToF1Frames::StateMachine F2ToF1Frames::sm_state_getInitialF1Frame(void)
{
    // Do we have enough buffered F2 data to make a complete F1 frame?
    if (f2DataBuffer.size() < 2352) {
        // Get more F2 data
        waitingForF2frames = true;
        return state_getInitialF1Frame;
    }

    qDebug() << "F2ToF1Frames::sm_state_getInitialF1Frame(): Got initial F1 frame";

    // Place the F1 frame data into a F1 frame object
    F1Frame tempF1Frame;
    tempF1Frame.setData(f2DataBuffer.mid(0, 2352), f2ErrorBuffer.mid(0, 2352));

    // Append the F1 frame to the frame buffer
    f1FrameBuffer.append(tempF1Frame);
    totalF1Frames++;

    // Remove the data from the F2 data buffer
    removeF2Data(2352);

    return state_getNextF1Frame;
}

F2ToF1Frames::StateMachine F2ToF1Frames::sm_state_getNextF1Frame(void)
{
    // Do we have enough buffered F2 data to make a complete F1 frame?
    if (f2DataBuffer.size() < 2352) {
        // Get more F2 data
        waitingForF2frames = true;
        return state_getNextF1Frame;
    }

    // Check sync pattern is present
    qint32 syncPosition = f2DataBuffer.indexOf(syncPattern);
    if (syncPosition != 0) {
        // Sync is missing
        poorSyncs++;
        missedF1SyncCount++;
        qDebug() << "F2ToF1Frames::sm_state_getNextF1Frame(): F1 Frame has missing sync!";

        if (poorSyncs > 4) {
            // We have missed 4 syncs in a row... set sync lost
            poorSyncs = 0;
            return state_syncLost;
        }
    } else poorSyncs = 0;

    // Place the F1 frame data into a F1 frame object
    F1Frame tempF1Frame;
    tempF1Frame.setData(f2DataBuffer.mid(0, 2352), f2ErrorBuffer.mid(0, 2352));

    // Append the F1 frame to the frame buffer
    f1FrameBuffer.append(tempF1Frame);
    totalF1Frames++;

    // Remove the data from the F2 data buffer
    removeF2Data(2352);

    return state_getNextF1Frame;
}

F2ToF1Frames::StateMachine F2ToF1Frames::sm_state_syncLost(void)
{
    qDebug() << "F2ToF1Frames::sm_state_syncLost(): F1 Frame sync has been lost!";
    F1SyncLost++;
    return state_getInitialSync;
}

// Method to remove F2 data from the start of the F2 data buffer (and the
// F2 error buffer)
void F2ToF1Frames::removeF2Data(qint32 number)
{
    if (number > f2DataBuffer.size()) {
        f2DataBuffer.clear();
        f2ErrorBuffer.clear();
    } else {
        // Shift the byte array back by 'number' elements
        f2DataBuffer.remove(0, number);
        f2ErrorBuffer.remove(0, number);
    }
}

