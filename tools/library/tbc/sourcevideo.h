/************************************************************************

    sourcevideo.h

    ld-decode-tools TBC library
    Copyright (C) 2018-2019 Simon Inns

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

#ifndef SOURCEVIDEO_H
#define SOURCEVIDEO_H

#include <QFile>
#include <QCache>
#include <QDebug>
#include <QVector>

class SourceVideo
{
public:
    // A QVector of timebase-corrected video samples.
    // This is usually a complete field, but it may be a partial field if
    // you've requested fewer lines from getVideoField (or if you've sliced it
    // yourself).
    using Data = QVector<quint16>;

    SourceVideo();
    ~SourceVideo();

    // Prevent copying or assignment
    SourceVideo(const SourceVideo &) = delete;
    SourceVideo& operator=(const SourceVideo &) = delete;

    // File handling methods
    bool open(QString filename, qint32 _fieldLength, qint32 _fieldLineLength = -1);
    void close(void);

    // Field handling methods
    Data getVideoField(qint32 fieldNumber, qint32 startFieldLine = -1, qint32 endFieldLine = -1);

    // Get and set methods
    bool isSourceValid();
    qint32 getNumberOfAvailableFields();
    qint32 getFieldLength();

private:
    // File handling globals
    QFile inputFile;
    qint64 inputFilePos;
    bool isSourceVideoOpen;
    qint32 availableFields;
    qint32 fieldLength;
    qint32 fieldByteLength;
    qint32 fieldLineLength;

    Data outputFieldData;

    // Field caching
    QCache<qint32, Data> fieldCache;
};

#endif // SOURCEVIDEO_H
