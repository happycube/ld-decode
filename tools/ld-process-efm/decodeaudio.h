/************************************************************************

    decodeaudio.h

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

#ifndef DECODEAUDIO_H
#define DECODEAUDIO_H

#include <QCoreApplication>
#include <QDebug>

#include "reedsolomon.h"

class DecodeAudio
{
public:
    DecodeAudio();

    qint32 getValidC1Count(void);
    qint32 getInvalidC1Count(void);
    qint32 getValidC2Count(void);
    qint32 getInvalidC2Count(void);
    qint32 getValidAudioSamplesCount(void);
    qint32 getInvalidAudioSamplesCount(void);

    QByteArray getOutputData(void);
    qint32 decodeBlock(uchar *blockData, uchar *blockErasures);

private:
    void interleaveC1Data(QByteArray previousF3, QByteArray currentF3,
                                       QByteArray previousF3E, QByteArray currentF3E,
                                       uchar *c1Data, bool *isErasure);
    void getC2Data(uchar *symBuffer, bool *isErasure);
    QString dataToString(uchar *data, qint32 length);
    void deInterleaveC2(uchar *outputData);

    // CIRC FEC class
    ReedSolomon reedSolomon;

    // C1 ECC buffer
    uchar c1Data[32];
    bool c1DataErasures[32];
    bool c1DataValid;
    qint32 validC1Count;
    qint32 invalidC1Count;
    qint32 validAudioSampleCount;
    qint32 invalidAudioSampleCount;

    // C1 ECC delay buffer
    struct C1Buffer {
        uchar c1Symbols[28];
        bool c1SymbolsValid;
    };
    QVector<C1Buffer> c1DelayBuffer;
    bool c2DataValid;
    qint32 validC2Count;
    qint32 invalidC2Count;

    // C2 EEC buffer
    uchar c2Data[28];
    bool c2DataErasures[28];

    // C2 De-interleave delay buffer
    struct C2Buffer {
        uchar c2Symbols[28];
        bool c2SymbolsValid;
    };
    QVector<C2Buffer> c2DelayBuffer;

    // Output data buffer
    QByteArray outputDataBuffer;

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
    QByteArray currentF3Erasures;
    QByteArray previousF3Frame;
    QByteArray previousF3Erasures;

    StateMachine sm_state_initial(void);
    StateMachine sm_state_processC1(void);
    StateMachine sm_state_processC2(void);
    StateMachine sm_state_processAudio(void);
};

#endif // DECODEAUDIO_H
