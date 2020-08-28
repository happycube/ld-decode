/************************************************************************

    sources.h

    ld-diffdod - TBC Differential Drop-Out Detection tool
    Copyright (C) 2019 Simon Inns

    This file is part of ld-decode-tools.

    ld-diffdod is free software: you can redistribute it and/or
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

#ifndef SOURCES_H
#define SOURCES_H

#include <QDebug>
#include <QFile>

#include <QObject>
#include <QAtomicInt>
#include <QElapsedTimer>
#include <QMutex>
#include <QThread>

#include "diffdod.h"

class Sources : public QObject
{
    Q_OBJECT

public:
    explicit Sources(QVector<QString> inputFilenames, bool reverse,
                     qint32 dodThreshold, bool lumaClip,
                     qint32 startVbi, qint32 lengthVbi,
                     qint32 maxThreads, QObject *parent = nullptr);

    bool process();

    // Member functions used by worker threads
    bool getInputFrame(qint32& targetVbiFrame,
                        QVector<SourceVideo::Data>& firstFields, QVector<SourceVideo::Data>& secondFields,
                        LdDecodeMetaData::VideoParameters& videoParameters,
                        QVector<qint32>& availableSourcesForFrame,
                        qint32& dodThreshold, bool& signalClip);

    bool setOutputFrame(qint32 targetVbiFrame,
                         QVector<DropOuts> firstFieldDropouts,
                         QVector<DropOuts> secondFieldDropouts,
                         QVector<qint32> availableSourcesForFrame);

private:
    // Source definition
    struct Source {
        SourceVideo sourceVideo;
        LdDecodeMetaData ldDecodeMetaData;
        QString filename;
        qint32 minimumVbiFrameNumber;
        qint32 maximumVbiFrameNumber;
        bool isSourceCav;
    };

    QVector<Source*> sourceVideos;
    qint32 currentSource;
    QElapsedTimer totalTimer;
    qint32 processedFrames;

    // Setup variables
    QVector<QString> m_inputFilenames;
    bool m_reverse;
    qint32 m_dodThreshold;
    bool m_signalClip;
    qint32 m_startVbi;
    qint32 m_lengthVbi;
    qint32 m_maxThreads;

    // Input stream variables (all guarded by inputMutex while threads are running)
    QMutex inputMutex;
    qint32 inputFrameNumber;
    qint32 lastFrameNumber;

    // Output stream variables (all guarded by outputMutex while threads are running)
    QMutex outputMutex;

    // Atomic abort flag shared by worker threads; workers watch this, and shut
    // down as soon as possible if it becomes true
    QAtomicInt abort;

    bool loadInputTbcFiles(QVector<QString> inputFilenames, bool reverse);
    void unloadInputTbcFiles();
    bool loadSource(QString filename, bool reverse);
    bool setDiscTypeAndMaxMinFrameVbi(qint32 sourceNumber);
    qint32 getMinimumVbiFrameNumber();
    qint32 getMaximumVbiFrameNumber();
    void verifySources(qint32 vbiStartFrame, qint32 length);
    QVector<qint32> getAvailableSourcesForFrame(qint32 vbiFrameNumber);
    qint32 convertVbiFrameNumberToSequential(qint32 vbiFrameNumber, qint32 sourceNumber);
    qint32 getNumberOfAvailableSources();
    //void processSources(qint32 vbiStartFrame, qint32 length, qint32 dodThreshold, bool lumaClip);
    void saveSources();
    QVector<SourceVideo::Data> getFieldData(qint32 targetVbiFrame, bool isFirstField,
                                                     QVector<qint32> &availableSourcesForFrame);
};

#endif // SOURCES_H
