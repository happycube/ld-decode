/************************************************************************

    sourceaudio.cpp

    ld-discmap - TBC and VBI alignment and correction
    Copyright (C) 2019-2020 Simon Inns

    This file is part of ld-decode-tools.

    ld-discmap is free software: you can redistribute it and/or
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

#include <QCoreApplication>
#include <QDebug>
#include <QFileInfo>
#include <QFile>

// TBC library includes
#include "lddecodemetadata.h"

class SourceAudio
{
public:
    SourceAudio();

    bool open(QFileInfo inputFileInfo);
    void close();
    QVector<qint16> getAudioForField(qint32 fieldNo);

private:
    LdDecodeMetaData *ldDecodeMetaData;
    QFile inputAudioFile;

    QVector<qint64> startPosition;
    QVector<qint64> fieldLength;
};

#endif // SOURCEAUDIO_H
