/************************************************************************

    vbidecoder.cpp

    ld-decode-tools TBC library
    Copyright (C) 2018-2019 Simon Inns

    This file is part of ld-decode-tools.

    ld-decode-tools is free software: you can redistribute it and/or
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

#ifndef VBIDECODER_H
#define VBIDECODER_H

#include <QObject>
#include <QDebug>

class VbiDecoder
{
public:
    // VBI Metadata definition
    enum VbiDiscTypes {
        unknownDiscType,    // 0
        clv,                // 1
        cav                 // 2
    };

    // VBI Sound modes
    enum VbiSoundModes {
        stereo,                 // 0
        mono,                   // 1
        audioSubCarriersOff,    // 2
        bilingual,              // 3
        stereo_stereo,          // 4
        stereo_bilingual,       // 5
        crossChannelStereo,     // 6
        bilingual_bilingual,    // 7
        mono_dump,              // 8
        stereo_dump,            // 9
        bilingual_dump,         // 10
        futureUse               // 11
    };

    // Overall container struct for VBI information
    struct Vbi {
        VbiDiscTypes type;
        QString userCode;
        qint32 picNo;
        qint32 chNo;
        qint32 clvHr;
        qint32 clvMin;
        qint32 clvSec;
        qint32 clvPicNo;
        VbiSoundModes soundMode;
        VbiSoundModes soundModeAm2;

        // Note: These booleans are virtual (and stored in a single int)
        bool leadIn;
        bool leadOut;
        bool picStop;
        bool cx;
        bool size;
        bool side;
        bool teletext;
        bool dump;
        bool fm;
        bool digital;
        bool parity;
        bool copyAm2;
        bool standardAm2;
    };

    VbiDecoder();
    Vbi decodeFrame(qint32 vbi16_1, qint32 vbi17_1, qint32 vbi18_1,
                    qint32 vbi16_2, qint32 vbi17_2, qint32 vbi18_2);
    Vbi decode(qint32 vbi16, qint32 vbi17, qint32 vbi18);

private:
    bool verboseDebug;
    bool parity(quint32 x4, quint32 x5);
};

#endif // VBIDECODER_H
