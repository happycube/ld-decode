/************************************************************************

    f3tof2frames.cpp

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

#include "f3tof2frames.h"
#include "logging.h"

F3ToF2Frames::F3ToF2Frames()
{
    // Initialise the statistics
    resetStatistics();
}

// Methods to handle statistics
void F3ToF2Frames::resetStatistics(void)
{
    c1Circ.resetStatistics();
    c2Circ.resetStatistics();
    c2Deinterleave.resetStatistics();
}

F3ToF2Frames::Statistics F3ToF2Frames::getStatistics(void)
{
    statistics.c1Circ_statistics = c1Circ.getStatistics();
    statistics.c2Circ_statistics = c2Circ.getStatistics();
    statistics.c2Deinterleave_statistics = c2Deinterleave.getStatistics();

    return statistics;
}

// Method to write status information to qInfo
void F3ToF2Frames::reportStatus(void)
{
    // Show C1 CIRC status
    c1Circ.reportStatus();

    // Show C2 CIRC status
    c2Circ.reportStatus();

    // Show C2 Deinterleave status
    c2Deinterleave.reportStatus();
}

// Flush the C1, C2 and deinterlacing delay buffers
void F3ToF2Frames::flush(void)
{
    // Flush all the delay buffers
    c1Circ.flush();
    c2Circ.flush();
    c2Deinterleave.flush();

    qDebug() << "F3ToF2Frames::flush(): Delay buffers flushed";
}

QVector<F2Frame> F3ToF2Frames::convert(QVector<F3Frame> f3Frames)
{
    QVector<F2Frame> f2Frames;

    if (f3Frames.size() == 0) return f2Frames;

    // Process the F3 frames
    for (qint32 i = 0; i < f3Frames.size(); i++) {
        // Process C1 CIRC
        c1Circ.pushF3Frame(f3Frames[i]);

        // Get C1 results (if available)
        QByteArray c1DataSymbols = c1Circ.getDataSymbols();
        QByteArray c1ErrorSymbols = c1Circ.getErrorSymbols();

        // If we have C1 results, process C2
        if (!c1DataSymbols.isEmpty()) {
            // Process C2 CIRC
            c2Circ.pushC1(c1DataSymbols, c1ErrorSymbols);

            // Get C2 results (if available)
            QByteArray c2DataSymbols = c2Circ.getDataSymbols();
            QByteArray c2ErrorSymbols = c2Circ.getErrorSymbols();

            // Only process the F2 frames if we received data
            if (!c2DataSymbols.isEmpty()) {
                // Deinterleave the C2
                c2Deinterleave.pushC2(c2DataSymbols, c2ErrorSymbols);

                QByteArray c2DeinterleavedData = c2Deinterleave.getDataSymbols();
                QByteArray c2DeinterleavedErrors = c2Deinterleave.getErrorSymbols();

                // If we have deinterleaved C2s, create an F2 frame
                if (!c2DeinterleavedData.isEmpty()) {
                    F2Frame newF2Frame;
                    newF2Frame.setData(c2DeinterleavedData, c2DeinterleavedErrors);
                    f2Frames.append(newF2Frame);
                }
            }
        }
    }

    return f2Frames;
}
