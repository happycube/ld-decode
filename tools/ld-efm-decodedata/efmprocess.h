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

#ifndef EFMPROCESS_H
#define EFMPROCESS_H

#include <QCoreApplication>
#include <QDebug>
#include <QFile>
#include <QDataStream>

class EfmProcess
{
public:
    EfmProcess();

    bool process(QString inputFilename, QString outputFilename);

private:
    QFile* inputFile;
    QFile* outputFile;

    // State machine state definitions
    enum StateMachine {
        state_initial,
        state_getSync0,
        state_getSync1,
        state_getInitialSection,
        state_getNextSection,
        state_processSection,
        state_syncLost,
        state_complete
    };

    StateMachine currentState;
    StateMachine nextState;

    QByteArray f3FrameSync0;
    QByteArray f3FrameSync1;
    QByteArray f3Section;

    qint32 missedSectionSyncCount;

    bool openInputF3File(QString filename);
    void closeInputF3File(void);
    QByteArray readF3Frames(qint32 numberOfFrames);
    bool openOutputDataFile(QString filename);
    void closeOutputDataFile(void);

    void processStateMachine(void);
    StateMachine sm_state_initial(void);
    StateMachine sm_state_getSync0(void);
    StateMachine sm_state_getSync1(void);
    StateMachine sm_state_getInitialSection(void);
    StateMachine sm_state_getNextSection(void);
    StateMachine sm_state_processSection(void);
    StateMachine sm_state_syncLost(void);
    StateMachine sm_state_complete(void);

    quint16 crc16(char *addr, quint16 num);

};

#endif // EFMPROCESS_H
