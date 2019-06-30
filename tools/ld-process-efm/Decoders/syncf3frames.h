/************************************************************************

    syncf3frames.cpp

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

#ifndef SYNCF3FRAMES_H
#define SYNCF3FRAMES_H

#include <QCoreApplication>
#include <QDebug>
#include <QFile>
#include <QDataStream>

#include "Datatypes/f3frame.h"

class SyncF3Frames
{
public:
    SyncF3Frames();

    // Statistics
    struct Statistics {
        qint32 totalF3Frames;
        qint32 discardedFrames;
        qint32 totalSections;
    };

    void startProcessing(QFile *inputFileHandle, QFile *outputFileHandle);
    void stopProcessing(void);
    Statistics getStatistics(void);
    void reportStatistics(void);
    void reset(void);

private:
    bool debugOn;
    bool abort;
    Statistics statistics;
    QVector<F3Frame> f3FrameBuffer;
    bool waitingForData;

    void clearStatistics(void);

    // State machine state definitions
    enum StateMachine {
        state_initial,
        state_findInitialSync0,
        state_findNextSync,
        state_syncLost,
        state_processSection
    };

    StateMachine currentState;
    StateMachine nextState;

    StateMachine sm_state_initial(void);
    StateMachine sm_state_findInitialSync0(void);
    StateMachine sm_state_findNextSync(void);
    StateMachine sm_state_syncLost(void);
    StateMachine sm_state_processSection(QDataStream *outputDataStream);
};

#endif // SYNCF3FRAMES_H
