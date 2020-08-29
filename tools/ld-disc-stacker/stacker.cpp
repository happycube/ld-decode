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

        // Return the processed fields
        stackingPool.setOutputFrame(frameNumber,
                                    stackField(firstSourceField, videoParameters[0], availableSourcesForFrame),
                stackField(secondSourceField, videoParameters[0], availableSourcesForFrame),
                firstFieldSeqNo[0], secondFieldSeqNo[0]);
    }
}

// Method to stack fields
SourceVideo::Data Stacker::stackField(QVector<SourceVideo::Data> inputFields,
                                      LdDecodeMetaData::VideoParameters videoParameters,
                                      QVector<qint32> availableSourcesForFrame)
{
    SourceVideo::Data outputField(inputFields[0].size());

    for (qint32 y = 0; y < videoParameters.fieldHeight; y++) {
        for (qint32 x = 0; x < videoParameters.fieldWidth; x++) {
            // Get the input values from the input sources
            QVector<quint16> inputValues;
            for (qint32 i = 0; i < availableSourcesForFrame.size(); i++) {
                qint32 currentSource = availableSourcesForFrame[i];
                inputValues.append(inputFields[currentSource][(videoParameters.fieldWidth * y) + x]);
            }

            // Store the median in the output field
            outputField[(videoParameters.fieldWidth * y) + x] = median(inputValues);
        }
    }

    return outputField;
}

// Method to find the median of a vector of qint16s
quint16 Stacker::median(QVector<quint16> v)
{
    size_t n = v.size() / 2;
    std::nth_element(v.begin(), v.begin()+n, v.end());
    return v[n];
}


