/************************************************************************

    phaselockedloop.h

    ld-efm-sampletodata - EFM sample to data processor for ld-decode
    Copyright (C) 2019 Simon Inns

    This file is part of ld-decode-tools.

    ld-efm-sampletodata is free software: you can redistribute it and/or
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

#ifndef PHASELOCKEDLOOP_H
#define PHASELOCKEDLOOP_H

#include <QCoreApplication>
#include <QDebug>

class Pll_t
{
public:
    Pll_t(QVector<qint32> &_result);
    void pushEdge(qreal sampleDelta);

private:
    qreal basePeriod;
    qreal minimumPeriod;
    qreal maximumPeriod;
    qreal periodAdjustBase;

    QVector<qint32> &result;
    qreal currentPeriod, phaseAdjust, refClockTime;
    qint32 frequencyHysteresis;
    qint32 tCounter;

    void pushTValue(qint32 bit);
};

#endif // PHASELOCKEDLOOP_H
