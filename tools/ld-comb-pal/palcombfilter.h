/************************************************************************

    palcombfilter.h

    ld-comb-pal - PAL colourisation filter for ld-decode
    Copyright (C) 2018-2019 Simon Inns

    This file is part of ld-decode-tools.

    ld-comb-pal is free software: you can redistribute it and/or
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

#ifndef PALCOMBFILTER_H
#define PALCOMBFILTER_H

#include <QObject>
#include <QAtomicInt>
#include <QByteArray>
#include <QElapsedTimer>
#include <QMap>
#include <QMutex>

#include "sourcevideo.h"
#include "lddecodemetadata.h"
#include "filterthread.h"

class PalCombFilter : public QObject
{
    Q_OBJECT
public:
    explicit PalCombFilter(QObject *parent = nullptr);
    bool process(QString inputFileName, QString outputFileName, qint32 startFrame, qint32 length, bool reverse, bool blackAndWhite, qint32 maxThreads);

    // Member functions used by worker threads
    bool getInputFrame(qint32& frameNumber, QByteArray& firstField, QByteArray& secondField, qreal& burstMedianIre);
    bool putOutputFrame(qint32 frameNumber, QByteArray& rgbOutput);

signals:

public slots:

private slots:

private:
    // Atomic abort flag shared by worker threads; workers watch this, and shut
    // down as soon as possible if it becomes true
    QAtomicInt abort;

    // Input stream information (all guarded by inputMutex while threads are running)
    QMutex inputMutex;
    qint32 inputFrameNumber;
    qint32 lastFrameNumber;
    LdDecodeMetaData ldDecodeMetaData;
    SourceVideo sourceVideo;

    // Output stream information (all guarded by outputMutex while threads are running)
    QMutex outputMutex;
    qint32 outputFrameNumber;
    QMap<qint32, QByteArray> pendingOutputFrames;
    QFile targetVideo;
    QElapsedTimer totalTimer;
};

#endif // PALCOMBFILTER_H
