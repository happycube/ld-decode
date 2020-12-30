/************************************************************************

    sourceaudio.h

    ld-decode-tools TBC library
    Copyright (C) 2018-2020 Simon Inns

    This file is part of ld-decode-tools.

    ld-decode-tools is free software: you can redistribute it and/or
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

#ifndef SOURCEAUDIO_H
#define SOURCEAUDIO_H

#include <QVector>
#include <QDebug>
#include <QFileInfo>
#include <QFile>

// TBC library includes
#include "lddecodemetadata.h"

class SourceAudio
{
public:
    // A QVector of timebase-corrected audio samples.
    using Data = QVector<qint16>;

    SourceAudio();
    ~SourceAudio();

    // Prevent copying or assignment
    SourceAudio(const SourceAudio &) = delete;
    SourceAudio& operator=(const SourceAudio &) = delete;

    // File handling methods
    bool open(QFileInfo inputFileInfo);
    void close();

    // Data handling methods
    Data getAudioData(qint32 startSample, qint32 numberOfSamples);

private:
    QFile inputAudioFile;
    qint64 audioFileByteLength;
};

#endif // SOURCEAUDIO_H
