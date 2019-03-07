/************************************************************************

    subcodeblock.h

    ld-process-efm - EFM data decoder
    Copyright (C) 2019 Simon Inns

    This file is part of ld-decode-tools.

    ld-process-efm is free software: you can redistribute it and/or
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

#ifndef SUBCODEBLOCK_H
#define SUBCODEBLOCK_H

#include <QCoreApplication>
#include <QDebug>

#include "f3frame.h"
#include "tracktime.h"

class SubcodeBlock
{
public:
    SubcodeBlock();

    enum Channels {
        channelP,
        channelQ,
        channelR,
        channelS,
        channelT,
        channelU,
        channelV,
        channelW
    };

    // Structure of the Q Control flags
    struct QControl {
        bool isStereoNotQuad;
        bool isAudioNotData;
        bool isCopyProtectedNotUnprotected;
        bool isNoPreempNotPreemp;
    };

    // Structure of the Q mode 4 metadata
    struct QMode4 {
        bool isLeadIn;
        bool isLeadOut;
        qint32 trackNumber;
        qint32 x;
        qint32 point;
        TrackTime trackTime;
        TrackTime discTime;
    };

    struct QMetadata {
        QControl qControl;
        QMode4 qMode4;
    };

    void setF3Frames(QVector<F3Frame> f3FramesIn);
    uchar *getChannelData(SubcodeBlock::Channels channel);
    F3Frame getFrame(qint32 frameNumber);
    qint32 getQMode(void);
    void setFirstAfterSync(bool parameter);
    bool getFirstAfterSync(void);
    QMetadata getQMetadata(void);

private:
    QMetadata qMetadata;

    QVector<F3Frame> f3Frames;
    qint32 qMode;
    bool firstAfterSync;

    // Subcode channels
    uchar pSubcode[12];
    uchar qSubcode[12];
    uchar rSubcode[12];
    uchar sSubcode[12];
    uchar tSubcode[12];
    uchar uSubcode[12];
    uchar vSubcode[12];
    uchar wSubcode[12];

    bool verifyQ(void);
    quint16 crc16(char *addr, quint16 num);
    qint32 decodeQAddress(void);
    void decodeQControl(void);
    void decodeQDataMode4(void);
    qint32 bcdToInteger(uchar bcd);

};

#endif // SUBCODEBLOCK_H
