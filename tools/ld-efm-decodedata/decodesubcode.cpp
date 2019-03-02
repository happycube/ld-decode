/************************************************************************

    decodesubcode.cpp

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

#include "decodesubcode.h"

DecodeSubcode::DecodeSubcode()
{
    // Initialise the state machine
    currentState = state_initial;
    nextState = currentState;

    frameCounter = 0;
    missedSectionSyncCount = 0;

    // Allocate space for the frames within the section buffer
    f3Section.resize(98);
    for (qint32 frameNo = 0; frameNo < 98; frameNo++) f3Section[frameNo].resize(34);

    // Set the current QMode to the default
    currentQMode = qMode_unknown;
    previousQMode = currentQMode;
}

// Method to return the current Q Mode
DecodeSubcode::QModes DecodeSubcode::getQMode(void)
{
    // If the current qMode is unknown, try to use the previous qMode
    if (currentQMode == qMode_unknown) {
        if (previousQMode != qMode_unknown) return previousQMode;
    }

    previousQMode = currentQMode;
    return currentQMode;
}

// State machine methods ----------------------------------------------------------------------------------------------

void DecodeSubcode::process(QByteArray f3FrameParam)
{
    // Ensure the F3 frame is the correct length
    if (f3FrameParam.size() != 34) {
        qDebug() << "DecodeSubcode::process(): Invalid F3 frame parameter (not 34 bytes!)";
        return;
    }

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
        case state_getSync0:
            nextState = sm_state_getSync0();
            break;
        case state_getSync1:
            nextState = sm_state_getSync1();
            break;
        case state_getInitialSection:
            nextState = sm_state_getInitialSection();
            break;
        case state_getNextSection:
            nextState = sm_state_getNextSection();
            break;
        case state_processSection:
            nextState = sm_state_processSection();
            break;
        case state_syncLost:
            nextState = sm_state_syncLost();
            break;
        }
    }
}

DecodeSubcode::StateMachine DecodeSubcode::sm_state_initial(void)
{
    return state_getSync0;
}

DecodeSubcode::StateMachine DecodeSubcode::sm_state_getSync0(void)
{
    // Read a F3 frame into the section
    f3Section[frameCounter] = currentF3Frame;

    // Does the current frame contain a SYNC0 marker?
    if (f3Section[frameCounter][0] == static_cast<char>(0x01)) {
        frameCounter++;
        waitingForF3frame = true;
        return state_getSync1;
    }

    // No SYNC0, discard current frame
    frameCounter = 0;
    waitingForF3frame = true;

    return state_getSync0;
}

DecodeSubcode::StateMachine DecodeSubcode::sm_state_getSync1(void)
{
    // Read a F3 frame into the section
    f3Section[frameCounter] = currentF3Frame;

    // Does the current frame contain a SYNC1 marker?
    if (f3Section[frameCounter][0] == static_cast<char>(0x02)) {
        frameCounter++;
        waitingForF3frame = true;
        return state_getInitialSection;
    }

    // No SYNC1, discard current frames and go back to looking for a SYNC0
    frameCounter = 0;
    waitingForF3frame = true;

    return state_getSync0;
}

DecodeSubcode::StateMachine DecodeSubcode::sm_state_getInitialSection(void)
{
    // Read a F3 frame into the section
    f3Section[frameCounter] = currentF3Frame;
    frameCounter++;

    // If we have 98 frames, the section is complete, process it
    if (frameCounter == 98) {
        return state_processSection;
    }

    // Need more frames to complete section
    waitingForF3frame = true;
    return state_getInitialSection;
}

DecodeSubcode::StateMachine DecodeSubcode::sm_state_getNextSection(void)
{
    // Read a F3 frame into the section
    f3Section[frameCounter] = currentF3Frame;
    frameCounter++;

    // If we have 2 frames, check the sync pattern
    if (frameCounter == 2) {
        if (f3Section[0][0] == static_cast<char>(0x01) && f3Section[1][0] == static_cast<char>(0x02)) {
            //qDebug() << "DecodeSubcode::sm_state_getNextSection(): Section SYNC0 and SYNC1 are valid";
            missedSectionSyncCount = 0;
        } else {
            qDebug() << "DecodeSubcode::sm_state_getNextSection(): Section SYNC0 and/or SYNC1 are INVALID";
            missedSectionSyncCount++;

            // If we have missed 4 syncs in a row, consider the sync as lost
            if (missedSectionSyncCount == 4) {
                missedSectionSyncCount = 0;
                return state_syncLost;
            }
        }
    }

    // If we have 98 frames, the section is complete, process it
    if (frameCounter == 98) {
        return state_processSection;
    }

    // Need more frames to complete section
    waitingForF3frame = true;
    return state_getNextSection;
}

DecodeSubcode::StateMachine DecodeSubcode::sm_state_processSection(void)
{
    // Extract the subcodes - there are 8 subcodes containing 96 bits (12 bytes)
    // per subcode.  Only subcodes p and q are supported by the CDROM standards
    uchar pSubcode[12];
    uchar qSubcode[12];

    qint32 frameNumber = 2; // 0 and 1 are SYNC0 and SYNC1
    for (qint32 byteC = 0; byteC < 12; byteC++) {
        pSubcode[byteC] = 0;
        qSubcode[byteC] = 0;
        for (qint32 bitC = 7; bitC >= 0; bitC--) {
            if (f3Section[frameNumber][1] & 0x80) pSubcode[byteC] |= (1 << bitC);
            if (f3Section[frameNumber][1] & 0x40) qSubcode[byteC] |= (1 << bitC);
            frameNumber++;
        }
    }

    // Decode the subcodes (for debug)
    decodeQ(qSubcode);

    // Discard section and get the next frame
    frameCounter = 0;
    waitingForF3frame = true;

    return state_getNextSection;
}

DecodeSubcode::StateMachine DecodeSubcode::sm_state_syncLost(void)
{
    qDebug() << "DecodeSubcode::sm_state_syncLost(): Subcode Sync has been lost!";

    // Discard all frames
    frameCounter = 0;

    // Return to looking for SYNC0
    return state_getSync0;
}

// Utility methods ----------------------------------------------------------------------------------------------------

// Method to decode the Q subcode
// Returns the Q Mode field number (or -1 if the Mode is unknown)
void DecodeSubcode::decodeQ(uchar *qSubcode)
{
    QString debugOut;

    // CRC check the Q-subcode - CRC is on control+mode+data 4+4+72 = 80 bits with 16-bit CRC (96 bits total)
    char crcSource[10];
    for (qint32 byteNo = 0; byteNo < 10; byteNo++) crcSource[byteNo] = static_cast<char>(qSubcode[byteNo]);
    quint16 crcChecksum = static_cast<quint16>(~((qSubcode[10] << 8) + qSubcode[11])); // Inverted on disc
    quint16 calcChecksum = crc16(crcSource, 10);

    // Is the Q subcode valid?
    if (crcChecksum != calcChecksum) {
        debugOut += "Q Subcode CRC failed - subcode is invalid";
        currentQMode = qMode_unknown;
        return;
    }

    // Q Subcode is valid; split it into fields
    qint32 qControlField = (qSubcode[0] & 0xF0) >> 4;
    qint32 qModeField = (qSubcode[0] & 0x0F);

    // Show Control field meaning
    switch(qControlField) {
    case 0: debugOut += "Control 0 (audio no pre-emp)";
        break;
    case 1: debugOut += "Control 1 (audio delayed pre-emp)";
        break;
    case 2: debugOut += "Control 2 (audio no pre-emp)";
        break;
    case 3: debugOut += "Control 3 (audio delayed pre-emp)";
        break;
    case 4: debugOut += "Control 4 (data no copy)";
        break;
    case 6: debugOut += "Control 6 (data with copy)";
        break;
    default: debugOut += "Control " + QString::number(qControlField) + " (unknown)";
    }

    // Show mode field meaning
    switch(qModeField) {
    case 0: debugOut += " - Mode 0 (non-CD)";
        currentQMode = qMode_0;
        break;
    case 1: debugOut += " - Mode 1 (CD Audio) Trk/Idx " + bcdToQString(qSubcode[1]) + "/" + bcdToQString(qSubcode[2]) +
                " - T: " + bcdToQString(qSubcode[3]) + ":" + bcdToQString(qSubcode[4]) + "." + bcdToQString(qSubcode[5]);
        currentQMode = qMode_1;
        break;
    case 2: debugOut += " - Mode 2 (Catalogue number)";
        currentQMode = qMode_2;
        break;
    case 3: debugOut += " - Mode 3 (track ID)";
        currentQMode = qMode_3;
        break;
    case 4: debugOut += " - Mode 4 (Video Audio) Trk/Idx " + bcdToQString(qSubcode[1]) + "/" + bcdToQString(qSubcode[2]) +
                " - T: " + bcdToQString(qSubcode[3]) + ":" + bcdToQString(qSubcode[4]) + "." + bcdToQString(qSubcode[5]);
        currentQMode = qMode_4;

        // qSubcode[7] is PFRAME
        switch (qSubcode[7]) {
        case 10: debugOut += " - NTSC CDV stereo";
            break;
        case 11: debugOut += " - NTSC CDV bilingual";
            break;
        case 12: debugOut += " - NTSC LV stereo";
            break;
        case 13: debugOut += " - NTSC LV bilingual";
            break;
        case 20: debugOut += " - PAL CDV stereo";
            break;
        case 21: debugOut += " - PAL CDV bilingual";
            break;
        case 22: debugOut += " - PAL LV stereo";
            break;
        case 23: debugOut += " - PAL LV bilingual";
            break;
        default: debugOut += " - Unknown";
        }
        break;
    default: debugOut += " - Mode Unknown " + QString::number(qModeField);
    }

    qDebug() << "DecodeSubcode::decodeQ():" << debugOut;
}

// Method to convert 2 digit BCD byte to 2 numeric characters
QString DecodeSubcode::bcdToQString(qint32 bcd)
{
    return QString("%1").arg(bcdToInteger(bcd), 2, 10, QChar('0'));
}

// Method to convert 2 digit BCD byte to an integer
qint32 DecodeSubcode::bcdToInteger(qint32 bcd)
{
   return (((bcd>>4)*10) + (bcd & 0xF));
}

// Method to perform CRC16 (XMODEM)
// Adapted from http://mdfs.net/Info/Comp/Comms/CRC16.htm
quint16 DecodeSubcode::crc16(char *addr, quint16 num)
{
    qint32 i;
    quint32 crc = 0;

    for (; num > 0; num--) {
        crc = crc ^ static_cast<quint32>(*addr++ << 8);
        for (i = 0; i < 8; i++) {
            crc = crc << 1;
            if (crc & 0x10000) crc = (crc ^ 0x1021) & 0xFFFF;
        }
    }

    return static_cast<quint16>(crc);
}
