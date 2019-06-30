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
#include <QFile>
#include <QTemporaryFile>
#include <QDebug>

#include "Decoders/efmtof3frames.h"
#include "Decoders/syncf3frames.h"
#include "Decoders/f3tof2frames.h"
#include "Decoders/f2framestoaudio.h"

class EfmProcess : public QThread
{
Q_OBJECT

public:
    explicit EfmProcess(QObject *parent = nullptr);
    ~EfmProcess() override;

    struct Statistics {
        EfmToF3Frames::Statistics efmToF3Frames;
        SyncF3Frames::Statistics syncF3Frames;
        F3ToF2Frames::Statistics f3ToF2Frames;
        F2FramesToAudio::Statistics f2FramesToAudio;
    };

    void startProcessing(QString _inputFilename, QFile *_audioOutputFileHandle);
    void stopProcessing();
    void quit();
    Statistics getStatistics(void);

signals:
    void processingComplete(bool audioAvailable, bool dataAvailable);

protected:
    void run() override;

private:
    // Thread control
    QMutex mutex;
    QWaitCondition condition;
    bool restart;
    bool cancel;
    bool abort;

    Statistics statistics;

    // Externally settable variables
    QString inputFilename;
    QFile *audioOutputFileHandle;

    // Thread-safe variables
    QString inputFilenameTs;
    QFile *audioOutputFileHandleTs;
};

#endif // EFMPROCESS_H
