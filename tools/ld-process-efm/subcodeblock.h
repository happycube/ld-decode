/************************************************************************

    subcodeblock.h

    ld-process-efm - EFM data decoder
    Copyright (C) 2019 Simon Inns

    This file is part of ld-decode-tools.

    ld-ldstoefm is free software: you can redistribute it and/or
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

#ifndef SUBCODEBLOCK_H
#define SUBCODEBLOCK_H

#include <QCoreApplication>
#include <QDebug>

class SubcodeBlock
{
public:
    SubcodeBlock();

    struct Block {
        uchar subcode[98];       // 98 bytes
        uchar data[32 * 98];     // 3136 bytes
        uchar erasures[32 * 98]; // 3136 bytes

        bool sync0;
        bool sync1;
    };

    bool blockReady(void);
    Block getBlock(void);
    qint32 getSyncLosses(void);
    qint32 getTotalBlocks(void);
    qint32 getPoorSyncs(void);
    void forceSyncLoss(void);
    void process(QByteArray f3FrameParam, QByteArray f3ErasuresParam);

private:
    Block block;

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

    QByteArray currentF3Frame;
    QByteArray currentF3Erasures;

    qint32 frameCounter;
    qint32 missedBlockSyncCount;
    bool isBlockReady;

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

#endif // SUBCODEBLOCK_H
