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

    uchar testCode[32];
    encode_data(c1Data, 28, testCode);
    hexDump("orig[] : ", c1Data, 32);
    hexDump("enco[] : ", testCode, 32);
    qDebug() << "--------------------------------------------------------------------------------------------------";

    // RS is 32, 28 (i.e. 28 bytes of data with 4 bytes of parity)
    initialize_ecc();
    decode_data(c1Data, 32); // Message length including parity

    if (check_syndrome() != 0) {
        //qDebug() << "DecodeAudio::sm_state_processC1(): C1 CIRC Failed!";
    } else {
        qDebug() << "DecodeAudio::sm_state_processC1(): C1 CIRC Passed! ***************************************************";
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

// Interleave frame0 (WmA bits) and frame1 (WmB bits) and invert parity
void DecodeAudio::interleaveFrameData(QByteArray f3Frame0, QByteArray f3Frame1, uchar *c1Data)
{
    // frame0 user data provides WmA and frame1 user data provides WmB

    // Get the user data from frame0 and frame1
    uchar userData0[32];
    uchar userData1[32];

    for (qint32 byteC = 0; byteC < 32; byteC++) {
        userData0[byteC] = static_cast<uchar>(f3Frame0[byteC + 2]);
        userData1[byteC] = static_cast<uchar>(f3Frame1[byteC + 2]);
    }

    //hexDump("userData0[] : ", userData0, 32);
    //hexDump("userData1[] : ", userData1, 32);

    // Interleave the user data - result is even bits from userData0 and odd bits from userData1
    for (qint32 byteC = 0; byteC < 32; byteC++) {
        uchar byte = 0;

        // Take WmA from userData0 and WmB from userData1
        byte |= ((1 << 7) & userData0[byteC]);
        byte |= ((1 << 6) & userData1[byteC]);
        byte |= ((1 << 5) & userData0[byteC]);
        byte |= ((1 << 4) & userData1[byteC]);
        byte |= ((1 << 3) & userData0[byteC]);
        byte |= ((1 << 2) & userData1[byteC]);
        byte |= ((1 << 1) & userData0[byteC]);
        byte |= ((1 << 0) & userData1[byteC]);

        c1Data[byteC] = byte;
    }

    // Invert the Qm parity bits
    c1Data[12] = c1Data[12] ^ 0xFF;
    c1Data[13] = c1Data[13] ^ 0xFF;
    c1Data[14] = c1Data[14] ^ 0xFF;
    c1Data[15] = c1Data[15] ^ 0xFF;

    // Invert the Pm parity bits
    c1Data[28] = c1Data[28] ^ 0xFF;
    c1Data[29] = c1Data[29] ^ 0xFF;
    c1Data[30] = c1Data[30] ^ 0xFF;
    c1Data[31] = c1Data[31] ^ 0xFF;

    //hexDump("   c1Data[] : ", c1Data, 32);
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

// Method to process audio data.  Note: 109 frames are required for C2
// level error correction, so this is the minimum we can process

// The received demodulated frame enters the CIRC decoder with all symbols at the same time,
// in parallel. The data decoding begins with a  1-symbol delay performed upon all even-numbered symbols.
// Two frames are therefore needed at this stage to rebuild an original undelayed 28-symbol frame.
// These delays, introduced during the encoding process, improve the correction of small burst errors
// by spreading two adjacent corrupt symbols over two user frames.

// The next operation reverses the polarity of the parity symbols in a bit-wise manner.
