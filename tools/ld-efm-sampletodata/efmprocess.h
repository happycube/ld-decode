/************************************************************************

    efmprocess.cpp

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

#ifndef EFMPROCESS_H
#define EFMPROCESS_H

#include <QCoreApplication>
#include <QDebug>
#include <QFile>
#include <QDataStream>

#include "filter.h"
#include "efmdecoder.h"

class EfmProcess
{
public:
    EfmProcess();

    bool process(QString inputFilename, QString outputFilename);

private:
    QFile* inputFile;
    QFile* outputFile;

    // ZC detector state
    bool zcFirstRun;
    qint16 zcPreviousInput;
    bool prevDirection;

    void zeroCrossDetection(QVector<qint16> inputBuffer, QVector<qint16> zeroBuffer, QVector<qreal> &zcDeltas);
    qint32 fillInputBuffer(QDataStream &inputStream, QVector<qint16> &inputBuffer, qint32 samples);
    bool openInputSampleFile(QString filename);
    void closeInputSampleFile(void);
    bool openOutputDataFile(QString filename);
    void closeOutputDataFile(void);
};

#endif // EFMPROCESS_H
