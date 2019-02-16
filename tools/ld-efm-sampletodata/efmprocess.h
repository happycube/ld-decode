/************************************************************************

    efmprocess.cpp

    ld-efm-sampletodata - EFM sample to data processor for ld-decode
    Copyright (C) 2019 Simon Inns

    This file is part of ld-decode-tools.

    ld-efm-sampletodata is free software: you can redistribute it and/or
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

#include "filter.h"
#include "efmdecoder.h"

class EfmProcess
{
public:
    EfmProcess();

    bool process(QString inputFilename, QString outputFilename, qint32 maxF3Param, bool verboseDecodeParam);

private:
    QFile* inputFile;
    QFile* outputFile;

    Filter filter;
    EfmDecoder efmDecoder;

    qint32 maxF3;
    bool verboseDecode;

    // State machine state definitions
    enum StateMachine {
        state_initial,
        state_getDataFirstSync,
        state_getDataSecondSync,
        state_findFirstSync,
        state_findSecondSync,
        state_processFrame,
        state_complete
    };

    StateMachine currentState;
    StateMachine nextState;

    QVector<qint16> inputBuffer;
    QVector<qint16> windowedBuffer;
    QVector<qreal> zcDeltas;
    qreal minimumFrameWidthInSamples;
    qreal lastFrameWidth;
    qint32 endSyncTransition;
    qint32 frameCounter;

    void processStateMachine(void);
    StateMachine sm_state_initial(void);
    StateMachine sm_state_getDataFirstSync(void);
    StateMachine sm_state_getDataSecondSync(void);
    StateMachine sm_state_findFirstSync(void);
    StateMachine sm_state_findSecondSync(void);
    StateMachine sm_state_processFrame(void);
    StateMachine sm_state_complete(void);

    bool openInputSampleFile(QString filename);
    void closeInputSampleFile(void);
    bool openOutputDataFile(QString filename);
    void closeOutputDataFile(void);

    QVector<qreal> zeroCrossDetection(QVector<qint16> inputBuffer, QVector<qreal> &zcDeltas, qint32 &usedSamples);
    qreal estimateInitialFrameWidth(QVector<qreal> zcDeltas);
    qint32 findSyncTransition(qreal approximateFrameWidth);
    void removeZcDeltas(qint32 number);
    bool fillWindowedBuffer(void);
};

#endif // EFMPROCESS_H
