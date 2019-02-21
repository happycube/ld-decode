/************************************************************************

    decodeaudio.h

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

#ifndef DECODEAUDIO_H
#define DECODEAUDIO_H

#include <QCoreApplication>
#include <QDebug>

#include "reedsolomon.h"

class DecodeAudio
{
public:
    DecodeAudio();

    void process(QByteArray f3FrameParam);

private:
    void interleaveC1Data(QByteArray f3Frame0, QByteArray f3Frame1, uchar *c1Data);
    void getC2Data(uchar *symBuffer, bool *isErasure);
    QString dataToString(uchar *data, qint32 length);
    void moveC2ParitySymbols(uchar *symBuffer, bool *isErasure);
    void deInterleaveC2(void);

    // CIRC FEC class
    ReedSolomon reedSolomon;

    // C1 ECC buffer
    uchar c1Symbols[32];
    bool c1SymbolsValid;
    qint32 validC1Count;
    qint32 invalidC1Count;

    // C2 ECC buffer
    struct C2Buffer {
        uchar c1Symbols[28];
        bool c1SymbolsValid;
    };
    QVector<C2Buffer> c1DelayBuffer;
    bool c2BufferValid;

    // State machine state definitions
    enum StateMachine {
        state_initial,
        state_processC1,
        state_processC2,
        state_processAudio
    };

    StateMachine currentState;
    StateMachine nextState;
    bool waitingForF3frame;
    QByteArray currentF3Frame;
    QByteArray previousF3Frame;

    StateMachine sm_state_initial(void);
    StateMachine sm_state_processC1(void);
    StateMachine sm_state_processC2(void);
    StateMachine sm_state_processAudio(void);
};

#endif // DECODEAUDIO_H
