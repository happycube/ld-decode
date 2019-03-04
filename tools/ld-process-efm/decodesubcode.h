/************************************************************************

    decodesubcode.h

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

#ifndef DECODESUBCODE_H
#define DECODESUBCODE_H

#include <QCoreApplication>
#include <QDebug>

class DecodeSubcode
{
public:
    DecodeSubcode();

    // Q-channel Decoding results
    enum QDecodeResult {
        audio,          // Data payload is audio
        data,           // Data payload is data
        crcFailure,     // CRC check failed
        invalid         // Some other error
    };

    QDecodeResult decodeBlock(uchar *subcodeData);

private:

    // Q-Channel control
    struct QControl {
        bool isStereo;
        bool isAudio;
        bool isCopyProtected;
        bool isNotPreEmp;
    };

    QString bcdToQString(uchar bcd);
    qint32 bcdToInteger(uchar bcd);
    bool verifyQ(uchar *qSubcode);
    quint16 crc16(char *addr, quint16 num);

    QControl decodeQControl(uchar *qSubcode);
    qint32 decodeQAddress(uchar *qSubcode);

    void decodeQDataMode4(uchar *qSubcode);

};

#endif // DECODESUBCODE_H
