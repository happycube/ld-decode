/************************************************************************

    efmtof3frames.h

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

#ifndef EFMTOF3FRAMES_H
#define EFMTOF3FRAMES_H

#include <QCoreApplication>
#include <QDebug>
#include <QFile>
#include <QDataStream>

#include "Datatypes/f3frame.h"

class EfmToF3Frames
{
public:
    EfmToF3Frames();

    // Statistics
    struct Statistics {
        qint32 undershootSyncs;
        qint32 validSyncs;
        qint32 overshootSyncs;
        qint32 syncLoss;

        qint32 undershootFrames;
        qint32 validFrames;
        qint32 overshootFrames;

        qint32 validTValues;
        qint32 invalidTValues;
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
    QByteArray efmDataBuffer;
    void clearStatistics(void);

    // State machine state definitions
    enum StateMachine {
        state_initial,
        state_findInitialSyncStage1,
        state_findInitialSyncStage2,
        state_findSecondSync,
        state_syncLost,
        state_processFrame
    };

    StateMachine currentState;
    StateMachine nextState;
    bool waitingForData;

    qint32 sequentialBadSyncCounter;
    qint32 endSyncTransition;

    StateMachine sm_state_initial(void);
    StateMachine sm_state_findInitialSyncStage1(void);
    StateMachine sm_state_findInitialSyncStage2(void);
    StateMachine sm_state_findSecondSync(void);
    StateMachine sm_state_syncLost(void);
    StateMachine sm_state_processFrame(QDataStream *outputDataStream);

    void removeEfmData(qint32 number);
};

#endif // EFMTOF3FRAMES_H
