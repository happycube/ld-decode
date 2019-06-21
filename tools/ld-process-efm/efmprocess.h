/************************************************************************

    efmprocess.h

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

#ifndef EFMPROCESS_H
#define EFMPROCESS_H

#include <QObject>
#include <QThread>
#include <QMutex>
#include <QWaitCondition>
#include <QString>
#include <QTime>
#include <QFile>
#include <QDebug>

#include "Datatypes/f3frame.h"
#include "Datatypes/f2frame.h"
#include "Datatypes/f1frame.h"
#include "Datatypes/sector.h"
#include "Datatypes/section.h"
#include "Decoder/efmtof3frames.h"
#include "Decoder/f3tof2frames.h"
#include "Decoder/f2tof1frames.h"
#include "Decoder/f3tosections.h"
#include "Decoder/f2framestoaudio.h"
#include "Decoder/f1tosectors.h"
#include "Decoder/sectorstodata.h"
#include "Decoder/sectiontometa.h"
#include "Decoder/sectorstometa.h"

class EfmProcess : public QThread
{
Q_OBJECT

public:
    explicit EfmProcess(QObject *parent = nullptr);
    ~EfmProcess() override;

    // Statistics structure
    struct Statistics {
        EfmToF3Frames::Statistics efmToF3Frames_statistics;
        F3ToF2Frames::Statistics f3ToF2Frames_statistics;
        F2FramesToAudio::Statistics f2FramesToAudio_statistics;
        SectorsToData::Statistics sectorsToData_statistics;
    };

    void reset(void);
    void resetStatistics(void);
    Statistics getStatistics(void);

    void startProcessing(QString inputFilename, QFile *audioOutputFile, QFile *dataOutputFile,
                         QFile *audioMetaOutputFile, QFile *dataMetaOutputFile);

    void cancelProcessing();
    void quit();

signals:
    void percentageProcessed(qint32);
    void completed(void);

protected:
    void run() override;

private:
    // Thread control
    QMutex mutex;
    QWaitCondition condition;
    bool restart;
    bool cancel;
    bool abort;

    // Externally settable variables
    QString inputFilename;
    QFile *audioOutputFile;
    QFile *dataOutputFile;
    QFile *audioMetaOutputFile;
    QFile *dataMetaOutputFile;

    // Thread-safe variables
    QString inputFilenameTs;
    QFile *audioOutputFileTs;
    QFile *dataOutputFileTs;
    QFile *audioMetaOutputFileTs;
    QFile *dataMetaOutputFileTs;
    QFile *inputFileHandle;

    EfmToF3Frames efmToF3Frames;
    F3ToF2Frames f3ToF2Frames;
    F2ToF1Frames f2ToF1Frames;
    F3ToSections f3ToSections;
    F2FramesToAudio f2FramesToAudio;
    F1ToSectors f1ToSectors;
    SectorsToData sectorsToData;
    SectionToMeta sectionToMeta;
    SectorsToMeta sectorsToMeta;

    Statistics statistics;

    bool openInputFile(QString inputFilename);
    void closeInputFile(void);
    QByteArray readEfmData(void);
    void reportStatus(bool processAudio, bool processData);
};

#endif // EFMPROCESS_H
