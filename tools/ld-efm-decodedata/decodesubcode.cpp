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

}

void DecodeSubcode::decodeQ(uchar *qSubcode)
{
    // CRC check the Q-subcode - CRC is on control+mode+data 4+4+72 = 80 bits with 16-bit CRC (96 bits total)
    char crcSource[10];
    for (qint32 byteNo = 0; byteNo < 10; byteNo++) crcSource[byteNo] = static_cast<char>(qSubcode[byteNo]);
    quint16 crcChecksum = static_cast<quint16>(~((qSubcode[10] << 8) + qSubcode[11])); // Inverted on disc
    quint16 calcChecksum = crc16(crcSource, 10);

    // Is the Q subcode valid?
    if (crcChecksum != calcChecksum) {
        qDebug() << "DecodeSubcode::decodeQ(): Q Subcode failed CRC check - invalid";
        return;
    }

    // Q Subcode is valid; split it into fields
    qint32 qControlField = (qSubcode[0] & 0xF0) >> 4;
    qint32 qModeField = (qSubcode[0] & 0x0F);

    // Show Control field meaning
    switch(qControlField) {
    case 0: qDebug() << "DecodeSubcode::decodeQ(): Control 0 (audio channels without pre-emphasis)";
        break;
    case 1: qDebug() << "DecodeSubcode::decodeQ(): Control 1 (audio channels with pre-emphasis 50/15us)";
        break;
    case 2: qDebug() << "DecodeSubcode::decodeQ(): Control 2 (audio channels without pre-emphasis)";
        break;
    case 3: qDebug() << "DecodeSubcode::decodeQ(): Control 3 (audio channels with pre-emphasis 50/15us)";
        break;
    case 4: qDebug() << "DecodeSubcode::decodeQ(): Control 4 (The user data is digital data and it shall not be copied)";
        break;
    case 6: qDebug() << "DecodeSubcode::decodeQ(): Control 5 (The user data is digital data and it may be copied)";
        break;
    default: qDebug() << "DecodeSubcode::decodeQ(): Control is unknown";
    }

    // Show mode field meaning
    switch(qModeField) {
    case 0: qDebug() << "DecodeSubcode::decodeQ(): Mode 0 for DATA-Q (typically used on non-CD information channels)";
        break;
    case 1: qDebug() << "DecodeSubcode::decodeQ(): Mode 1 for DATA-Q (Audio track/time information)";
        qDebug() << "DecodeSubcode::decodeQ(): Track" << qSubcode[1] << "/ Index" << qSubcode[2] << " - Time (m:s.f):" << qSubcode[3] << ":" << qSubcode[4] << "." << qSubcode[5];
        break;
    case 2: qDebug() << "DecodeSubcode::decodeQ(): Mode 2 for DATA-Q (Catalogue number of the disc)";
        break;
    case 3: qDebug() << "DecodeSubcode::decodeQ(): Mode 3 for DATA-Q (Unique number for an audio track)";
        break;
    case 4: qDebug() << "DecodeSubcode::decodeQ(): Mode 4 for DATA-Q (Video track/time information)";
        qDebug() << "DecodeSubcode::decodeQ(): Track" << qSubcode[1] << "/ Index" << qSubcode[2] << " - Time (m:s.f):" << qSubcode[3] << ":" << qSubcode[4] << "." << qSubcode[5];

        // qSubcode[7] is PFRAME
        switch (qSubcode[7]) {
        case 10: qDebug() << "DecodeSubcode::decodeQ(): Video system: NTSC 'video single' with digital stereo sound";
            break;
        case 11: qDebug() << "DecodeSubcode::decodeQ(): Video system: NTSC 'video single' with digital bilingual sound";
            break;
        case 12: qDebug() << "DecodeSubcode::decodeQ(): Video system: NTSC 'LV disc' with digital stereo sound";
            break;
        case 13: qDebug() << "DecodeSubcode::decodeQ(): Video system: NTSC 'LV disc' with digital bilingual sound";
            break;
        case 20: qDebug() << "DecodeSubcode::decodeQ(): Video system: PAL 'video single' with digital stereo sound";
            break;
        case 21: qDebug() << "DecodeSubcode::decodeQ(): Video system: PAL 'video single' with digital bilingual sound";
            break;
        case 22: qDebug() << "DecodeSubcode::decodeQ(): Video system: PAL 'LV disc' with digital stereo sound";
            break;
        case 23: qDebug() << "DecodeSubcode::decodeQ(): Video system: PAL 'LV disc' with digital bilingual sound";
            break;
        default: qDebug() << "DecodeSubcode::decodeQ(): Video system: Unknown";
        }
        break;
    default: qDebug() << "DecodeSubcode::decodeQ(): Mode is unknown";
    }
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
