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

#include "f3tosections.h"

F3ToSections::F3ToSections()
{
    // Initialise the state machine
    currentState = state_initial;
    nextState = currentState;

    missedSectionSyncCount = 0;
    sectionSyncLost = 0;
    poorSyncs = 0;
    totalSections = 0;

    // Clear the sync flags
    sync0 = false;
    sync1 = false;
}

// Method to write status information to qInfo
void F3ToSections::reportStatus(void)
{
    qInfo() << "F3 to section converter:";
    qInfo() << "  Total number of sections =" << totalSections;
    qInfo() << "  Number of sections with SYNC0 or SYNC1 missing =" << poorSyncs;
    qInfo() << "  Lost section sync" << sectionSyncLost << "times";
}

// Convert the F3 frames into sections
// Note: this method is reentrant - any unused F3 frames are
// stored by the class and used in addition to the passed
// F3 frames to ensure no data is lost between conversion calls
QVector<Section> F3ToSections::convert(QVector<F3Frame> f3FramesIn)
{
    // Clear any existing sections from the buffer
    sections.clear();

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
            case state_getInitialSection:
                nextState = sm_state_getInitialSection();
                break;
            case state_getNextSection:
                nextState = sm_state_getNextSection();
                break;
            case state_syncLost:
                nextState = sm_state_syncLost();
                break;
            }
        }
    }

    return sections;
}

F3ToSections::StateMachine F3ToSections::sm_state_initial(void)
{
    sectionBuffer.clear();

    // Clear the sync flags
    sync0 = false;
    sync1 = false;

    return state_getSync0;
}

F3ToSections::StateMachine F3ToSections::sm_state_getSync0(void)
{
    // Does the current frame contain a SYNC0 marker?
    if (currentF3Frame.isSubcodeSync0()) {
        // Place the current subcode symbol into the section buffer
        sectionBuffer.append(static_cast<char>(currentF3Frame.getSubcodeSymbol()));

        waitingForF3frame = true;
        return state_getSync1;
    }

    // No SYNC0, discard the section buffer
    sectionBuffer.clear();

    // Clear the sync flags
    sync0 = false;
    sync1 = false;

    waitingForF3frame = true;

    return state_getSync0;
}

F3ToSections::StateMachine F3ToSections::sm_state_getSync1(void)
{
    // Does the current F3 frame contain a SYNC1 marker?
    if (currentF3Frame.isSubcodeSync1()) {
        // Place the current subcode symbol into the section buffer
        sectionBuffer.append(static_cast<char>(currentF3Frame.getSubcodeSymbol()));

        waitingForF3frame = true;
        return state_getInitialSection;
    }

    // No SYNC1, discard current frames and go back to looking for a SYNC0
    sectionBuffer.clear();

    // Clear the sync flags
    sync0 = false;
    sync1 = false;

    waitingForF3frame = true;

    return state_getSync0;
}

F3ToSections::StateMachine F3ToSections::sm_state_getInitialSection(void)
{
    // Place the current subcode symbol into the section buffer
    sectionBuffer.append(static_cast<char>(currentF3Frame.getSubcodeSymbol()));

    // If we have 98 subcode symbols, the section is complete
    if (sectionBuffer.size() == 98) {
        // Create a section using the buffered symbols
        Section newSubcodeBlock;
        newSubcodeBlock.setData(sectionBuffer);
        sections.append(newSubcodeBlock);
        totalSections++;
        //qDebug() << "F3ToSections::sm_state_getInitialBlock(): Got initial section";

        // Discard current section buffer
        sectionBuffer.clear();

        // Clear the sync flags
        sync0 = false;
        sync1 = false;

        waitingForF3frame = true;
        return state_getNextSection;
    }

    // Need more frames to complete section
    waitingForF3frame = true;
    return state_getInitialSection;
}

F3ToSections::StateMachine F3ToSections::sm_state_getNextSection(void)
{
    // Place the current subcode symbol into the section buffer
    sectionBuffer.append(static_cast<char>(currentF3Frame.getSubcodeSymbol()));

    // Check for sync symbols
    if (sectionBuffer.size() == 1) {
        if (currentF3Frame.isSubcodeSync0()) sync0 = true;
    }

    if (sectionBuffer.size() == 2) {
        if (currentF3Frame.isSubcodeSync1()) sync1 = true;
    }

    // If we have 2 frames in the section buffer, check the sync pattern
    if (sectionBuffer.size() == 2) {
        if (sync0 && sync1) {
            missedSectionSyncCount = 0;
        } else {
            missedSectionSyncCount++;
            poorSyncs++;

            // If we have missed 4 syncs in a row, consider the sync as lost
            if (missedSectionSyncCount == 4) {
                missedSectionSyncCount = 0;
                return state_syncLost;
            }
        }
    }

    // If we have 98 symbols, the section is complete
    if (sectionBuffer.size() == 98) {
        // Create a section using the buffered symbols
        Section newSubcodeBlock;
        newSubcodeBlock.setData(sectionBuffer);
        sections.append(newSubcodeBlock);
        totalSections++;

        // Discard current section buffer
        sectionBuffer.clear();

        // Clear the sync flags
        sync0 = false;
        sync1 = false;

        waitingForF3frame = true;
        return state_getNextSection;
    }

    // Need more frames to complete the block
    waitingForF3frame = true;
    return state_getNextSection;
}

F3ToSections::StateMachine F3ToSections::sm_state_syncLost(void)
{
    qDebug() << "F3ToSections::sm_state_syncLost(): Section sync has been lost!";
    sectionSyncLost++;

    // Discard all section subcode symbols
    sectionBuffer.clear();

    // Clear the sync flags
    sync0 = false;
    sync1 = false;

    // Return to looking for initial SYNC0
    return state_getSync0;
}
