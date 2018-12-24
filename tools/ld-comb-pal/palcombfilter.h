/************************************************************************

    palcombfilter.h

    ld-comb-pal - PAL colourisation filter for ld-decode
    Copyright (C) 2018 Simon Inns

    This file is part of ld-decode-tools.

    ld-comb-pal is free software: you can redistribute it and/or
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

#ifndef PALCOMBFILTER_H
#define PALCOMBFILTER_H

#include <QObject>
#include <QElapsedTimer>

#include "sourcevideo.h"
#include "lddecodemetadata.h"
#include "filterthread.h"

class PalCombFilter : public QObject
{
    Q_OBJECT
public:
    explicit PalCombFilter(QObject *parent = nullptr);
    bool process(QString inputFileName, QString outputFileName, qint32 startFrame, qint32 length, bool isVP415CropSet);

signals:

public slots:

private slots:

private:
    LdDecodeMetaData ldDecodeMetaData;
    SourceVideo sourceVideo;

    qint32 getAvailableNumberOfFrames(void);
    qint32 getFirstFieldNumber(qint32 frameNumber);
    qint32 getSecondFieldNumber(qint32 frameNumber);
};

#endif // PALCOMBFILTER_H
