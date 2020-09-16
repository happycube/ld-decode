/************************************************************************

    vitsanalyser.h

    ld-process-vits - Vertical Interval Test Signal processing
    Copyright (C) 2020 Simon Inns

    This file is part of ld-decode-tools.

    ld-process-vits is free software: you can redistribute it and/or
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

#ifndef VITSANALYSER_H
#define VITSANALYSER_H

#include <QObject>
#include <QAtomicInt>
#include <QThread>
#include <QDebug>

#include <cmath>

#include "lddecodemetadata.h"
#include "sourcevideo.h"

class ProcessingPool;

class VitsAnalyser : public QThread {
    Q_OBJECT

public:
    explicit VitsAnalyser(QAtomicInt& _abort, ProcessingPool& _processingPool, QObject *parent = nullptr);

protected:
    void run() override;

private:
    // Decoder pool
    QAtomicInt& abort;
    ProcessingPool& processingPool;

    // Temporary output buffer
    LdDecodeMetaData::Field outputData;

    // Other settings
    LdDecodeMetaData::VideoParameters videoParameters;

    QVector<double> getFieldLineSlice(const SourceVideo::Data &sourceField, qint32 fieldLine, qint32 startUs, qint32 lengthUs);
    QVector<double> limitByRange(QVector<double> &data, double floor, double ceiling);
    double calculateSnr(QVector<double> &data, bool usePsnr);
    double calcMean(QVector<double> &data);
    double calcStd(QVector<double> &data);
    double roundDouble(double in, qint32 decimalPlaces);
};

#endif // VITSANALYSER_H
