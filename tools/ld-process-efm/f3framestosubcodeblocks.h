/************************************************************************

    f3framestosubcodeblocks.h

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

#ifndef F3FRAMESTOSUBCODEBLOCKS_H
#define F3FRAMESTOSUBCODEBLOCKS_H

#include <QCoreApplication>
#include <QDebug>

#include "f3frame.h"
#include "subcodeblock.h"

class F3FramesToSubcodeBlocks
{
public:
    F3FramesToSubcodeBlocks();

    void reportStatus(void);
    QVector<SubcodeBlock> convert(QVector<F3Frame> f3FramesIn);

private:
    // Subcode block buffer
    QVector<SubcodeBlock> subcodeBlocks;

    // F3 Frame buffer
    QVector<F3Frame> f3Frames;

    // State machine state definitions
    enum StateMachine {
        state_initial,
        state_getSync0,
        state_getSync1,
        state_getInitialBlock,
        state_getNextBlock,
        state_syncLost
    };

    StateMachine currentState;
    StateMachine nextState;
    bool waitingForF3frame;

    F3Frame currentF3Frame;

    qint32 missedBlockSyncCount;
    qint32 blockSyncLost;
    qint32 totalBlocks;
    qint32 poorSyncs;

    StateMachine sm_state_initial(void);
    StateMachine sm_state_getSync0(void);
    StateMachine sm_state_getSync1(void);
    StateMachine sm_state_getInitialBlock(void);
    StateMachine sm_state_getNextBlock(void);
    StateMachine sm_state_syncLost(void);
};

#endif // F3FRAMESTOSUBCODEBLOCKS_H
