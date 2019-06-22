/************************************************************************

    sectorstometa.h

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

#ifndef SECTORSTOMETA_H
#define SECTORSTOMETA_H

#include <QCoreApplication>
#include <QFile>
#include <QDebug>

#include "Datatypes/sector.h"

class SectorsToMeta
{
public:
    SectorsToMeta();

    void reset(void);
    bool setOutputFile(QFile *outputFileHandle);
    void flushMetadata(void);

    void reportStatus(void);
    void process(QVector<Sector> sectors);

private:
    struct Metadatum {
        TrackTime address;
        qint32 mode;
        bool isCorrected;
    };

    QVector<Metadatum> metadata;

    qint32 validSectors;
    qint32 invalidSectors;
    QString jsonFilename;
    QFile *outputFileHandle;
};

#endif // SECTORSTOMETA_H
