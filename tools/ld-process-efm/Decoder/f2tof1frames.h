/************************************************************************

    f2tof1frames.h

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

#ifndef F2TOF1FRAMES_H
#define F2TOF1FRAMES_H

#include <QCoreApplication>
#include <QDebug>

#include "f2frame.h"
#include "f1frame.h"

class F2ToF1Frames
{
public:
    F2ToF1Frames();

    void reportStatus(void);
    QVector<F1Frame> convert(QVector<F2Frame> f2FramesIn);

private:
    // This is the F1 frame sync pattern
    QByteArray syncPattern;

    // F1 frame buffer
    QVector<F1Frame> f1FrameBuffer;

    // F1 data buffer
    QByteArray f2DataBuffer;
    QByteArray f2ErrorBuffer;

    // State machine state definitions
    enum StateMachine {
        state_initial,
        state_getInitialSync,
        state_getInitialF1Frame,
        state_getNextF1Frame,
        state_syncLost
    };

    StateMachine currentState;
    StateMachine nextState;
    bool waitingForF2frames;

    F2Frame currentF2Frame;

    qint32 missedF1SyncCount;
    qint32 F1SyncLost;
    qint32 totalF1Frames;
    qint32 poorSyncs;

    StateMachine sm_state_initial(void);
    StateMachine sm_state_getInitialSync(void);
    StateMachine sm_state_getInitialF1Frame(void);
    StateMachine sm_state_getNextF1Frame(void);
    StateMachine sm_state_syncLost(void);

    void removeF2Data(qint32 number);
};

#endif // F2TOF1FRAMES_H
