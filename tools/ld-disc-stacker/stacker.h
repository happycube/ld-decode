/************************************************************************

    stacker.h

    ld-disc-stacker - Disc stacking for ld-decode
    Copyright (C) 2020-2022 Simon Inns

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

#ifndef STACKER_H
#define STACKER_H

#include <QObject>
#include <QElapsedTimer>
#include <QAtomicInt>
#include <QThread>
#include <QDebug>

#include "sourcevideo.h"
#include "lddecodemetadata.h"

class StackingPool;

class Stacker : public QThread
{
    Q_OBJECT
public:
    explicit Stacker(QAtomicInt& _abort, StackingPool& _stackingPool, QObject *parent = nullptr);

protected:
    void run() override;

private:
    // Stacking pool
    QAtomicInt& abort;
    StackingPool& stackingPool;
    QVector<LdDecodeMetaData::VideoParameters> videoParameters;

    void stackField(const qint32 frameNumber,const QVector<SourceVideo::Data>& inputFields,const LdDecodeMetaData::VideoParameters& videoParameters,
                    const QVector<LdDecodeMetaData::Field>& fieldMetadata,const QVector<qint32> availableSourcesForFrame,const bool& noDiffDod,const bool& passThrough,
                    SourceVideo::Data &outputField, DropOuts &dropOuts,const qint32& mode,const qint32& smartThreshold,const bool& verbose);
    void getProcessedSample(const qint32 x, const qint32 y, const QVector<qint32>& availableSourcesForFrame, const QVector<SourceVideo::Data>& inputFields, QVector<QVector<quint16>>& tmpField, const LdDecodeMetaData::VideoParameters& videoParameters, const QVector<LdDecodeMetaData::Field>& fieldMetadata, QVector<quint16>& sample, QVector<quint16>& sampleN, QVector<quint16>& sampleS, QVector<quint16>& sampleE, QVector<quint16>& sampleW, QVector<bool>& isAllDropout, const bool& noDiffDod, const bool& verbose);
    inline quint16 median(QVector<quint16> v);
    inline qint32 mean(const QVector<quint16>& v);
    inline quint16 closest(const QVector<quint16>& v,const qint32 target);
    quint16 stackMode(const QVector<quint16>& elements, const QVector<quint16>& elementsN,const QVector<quint16>& elementsS,const QVector<quint16>& elementsE, const QVector<quint16>& elementsW,const QVector<bool>& isAllDropout, const qint32& mode, const qint32& smartThreshold);
    inline bool isDropout(const DropOuts& dropOuts, const qint32 fieldX, const qint32 fieldY);
    inline bool haveAllDropout(const QVector<LdDecodeMetaData::Field>& fieldMetadata, const qint32 x, const qint32 y);
    QVector<quint16> diffDod(const QVector<quint16>& inputValues,const LdDecodeMetaData::VideoParameters& videoParameters,const bool& verbose);
};

#endif // STACKER_H
