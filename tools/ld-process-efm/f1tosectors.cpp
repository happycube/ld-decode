/************************************************************************

    f1tosectors.cpp

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

#include "f1tosectors.h"

F1ToSectors::F1ToSectors()
{
    validSectors = 0;
    invalidSectors = 0;
    correctedSectors = 0;
}

void F1ToSectors::reportStatus(void)
{
    qInfo() << "Data sector processing:";
    qInfo() << "  Total number of sectors processed =" << validSectors + invalidSectors;
    qInfo() << "  Number of good sectors =" << validSectors << "of which" << correctedSectors << "were ECC corrected";
    qInfo() << "  Number of unrecoverable sectors =" << invalidSectors;
}

QVector<Sector> F1ToSectors::convert(QVector<F1Frame> f1FramesIn)
{
    // Process the F1 frames as sectors
    QVector<Sector> sectors;
    for (qint32 i = 0; i < f1FramesIn.size(); i++) {
        Sector sector;
        sector.setData(f1FramesIn[i]);
        if (sector.isValid()) {
            validSectors++;
            if (sector.isCorrected()) correctedSectors++;

            //qDebug() << "F1Frame mode =" << sector.getMode() << "address =" << sector.getAddress().getTimeAsQString();
        } else {
            invalidSectors++;

            qDebug() << "F1Frame mode =" << sector.getMode() << "address =" << sector.getAddress().getTimeAsQString() << "Invalid";
        }
        sectors.append(sector);
    }

    return sectors;
}
