/************************************************************************

    sector.h

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

#ifndef SECTOR_H
#define SECTOR_H

#include "f1frame.h"
#include "tracktime.h"

class Sector
{
public:
    Sector();

    void setData(F1Frame f1Frame);
    qint32 getMode(void);
    TrackTime getAddress(void);
    QByteArray getUserData(void);
    bool isValid(void);

private:
    // Mode 1 sector fields:
    // 3 + 1 + 2048 + 4 + 8 + 172 + 104 = 2340 bytes
    TrackTime address; // 3 bytes
    qint32 mode; // 1 byte
    QByteArray userData;
    quint32 edc;
    uchar intermediate[8];
    uchar pParity[172];
    uchar qParity[104];
    bool valid;

    qint32 bcdToInteger(uchar bcd);
    QString dataToString(QByteArray data);

    quint32 edc_lut[256];
    quint32 edcCompute(quint32 edc, uchar *src, qint32 size);
};

#endif // SECTOR_H
