/************************************************************************

    f3tosections.cpp

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

#ifndef F3TOSECTIONS_H
#define F3TOSECTIONS_H

#include <QCoreApplication>
#include <QDebug>

#include "f3frame.h"
#include "section.h"

class F3ToSections
{
public:
    F3ToSections();

    void reset(void);
    void resetStatistics(void);
    void reportStatus(void);
    QVector<Section> convert(QVector<F3Frame> f3FramesIn);

private:
    // Section buffer
    QVector<Section> sections;

    // Section subcode buffer
    QByteArray sectionBuffer;

    // State machine state definitions
    enum StateMachine {
        state_initial,
        state_getSync0,
        state_getSync1,
        state_getInitialSection,
        state_getNextSection,
        state_syncLost
    };

    StateMachine currentState;
    StateMachine nextState;
    bool waitingForF3frame;

    F3Frame currentF3Frame;
    bool sync0;
    bool sync1;

    qint32 missedSectionSyncCount;
    qint32 sectionSyncLost;
    qint32 totalSections;
    qint32 poorSyncs;

    StateMachine sm_state_initial(void);
    StateMachine sm_state_getSync0(void);
    StateMachine sm_state_getSync1(void);
    StateMachine sm_state_getInitialSection(void);
    StateMachine sm_state_getNextSection(void);
    StateMachine sm_state_syncLost(void);
};

#endif // F3TOSECTIONS_H
