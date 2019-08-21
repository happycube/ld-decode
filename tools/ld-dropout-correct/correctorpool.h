/************************************************************************

    correctorpool.h

    ld-dropout-correct - Dropout correction for ld-decode
    Copyright (C) 2018-2019 Simon Inns

    This file is part of ld-decode-tools.

    ld-dropout-correct is free software: you can redistribute it and/or
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

#ifndef CORRECTORPOOL_H
#define CORRECTORPOOL_H

#include <QObject>
#include <QAtomicInt>
#include <QByteArray>
#include <QElapsedTimer>
#include <QMutex>
#include <QThread>

#include "sourcevideo.h"
#include "lddecodemetadata.h"
#include "dropoutcorrect.h"

class CorrectorPool : public QObject
{
    Q_OBJECT
public:
    explicit CorrectorPool(QString _inputFileName, QString _outputFilename, qint32 _maxThreads, LdDecodeMetaData &_ldDecodeMetaData,
                           bool _reverse, bool _intraField, bool _overCorrect, QObject *parent = nullptr);

    bool process();

    // Member functions used by worker threads
    bool getInputFrame(qint32& frameNumber,
                       qint32& firstFieldNumber, QByteArray& firstFieldVideoData, LdDecodeMetaData::Field& firstFieldMetadata,
                       qint32& secondFieldNumber, QByteArray& secondFieldVideoData, LdDecodeMetaData::Field& secondFieldMetadata,
                       LdDecodeMetaData::VideoParameters& videoParameters,
                       bool& _reverse, bool& _intraField, bool& _overCorrect);

    bool setOutputFrame(qint32 frameNumber,
                        QByteArray firstTargetFieldData, QByteArray secondTargetFieldData,
                        qint32 firstFieldSeqNo, qint32 secondFieldSeqNo);

private:
    QString inputFilename;
    QString outputFilename;
    qint32 maxThreads;
    bool reverse;
    bool intraField;
    bool overCorrect;
    QElapsedTimer totalTimer;

    // Atomic abort flag shared by worker threads; workers watch this, and shut
    // down as soon as possible if it becomes true
    QAtomicInt abort;

    // Input stream information (all guarded by inputMutex while threads are running)
    QMutex inputMutex;
    qint32 inputFrameNumber;
    qint32 lastFrameNumber;
    LdDecodeMetaData &ldDecodeMetaData;
    SourceVideo sourceVideo;

    // Output stream information (all guarded by outputMutex while threads are running)
    QMutex outputMutex;

    struct OutputFrame {
        QByteArray firstTargetFieldData;
        QByteArray secondTargetFieldData;
        qint32 firstFieldSeqNo;
        qint32 secondFieldSeqNo;
    };

    qint32 outputFrameNumber;
    QMap<qint32, OutputFrame> pendingOutputFrames;
    QFile targetVideo;
};

#endif // CORRECTORPOOL_H
