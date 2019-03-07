/************************************************************************

    f3framestosubcodeblocks.cpp

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

#include "f3framestosubcodeblocks.h"

F3FramesToSubcodeBlocks::F3FramesToSubcodeBlocks()
{
    // Initialise the state machine
    currentState = state_initial;
    nextState = currentState;

    missedBlockSyncCount = 0;
    blockSyncLost = 0;
    poorSyncs = 0;
    totalBlocks = 0;
}

// Method to write status information to qInfo
void F3FramesToSubcodeBlocks::reportStatus(void)
{
    qInfo() << "F3 to subcode block converter:";
    qInfo() << "  Total number of subcode blocks =" << totalBlocks;
    qInfo() << "  Number of blocks with SYNC0 or SYNC1 missing =" << poorSyncs;
    qInfo() << "  Lost subcode block sync" << blockSyncLost << "times";
}

// Convert the F3 frames into subcode blocks
// Note: this method is reentrant - any unused F3 frames are
// stored by the class and used in addition to the passed
// F3 frames to ensure no data is lost between conversion calls
QVector<SubcodeBlock> F3FramesToSubcodeBlocks::convert(QVector<F3Frame> f3FramesIn)
{
    // Clear any existing subcode blocks from the buffer
    subcodeBlocks.clear();

    // Process all of the passed F3 frames
    for (qint32 i = 0; i < f3FramesIn.size(); i++) {
        currentF3Frame = f3FramesIn[i];

        // Since we have a new F3 frame, clear the waiting flag
        waitingForF3frame = false;

        // Process the state machine until another F3 frame is required
        while (!waitingForF3frame) {
            currentState = nextState;

            switch (currentState) {
            case state_initial:
                nextState = sm_state_initial();
                break;
            case state_getSync0:
                nextState = sm_state_getSync0();
                break;
            case state_getSync1:
                nextState = sm_state_getSync1();
                break;
            case state_getInitialBlock:
                nextState = sm_state_getInitialBlock();
                break;
            case state_getNextBlock:
                nextState = sm_state_getNextBlock();
                break;
            case state_syncLost:
                nextState = sm_state_syncLost();
                break;
            }
        }
    }

    return subcodeBlocks;
}

F3FramesToSubcodeBlocks::StateMachine F3FramesToSubcodeBlocks::sm_state_initial(void)
{
    f3Frames.clear();
    return state_getSync0;
}

F3FramesToSubcodeBlocks::StateMachine F3FramesToSubcodeBlocks::sm_state_getSync0(void)
{
    // Does the current frame contain a SYNC0 marker?
    if (currentF3Frame.isSubcodeSync0()) {
        // Place the current frame into the block frame buffer
        f3Frames.append(currentF3Frame);

        waitingForF3frame = true;
        return state_getSync1;
    }

    // No SYNC0, discard the current frames
    f3Frames.clear();
    waitingForF3frame = true;

    return state_getSync0;
}

F3FramesToSubcodeBlocks::StateMachine F3FramesToSubcodeBlocks::sm_state_getSync1(void)
{
    // Does the current F3 frame contain a SYNC1 marker?
    if (currentF3Frame.isSubcodeSync1()) {
        // Place the current frame into the block frame buffer
        f3Frames.append(currentF3Frame);

        waitingForF3frame = true;
        return state_getInitialBlock;
    }

    // No SYNC1, discard current frames and go back to looking for a SYNC0
    f3Frames.clear();
    waitingForF3frame = true;

    return state_getSync0;
}

F3FramesToSubcodeBlocks::StateMachine F3FramesToSubcodeBlocks::sm_state_getInitialBlock(void)
{
    // Place the current frame into the block frame buffer
    f3Frames.append(currentF3Frame);

    // If we have 98 frames, the block is complete
    if (f3Frames.size() == 98) {
        // Create a subcode block using the buffered F3 Frames
        SubcodeBlock newSubcodeBlock;
        newSubcodeBlock.setF3Frames(f3Frames);
        newSubcodeBlock.setFirstAfterSync(true);
        subcodeBlocks.append(newSubcodeBlock);
        totalBlocks++;
        //qDebug() << "F3FramesToSubcodeBlocks::sm_state_getInitialBlock(): Got initial subcode block";

        // Discard current block frames get the next block
        f3Frames.clear();
        waitingForF3frame = true;
        return state_getNextBlock;
    }

    // Need more frames to complete section
    waitingForF3frame = true;
    return state_getInitialBlock;
}

F3FramesToSubcodeBlocks::StateMachine F3FramesToSubcodeBlocks::sm_state_getNextBlock(void)
{
    // Place the current frame into the block frame buffer
    f3Frames.append(currentF3Frame);

    // If we have 2 frames in the current block, check the sync pattern
    if (f3Frames.size() == 2) {
        if (f3Frames[0].isSubcodeSync0() && f3Frames[1].isSubcodeSync1()) {
            //qDebug() << "SubcodeBlock::sm_state_getNextSection(): Section SYNC0 and SYNC1 are valid";
            missedBlockSyncCount = 0;
        } else {
            missedBlockSyncCount++;
            poorSyncs++;
            //qDebug() << "SubcodeBlock::sm_state_getNextBlock(): Section SYNC0 and/or SYNC1 are INVALID - missed sync #" << missedBlockSyncCount;

            // If we have missed 4 syncs in a row, consider the sync as lost
            if (missedBlockSyncCount == 4) {
                missedBlockSyncCount = 0;
                return state_syncLost;
            }
        }
    }

    // If we have 98 frames, the block is complete
    if (f3Frames.size() == 98) {
        // Create a subcode block using the buffered F3 Frames
        SubcodeBlock newSubcodeBlock;
        newSubcodeBlock.setF3Frames(f3Frames);
        newSubcodeBlock.setFirstAfterSync(false);
        subcodeBlocks.append(newSubcodeBlock);
        totalBlocks++;
        //qDebug() << "F3FramesToSubcodeBlocks::sm_state_getInitialBlock(): Got subcode block";

        // Discard current block frames get the next block
        f3Frames.clear();
        waitingForF3frame = true;
        return state_getNextBlock;
    }

    // Need more frames to complete the block
    waitingForF3frame = true;
    return state_getNextBlock;
}

F3FramesToSubcodeBlocks::StateMachine F3FramesToSubcodeBlocks::sm_state_syncLost(void)
{
    qDebug() << "SubcodeBlock::sm_state_syncLost(): Subcode block sync has been lost!";
    blockSyncLost++;

    // Discard all F3 frames
    f3Frames.clear();

    // Return to looking for initial SYNC0
    return state_getSync0;
}
