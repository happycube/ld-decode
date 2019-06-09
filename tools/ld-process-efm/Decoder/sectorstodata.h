/************************************************************************

    sectorstodata.h

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

#ifndef SECTORSTODATA_H
#define SECTORSTODATA_H

#include <QCoreApplication>
#include <QDebug>
#include <QFile>

#include "sector.h"
#include "tracktime.h"

class SectorsToData
{
public:
    SectorsToData();

    void reportStatus(void);
    bool setOutputFile(QFile *outputFileHandle);
    void convert(QVector<Sector> sectors);

private:
    QFile *outputFileHandle;
    qint32 sectorsOut;

    bool gotFirstValidSector;
    TrackTime lastGoodAddress;

    qint32 gapSectors;
    qint32 missingSectors;

    QVector<qint32> missingStartSector;
    QVector<qint32> missingEndSector;
    QVector<bool> isGap;
};

#endif // SECTORSTODATA_H
