/************************************************************************

    f3framer.cpp

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

#include "f3framer.h"

// This class is responsible for splitting the input EFM T-value data
// into F3 frames by tracking the frame sync patterns and decoding the
// 14-bit EFM data into 8-bit data values

F3Framer::F3Framer()
{
    // Initialise the state machine
    currentState = state_initial;
    nextState = currentState;
    waitingForDeltas = false;

    // Default the success tracking variables
    decodePass = 0;
    decodeFailed = 0;
    syncLoss = 0;
    efmTranslationFail = 0;
    poorSync = 0;

    verboseDebug = false;
}

// Get the number of decodes that passed one the first try
qint32 F3Framer::getPass(void)
{
    return decodePass;
}

// Get the number of decodes that failed
qint32 F3Framer::getFailed(void)
{
    return decodeFailed;
}

// Get the number of sync losses
qint32 F3Framer::getSyncLoss(void)
{
    return syncLoss;
}

// Get the number of EFM translations that failed
qint32 F3Framer::getFailedEfmTranslations(void)
{
    return efmTranslationFail;
}

// Is an F3 frame ready?
qint32 F3Framer::f3FramesReady(void)
{
    return f3Frames.size();
}

// Get the F3 frame and the erasures
void F3Framer::getF3Frames(QByteArray &f3FrameBuffer, QByteArray &f3ErasureBuffer)
{
    f3FrameBuffer.resize(f3Frames.size() * 34);
    f3ErasureBuffer.resize(f3Frames.size() * 34);

    qint32 pointer = 0;
    for (qint32 frame = 0; frame < f3Frames.size(); frame++) {
        // Copy the 34 byte frame
        for (qint32 byteC = 0; byteC < 34; byteC++) {
            f3FrameBuffer[pointer] = static_cast<char>(f3Frames[frame].outputF3Data[byteC]);
            if (f3Frames[frame].outputF3Erasures[byteC]) {
                f3ErasureBuffer[pointer] = 1;
            } else {
                f3ErasureBuffer[pointer] = 0;
            }
            pointer++;
        }
    }

    f3Frames.clear();
}

// Process the state machine
void F3Framer::process(QByteArray efmDataIn, bool verboseDebugParam)
{
    waitingForDeltas = false;
    verboseDebug = verboseDebugParam;

    // Append the incoming EFM data to the buffer
    efmData.append(efmDataIn);

    while (!waitingForDeltas) {
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
            nextState = sm_state_processFrame();
            break;
        }
    }
}

F3Framer::StateMachine F3Framer::sm_state_initial(void)
{
    return state_findInitialSyncStage1;
}

// Search for the first T11+T11 sync pattern in the input buffer
F3Framer::StateMachine F3Framer::sm_state_findInitialSyncStage1(void)
{
    // Find the first T11+T11 sync pattern in the input buffer
    qint32 startSyncTransition = -1;

    for (qint32 i = 0; i < efmData.size() - 1; i++) {
        if (efmData[i] == static_cast<char>(11) && efmData[i + 1] == static_cast<char>(11)) {
            startSyncTransition = i;
            break;
        }
    }

    if (startSyncTransition == -1) {
        if (verboseDebug) qDebug() << "F3Framer::sm_state_findInitialSyncStage1(): No initial sync found in input buffer, requesting more data";

        // Discard the transitions already tested and try again
        removePllResults(efmData.size() - 1);

        waitingForDeltas = true;
        return state_findInitialSyncStage1;
    }

    if (verboseDebug) qDebug() << "F3Framer::sm_state_findInitialSyncStage1(): Initial sync found at transition" << startSyncTransition;

    // Discard all transitions up to the sync start (so the pllResult is the start of frame T11)
    removePllResults(startSyncTransition);

    // Move to find initial sync stage 2
    return state_findInitialSyncStage2;
}

F3Framer::StateMachine F3Framer::sm_state_findInitialSyncStage2(void)
{
    // Find the next T11+T11 sync pattern in the input buffer
    endSyncTransition = -1;
    qint32 tTotal = 11;

    qint32 searchLength = 588 * 4;

    for (qint32 i = 1; i < efmData.size() - 1; i++) {
        if (efmData[i] == static_cast<char>(11) && efmData[i + 1] == static_cast<char>(11)) {
            endSyncTransition = i;
            break;
        }
        tTotal += efmData[i];

        // If we are more than a few frame lengths out, give up
        if (tTotal > searchLength) {
            endSyncTransition = i;
            break;
        }
    }

    if (tTotal > searchLength) {
        if (verboseDebug) qDebug() << "F3Framer::sm_state_findInitialSyncStage2(): No second sync found within a reasonable length, going back to look for new initial sync.  T =" << tTotal;
        removePllResults(endSyncTransition);
        return state_findInitialSyncStage1;
    }

    if (endSyncTransition == -1) {
        if (verboseDebug) qDebug() << "F3Framer::sm_state_findInitialSyncStage2(): No second sync found in input buffer, requesting more data.  T =" << tTotal;

        waitingForDeltas = true;
        return state_findInitialSyncStage2;
    }

    if (verboseDebug) qDebug() << "F3Framer::sm_state_findInitialSyncStage2(): Found second initial sync at" << endSyncTransition;

    // Is the frame length valid?
    if (tTotal != 588) {
        // Discard the transitions already tested and try again
        if (verboseDebug) qDebug() << "F3Framer::sm_state_findInitialSyncStage2(): Invalid T length of" << tTotal << " - trying again";
        removePllResults(endSyncTransition);
        return state_findInitialSyncStage2;
    }

    if (verboseDebug) qDebug() << "Found first F3 frame with a valid length of 588 bits";
    return state_processFrame;
}

F3Framer::StateMachine F3Framer::sm_state_findSecondSync(void)
{
    // Get at least 588 bits of data
    qint32 i = 0;
    qint32 tTotal = 0;
    while (i < efmData.size() && tTotal < 588) {
        tTotal += efmData[i];
        i++;
    }

    // Did we have enough data to reach a tTotal of 588?
    if (tTotal < 588) {
        //if (verboseDebug) qDebug() << "F3Framer::sm_state_findSecondSync(): Need more data to reach required tTotal";
        // Indicate that more deltas are required and stay in this state
        waitingForDeltas = true;
        return state_findSecondSync;
    }

    // Do we have enough data to verify the sync position?
    if ((efmData.size() - i) < 2) {
        //if (verboseDebug) qDebug() << "F3Framer::sm_state_findSecondSync(): Need more data to verify sync position";
        // Indicate that more deltas are required and stay in this state
        waitingForDeltas = true;
        return state_findSecondSync;
    }

    // Is tTotal correct?
    if (tTotal == 588) {
        endSyncTransition = i;
        poorSync = 0;
    } else {
        // Handle various possible sync issues in a (hopefully) smart way
        if (efmData[i] == static_cast<char>(11) && efmData[i + 1] == static_cast<char>(11)) {
            if (verboseDebug) qDebug() << "F3Framer::sm_state_findSecondSync(): Sync is in the right position and is valid - frame contains invalid T value";
            endSyncTransition = i;
            poorSync = 0;
        } else if (efmData[i - 1] == static_cast<char>(11) && efmData[i] == static_cast<char>(11)) {
            if (verboseDebug) qDebug() << "F3Framer::sm_state_findSecondSync(): Sync valid, but off by one transition backwards";
            endSyncTransition = i - 1;
            poorSync = 0;
        } else if (efmData[i - 1] >= static_cast<char>(10) && efmData[i] >= static_cast<char>(10)) {
            if (verboseDebug) qDebug() << "F3Framer::sm_state_findSecondSync(): Sync value low and off by one transition backwards";
            endSyncTransition = i - 1;
            poorSync = 0;
        } else {
            if (abs(tTotal - 588) < 3) {
                if (verboseDebug) qDebug() << "F3Framer::sm_state_findSecondSync(): tTotal was incorrect (" << tTotal
                         << "), but error is less than T3, so nothing much to do about it";
                endSyncTransition = i;
                poorSync = 0;
            } else if (abs(tTotal - 588) >= 3) {
                    if (verboseDebug) qDebug() << "F3Framer::sm_state_findSecondSync(): tTotal was incorrect (" << tTotal
                             << "), moving end transition in attempt to correct";
                    if (tTotal > 588) endSyncTransition = i - 1; else endSyncTransition = i;
                    poorSync = 0;
            } else if (efmData[i] == static_cast<char>(11) && efmData[i + 1] == static_cast<char>(11)) {
                if (verboseDebug) qDebug() << "F3Framer::sm_state_findSecondSync(): Sync valid, but off by one transition forward";
                endSyncTransition = i;
                poorSync = 0;
            } else if (efmData[i] >= static_cast<char>(10) && efmData[i + 1] >= static_cast<char>(10)) {
                if (verboseDebug) qDebug() << "F3Framer::sm_state_findSecondSync(): Sync value low and off by one transition forward";
                endSyncTransition = i;
                poorSync = 0;
            } else {
                if (verboseDebug) qDebug() << "F3Framer::sm_state_findSecondSync(): Sync appears to be missing causing an" <<
                            "overshoot; dropping a T value and marking as poor sync #" << poorSync;
                endSyncTransition = i;
                poorSync++;
            }
        }
    }

    // Hit limit of poor sync detections?
    if (poorSync > 16) {
        poorSync = 0;
        if (verboseDebug) qDebug() << "F3Framer::sm_state_findSecondSync(): Too many poor sync detections (>16) - sync lost";
        return state_syncLost;
    }

    // Move to the process frame state
    return state_processFrame;
}

F3Framer::StateMachine F3Framer::sm_state_syncLost(void)
{
    if (verboseDebug) qDebug() << "F3Framer::sm_state_syncLost(): Sync was completely lost!";
    syncLoss++;
    return state_findInitialSyncStage1;
}

F3Framer::StateMachine F3Framer::sm_state_processFrame(void)
{
    QVector<qint32> frameT(endSyncTransition);
    qint32 tTotal = 0;
    for (qint32 delta = 0; delta < endSyncTransition; delta++) {
        qint32 value = efmData[delta];

        if (value < 3) {
            if (verboseDebug) qDebug() << "F3Framer::sm_state_processFrame(): Invalid T value <3";
        }
        if (value > 11) {
            if (verboseDebug) qDebug() << "F3Framer::sm_state_processFrame(): Invalid T value >11";
        }

        tTotal += value;
        frameT[delta] = value;
    }
    if (tTotal == 588) {
        //if (verboseDebug) qDebug() << "F3Framer::sm_state_processFrame(): Decode successful";
        decodePass++;
    } else {
        if (verboseDebug) qDebug() << "F3Framer::sm_state_processFrame(): Decode failed - F3 frame length T =" << tTotal;
        decodeFailed++;
    }

    // Discard all transitions up to the sync end
    removePllResults(endSyncTransition);

    // Translate the F3 frame T results into a bit-stream of data
    f3Frames.resize(f3Frames.size() + 1);
    convertTvaluesToData(frameT, f3Frames[f3Frames.size() - 1].outputF3Data, f3Frames[f3Frames.size() - 1].outputF3Erasures);

    // Find the next sync position
    return state_findSecondSync;
}

// Utility functions --------------------------------------------------------------------------------------------------

// Method to remove deltas from the start of the buffer
void F3Framer::removePllResults(qint32 number)
{
    if (number > efmData.size()) {
        efmData.clear();
    } else {
        // Shift the byte array back by 'number' elements
        efmData.remove(0, number);
    }
}

// This method takes a vector of T values and returns a byte array
// of 8-bit decoded data (33 bytes per F3 frame)
void F3Framer::convertTvaluesToData(QVector<qint32> frameT, uchar* outputData, bool* outputErasures)
{
    // Firstly we have to make a bit-stream of the 588 channel bits including
    // all of the sync pattern and merge bits
    uchar rawFrameData[80]; // 74 plus some overflow
    qint32 bitPosition = 7;
    qint32 bytePosition = 0;
    uchar byteData = 0;

    for (qint32 tPosition = 0; tPosition < frameT.size(); tPosition++) {
        for (qint32 bitCount = 0; bitCount < frameT[tPosition]; bitCount++) {
            if (bitCount == 0) byteData |= (1 << bitPosition);
            bitPosition--;

            if (bitPosition < 0) {
                rawFrameData[bytePosition] = byteData;
                byteData = 0;
                bitPosition = 7;
                bytePosition++;
            }
        }
    }

    // Add in the last nybble to get from 73.5 to 74 bytes
    rawFrameData[bytePosition] = byteData;

    //qDebug() << "F3Frame data:" << dataToString(rawFrameData, 74);

    // Secondly, we take the bit stream and extract just the EFM values it contains
    // There are 33 EFM values per F3 frame

    // Composition of an EFM packet is as follows:
    //
    //  1 * (24 + 3) bits sync pattern         =  27
    //  1 * (14 + 3) bits control and display  =  17
    // 32 * (14 + 3) data+parity               = 544
    //                                   total = 588 bits

    // Which demodulates to an F3 frame of:
    //
    // Sync Pattern (discarded)
    //  1 byte control
    // 32 bytes data+parity
    //
    // Total of 33 bytes

    quint32 efmValues[33];
    qint32 currentBit = 0;

    // Ignore the sync pattern (which is 24 bits plus 3 merging bits)
    // To-do: check the sync pattern; could be useful debug
    currentBit += 24 + 3;

    // Get the 33 x 14-bit EFM values
    for (qint32 counter = 0; counter < 33; counter++) {
        efmValues[counter] = getBits(rawFrameData, currentBit, 14);
        currentBit += 14 + 3; // the value plus 3 merging bits
        //if (verboseDebug) qDebug() << "efmValues =" << efmValues[counter];
    }

    // Thirdly we take each EFM value, look it up and replace it with the
    // 8-bit value it represents

    // Note: Each output F3 frame consists of 34 bytes.  1 byte of sync data and
    // 33 bytes of actual F3 data.  We add the additional 1 byte so F3 frame
    // sync can be performed later (it's not a real F3 data byte, but otherwise
    // the SYNC0 and SYNC1 would be lost as they cannot be converted as EFM values)
    outputData[0] = 0; // No sync
    outputErasures[0] = false;
    if (efmValues[0] == 0x801) outputData[0] = 0x01; // SYNC0
    if (efmValues[0] == 0x012) outputData[0] = 0x02; // SYNC1

    for (qint32 counter = 1; counter < 34; counter++) {
        qint32 result = -1;

        if (counter == 1 && (efmValues[0] == 0x801 || efmValues[0] == 0x012)) {
            // Sync bit, can't translate, so set data to 0
            outputData[counter] = 0;
            outputErasures[counter] = false;
            result = 1;
        } else {
            // Normal EFM - translate to 8-bit value
            quint32 lutPos = 0;
            while (lutPos < 256 && result != 1) {
                if (efm2numberLUT[lutPos] == efmValues[counter - 1]) {
                    outputData[counter] = static_cast<uchar>(lutPos);
                    outputErasures[counter] = false;
                    result = 1;
                }
                lutPos++;
            }
        }

        if (result == -1) {
            if (verboseDebug) qDebug() << "F3Framer::convertTvaluesToData(): 14-bit EFM value" << efmValues[counter - 1] <<
                        "not found in translation look-up table, position =" << counter;
            efmTranslationFail++;
            outputData[counter] = 0;
            outputErasures[counter] = true;
        }
    }

    //if (verboseDebug) qDebug() << "Output data =" << dataToString(outputData, 34);
}

// Method to get 'width' bits (max 32) from a byte array starting from
// bit 'bitIndex'
quint32 F3Framer::getBits(uchar *rawData, qint32 bitIndex, qint32 width)
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

// This method is for debug and outputs an array of 8-bit unsigned data as a hex string
QString F3Framer::dataToString(uchar *data, qint32 length)
{
    QString output;

    for (qint32 count = 0; count < length; count++) {
        output += QString("%1").arg(data[count], 2, 16, QChar('0'));
    }

    return output;
}
