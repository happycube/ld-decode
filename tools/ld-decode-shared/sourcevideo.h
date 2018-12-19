/************************************************************************

    sourcevideo.h

    ld-decode-tools shared library
    Copyright (C) 2018 Simon Inns

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

#include "ld-decode-shared_global.h"

#include <QObject>
#include <QFile>
#include <QDebug>
#include <QCache>

#include "sourcefield.h"

class LDDECODESHAREDSHARED_EXPORT SourceVideo : public QObject
{
    Q_OBJECT

public:
    explicit SourceVideo(QObject *parent = nullptr);
    ~SourceVideo() override;

    // File handling methods
    bool open(QString fileName, qint32 fieldLengthParam);
    void close(void);

    // Field handling methods
    SourceField *getVideoField(qint32 fieldNumber);

    // Get and set methods
    bool isSourceValid(void);
    qint32 getNumberOfAvailableFields(void);

private:
    // File handling globals
    QFile *inputFile;
    QString fileName;
    bool isSourceVideoValid;
    qint32 availableFields;
    qint32 fieldLength;

    // Field caching
    SourceField *sourceField;
    QCache<qint32, SourceField> fieldCache;

    // Data processing methods
    bool seekToFieldNumber(qint32 fieldNumber);
    QByteArray readRawFieldData(void);
};

#endif // SOURCEVIDEO_H
