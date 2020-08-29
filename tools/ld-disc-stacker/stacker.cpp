/************************************************************************

    stacker.cpp

    ld-disc-stacker - Disc stacking for ld-decode
    Copyright (C) 2020 Simon Inns

    This file is part of ld-decode-tools.

    ld-disc-stacker is free software: you can redistribute it and/or
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

#include "stacker.h"
#include "stackingpool.h"

Stacker::Stacker(QAtomicInt& _abort, StackingPool& _stackingPool, QObject *parent)
    : QThread(parent), abort(_abort), stackingPool(_stackingPool)
{
}

void Stacker::run()
{
    // Variables for getInputFrame
    qint32 frameNumber;
    QVector<qint32> firstFieldSeqNo;
    QVector<qint32> secondFieldSeqNo;
    QVector<SourceVideo::Data> firstSourceField;
    QVector<SourceVideo::Data> secondSourceField;
    QVector<LdDecodeMetaData::Field> firstFieldMetadata;
    QVector<LdDecodeMetaData::Field> secondFieldMetadata;
    bool reverse;
    QVector<qint32> availableSourcesForFrame;

    while(!abort) {
        // Get the next field to process from the input file
        if (!stackingPool.getInputFrame(frameNumber, firstFieldSeqNo, firstSourceField, firstFieldMetadata,
                                       secondFieldSeqNo, secondSourceField, secondFieldMetadata,
                                       videoParameters, reverse,
                                       availableSourcesForFrame)) {
            // No more input fields -- exit
            break;
        }

        qint32 totalAvailableSources = firstFieldSeqNo.size();
        qDebug().nospace() << "Frame #" << frameNumber << " - There are " << totalAvailableSources << " sources available of which " <<
                              availableSourcesForFrame.size() << " contain the required frame";

        // Copy the input frames' data to the target frames.
        // We'll use these both as source and target during correction, which
        // is OK because we're careful not to copy data from another dropout.
        QVector<SourceVideo::Data> firstFieldData = firstSourceField;
        QVector<SourceVideo::Data> secondFieldData = secondSourceField;

        // Processing goes here...........

        // Return the processed fields
        stackingPool.setOutputFrame(frameNumber, firstFieldData[0], secondFieldData[0], firstFieldSeqNo[0], secondFieldSeqNo[0]);
    }
}




