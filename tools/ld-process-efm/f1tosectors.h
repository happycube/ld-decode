/************************************************************************

    f1tosectors.h

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

#ifndef F1TOSECTORS_H
#define F1TOSECTORS_H

#include <QCoreApplication>
#include <QDebug>

#include "sector.h"
#include "f1frame.h"

class F1ToSectors
{
public:
    F1ToSectors();

    void reportStatus(void);
    QVector<Sector> convert(QVector<F1Frame> f1FramesIn);

private:
    qint32 validSectors;
    qint32 invalidSectors;
    qint32 correctedSectors;
};

#endif // F1TOSECTORS_H
