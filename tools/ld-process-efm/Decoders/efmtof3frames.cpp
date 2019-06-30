/************************************************************************

    efmtof3frames.cpp

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

#include "efmtof3frames.h"

EfmToF3Frames::EfmToF3Frames()
{
    debugOn = false;
    abort = false;
}

// Public methods -----------------------------------------------------------------------------------------------------

void EfmToF3Frames::startProcessing(QFile *inputFileHandle, QFile *outputFileHandle)
{
    abort = false;

    // Reset the object
    reset();

    // Initialise the state-machine
    efmDataBuffer.clear();
    currentState = state_initial;
    nextState = currentState;
    waitingForData = false;
    sequentialBadSyncCounter = 0;
    endSyncTransition = 0;

    bool endOfInputFile = false;
    if (debugOn) qDebug() << "EfmToF3Frames::startProcessing(): Initial input file size of" << inputFileHandle->bytesAvailable() << "bytes";

    // Define an output data stream
    QDataStream outputDataStream(outputFileHandle);

    do {
        // Read the EFM data into the buffer
        QByteArray efmInputBuffer;
        qint32 efmInputBufferSize = 1024 * 256;
        efmInputBuffer.resize(efmInputBufferSize);
        qint64 bytesRead = inputFileHandle->read(efmInputBuffer.data(), efmInputBuffer.size());
        if (bytesRead != efmInputBufferSize) {
            efmInputBuffer.resize(static_cast<qint32>(bytesRead));
            if (inputFileHandle->bytesAvailable() == 0) endOfInputFile = true;
        }
        if (debugOn) qDebug() << "EfmToF3Frames::startProcessing(): Read" << efmInputBuffer.size() << "bytes -" << inputFileHandle->bytesAvailable() << "left";

        // Append input data to the processing buffer
        efmDataBuffer.append(efmInputBuffer);

        waitingForData = false;
        while (!waitingForData) {
            currentState = nextState;

            switch (currentState) {
            case state_initial:
                nextState = sm_state_initial();
                break;
            case state_findInitialSyncStage1:
                nextState = sm_state_findInitialSyncStage1();
                break;
            case state_findInitialSyncStage2:
                nextState = sm_state_findInitialSyncStage2();
                break;
            case state_findSecondSync:
                nextState = sm_state_findSecondSync();
                break;
            case state_syncLost:
                nextState = sm_state_syncLost();
                break;
            case state_processFrame:
                nextState = sm_state_processFrame(&outputDataStream);
                break;
            }
        }
    } while (!endOfInputFile && !abort);

    if (debugOn) qDebug() << "EfmToF3Frames::startProcessing(): No more data to processes";
}

void EfmToF3Frames::stopProcessing(void)
{
    abort = true;
}

EfmToF3Frames::Statistics EfmToF3Frames::getStatistics(void)
{
    return statistics;
}

void EfmToF3Frames::reportStatistics(void)
{
    qInfo() << "";
    qInfo() << "EFM to F3 Frames:";
    qInfo() << "        Valid syncs:" << statistics.validSyncs;
    qInfo() << "    Overshoot syncs:" << statistics.overshootSyncs;
    qInfo() << "   Undershoot syncs:" << statistics.undershootSyncs;
    qInfo() << "        TOTAL syncs:" << statistics.validSyncs + statistics.overshootSyncs + statistics.undershootSyncs;
    qInfo() << "";
    qInfo() << "     Valid T-values:" << statistics.validTValues;
    qInfo() << "   Invalid T-values:" << statistics.invalidTValues;
    qInfo() << "     TOTAL T-values:" << statistics.validTValues + statistics.invalidTValues;
    qInfo() << "";
    qInfo() << "       Valid frames:" << statistics.validFrames;
    qInfo() << "   Overshoot frames:" << statistics.overshootFrames;
    qInfo() << "  Undershoot frames:" << statistics.undershootFrames;
    qInfo() << "       TOTAL frames:" << statistics.validFrames + statistics.overshootFrames + statistics.undershootFrames;
}

void EfmToF3Frames::reset(void)
{
    clearStatistics();
}

// Private methods ----------------------------------------------------------------------------------------------------

void EfmToF3Frames::clearStatistics(void)
{
    statistics.undershootSyncs = 0;
    statistics.validSyncs = 0;
    statistics.overshootSyncs = 0;

    statistics.undershootFrames = 0;
    statistics.validFrames = 0;
    statistics.overshootFrames = 0;

    statistics.validTValues = 0;
    statistics.invalidTValues = 0;
}

// Processing state machine methods -----------------------------------------------------------------------------------

// Initial state machine state
EfmToF3Frames::StateMachine EfmToF3Frames::sm_state_initial(void)
{
    if (debugOn) qDebug() << "EfmToF3Frames::sm_state_initial(): Called";
    return state_findInitialSyncStage1;
}

// Search for the first T11+T11 sync pattern in the EFM buffer
EfmToF3Frames::StateMachine EfmToF3Frames::sm_state_findInitialSyncStage1(void)
{
    if (debugOn) qDebug() << "EfmToF3Frames::sm_state_findInitialSyncStage1(): Called";

    // Find the first T11+T11 sync pattern in the EFM buffer
    qint32 startSyncTransition = -1;

    for (qint32 i = 0; i < efmDataBuffer.size() - 1; i++) {
        if (efmDataBuffer[i] == static_cast<char>(11) && efmDataBuffer[i + 1] == static_cast<char>(11)) {
            startSyncTransition = i;
            break;
        }
    }

    if (startSyncTransition == -1) {
        if (debugOn) qDebug() << "EfmToF3Frames::sm_state_findInitialSyncStage1(): No initial F3 sync found in EFM buffer, requesting more data";

        // Discard the EFM already tested and try again
        removeEfmData(efmDataBuffer.size() - 1);

        waitingForData = true;
        return state_findInitialSyncStage1;
    }

    if (debugOn) qDebug() << "EfmToF3Frames::sm_state_findInitialSyncStage1(): Initial F3 sync found at buffer position" << startSyncTransition;

    // Discard all EFM data up to the sync start
    removeEfmData(startSyncTransition);

    // Move to find initial sync stage 2
    return state_findInitialSyncStage2;
}

EfmToF3Frames::StateMachine EfmToF3Frames::sm_state_findInitialSyncStage2(void)
{
    if (debugOn) qDebug() << "EfmToF3Frames::sm_state_findInitialSyncStage2(): Called";

    // Find the next T11+T11 sync pattern in the EFM buffer
    endSyncTransition = -1;
    qint32 tTotal = 11;

    qint32 searchLength = 588 * 4;

    for (qint32 i = 1; i < efmDataBuffer.size() - 1; i++) {
        if (efmDataBuffer[i] == static_cast<char>(11) && efmDataBuffer[i + 1] == static_cast<char>(11)) {
            endSyncTransition = i;
            break;
        }
        tTotal += efmDataBuffer[i];

        // If we are more than a few F3 frame lengths out, give up
        if (tTotal > searchLength) {
            endSyncTransition = i;
            break;
        }
    }

    if (tTotal > searchLength) {
        if (debugOn) qDebug() << "EfmToF3Frames::sm_state_findInitialSyncStage2(): No second F3 sync found within a reasonable length, going back to look for new initial sync.  T =" << tTotal;
        removeEfmData(endSyncTransition);
        return state_findInitialSyncStage1;
    }

    if (endSyncTransition == -1) {
        waitingForData = true;
        return state_findInitialSyncStage2;
    }

    // Is the frame length valid (or close enough)?
    if (tTotal < 587 || tTotal > 589) {
        // Discard the transitions already tested and try again
        removeEfmData(endSyncTransition);
        return state_findInitialSyncStage2;
    }

    if (debugOn) qDebug() << "EfmToF3Frames::sm_state_findInitialSyncStage2(): Found first F3 frame with a length of" << tTotal << "bits";

    return state_processFrame;
}

EfmToF3Frames::StateMachine EfmToF3Frames::sm_state_findSecondSync(void)
{
    if (debugOn) qDebug() << "EfmToF3Frames::sm_state_findSecondSync(): Called";

    // Get at least 588 bits of data
    qint32 i = 0;
    qint32 tTotal = 0;
    while (i < efmDataBuffer.size() && tTotal < 588) {
        tTotal += efmDataBuffer[i];
        i++;
    }

    // Did we have enough data to reach a tTotal of 588?
    if (tTotal < 588) {
        // Indicate that more deltas are required and stay in this state
        waitingForData = true;
        return state_findSecondSync;
    }

    // Do we have enough data to verify the sync position?
    if ((efmDataBuffer.size() - i) < 2) {
        // Indicate that more deltas are required and stay in this state
        waitingForData = true;
        return state_findSecondSync;
    }

    // Is tTotal correct?
    if (tTotal == 588) {
        endSyncTransition = i;
        sequentialBadSyncCounter = 0;
        statistics.validSyncs++;
        //if (debugOn) qDebug() << "EfmToF3Frames::sm_state_findSecondSync(): Got good F3 sync";
    } else {
        // Handle various possible sync issues in a (hopefully) smart way
        if (efmDataBuffer[i] == static_cast<char>(11) && efmDataBuffer[i + 1] == static_cast<char>(11)) {
            if (debugOn) qDebug() << "EfmToF3Frames::sm_state_findSecondSync(): F3 Sync is in the right position and is valid - frame contains invalid T value";
            endSyncTransition = i;
            statistics.validSyncs++;
        } else if (efmDataBuffer[i - 1] == static_cast<char>(11) && efmDataBuffer[i] == static_cast<char>(11)) {
            if (debugOn) qDebug() << "EfmToF3Frames::sm_state_findSecondSync(): F3 Sync valid, but off by one transition backwards";
            endSyncTransition = i - 1;
            statistics.undershootSyncs++;
        } else if (efmDataBuffer[i - 1] >= static_cast<char>(10) && efmDataBuffer[i] >= static_cast<char>(10)) {
            if (debugOn) qDebug() << "EfmToF3Frames::sm_state_findSecondSync(): F3 Sync value low and off by one transition backwards";
            endSyncTransition = i - 1;
            statistics.undershootSyncs++;
        } else {
            if (abs(tTotal - 588) < 3) {
                if (debugOn) qDebug() << "EfmToF3Frames::sm_state_findSecondSync(): F3 frame length was incorrect (" << tTotal
                         << "), but error is less than T3, so nothing much to do about it";
                endSyncTransition = i;
                sequentialBadSyncCounter++;
                if (tTotal > 588) statistics.overshootSyncs++; else statistics.undershootSyncs++;
            } else if (abs(tTotal - 588) >= 3) {
                    if (debugOn) qDebug() << "EfmToF3Frames::sm_state_findSecondSync(): F3 frame length was incorrect (" << tTotal
                             << "), moving end transition in attempt to correct";
                    if (tTotal > 588) endSyncTransition = i - 1; else endSyncTransition = i;
                    sequentialBadSyncCounter++;
                    if (tTotal > 588) statistics.overshootSyncs++; else statistics.undershootSyncs++;
            } else if (efmDataBuffer[i] == static_cast<char>(11) && efmDataBuffer[i + 1] == static_cast<char>(11)) {
                if (debugOn) qDebug() << "EfmToF3Frames::sm_state_findSecondSync(): F3 Sync valid, but off by one transition forward";
                endSyncTransition = i;
                statistics.overshootSyncs++;
            } else if (efmDataBuffer[i] >= static_cast<char>(10) && efmDataBuffer[i + 1] >= static_cast<char>(10)) {
                if (debugOn) qDebug() << "EfmToF3Frames::sm_state_findSecondSync(): F3 Sync value low and off by one transition forward";
                endSyncTransition = i;
                statistics.overshootSyncs++;
            } else {
                if (debugOn) qDebug() << "EfmToF3Frames::sm_state_findSecondSync(): F3 Sync appears to be missing causing an" <<
                           "overshoot; dropping a T value and marking as poor sync #" << sequentialBadSyncCounter;
                endSyncTransition = i;
                sequentialBadSyncCounter++;
                statistics.overshootSyncs++;
            }
        }
    }

    //if (tTotal != 588) if (debugOn) qDebug() << "EfmToF3Frames::sm_state_findSecondSync(): F3 Frame length incorrect at" << tTotal << "bytes (expected 588)";

    // Hit limit of poor sync detections?
    if (sequentialBadSyncCounter > 16) {
        sequentialBadSyncCounter = 0;
        if (debugOn) qDebug() << "EfmToF3Frames::sm_state_findSecondSync(): Too many F3 sequential poor sync detections (>16) - sync lost";
        return state_syncLost;
    }

    // Move to the process frame state
    return state_processFrame;
}

EfmToF3Frames::StateMachine EfmToF3Frames::sm_state_syncLost(void)
{
    if (debugOn) qDebug() << "EfmToF3Frames::sm_state_syncLost(): Called";
    statistics.syncLoss++;
    return state_findInitialSyncStage1;
}

EfmToF3Frames::StateMachine EfmToF3Frames::sm_state_processFrame(QDataStream *outputDataStream)
{
    if (debugOn) qDebug() << "EfmToF3Frames::sm_state_processFrame(): Called";

    // Convert the T-values into a byte-stream.  The sum of T-values in every frame should be 588
    // and is padded or truncated if incorrect.

    qint32 tTotal = 0;
    QVector<qint32> frameT;
    for (qint32 delta = 0; delta < endSyncTransition; delta++) {
        qint32 value = efmDataBuffer[delta];

        if (value < 3) {
            statistics.invalidTValues++;
            value = 3;
        } else if (value > 11) {
            statistics.invalidTValues++;
            value = 11;
        } else statistics.validTValues++;

        // Keep track of the total T and append to the F3 frame to be processed
        tTotal += value;
        frameT.append(value);
    }

    // Track framing accuracy
    if (tTotal < 588) statistics.undershootFrames++;
    if (tTotal == 588) statistics.validFrames++;
    if (tTotal > 588) statistics.overshootFrames++;

    // Now we hand the data over to the F3 frame class which converts the data
    // into a F3 frame
    F3Frame f3Frame;
    f3Frame.setTValues(frameT);

    // Now save the F3 frame to our output data stream
    *outputDataStream << f3Frame;

    // Discard all transitions up to the sync end
    removeEfmData(endSyncTransition);

    // Find the next sync position
    return state_findSecondSync;
}

// Method to remove EFM data from the start of the buffer
void EfmToF3Frames::removeEfmData(qint32 number)
{
    if (number > efmDataBuffer.size()) {
        efmDataBuffer.clear();
    } else {
        // Shift the byte array back by 'number' elements
        efmDataBuffer.remove(0, number);
    }
}
