/************************************************************************

    ntscfilter.h

    ld-comb-ntsc - NTSC colourisation filter for ld-decode
    Copyright (C) 2018 Chad Page
    Copyright (C) 2018 Simon Inns

    This file is part of ld-decode-tools.

    ld-comb-ntsc is free software: you can redistribute it and/or
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

#ifndef NTSCFILTER_H
#define NTSCFILTER_H

#include <QObject>
#include <QDebug>
#include <QFile>
#include <QElapsedTimer>

// Include the ld-decode-tools shared libary headers
#include "sourcevideo.h"
#include "lddecodemetadata.h"

#include "comb.h"

class NtscFilter : public QObject
{
    Q_OBJECT
public:
    explicit NtscFilter(QObject *parent = nullptr);

    bool process(QString inputFileName, QString outputFileName, qint32 startFrame, qint32 length, bool reverse = false, qint32 filterDepth = 2,
                 bool blackAndWhite = false, bool adaptive2d = true, bool opticalFlow = true);

signals:

public slots:

private:
    LdDecodeMetaData ldDecodeMetaData;
    SourceVideo sourceVideo;
};

#endif // NTSCFILTER_H
