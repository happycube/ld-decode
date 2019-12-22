/************************************************************************

    discmap.cpp

    ld-discmap - TBC and VBI alignment and correction
    Copyright (C) 2019 Simon Inns

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

#ifndef DISCMAP_H
#define DISCMAP_H

#include <QObject>
#include <QDebug>
#include <QFile>

#include "vbimapper.h"

// TBC library includes
#include "sourcevideo.h"
#include "lddecodemetadata.h"

class DiscMap : public QObject
{
    Q_OBJECT
public:
    explicit DiscMap(QObject *parent = nullptr);
    bool process(QString inputFilename, QString outputFilename, bool reverse, bool mapOnly);

private:
    SourceVideo sourceVideo;
    LdDecodeMetaData sourceMetaData;
    VbiMapper vbiMapper;

    bool loadSource(QString filename, bool reverse);
    bool mapSource();
    bool saveSource(QString filename);

    qint32 convertFrameToVbi(qint32 frameNumber);
    qint32 convertFrameToClvPicNo(qint32 frameNumber);
    qint32 convertFrameToClvTimeCode(qint32 frameNumber);
};

#endif // DISCMAP_H
