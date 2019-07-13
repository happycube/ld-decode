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

class LDDECODESHAREDSHARED_EXPORT SourceVideo : public QObject
{
    Q_OBJECT

public:
    explicit SourceVideo(QObject *parent = nullptr);
    ~SourceVideo() override;

    // File handling methods
    bool open(QString filename, qint32 _fieldLength);
    void close(void);

    // Field handling methods
    QByteArray getVideoField(qint32 fieldNumber, bool noPreCache = false);

    // Get and set methods
    bool isSourceValid();
    qint32 getNumberOfAvailableFields();

private:
    // File handling globals
    QFile inputFile;
    bool isSourceVideoOpen;
    qint32 availableFields;
    qint32 fieldLength;

    // Field caching
    struct Cache {
        QVector<QByteArray> storage;
        qint32 maximumItems;
        qint32 items;
        qint32 startFieldNumber;

        qint32 hit;
        qint32 miss;
    };

    Cache cache;
};

#endif // SOURCEVIDEO_H
