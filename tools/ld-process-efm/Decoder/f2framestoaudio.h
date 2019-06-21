/************************************************************************

    f2framestoaudio.h

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

#ifndef F2FRAMESTOAUDIO_H
#define F2FRAMESTOAUDIO_H

#include <QCoreApplication>
#include <QDebug>
#include <QFile>

#include "Datatypes/f2frame.h"
#include "Datatypes/section.h"
#include "Datatypes/tracktime.h"

class F2FramesToAudio
{
public:
    F2FramesToAudio();

    struct Statistics {
        qint32 validAudioSamples;
        qint32 invalidAudioSamples;
        qint32 sectionsProcessed;
        qint32 encoderRunning;
        qint32 encoderStopped;
        qint32 unknownQMode;
        qint32 trackNumber;
        TrackTime trackTime;
        TrackTime discTime;
    };

    void reset(void);
    void resetStatistics(void);
    Statistics getStatistics(void);

    void reportStatus(void);
    bool setOutputFile(QFile *outputFileHandle);
    void convert(QVector<F2Frame> f2Frames, QVector<Section> sections);

private:
    Statistics statistics;
    QFile *outputFileHandle;

    QVector<Section> sectionsIn;
    QVector<F2Frame> f2FramesIn;

    void processAudio(void);
};

#endif // F2FRAMESTOAUDIO_H
