/************************************************************************

    f3tof2frames.h

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

#ifndef F3TOF2FRAMES_H
#define F3TOF2FRAMES_H

#include <QCoreApplication>
#include <QDebug>

#include "f3frame.h"
#include "f2frame.h"
#include "c1circ.h"
#include "c2circ.h"
#include "c2deinterleave.h"

class F3ToF2Frames
{
public:
    F3ToF2Frames();

    // Statistics data structure
    struct Statistics {
        C1Circ::Statistics c1Circ_statistics;
        C2Circ::Statistics c2Circ_statistics;
        C2Deinterleave::Statistics c2Deinterleave_statistics;
    };

    void reset(void);
    void resetStatistics(void);
    Statistics getStatistics(void);

    void reportStatus(void);
    void flush(void);
    QVector<F2Frame> convert(QVector<F3Frame> f3Frames);

private:
    C1Circ c1Circ;
    C2Circ c2Circ;
    C2Deinterleave c2Deinterleave;

    Statistics statistics;
};

#endif // F3TOF2FRAMES_H
