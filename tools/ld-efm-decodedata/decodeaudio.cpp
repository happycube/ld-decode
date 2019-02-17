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
}

void DecodeAudio::process(QByteArray f3FrameParam)
{
    // Ensure the F3 frame isn't empty
    if (f3FrameParam.isEmpty()) return;

    currentF3Frame = f3FrameParam;

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

DecodeAudio::StateMachine DecodeAudio::sm_state_processC1(void)
{
    //qDebug() << "DecodeAudio::sm_state_processC1(): Called";

    // Process the C1
    uchar c1Data[32];
    interleaveFrameData(previousF3Frame, currentF3Frame, c1Data);

    // Initialise the error correction library
    initialize_ecc();

    // RS is 32, 28 (i.e. 28 bytes of data with 4 bytes of parity)
    decode_data(c1Data, 32); // Message length including parity

    // Check the syndrome to see if there were errors in the data
    if (check_syndrome() != 0) {
        //qDebug() << "DecodeAudio::sm_state_processC1(): C1 CIRC Failed! check_syndrome =" << check_syndrome() << "******************************************************";
    } else {
        qDebug() << "DecodeAudio::sm_state_processC1(): C1 CIRC Passed! ===========================================================";
    }

    // Store the frame and get a new frame
    previousF3Frame = currentF3Frame;
    waitingForF3frame = true;

    return state_processC1;
}

DecodeAudio::StateMachine DecodeAudio::sm_state_processC2(void)
{
    qDebug() << "DecodeAudio::sm_state_processC2(): Called";

    // Now the C2 is complete, process the audio
    return state_processAudio;
}

DecodeAudio::StateMachine DecodeAudio::sm_state_processAudio(void)
{
    qDebug() << "DecodeAudio::sm_state_processAudio(): Called";

    // Discard the C2 and get the next C1
    return state_processC1;
}

// Utility methods ----------------------------------------------------------------------------------------------------

// Interleave current and previous F3 frame symbols and then invert parity words
void DecodeAudio::interleaveFrameData(QByteArray previousF3Frame, QByteArray currentF3Frame, uchar *c1Data)
{
    // Interleave the symbols
    for (qint32 byteC = 0; byteC < 32; byteC += 2) {
        c1Data[byteC] = static_cast<uchar>(currentF3Frame[byteC + 2]);
        c1Data[byteC+1] = static_cast<uchar>(previousF3Frame[byteC + 1 + 2]);
        // +2 as F3Frame has 2 additional sync bits before user data
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

void DecodeAudio::hexDump(QString title, uchar *data, qint32 length)
{
    QString output;

    output += title;

    for (qint32 count = 0; count < length; count++) {
        output += QString("%1").arg(data[count], 2, 16, QChar('0'));
    }

    qDebug().noquote() << output;
}

