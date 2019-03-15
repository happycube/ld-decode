/************************************************************************

    f1frame.cpp

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

#ifndef F1FRAME_H
#define F1FRAME_H

#include <QCoreApplication>
#include <QDebug>

#include "f2frame.h"
#include "tracktime.h"

class F1Frame
{
public:
    F1Frame();

    void setData(QByteArray dataParam);
    QByteArray getDataSymbols(void);
    qint32 getMode(void);
    TrackTime getAddress(void);

private:
    QByteArray dataSymbols;
    qint32 bcdToInteger(uchar bcd);

    qint32 sectorMode;
    TrackTime sectorAddress;
};

#endif // F1FRAME_H
