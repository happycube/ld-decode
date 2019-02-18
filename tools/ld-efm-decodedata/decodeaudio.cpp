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

    // Initialise the error correction library
    initialize_ecc();
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

    // Interleave the current and previous frame to generate the C1 symbols
    interleaveC1Data(previousF3Frame, currentF3Frame, c1Symbols);

    // RS is 32, 28 (i.e. 28 symbols (bytes) of data with 4 bytes of parity)
    decode_data(c1Symbols, 32); // Message length including parity (28 + 4)

    // Check the syndrome to see if there were errors in the data
    qint32 erasures[16];
    qint32 nerasures = 0;
    c1SymbolsValid = false;

    // Perform error correction
    if (check_syndrome() != 0) {
//        // Attempt to correct any corrupted symbols
//        if (correct_errors_erasures(c1Symbols, 32, nerasures, erasures) == 1) {
//            // Correction successful, symbols are valid
//            c1SymbolsValid = true;
//        }
    } else {
        // Symbols are valid
        c1SymbolsValid = true;
    }

    if (c1SymbolsValid) qDebug() << "Valid C1 *********************";
    //else qDebug() << "Invalid C1";

    // Store the frame and get a new frame
    previousF3Frame = currentF3Frame;
    waitingForF3frame = true;

    // Process C2 stage
    return state_processC2;
}

DecodeAudio::StateMachine DecodeAudio::sm_state_processC2(void)
{
    //qDebug() << "DecodeAudio::sm_state_processC2(): Called";
    c2BufferValid = false;

    // Place the C1 symbols in the C1 delay buffer
    C2Buffer c2Entry;
    for (qint32 byteC = 0; byteC < 28; byteC++) c2Entry.c1Symbols[byteC] = c1Symbols[byteC];
    c2Entry.c1SymbolsValid = c1SymbolsValid;
    c1DelayBuffer.append(c2Entry);

    // If the buffer is full, remove the first entry so it's always 109 C1s long
    if (c1DelayBuffer.size() > 109) {
        c1DelayBuffer.removeFirst();
    }

    // If we have 109 C1s then we can process the C2 ECC
    if (c1DelayBuffer.size() == 109) {
        uchar c2Buffer[28];
        bool c2BufferErasures[28];
        getC2Data(c2Buffer, c2BufferErasures);

        // Prepare the erasures in the format required by rscode-1.3
        qint32 erasures[28];
        qint32 nerasures = 0;
        for (qint32 count = 0; count < 28; count++) {
            if (c2BufferErasures[count]) {
                // Symbol is erased
                erasures[nerasures] = 27 - count;
                nerasures++;
            }
        }

        // Perform the C2 decode
        decode_data(c2Buffer, 28);

        // Perform error correction (we can correct 4 errors at the most)
        if (check_syndrome() != 0) {
            // Attempt to correct any corrupted symbols
            if (correct_errors_erasures(c2Buffer, 28, nerasures, erasures) == 1) {
                // Correction successful, symbols are valid
                c2BufferValid = true;
            }
        } else {
            // Symbols are valid
            c2BufferValid = true;
        }

        //if (c2BufferValid) qDebug() << "DecodeAudio::sm_state_processC2(): C2 CIRC success -----------------------------------------------------------------------";
        //else qDebug() << "DecodeAudio::sm_state_processC2(): C2 CIRC failed, nerasures =" << nerasures;
    }

    return state_processAudio;
}

DecodeAudio::StateMachine DecodeAudio::sm_state_processAudio(void)
{
    //if (c2SymbolsValid) qDebug() << "DecodeAudio::sm_state_processAudio(): Called with valid C2 =====================================================================================";

    // Discard the C2 and get the next C1
    return state_processC1;
}

// Utility methods ----------------------------------------------------------------------------------------------------

// Interleave current and previous F3 frame symbols and then invert parity words
void DecodeAudio::interleaveC1Data(QByteArray previousF3Frame, QByteArray currentF3Frame, uchar *c1Data)
{
    // Interleave the symbols
    for (qint32 byteC = 0; byteC < 32; byteC += 2) {
        c1Data[byteC] = static_cast<uchar>(currentF3Frame[byteC]);
        c1Data[byteC+1] = static_cast<uchar>(previousF3Frame[byteC + 1]);
    }

    // Invert the Qm parity bits
    c1Data[12] = ~c1Data[12];
    c1Data[13] = ~c1Data[13];
    c1Data[14] = ~c1Data[14];
    c1Data[15] = ~c1Data[15];

    // Invert the Pm parity bits
    c1Data[28] = ~c1Data[28];
    c1Data[29] = ~c1Data[29];
    c1Data[30] = ~c1Data[30];
    c1Data[31] = ~c1Data[31];
}

// Gets the C2 data from the C1 buffer by applying delay lines of unequal length
// according to fig. 13 in IEC 60908
void DecodeAudio::getC2Data(uchar *symBuffer, bool *isErasure)
{
    // Longest delay is 27 * 4 = 108
    for (qint32 byteC = 0; byteC < 28; byteC++) {

        qint32 delayC1Line = (108 - ((27 - byteC) * 4));
        symBuffer[byteC] = c1DelayBuffer[delayC1Line].c1Symbols[byteC];
        if (c1DelayBuffer[delayC1Line].c1SymbolsValid) {
            isErasure[byteC] = true;
        } else {
            isErasure[byteC] = false;
        }
    }
}

// Move the C2 parity symbols to the end of the C2 symbols
// Note: I don't think this is required
void DecodeAudio::moveC2ParitySymbols(uchar *symBuffer, bool *isErasure)
{
    uchar symTemp[28];
    bool isErasureTemp[28];

    // Move the first 12 words
    for (qint32 byteC = 0; byteC < 12; byteC++) {
        symTemp[byteC] = symBuffer[byteC];
        isErasureTemp[byteC] = isErasure[byteC];
    }

    // Move the last 12 words
    for (qint32 byteC = 16; byteC < 28; byteC++) {
        symTemp[byteC - 4] = symBuffer[byteC];
        isErasureTemp[byteC - 4] = isErasure[byteC];
    }

    // Move the 4 parity words
    symTemp[24] = symBuffer[12];
    symTemp[25] = symBuffer[13];
    symTemp[26] = symBuffer[14];
    symTemp[27] = symBuffer[15];

    isErasureTemp[24] = isErasure[12];
    isErasureTemp[25] = isErasure[13];
    isErasureTemp[26] = isErasure[14];
    isErasureTemp[27] = isErasure[15];

    // Copy the temporary data to the primary data
    for (qint32 byteC = 0; byteC < 28; byteC++) {
        symBuffer[byteC] = symTemp[byteC];
        isErasure[byteC] = isErasureTemp[byteC];
    }
}

void DecodeAudio::hexDump(QString title, uchar *data, qint32 length)
{
    QString output;

    output += title;

    for (qint32 count = 0; count < length; count++) {
        output += QString("%1").arg(data[count], 2, 16, QChar('0'));
    }

    qDebug().noquote() << output;
}

// Note: not complete - to-do
void DecodeAudio::deInterleaveC2(void)
{
    // Also needs 2 frame delay

    //        // Note: This is according to IEC60908 Figure 13 - CIRC decoder
    //        c2symbols[ 0] =  c2BufferCurrent[ 0];
    //        c2symbols[ 1] =  c2BufferCurrent[ 1];
    //        c2symbols[ 2] =  c2BufferCurrent[ 6];
    //        c2symbols[ 3] =  c2BufferCurrent[ 7];
    //        c2symbols[ 4] = c2BufferPrevious[16];
    //        c2symbols[ 5] = c2BufferPrevious[17];
    //        c2symbols[ 6] = c2BufferPrevious[22];
    //        c2symbols[ 7] = c2BufferPrevious[23];
    //        c2symbols[ 8] =  c2BufferCurrent[ 2];
    //        c2symbols[ 9] =  c2BufferCurrent[ 3];
    //        c2symbols[10] =  c2BufferCurrent[ 8];
    //        c2symbols[11] =  c2BufferCurrent[ 9];
    //        c2symbols[12] = c2BufferPrevious[18];
    //        c2symbols[13] = c2BufferPrevious[19];
    //        c2symbols[14] = c2BufferPrevious[24];
    //        c2symbols[15] = c2BufferPrevious[25];
    //        c2symbols[16] =  c2BufferCurrent[ 4];
    //        c2symbols[17] =  c2BufferCurrent[ 5];
    //        c2symbols[18] =  c2BufferCurrent[10];
    //        c2symbols[19] =  c2BufferCurrent[11];
    //        c2symbols[20] = c2BufferPrevious[20];
    //        c2symbols[21] = c2BufferPrevious[21];
    //        c2symbols[22] = c2BufferPrevious[26];
    //        c2symbols[23] = c2BufferPrevious[27];
}




