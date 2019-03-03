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

    // Available Q Modes
    enum QModes {
        qMode_0,
        qMode_1,
        qMode_2,
        qMode_3,
        qMode_4,
        qMode_unknown
    };

    void process(QByteArray f3FrameParam);
    QModes getQMode(void);

private:
    void decodeQ(uchar *qSubcode);
    QString bcdToQString(qint32 bcd);
    qint32 bcdToInteger(qint32 bcd);
    quint16 crc16(char *addr, quint16 num);

    QModes currentQMode;
    QModes previousQMode;

    // State machine state definitions
    enum StateMachine {
        state_initial,
        state_getSync0,
        state_getSync1,
        state_getInitialSection,
        state_getNextSection,
        state_processSection,
        state_syncLost
    };

    StateMachine currentState;
    StateMachine nextState;
    bool waitingForF3frame;

    QByteArray currentF3Frame;
    QVector<QByteArray> f3Section;

    qint32 frameCounter;
    qint32 missedSectionSyncCount;

    StateMachine sm_state_initial(void);
    StateMachine sm_state_getSync0(void);
    StateMachine sm_state_getSync1(void);
    StateMachine sm_state_getInitialSection(void);
    StateMachine sm_state_getNextSection(void);
    StateMachine sm_state_processSection(void);
    StateMachine sm_state_syncLost(void);
};

#endif // DECODESUBCODE_H
