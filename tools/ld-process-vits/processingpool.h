/************************************************************************

    processingpool.cpp

    ld-process-vits - Vertical Interval Test Signal processing
    Copyright (C) 2020 Simon Inns

    This file is part of ld-decode-tools.

    ld-process-vits is free software: you can redistribute it and/or
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

#ifndef PROCESSINGPOOL_H
#define PROCESSINGPOOL_H

#include <QAtomicInt>
#include <QElapsedTimer>
#include <QMutex>
#include <QThread>

#include "sourcevideo.h"
#include "lddecodemetadata.h"
#include "vitsanalyser.h"

class ProcessingPool
{
public:
    explicit ProcessingPool(QString _inputFilename, QString _outputJsonFilename,
                        qint32 _maxThreads, LdDecodeMetaData &_ldDecodeMetaData);
    bool process();

    // Member functions used by worker threads
    bool getInputField(qint32 &fieldNumber, SourceVideo::Data &fieldVideoData, LdDecodeMetaData::Field &fieldMetadata, LdDecodeMetaData::VideoParameters &videoParameters);
    bool setOutputField(qint32 fieldNumber, LdDecodeMetaData::Field fieldMetadata);

private:
    QString inputFilename;
    QString outputJsonFilename;
    qint32 maxThreads;
    QElapsedTimer totalTimer;

    // Atomic abort flag shared by worker threads; workers watch this, and shut
    // down as soon as possible if it becomes true
    QAtomicInt abort;

    // Input stream information (all guarded by inputMutex while threads are running)
    QMutex inputMutex;
    qint32 inputFieldNumber;
    qint32 lastFieldNumber;
    LdDecodeMetaData &ldDecodeMetaData;
    SourceVideo sourceVideo;

    // Output stream information (all guarded by outputMutex while threads are running)
    QMutex outputMutex;
    QFile targetJson;
};

#endif // PROCESSINGPOOL_H
