/************************************************************************

    vbilinedecoder.h

    ld-process-vbi - VBI and IEC NTSC specific processor for ld-decode
    Copyright (C) 2018-2019 Simon Inns

    This file is part of ld-decode-tools.

    ld-process-vbi is free software: you can redistribute it and/or
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

#ifndef VBILINEDECODER_H
#define VBILINEDECODER_H

#include <QObject>
#include <QAtomicInt>
#include <QThread>
#include <QDebug>

#include "lddecodemetadata.h"
#include "sourcevideo.h"

class DecoderPool;

class VbiLineDecoder : public QThread {
    Q_OBJECT

public:
    explicit VbiLineDecoder(QAtomicInt& _abort, DecoderPool& _decoderPool, QObject *parent = nullptr);

    // The range of field lines needed from the input file (1-based, inclusive)
    // Extended to lines 1-26 to include VITS measurement lines
    static constexpr qint32 startFieldLine = 1;
    static constexpr qint32 endFieldLine = 26;

protected:
    void run() override;

private:
    // Decoder pool
    QAtomicInt& abort;
    DecoderPool& decoderPool;

    SourceVideo::Data getFieldLine(const SourceVideo::Data& sourceField, qint32 fieldLine,
                                   const LdDecodeMetaData::VideoParameters& videoParameters);

    // VITS processing methods
    void processVitsMetrics(const SourceVideo::Data &sourceField,
                           const LdDecodeMetaData::VideoParameters &videoParameters,
                           LdDecodeMetaData::Field &fieldMetadata);
    QVector<double> getFieldLineSlice(const SourceVideo::Data &sourceField, qint32 fieldLine,
                                     qint32 startUs, qint32 lengthUs,
                                     const LdDecodeMetaData::VideoParameters &videoParameters);
    double calculateSnr(QVector<double> &data, bool usePsnr);
    double calcMean(QVector<double> &data);
    double calcStd(QVector<double> &data);
    double roundDouble(double in, qint32 decimalPlaces);
};

#endif // VBILINEDECODER_H
