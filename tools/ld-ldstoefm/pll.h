/************************************************************************

    pll.h

    ld-ldstoefm - LDS sample to EFM data processing
    Copyright (C) 2019 Simon Inns

    This file is part of ld-decode-tools.

    ld-ldstoefm is free software: you can redistribute it and/or
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

#ifndef PLL_H
#define PLL_H

#include <QCoreApplication>
#include <QDebug>

class Pll
{
public:
    Pll();

    QByteArray process(QByteArray buffer);

private:
    // ZC detector state
    qint16 zcPreviousInput;
    qreal delta;

    // PLL state
    QByteArray pllResult;
    qreal basePeriod;
    qreal minimumPeriod;
    qreal maximumPeriod;
    qreal periodAdjustBase;

    qreal currentPeriod, phaseAdjust, refClockTime;
    qint32 frequencyHysteresis;
    qint8 tCounter;

    void pushEdge(qreal sampleDelta);
};

#endif // PLL_H
