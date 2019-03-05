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
#include <QTime>

class DecodeSubcode
{
public:
    DecodeSubcode();

    // Q-channel Decoding results
    enum QDecodeResult {
        qMode0,
        qMode1,
        qMode2,
        qMode3,
        qMode4,
        invalid
    };

    // Q-Channel control
    struct QControl {
        bool isStereo;
        bool isAudio;
        bool isCopyProtected;
        bool isNotPreEmp;
    };

    struct QFrameMode4 {
        QControl qControl;
        QTime trackTime;
        qint32 trackFrame;
        QTime discTime;
        qint32 discFrame;
        bool leadin;
        bool leadout;

        qint32 tno;
        qint32 x;
        qint32 point;

        bool isValid;
    };

    QDecodeResult decodeBlock(uchar *subcodeData);
    QFrameMode4 getQMode4(void);

private:
    QFrameMode4 qFrameMode4;

    QString bcdToQString(uchar bcd);
    qint32 bcdToInteger(uchar bcd);
    bool verifyQ(uchar *qSubcode);
    quint16 crc16(char *addr, quint16 num);

    QControl decodeQControl(uchar *qSubcode);
    qint32 decodeQAddress(uchar *qSubcode);

    QFrameMode4 decodeQDataMode4(uchar *qSubcode);
    QFrameMode4 defaultQMode4(void);

};

#endif // DECODESUBCODE_H
