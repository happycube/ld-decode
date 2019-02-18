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
    verbose = false;

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

void DecodeSubcode::setVerboseDebug(bool verboseDebug)
{
    verbose = verboseDebug;
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
    if (verbose) qDebug() << "DecodeSubcode::sm_state_initial(): Current state: sm_state_initial";
    return state_getSync0;
}

DecodeSubcode::StateMachine DecodeSubcode::sm_state_getSync0(void)
{
    // Read a F3 frame into the section
    f3Section[frameCounter] = currentF3Frame;

    // Does the current frame contain a SYNC0 marker?
    if (f3Section[frameCounter][0] == static_cast<char>(0x01)) {
        if (verbose) qDebug() << "DecodeSubcode::sm_state_getSync0(): SYNC0 found";
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
        if (verbose) qDebug() << "DecodeSubcode::sm_state_getSync1(): SYNC1 found";
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
        if (verbose) qDebug() << "DecodeSubcode::sm_state_getInitialSection(): 98 frames received - Section is complete";
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
            if (verbose) qDebug() << "DecodeSubcode::sm_state_getNextSection(): Section SYNC0 and SYNC1 are valid";
            missedSectionSyncCount = 0;
        } else {
            if (verbose) qDebug() << "DecodeSubcode::sm_state_getNextSection(): Section SYNC0 and/or SYNC1 are INVALID";
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
        if (verbose) qDebug() << "DecodeSubcode::sm_state_getNextSection(): 98 frames received - Section is complete";
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
    if (verbose) qDebug() << "DecodeSubcode::sm_state_syncLost(): Sync has been lost!";

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
    // CRC check the Q-subcode - CRC is on control+mode+data 4+4+72 = 80 bits with 16-bit CRC (96 bits total)
    char crcSource[10];
    for (qint32 byteNo = 0; byteNo < 10; byteNo++) crcSource[byteNo] = static_cast<char>(qSubcode[byteNo]);
    quint16 crcChecksum = static_cast<quint16>(~((qSubcode[10] << 8) + qSubcode[11])); // Inverted on disc
    quint16 calcChecksum = crc16(crcSource, 10);

    // Is the Q subcode valid?
    if (crcChecksum != calcChecksum) {
        if (verbose) qDebug() << "DecodeSubcode::decodeQ(): Q Subcode failed CRC check - INVALID Q SUBCODE";
        currentQMode = qMode_unknown;
        return;
    }

    // Q Subcode is valid; split it into fields
    qint32 qControlField = (qSubcode[0] & 0xF0) >> 4;
    qint32 qModeField = (qSubcode[0] & 0x0F);

    // Show Control field meaning
    switch(qControlField) {
    case 0: if (verbose) qDebug() << "DecodeSubcode::decodeQ(): Control 0 (audio channels without pre-emphasis)";
        break;
    case 1: if (verbose) qDebug() << "DecodeSubcode::decodeQ(): Control 1 (audio channels with pre-emphasis 50/15us)";
        break;
    case 2: if (verbose) qDebug() << "DecodeSubcode::decodeQ(): Control 2 (audio channels without pre-emphasis)";
        break;
    case 3: if (verbose) qDebug() << "DecodeSubcode::decodeQ(): Control 3 (audio channels with pre-emphasis 50/15us)";
        break;
    case 4: if (verbose) qDebug() << "DecodeSubcode::decodeQ(): Control 4 (The user data is digital data and it shall not be copied)";
        break;
    case 6: if (verbose) qDebug() << "DecodeSubcode::decodeQ(): Control 5 (The user data is digital data and it may be copied)";
        break;
    default: if (verbose) qDebug() << "DecodeSubcode::decodeQ(): Control is unknown";
    }

    // Show mode field meaning
    switch(qModeField) {
    case 0: if (verbose) qDebug() << "DecodeSubcode::decodeQ(): Mode 0 for DATA-Q (typically used on non-CD information channels)";
        currentQMode = qMode_0;
        break;
    case 1: if (verbose) qDebug() << "DecodeSubcode::decodeQ(): Mode 1 for DATA-Q (Audio track/time information)";
        if (verbose) qDebug().noquote().nospace() << "DecodeSubcode::decodeQ(): Track " << bcdToQString(qSubcode[1]) << " / Index " << bcdToQString(qSubcode[2]) <<
                    " - Time (m:s.f): " << bcdToQString(qSubcode[3]) << ":" << bcdToQString(qSubcode[4]) << "." << bcdToQString(qSubcode[5]);
        currentQMode = qMode_1;
        break;
    case 2: if (verbose) qDebug() << "DecodeSubcode::decodeQ(): Mode 2 for DATA-Q (Catalogue number of the disc)";
        currentQMode = qMode_2;
        break;
    case 3: if (verbose) qDebug() << "DecodeSubcode::decodeQ(): Mode 3 for DATA-Q (Unique number for an audio track)";
        currentQMode = qMode_3;
        break;
    case 4: if (verbose) qDebug() << "DecodeSubcode::decodeQ(): Mode 4 for DATA-Q (Video track/time information)";
        if (verbose) qDebug().noquote().nospace() << "DecodeSubcode::decodeQ(): Track " << bcdToQString(qSubcode[1]) << " / Index " << bcdToQString(qSubcode[2]) <<
                    " - Time (m:s.f): " << bcdToQString(qSubcode[3]) << ":" << bcdToQString(qSubcode[4]) << "." << bcdToQString(qSubcode[5]);
        currentQMode = qMode_4;

        // qSubcode[7] is PFRAME
        switch (qSubcode[7]) {
        case 10: if (verbose) qDebug() << "DecodeSubcode::decodeQ(): Video system: NTSC 'video single' with digital stereo sound";
            break;
        case 11: if (verbose) qDebug() << "DecodeSubcode::decodeQ(): Video system: NTSC 'video single' with digital bilingual sound";
            break;
        case 12: if (verbose) qDebug() << "DecodeSubcode::decodeQ(): Video system: NTSC 'LV disc' with digital stereo sound";
            break;
        case 13: if (verbose) qDebug() << "DecodeSubcode::decodeQ(): Video system: NTSC 'LV disc' with digital bilingual sound";
            break;
        case 20: if (verbose) qDebug() << "DecodeSubcode::decodeQ(): Video system: PAL 'video single' with digital stereo sound";
            break;
        case 21: if (verbose) qDebug() << "DecodeSubcode::decodeQ(): Video system: PAL 'video single' with digital bilingual sound";
            break;
        case 22: if (verbose) qDebug() << "DecodeSubcode::decodeQ(): Video system: PAL 'LV disc' with digital stereo sound";
            break;
        case 23: if (verbose) qDebug() << "DecodeSubcode::decodeQ(): Video system: PAL 'LV disc' with digital bilingual sound";
            break;
        default: if (verbose) qDebug() << "DecodeSubcode::decodeQ(): Video system: Unknown";
        }
        break;
    default: if (verbose) qDebug() << "DecodeSubcode::decodeQ(): Mode is unknown";
    }
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
