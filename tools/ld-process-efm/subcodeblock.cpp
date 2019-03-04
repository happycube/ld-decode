/************************************************************************

    subcodeblock.cpp

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

#include "subcodeblock.h"

// Note: This class is responsible for separating F3 Frames into
// subcode blocks.  Each subcoding block requires 98 F3 Frames.
// There are 75 subcode blocks per second.
//
// Every subcode block contains 98 bytes of subcode information
// and 98 * 32 bytes of channel data
//
// Subcode block sync is provided by two sync patterns S0 and S1
// at the start of every block

SubcodeBlock::SubcodeBlock()
{
    // Initialise the state machine
    currentState = state_initial;
    nextState = currentState;

    frameCounter = 0;
    missedBlockSyncCount = 0;

    block.sync0 = false;
    block.sync1 = false;

    isBlockReady = false;
    blockSyncLost = 0;
    totalBlocks = 0;
    poorSyncs = 0;
}

// Method returns true if a block is ready
bool SubcodeBlock::blockReady(void)
{
    return isBlockReady;
}

// Method to retrieve the processed block
SubcodeBlock::Block SubcodeBlock::getBlock(void)
{
    isBlockReady = false;
    return block;
}

// Method to retrieve the number of sync losses
qint32 SubcodeBlock::getSyncLosses(void)
{
    return blockSyncLost;
}

// Method to retrieve the number of blocks processed
qint32 SubcodeBlock::getTotalBlocks(void)
{
    return totalBlocks;
}

// Method to retrieve the number of blocks with sync0 and/or sync1 missing
qint32 SubcodeBlock::getPoorSyncs(void)
{
    return poorSyncs;
}

// This method is used by higher level decodes to indicate that sync is lost
// (based on invalid data or other detectable errors)
void SubcodeBlock::forceSyncLoss(void)
{
    qDebug() << "SubcodeBlock::forceSyncLoss(): Forcing sync loss!";
    nextState = state_syncLost;
}

// State machine methods ----------------------------------------------------------------------------------------------

void SubcodeBlock::process(QByteArray f3FrameParam, QByteArray f3ErasuresParam)
{
    // Ensure the F3 frame is the correct length
    if (f3FrameParam.size() != 34) {
        qDebug() << "SubcodeBlock::process(): Invalid F3 frame passed (not 34 bytes!)";
        return;
    }

    // Copy the incoming F3 frame and erasure data
    currentF3Frame = f3FrameParam;
    currentF3Erasures = f3ErasuresParam;

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

SubcodeBlock::StateMachine SubcodeBlock::sm_state_initial(void)
{
    return state_getSync0;
}

SubcodeBlock::StateMachine SubcodeBlock::sm_state_getSync0(void)
{
    // Does the current frame contain a SYNC0 marker?
    if (currentF3Frame[0] == static_cast<char>(0x01)) {
        // Copy the subcode data from the current F3 frame into the block
        block.subcode[frameCounter] = static_cast<uchar>(currentF3Frame[1]);

        // Copy the data and erasures from the current F3 frame into the block
        for (qint32 i = 0; i < 32; i++) {
            block.data[(frameCounter * 32) + i] = static_cast<uchar>(currentF3Frame[i + 2]);
            block.erasures[(frameCounter * 32) + i] = static_cast<uchar>(currentF3Erasures[i + 2]);
        }
        block.sync0 = true;

        frameCounter++;
        waitingForF3frame = true;
        return state_getSync1;
    }

    // No SYNC0, discard current frame
    frameCounter = 0;
    block.sync0 = false;
    waitingForF3frame = true;

    return state_getSync0;
}

SubcodeBlock::StateMachine SubcodeBlock::sm_state_getSync1(void)
{
    // Does the current F3 frame contain a SYNC1 marker?
    if (currentF3Frame[0] == static_cast<char>(0x02)) {
        // Copy the subcode data from the current F3 frame into the block
        block.subcode[frameCounter] = static_cast<uchar>(currentF3Frame[1]);

        // Copy the data and erasures from the current F3 frame into the block
        for (qint32 i = 0; i < 32; i++) {
            block.data[(frameCounter * 32) + i] = static_cast<uchar>(currentF3Frame[i + 2]);
            block.erasures[(frameCounter * 32) + i] = static_cast<uchar>(currentF3Erasures[i + 2]);
        }
        block.sync1 = true;

        frameCounter++;
        waitingForF3frame = true;
        return state_getInitialBlock;
    }

    // No SYNC1, discard current frames and go back to looking for a SYNC0
    frameCounter = 0;
    block.sync1 = false;
    waitingForF3frame = true;

    return state_getSync0;
}

SubcodeBlock::StateMachine SubcodeBlock::sm_state_getInitialBlock(void)
{
    // Copy the subcode data from the current F3 frame into the block
    block.subcode[frameCounter] = static_cast<uchar>(currentF3Frame[1]);

    // Copy the data and erasures from the current F3 frame into the block
    for (qint32 i = 0; i < 32; i++) {
        block.data[(frameCounter * 32) + i] = static_cast<uchar>(currentF3Frame[i + 2]);
        block.erasures[(frameCounter * 32) + i] = static_cast<uchar>(currentF3Erasures[i + 2]);
    }

    frameCounter++;

    // If we have 98 frames, the section is complete, process it
    if (frameCounter == 98) {
        isBlockReady = true;
        totalBlocks++;
        frameCounter = 0;
        waitingForF3frame = true;
        return state_getNextBlock;
    }

    // Need more frames to complete section
    waitingForF3frame = true;
    return state_getInitialBlock;
}

SubcodeBlock::StateMachine SubcodeBlock::sm_state_getNextBlock(void)
{
    // Copy the subcode data from the current F3 frame into the block
    block.subcode[frameCounter] = static_cast<uchar>(currentF3Frame[1]);

    // Copy the data and erasures from the current F3 frame into the block
    for (qint32 i = 0; i < 32; i++) {
        block.data[(frameCounter * 32) + i] = static_cast<uchar>(currentF3Frame[i + 2]);
        block.erasures[(frameCounter * 32) + i] = static_cast<uchar>(currentF3Erasures[i + 2]);
    }

    // Check for sync markers
    if (frameCounter == 0) {
        if (currentF3Frame[0] == static_cast<char>(0x01)) block.sync0 = true; else block.sync0 = false;
    }
    if (frameCounter == 1) {
        if (currentF3Frame[0] == static_cast<char>(0x02)) block.sync1 = true; else block.sync1 = false;
    }

    frameCounter++;

    // If we have 2 frames in the current block, check the sync pattern
    if (frameCounter == 2) {
        if (block.sync0 && block.sync1) {
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

    // If we have 98 frames, the section is complete, process it
    if (frameCounter == 98) {
        isBlockReady = true;
        totalBlocks++;
        frameCounter = 0;
        waitingForF3frame = true;
        return state_getNextBlock;
    }

    // Need more frames to complete the block
    waitingForF3frame = true;
    return state_getNextBlock;
}

SubcodeBlock::StateMachine SubcodeBlock::sm_state_syncLost(void)
{
    qDebug() << "SubcodeBlock::sm_state_syncLost(): Subcode block sync has been lost!";
    blockSyncLost++;

    // Discard all F3 frames
    frameCounter = 0;
    block.sync0 = false;
    block.sync1 = false;

    // Return to looking for initial SYNC0
    return state_getSync0;
}
