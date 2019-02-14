/************************************************************************

    efmprocess.cpp

    ld-efm-decodedata - EFM data decoder for ld-decode
    Copyright (C) 2019 Simon Inns

    This file is part of ld-decode-tools.

    ld-efm-decodedata is free software: you can redistribute it and/or
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

#include "efmprocess.h"

EfmProcess::EfmProcess()
{

}

bool EfmProcess::process(QString inputFilename, QString outputFilename)
{
    (void) outputFilename;

    // Open the input F3 data file
    if (!openInputF3File(inputFilename)) {
        qCritical() << "Could not open F3 data input file!";
        return false;
    }

    // Perform the actual processing
    processStateMachine();

    // Close the input F3 data file
    closeInputF3File();
    return true;
}

// Method to open the input F3 data file for reading
bool EfmProcess::openInputF3File(QString filename)
{
    // Open the input file
    inputFile = new QFile(filename);
    if (!inputFile->open(QIODevice::ReadOnly)) {
        // Failed to open input file
        qDebug() << "EfmProcess::openInputSampleFile(): Could not open " << filename << "as sampled EFM input file";
        return false;
    }

    return true;
}

// Method to close the input F3 data file
void EfmProcess::closeInputF3File(void)
{
    // Close the input file
    inputFile->close();
}

// Method to read F3 frames from the input file
QByteArray EfmProcess::readF3Frames(qint32 numberOfFrames)
{
    QByteArray f3FrameData;

    qint32 bytesToRead = numberOfFrames * 34; // Each F3 frame is 34 bytes (1 sync indicator and 33 real bytes)
    f3FrameData.resize(bytesToRead);

    qint64 bytesRead = inputFile->read(f3FrameData.data(), bytesToRead);

    if (bytesRead != bytesToRead) {
        qDebug() << "EfmProcess::readF3Frames(): Ran out of input data";
        f3FrameData.clear();
    }

    return f3FrameData;
}

// Method to open the output data file for writing
bool EfmProcess::openOutputDataFile(QString filename)
{
    // Open the output file
    outputFile = new QFile(filename);
    if (!outputFile->open(QIODevice::WriteOnly)) {
        // Failed to open output file
        qDebug() << "EfmProcess::openOutputDataFile(): Could not open " << filename << "as output data file";
        return false;
    }

    return true;
}

// Method to close the output data file
void EfmProcess::closeOutputDataFile(void)
{
    // Close the output file
    outputFile->close();
}

void EfmProcess::processStateMachine(void)
{
    // Initialise the state machine
    currentState = state_initial;
    nextState = currentState;

    missedSectionSyncCount = 0;

    while (currentState != state_complete) {
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
        case state_processSection:
            nextState = sm_state_processSection();
            break;
        case state_syncLost:
            nextState = sm_state_syncLost();
            break;
        case state_complete:
            nextState = sm_state_complete();
            break;
        }
    }
}

EfmProcess::StateMachine EfmProcess::sm_state_initial(void)
{
    qDebug() << "Current state: sm_state_initial";
    return state_getSync0;
}

EfmProcess::StateMachine EfmProcess::sm_state_getSync0(void)
{
    //qDebug() << "Current state: sm_state_getSync0";

    // Read a F3 frame
    f3FrameSync0 = readF3Frames(1);
    if (f3FrameSync0.isEmpty()) return state_complete;

    // Is it a SYNC0?
    if (f3FrameSync0[0] == static_cast<char>(0x01)) {
        qDebug() << "EfmProcess::sm_state_getSync0(): SYNC0 found";
        return state_getSync1;
    }

    return state_getSync0;
}

EfmProcess::StateMachine EfmProcess::sm_state_getSync1(void)
{
    qDebug() << "Current state: sm_state_getSync1";

    // Read a F3 frame
    f3FrameSync1 = readF3Frames(1);
    if (f3FrameSync1.isEmpty()) return state_complete;

    // Is it a SYNC0?
    if (f3FrameSync1[0] == static_cast<char>(0x02)) {
        qDebug() << "EfmProcess::sm_state_getSync1(): SYNC1 found";
        return state_getInitialSection;
    }

    return state_getSync0;
}

EfmProcess::StateMachine EfmProcess::sm_state_getInitialSection(void)
{
    qDebug() << "Current state: sm_state_getInitialSection";

    // Since we've already read two F3 frames looking for the sync, we
    // need to construct the initial section using the two F3 frames
    // that have been read already
    f3Section.clear();
    f3Section.append(f3FrameSync0);
    f3Section.append(f3FrameSync1);

    // Read the rest of the section (sync0, sync1 and then 96 bytes)
    f3Section.append(readF3Frames(96));
    if (f3Section.size() != (98 * 34)) {
        qDebug() << "EfmProcess::sm_state_getInitialSection(): Couldn't get complete section, size was" <<
                    f3Section.size() << "bytes";
        return state_complete;
    }

    return state_processSection;
}

EfmProcess::StateMachine EfmProcess::sm_state_getNextSection(void)
{
    //qDebug() << "Current state: sm_state_getNextSection";

    // Read the next frame
    f3Section = readF3Frames(98);
    if (f3Section.size() != (98 * 34)) {
        qDebug() << "EfmProcess::sm_state_getNextSection(): Couldn't get complete section, size was" <<
                    f3Section.size() << "bytes";
        return state_complete;
    }

    // Check for sync
    if (f3Section[0] == static_cast<char>(0x01) && f3Section[34] == static_cast<char>(0x02)) {
        qDebug() << "EfmProcess::sm_state_getNextSection(): Section SYNC0 and SYNC1 are valid";
        missedSectionSyncCount = 0;
    } else {
        if (f3Section[0] == static_cast<char>(0x01)) {
            qDebug() << "EfmProcess::sm_state_getNextSection(): Only SYNC0 is valid for the section";
            missedSectionSyncCount = 0;
        } else if (f3Section[34] == static_cast<char>(0x02)) {
            qDebug() << "EfmProcess::sm_state_getNextSection(): Only SYNC1 is valid for the section";
            missedSectionSyncCount = 0;
        } else {
            qDebug() << "EfmProcess::sm_state_getNextSection(): Section does not have valid sync";
            missedSectionSyncCount++;
        }
    }

    // If we've completely missed two syncs in a row, change to the lost sync state
    if (missedSectionSyncCount == 2) {
        return state_syncLost;
    }

    return state_processSection;
}

EfmProcess::StateMachine EfmProcess::sm_state_processSection(void)
{
    //qDebug() << "Current state: sm_state_processSection";

    qint32 pCount = 0;
    qint32 qCount = 0;

    for (qint32 count = 0; count < 98; count++) {
        if (f3Section[(count * 34) + 1] & 0x80) pCount++;
        if (f3Section[(count * 34) + 1] & 0x40) qCount++;
    }

    qDebug() << "EfmProcess::sm_state_processSection(): Q =" << qCount << "P =" << pCount;

    return state_getNextSection;
}

EfmProcess::StateMachine EfmProcess::sm_state_syncLost(void)
{
    qDebug() << "Current state: sm_state_syncLost";
    return state_getSync0;
}

EfmProcess::StateMachine EfmProcess::sm_state_complete(void)
{
    qDebug() << "Current state: sm_state_complete";
    return state_complete;
}




