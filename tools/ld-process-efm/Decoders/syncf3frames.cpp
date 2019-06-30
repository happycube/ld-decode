/************************************************************************

    syncf3frames.cpp

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

#include "syncf3frames.h"

// Note: This class ensures that the F3 Frame output is synchronised with
// the subcode sections.  This is required for audio processing as, without
// the subcode metadata, it's not possible to resync audio data if the input
// data is corrupt.  This wasn't an issue on real players, as the play back
// would just "start again" - however, here the audio must keep sync with the
// video output from ld-decode, so the sample gaps caused by corruption must
// be replaced with exact 'gaps' that can only be calculated if we keep the
// subcode metadata and F3 frames synchronised throughout the decoding process.
//
// This sync isn't required for data-only EFM (as the metadata and sectors
// are contained in the same stream of data).

SyncF3Frames::SyncF3Frames()
{
    debugOn = false;
    abort = false;
}

// Public methods -----------------------------------------------------------------------------------------------------

void SyncF3Frames::startProcessing(QFile *inputFileHandle, QFile *outputFileHandle)
{
    abort = false;

    // Clear the statistic counters
    clearStatistics();

    // Initialise the state-machine
    currentState = state_initial;
    nextState = currentState;
    waitingForData = false;

    // Define an input data stream
    QDataStream inputDataStream(inputFileHandle);

    // Define an output data stream
    QDataStream outputDataStream(outputFileHandle);

    if (debugOn) qDebug() << "SyncF3Frames::startProcessing(): Initial input file size of" << inputFileHandle->bytesAvailable() << "bytes";

    // Find the first subcode sync frame
    F3Frame f3frame;
    while (inputFileHandle->bytesAvailable() != 0 && !abort) {
        inputDataStream >> f3frame;
        f3FrameBuffer.append(f3frame);
        statistics.totalF3Frames++;

        waitingForData = false;
        while (!waitingForData) {
            currentState = nextState;

            switch (currentState) {
            case state_initial:
                nextState = sm_state_initial();
                break;
            case state_findInitialSync0:
                nextState = sm_state_findInitialSync0();
                break;
            case state_findNextSync:
                nextState = sm_state_findNextSync();
                break;
            case state_syncLost:
                nextState = sm_state_syncLost();
                break;
            case state_processSection:
                nextState = sm_state_processSection(&outputDataStream);
                break;
            }
        }
    }

    if (debugOn) qDebug() << "SyncF3Frames::startProcessing(): No more data to processes";
}

void SyncF3Frames::stopProcessing(void)
{
    abort = true;
}

SyncF3Frames::Statistics SyncF3Frames::getStatistics(void)
{
    return statistics;
}

void SyncF3Frames::reportStatistics(void)
{
    qInfo() << "";
    qInfo() << "F3 Frame synchronisation:";
    qInfo() << "   Total input F3 Frames:" << statistics.totalF3Frames;
    qInfo() << "        Discarded Frames:" << statistics.discardedFrames;
    qInfo() << "    Total valid sections:" << statistics.totalSections << "(" << statistics.totalSections * 98 << "F3 Frames )";
}

// Private methods ----------------------------------------------------------------------------------------------------

void SyncF3Frames::clearStatistics(void)
{
    statistics.totalF3Frames = 0;
    statistics.discardedFrames = 0;
    statistics.totalSections = 0;
}

// Processing state machine methods -----------------------------------------------------------------------------------

// Initial state machine state
SyncF3Frames::StateMachine SyncF3Frames::sm_state_initial(void)
{
    if (debugOn) qDebug() << "SyncF3Frames::sm_state_initial(): Called";
    return state_findInitialSync0;
}

SyncF3Frames::StateMachine SyncF3Frames::sm_state_findInitialSync0(void)
{
    //if (debugOn) qDebug() << "SyncF3Frames::sm_state_findInitialSync0(): Called";

    if (f3FrameBuffer[f3FrameBuffer.size() - 1].isSubcodeSync0()) {
        if (debugOn) qDebug() << "SyncF3Frames::sm_state_findInitialSync0(): Found initial sync0";
        waitingForData = true;
        return state_findNextSync;
    }

    f3FrameBuffer.removeLast();
    statistics.discardedFrames++;
    waitingForData = true;
    return state_findInitialSync0;
}

SyncF3Frames::StateMachine SyncF3Frames::sm_state_findNextSync(void)
{
    //if (debugOn) qDebug() << "SyncF3Frames::sm_state_findNextSync(): Called";

    // If we identify the end of the section, process it
    if (f3FrameBuffer[f3FrameBuffer.size() - 1].isSubcodeSync0()) {
        return state_processSection;
    }

    // If we exceed 99 frames in the buffer with no sync, clear it out to
    // prevent the buffer from growing too large (99 frames is the 98 F3 frames that make
    // up the section, plus the first frame from the next section (containing the sync)
    waitingForData = true;
    if (f3FrameBuffer.size() > 99) {
        if (debugOn) qDebug() << "SyncF3Frames::sm_state_findNextSync(): More than 99 F3 Frames since last sync - sync lost!";
        return state_syncLost;
    }
    return state_findNextSync;
}

SyncF3Frames::StateMachine SyncF3Frames::sm_state_syncLost(void)
{
    if (debugOn) qDebug() << "SyncF3Frames::sm_state_syncLost(): Called";

    // We have lost sync; clear the buffer and go back to looking for an initial sync
    statistics.discardedFrames += f3FrameBuffer.size();
    f3FrameBuffer.clear();
    waitingForData = true;
    return state_findInitialSync0;
}

SyncF3Frames::StateMachine SyncF3Frames::sm_state_processSection(QDataStream *outputDataStream)
{
    //if (debugOn) qDebug() << "SyncF3Frames::sm_state_processSection(): Called";

    // Store the start frame of the next section
    F3Frame f3Frame;
    f3Frame = f3FrameBuffer[f3FrameBuffer.size() - 1];

    // Ensure we have a complete section
    if ((f3FrameBuffer.size() - 1) != 98) {
        if (debugOn) qDebug() << "SyncF3Frames::sm_state_processSection(): Section has invalid length of" << f3FrameBuffer.size() - 1 << "- discarding";
        statistics.discardedFrames += f3FrameBuffer.size() - 1;
        f3FrameBuffer.clear();
        f3FrameBuffer.append(f3Frame);
        return state_syncLost;
    }

    // Write the complete section of 98 F3 frames to the output stream
    for (qint32 i = 0; i < 98; i++) {
        *outputDataStream << f3FrameBuffer[i];
    }
    statistics.totalSections++;

    // Remove the processed section from the F3 frame buffer
    f3FrameBuffer.clear();
    f3FrameBuffer.append(f3Frame);

    waitingForData = true;
    return state_findNextSync;
}
