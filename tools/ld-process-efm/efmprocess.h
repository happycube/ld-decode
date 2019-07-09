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

    void setDebug(bool _debug_EfmToF3Frames, bool _debug_SyncF3Frames,
                              bool _debug_F3ToF2Frames, bool _debug_F2FramesToAudio);
    void setAudioErrorTreatment(F2FramesToAudio::ErrorTreatment _errorTreatment);
    void reportStatistics();
    void startProcessing(QFile *_inputFilename, QFile *_audioOutputFilename, QFile *_dataOutputFilename);
    void stopProcessing();
    void quit();
    Statistics getStatistics();
    void reset();

signals:
    void processingComplete(bool audioAvailable, bool dataAvailable);
    void percentProcessed(qint32 percent);

protected:
    void run() override;

private:
    // Thread control
    QMutex mutex;
    QWaitCondition condition;
    bool restart;
    bool cancel;
    bool abort;

    // Debug
    bool debug_EfmToF3Frames;
    bool debug_F2FramesToAudio;
    bool debug_F3ToF2Frames;
    bool debug_SyncF3Frames;

    // Audio options
    F2FramesToAudio::ErrorTreatment errorTreatment;

    // Class globals
    EfmToF3Frames efmToF3Frames;
    SyncF3Frames syncF3Frames;
    F3ToF2Frames f3ToF2Frames;
    F2FramesToAudio f2FramesToAudio;

    Statistics statistics;

    // Externally settable variables
    QFile* efmInputFileHandle;
    QFile* audioOutputFileHandle;
    QFile* dataOutputFileHandle;

    // Thread-safe variables
    QFile* efmInputFileHandleTs;
    QFile* audioOutputFileHandleTs;
    QFile* dataOutputFileHandleTs;

    QByteArray readEfmData(void);
};

#endif // EFMPROCESS_H
