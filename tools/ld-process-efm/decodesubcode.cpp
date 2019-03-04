/************************************************************************

    decodesubcode.cpp

    ld-process-efm - EFM data decoder
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

// This method decodes the subcode data
// Right now it only looks at the Q channel, but it decodes all
// 8 channels for future use
//
// Returns true if block contains audio and false if block contains data
DecodeSubcode::QDecodeResult DecodeSubcode::decodeBlock(uchar *subcodeData)
{
    DecodeSubcode::QDecodeResult result = invalid;

    // Extract the subcode channels - there are 8 subcodes containing 96 bits (12 bytes)
    // per subcode.  Only channels P and Q are supported by the red-book CD standards
    uchar pSubcode[12];
    uchar qSubcode[12];
    uchar rSubcode[12];
    uchar sSubcode[12];
    uchar tSubcode[12];
    uchar uSubcode[12];
    uchar vSubcode[12];
    uchar wSubcode[12];

    qint32 dataPointer = 2;
    for (qint32 byteC = 0; byteC < 12; byteC++) {
        // Initialise the channel bytes
        pSubcode[byteC] = 0;
        qSubcode[byteC] = 0;
        rSubcode[byteC] = 0;
        sSubcode[byteC] = 0;
        tSubcode[byteC] = 0;
        uSubcode[byteC] = 0;
        vSubcode[byteC] = 0;
        wSubcode[byteC] = 0;

        // Copy in the channel data from the subscode data
        for (qint32 bitC = 7; bitC >= 0; bitC--) {
            if (subcodeData[dataPointer] & 0x80) pSubcode[byteC] |= (1 << bitC);
            if (subcodeData[dataPointer] & 0x40) qSubcode[byteC] |= (1 << bitC);
            if (subcodeData[dataPointer] & 0x20) rSubcode[byteC] |= (1 << bitC);
            if (subcodeData[dataPointer] & 0x10) sSubcode[byteC] |= (1 << bitC);
            if (subcodeData[dataPointer] & 0x08) tSubcode[byteC] |= (1 << bitC);
            if (subcodeData[dataPointer] & 0x04) uSubcode[byteC] |= (1 << bitC);
            if (subcodeData[dataPointer] & 0x02) vSubcode[byteC] |= (1 << bitC);
            if (subcodeData[dataPointer] & 0x01) wSubcode[byteC] |= (1 << bitC);
            dataPointer++;
        }
    }

    // Verify the Q-channel payload is valid
    bool qChannelValid = verifyQ(qSubcode);

    // If the Q channel payload is valid, decode it
    qint32 qMode = -1;
    DecodeSubcode::QControl qControl;
    if (qChannelValid) {
        // Get the control parameters
        qControl = decodeQControl(qSubcode);

        // Get the Q Mode
        qMode = decodeQAddress(qSubcode);

        // Get the Q Mode parameters
        if (qMode == 0) {
            qDebug() << "DecodeSubcode::decode(): Q Mode 0: Not supported!";
            result = data;
        }
        if (qMode == 1) {
            qDebug() << "DecodeSubcode::decode(): Q Mode 1: Not supported!";
            result = audio;
        }
        if (qMode == 2) {
            qDebug() << "DecodeSubcode::decode(): Q Mode 2: Not supported!";
            result = audio;
        }
        if (qMode == 3) {
            qDebug() << "DecodeSubcode::decode(): Q Mode 3: Not supported!";
            result = audio;
        }
        if (qMode == 4) {
            decodeQDataMode4(qSubcode); // Q Mode 4 = Video audio
            result = audio;
        }

        if (qMode == -1) qDebug() << "DecodeSubcode::decode(): Invalid Q Mode reported by subcode block!";
    } else {
        result = crcFailure;
    }

    return result;
}

// Method to convert 2 digit BCD byte to 2 numeric characters
QString DecodeSubcode::bcdToQString(uchar bcd)
{
    return QString("%1").arg(bcdToInteger(bcd), 2, 10, QChar('0'));
}

// Method to convert 2 digit BCD byte to an integer
qint32 DecodeSubcode::bcdToInteger(uchar bcd)
{
   return (((bcd>>4)*10) + (bcd & 0xF));
}

// Method to CRC verify the Q subcode payload
bool DecodeSubcode::verifyQ(uchar *qSubcode)
{
    // CRC check the Q-subcode - CRC is on control+mode+data 4+4+72 = 80 bits with 16-bit CRC (96 bits total)
    char crcSource[10];
    for (qint32 byteNo = 0; byteNo < 10; byteNo++) crcSource[byteNo] = static_cast<char>(qSubcode[byteNo]);
    quint16 crcChecksum = static_cast<quint16>(~((qSubcode[10] << 8) + qSubcode[11])); // Inverted on disc
    quint16 calcChecksum = crc16(crcSource, 10);

    // Is the Q subcode valid?
    if (crcChecksum != calcChecksum) {
        qDebug() << "DecodeSubcode::decodeQ(): Q Subcode CRC failed - Q subcode payload is invalid";
        return false;
    }

    return true;
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

// Method to decode the Q subcode CONTROL field
DecodeSubcode::QControl DecodeSubcode::decodeQControl(uchar *qSubcode)
{
    DecodeSubcode::QControl qControl;

    // Get the control payload
    qint32 qControlField = (qSubcode[0] & 0xF0) >> 4;

    // Control field values can be:
    //
    // x000 = 2-Channel/4-Channel
    // 0x00 = audio/data
    // 00x0 = Copy not permitted/copy permitted
    // 000x = pre-emphasis off/pre-emphasis on

    if ((qControlField & 0x08) == 0x08) qControl.isStereo = false; else qControl.isStereo = true;
    if ((qControlField & 0x04) == 0x04) qControl.isAudio = false; else qControl.isAudio = true;
    if ((qControlField & 0x02) == 0x02) qControl.isCopyProtected = false; else qControl.isCopyProtected = true;
    if ((qControlField & 0x01) == 0x01) qControl.isNotPreEmp = false; else qControl.isNotPreEmp = true;

//    QString debugOut;
//    if (qControl.isStereo) debugOut += "2 Channel"; else debugOut += "4 Channel";
//    if (qControl.isAudio) debugOut += " - Audio"; else debugOut += " - Data";
//    if (qControl.isCopyProtected) debugOut += " - Copy protected"; else debugOut += " - Not copy protected";
//    if (qControl.isNotPreEmp) debugOut += " - Pre-emphasis"; else debugOut += " - No pre-emphasis";
//    qDebug() << "DecodeSubcode::decodeQControl():" << debugOut;

    return qControl;
}

// Method to decode the Q subcode ADR field
qint32 DecodeSubcode::decodeQAddress(uchar *qSubcode)
{
    // Get the Q Mode value
    qint32 qMode = (qSubcode[0] & 0x0F);

    // Range check
    if (qMode < 0 || qMode > 4) qMode = -1;

    return qMode;
}

// Method to decode Q subcode Mode 4 DATA-Q
void DecodeSubcode::decodeQDataMode4(uchar *qSubcode)
{
    QString debugOut;

    // Get the track number (TNO) field
    qint32 tno = bcdToInteger(qSubcode[1]);

    // Use TNO to detect lead-in, audio or lead-out
    if (qSubcode[1] == 0xAA) {
        // Lead out
        debugOut += "Mode 4 (Video audio) Lead-out - ";
        debugOut += "TNO=170 ";
        debugOut += "X=" + bcdToQString(qSubcode[2]) + " ";
        debugOut += "MIN=" + bcdToQString(qSubcode[3]) + " ";
        debugOut += "SEC=" + bcdToQString(qSubcode[4]) + " ";
        debugOut += "FRAME=" + bcdToQString(qSubcode[5]) + " ";
        //debugOut += "ZERO=" + bcdToQString(qSubcode[6]) + " ";
        debugOut += "AMIN=" + bcdToQString(qSubcode[7]) + " ";
        debugOut += "ASEC=" + bcdToQString(qSubcode[8]) + " ";
        debugOut += "AFRAME=" + bcdToQString(qSubcode[9]);
    } else if (tno == 0) {
        // Lead in
        debugOut += "Mode 4 (Video audio) Lead-in - ";
        debugOut += "TNO=" + bcdToQString(qSubcode[1]) + " ";
        debugOut += "POINT=" + bcdToQString(qSubcode[2]) + " ";
        debugOut += "MIN=" + bcdToQString(qSubcode[3]) + " ";
        debugOut += "SEC=" + bcdToQString(qSubcode[4]) + " ";
        debugOut += "FRAME=" + bcdToQString(qSubcode[5]) + " ";
        //debugOut += "ZERO=" + bcdToQString(qSubcode[6]) + " ";
        debugOut += "PMIN=" + bcdToQString(qSubcode[7]) + " ";
        debugOut += "PSEC=" + bcdToQString(qSubcode[8]) + " ";
        debugOut += "PFRAME=" + bcdToQString(qSubcode[9]);
    } else {
        // Audio
        debugOut += "Mode 4 (Video audio) Audio - ";
        debugOut += "TNO=" + bcdToQString(qSubcode[1]) + " ";
        debugOut += "X=" + bcdToQString(qSubcode[2]) + " ";
        debugOut += "MIN=" + bcdToQString(qSubcode[3]) + " ";
        debugOut += "SEC=" + bcdToQString(qSubcode[4]) + " ";
        debugOut += "FRAME=" + bcdToQString(qSubcode[5]) + " ";
        //debugOut += "ZERO=" + bcdToQString(qSubcode[6]) + " ";
        debugOut += "AMIN=" + bcdToQString(qSubcode[7]) + " ";
        debugOut += "ASEC=" + bcdToQString(qSubcode[8]) + " ";
        debugOut += "AFRAME=" + bcdToQString(qSubcode[9]);
    }

    qDebug().noquote() << "DecodeSubcode::decodeQDataMode4():" << debugOut;
}



