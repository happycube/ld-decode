/************************************************************************

    decodeaudio.cpp

    ld-efm-decodedata - EFM data decoder for ld-decode
    Copyright (C) 2019 Simon Inns

    This file is part of ld-decode-tools.

    ld-efm-decodedata is free software: you can redistribute it and/or
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

#include "decodeaudio.h"

DecodeAudio::DecodeAudio()
{
    // Initialise the state machine
    currentState = state_initial;
    nextState = currentState;

    currentF3Frame.clear();
    previousF3Frame.clear();
    currentF3Frame.resize(32);
    previousF3Frame.resize(32);

    validC1Count = 0;
    invalidC1Count = 0;

    validC2Count = 0;
    invalidC2Count = 0;
}

// Get the F3 frame
QByteArray DecodeAudio::getOutputData(void)
{
    QByteArray outputData = outputDataBuffer;
    outputDataBuffer.clear();
    return outputData;
}

// Get the C1 statistic
qint32 DecodeAudio::getValidC1Count(void)
{
    return validC1Count;
}

// Get the C1 statistic
qint32 DecodeAudio::getInvalidC1Count(void)
{
    return invalidC1Count;
}

// Get the C2 statistic
qint32 DecodeAudio::getValidC2Count(void)
{
    return validC2Count;
}

// Get the C2 statistic
qint32 DecodeAudio::getInvalidC2Count(void)
{
    return invalidC2Count;
}

void DecodeAudio::process(QByteArray f3FrameParam)
{
    // Ensure the F3 frame is the correct length
    if (f3FrameParam.size() != 34) {
        qDebug() << "DecodeAudio::process(): Invalid F3 frame parameter (not 34 bytes!)";
        return;
    }

    // Get the 32 bytes of user-data from the frame parameter
    // 0 is the sync indicator, 1 is the subcode and 2-34 is the data
    for (qint32 byteC = 0; byteC < 32; byteC++) currentF3Frame[byteC] = f3FrameParam[byteC + 2];

    // Since we have a new F3 frame, clear the waiting flag
    waitingForF3frame = false;

    // Process the state machine until another F3 frame is required
    while (!waitingForF3frame) {
        currentState = nextState;

        switch (currentState) {
        case state_initial:
            nextState = sm_state_initial();
            break;
        case state_processC1:
            nextState = sm_state_processC1();
            break;
        case state_processC2:
            nextState = sm_state_processC2();
            break;
        case state_processAudio:
            nextState = sm_state_processAudio();
            break;
        }
    }
}

DecodeAudio::StateMachine DecodeAudio::sm_state_initial(void)
{
    qDebug() << "DecodeAudio::sm_state_initial(): Called";

    // We need at least 2 frames to process a C1
    previousF3Frame = currentF3Frame;
    waitingForF3frame = true;

    return state_processC1;
}

// Process the C1 level error correction
DecodeAudio::StateMachine DecodeAudio::sm_state_processC1(void)
{
    //qDebug() << "DecodeAudio::sm_state_processC1(): Called";

    // Interleave the current and previous frame to generate the C1 data
    interleaveC1Data(previousF3Frame, currentF3Frame, c1Data);

    // Perform the Reed-Solomon CIRC
    if (reedSolomon.decodeC1(c1Data)) {
        validC1Count++;
        c1DataValid = true;
        //qDebug() << "DecodeAudio::sm_state_processC1(): Valid C1 #" << validC1Count;
    } else {
        invalidC1Count++;
        c1DataValid = false;
        //qDebug() << "DecodeAudio::sm_state_processC1(): Invalid C1 #" << invalidC1Count;
    }

    // Store the frame and get a new frame
    previousF3Frame = currentF3Frame;
    waitingForF3frame = true;

    // Process C2 stage
    return state_processC2;
}

DecodeAudio::StateMachine DecodeAudio::sm_state_processC2(void)
{
    //qDebug() << "DecodeAudio::sm_state_processC2(): Called";
    c2DataValid = false;

    // Place the C1 data in the C1 delay buffer
    C1Buffer c1BufferEntry;
    for (qint32 byteC = 0; byteC < 28; byteC++) c1BufferEntry.c1Symbols[byteC] = c1Data[byteC];
    c1BufferEntry.c1SymbolsValid = c1DataValid;
    c1DelayBuffer.append(c1BufferEntry);

    // If the buffer is full, remove the first entry so it's always 109 C1s long
    if (c1DelayBuffer.size() > 109) {
        c1DelayBuffer.removeFirst();
    }

    // If we have 109 C1s then we can process the C2 ECC
    if (c1DelayBuffer.size() == 109) {
        // Get the C2 Data
        getC2Data(c2Data, c2DataErasures);

        // Perform the Reed-Solomon CIRC
        if (reedSolomon.decodeC2(c2Data, c2DataErasures)) {
            // C2 Success
            validC2Count++;
            c2DataValid = true;
            qDebug() << "DecodeAudio::sm_state_processC2(): Valid C2 #" << validC2Count;
        } else {
            // C2 Failure
            invalidC2Count++;
            c2DataValid = false;
            qDebug() << "DecodeAudio::sm_state_processC2(): Invalid C2 #" << invalidC2Count;
        }
    }

    return state_processAudio;
}

DecodeAudio::StateMachine DecodeAudio::sm_state_processAudio(void)
{
    // Place the C2 data in the C2 delay buffer
    C2Buffer c2BufferEntry;
    for (qint32 byteC = 0; byteC < 28; byteC++) c2BufferEntry.c2Symbols[byteC] = c2Data[byteC];
    c2BufferEntry.c2SymbolsValid = c2DataValid;
    c2DelayBuffer.append(c2BufferEntry);

    // If the buffer is full, remove the first entry so it's always 3 C2s long
    if (c2DelayBuffer.size() > 3) {
        c2DelayBuffer.removeFirst();
    }

    // If we have 3 C2s then we can perform de-interleaving to recover the original data
    if (c2DelayBuffer.size() == 3) {
        uchar outputData[24];
        deInterleaveC2(outputData);

        // Save the output data in the output data buffer
        qint32 odbPointer = outputDataBuffer.size();
        outputDataBuffer.resize(outputDataBuffer.size() + 24);
        for (qint32 byteC = 0; byteC < 24; byteC++) {
            outputDataBuffer[byteC + odbPointer] = static_cast<char>(outputData[byteC]);
        }
    }

    // Discard the C2 and get the next C1
    return state_processC1;
}

// Utility methods ----------------------------------------------------------------------------------------------------

// Interleave current and previous F3 frame symbols and then invert parity words
void DecodeAudio::interleaveC1Data(QByteArray previousF3Frame, QByteArray currentF3Frame, uchar *c1Data)
{
    uchar *prev = reinterpret_cast<uchar*>(previousF3Frame.data());
    uchar *curr = reinterpret_cast<uchar*>(currentF3Frame.data());

    // Interleave the symbols
    for (qint32 byteC = 0; byteC < 32; byteC += 2) {
        c1Data[byteC] = curr[byteC];
        c1Data[byteC+1] = prev[byteC + 1];
    }

    // Invert the Qm parity bits
    c1Data[12] ^= 0xFF;
    c1Data[13] ^= 0xFF;
    c1Data[14] ^= 0xFF;
    c1Data[15] ^= 0xFF;

    // Invert the Pm parity bits
    c1Data[28] ^= 0xFF;
    c1Data[29] ^= 0xFF;
    c1Data[30] ^= 0xFF;
    c1Data[31] ^= 0xFF;
}

// Gets the C2 data from the C1 buffer by applying delay lines of unequal length
// according to fig. 13 in IEC 60908
void DecodeAudio::getC2Data(uchar *symBuffer, bool *isErasure)
{
    // Longest delay is 27 * 4 = 108
    for (qint32 byteC = 0; byteC < 28; byteC++) {

        qint32 delayC1Line = (108 - ((27 - byteC) * 4));
        symBuffer[byteC] = c1DelayBuffer[delayC1Line].c1Symbols[byteC];

        // If the C1 symbol is valid, mark C2 symbol as valid
        // otherwise, mark it as an erasure
        if (c1DelayBuffer[delayC1Line].c1SymbolsValid) {
            isErasure[byteC] = false;
        } else {
            isErasure[byteC] = true;
        }
    }
}

// Note: not complete - to-do
void DecodeAudio::deInterleaveC2(uchar *outputData)
{
    // Note: This is according to IEC60908 Figure 13 - CIRC decoder
    // Buffer 2 is current, buffer 0 is 2-frame delays behind
    qint32 curr = 2; // C2 0-frame delay
    qint32 prev = 0; // C2 2=frame delay

    // Note: This drops the parity leaving 24 bytes of data (12 words of 16 bits)
    outputData[ 0] = c2DelayBuffer[curr].c2Symbols[ 0];
    outputData[ 1] = c2DelayBuffer[curr].c2Symbols[ 1];
    outputData[ 2] = c2DelayBuffer[curr].c2Symbols[ 6];
    outputData[ 3] = c2DelayBuffer[curr].c2Symbols[ 7];

    outputData[ 4] = c2DelayBuffer[prev].c2Symbols[16];
    outputData[ 5] = c2DelayBuffer[prev].c2Symbols[17];
    outputData[ 6] = c2DelayBuffer[prev].c2Symbols[22];
    outputData[ 7] = c2DelayBuffer[prev].c2Symbols[23];

    outputData[ 8] = c2DelayBuffer[curr].c2Symbols[ 2];
    outputData[ 9] = c2DelayBuffer[curr].c2Symbols[ 3];
    outputData[10] = c2DelayBuffer[curr].c2Symbols[ 8];
    outputData[11] = c2DelayBuffer[curr].c2Symbols[ 9];

    outputData[12] = c2DelayBuffer[prev].c2Symbols[18];
    outputData[13] = c2DelayBuffer[prev].c2Symbols[19];
    outputData[14] = c2DelayBuffer[prev].c2Symbols[24];
    outputData[15] = c2DelayBuffer[prev].c2Symbols[25];

    outputData[16] = c2DelayBuffer[curr].c2Symbols[ 4];
    outputData[17] = c2DelayBuffer[curr].c2Symbols[ 5];
    outputData[18] = c2DelayBuffer[curr].c2Symbols[10];
    outputData[19] = c2DelayBuffer[curr].c2Symbols[11];

    outputData[20] = c2DelayBuffer[prev].c2Symbols[20];
    outputData[21] = c2DelayBuffer[prev].c2Symbols[21];
    outputData[22] = c2DelayBuffer[prev].c2Symbols[26];
    outputData[23] = c2DelayBuffer[prev].c2Symbols[27];
}

// This method is for debug and outputs an array of 8-bit unsigned data as a hex string
QString DecodeAudio::dataToString(uchar *data, qint32 length)
{
    QString output;

    for (qint32 count = 0; count < length; count++) {
        output += QString("%1").arg(data[count], 2, 16, QChar('0'));
    }

    return output;
}
