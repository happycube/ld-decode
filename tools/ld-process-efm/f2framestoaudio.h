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
#include <QDataStream>

#include "f2frame.h"

class F2FramesToAudio
{
public:
    F2FramesToAudio();

    void reportStatus(void);
    bool openOutputFile(QString filename);
    void closeOutputFile(void);
    void convert(QVector<F2Frame> f2Frames);

private:
    QFile *outputFileHandle;
    QDataStream *outputStream;
    qint32 audioSamples;
};

#endif // F2FRAMESTOAUDIO_H
