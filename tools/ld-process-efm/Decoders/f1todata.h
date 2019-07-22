/************************************************************************

    f1todata.h

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

#ifndef F1TOSECTORS_H
#define F1TOSECTORS_H

#include <QCoreApplication>
#include <QDebug>

#include "Datatypes/f1frame.h"
#include "Datatypes/sector.h"

class F1ToData
{
public:
    F1ToData();

    struct Statistics {
        qint32 validSectors;
        qint32 invalidSectors;
        qint32 totalSectors;

        TrackTime startAddress;
        TrackTime currentAddress;
    };

    QByteArray process(QVector<F1Frame> f1FramesIn, bool debugState);

    Statistics getStatistics();
    void reportStatistics();
    void reset();
    void clearStatistics();

private:
    bool debugOn;
    Statistics statistics;

    QVector<F1Frame> f1FrameBuffer;
    QByteArray dataOutputBuffer;
    bool waitingForData;

    // State-machine variables
    enum StateMachine {
        state_initial,
        state_getSync,
        state_processFrame
    };

    StateMachine currentState;
    StateMachine nextState;

    StateMachine sm_state_initial();
    StateMachine sm_state_getSync();
    StateMachine sm_state_processFrame();
};

#endif // F1TOSECTORS_H
