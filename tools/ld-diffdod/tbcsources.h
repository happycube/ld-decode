/************************************************************************

    tbcsources.h

    ld-diffdod - TBC Differential Drop-Out Detection tool
    Copyright (C) 2019 Simon Inns

    This file is part of ld-decode-tools.

    ld-diffdod is free software: you can redistribute it and/or
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

#ifndef TBCSOURCES_H
#define TBCSOURCES_H

#include <QObject>
#include <QList>
#include <QtConcurrent/QtConcurrent>
#include <QDebug>

// TBC library includes
#include "sourcevideo.h"
#include "lddecodemetadata.h"
#include "vbidecoder.h"
#include "filters.h"

class TbcSources : public QObject
{
    Q_OBJECT
public:
    explicit TbcSources(QObject *parent = nullptr);

    bool loadSource(QString filename, bool reverse);
    bool unloadSource();
    bool saveSources(qint32 vbiStartFrame, qint32 length, qint32 dodThreshold, bool lumaClip);

    qint32 getNumberOfAvailableSources();
    qint32 getMinimumVbiFrameNumber();
    qint32 getMaximumVbiFrameNumber();
    void verifySources(qint32 vbiStartFrame, qint32 length);

private:
    // Source definition
    struct Source {
        SourceVideo sourceVideo;
        LdDecodeMetaData ldDecodeMetaData;
        QString filename;
        qint32 minimumVbiFrameNumber;
        qint32 maximumVbiFrameNumber;
        bool isSourceCav;
    };

    // The frame number is common between sources
    qint32 currentVbiFrameNumber;

    QVector<Source*> sourceVideos;
    qint32 currentSource;

    void performFrameDiffDod(qint32 targetVbiFrame, qint32 dodOnThreshold, bool lumaClip);
    QVector<SourceVideo::Data> getFieldData(qint32 targetVbiFrame, bool isFirstField);
    QVector<QByteArray> getFieldErrorByMedian(qint32 targetVbiFrame, QVector<SourceVideo::Data> &fields, qint32 dodThreshold);
    qint32 median(QVector<qint32> v);
    void performLumaClip(qint32 targetVbiFrame, QVector<SourceVideo::Data> &fields, QVector<QByteArray> &fieldsDiff);
    QVector<LdDecodeMetaData::DropOuts> getFieldDropouts(qint32 targetVbiFrame, QVector<QByteArray> &fieldsDiff, bool isFirstField);
    void writeDropoutMetadata(qint32 targetVbiFrame, QVector<LdDecodeMetaData::DropOuts> &firstFieldDropouts,
                              QVector<LdDecodeMetaData::DropOuts> &secondFieldDropouts);
    void concatenateFieldDropouts(qint32 targetVbiFrame, QVector<LdDecodeMetaData::DropOuts> &dropouts);

    QVector<qint32> getAvailableSourcesForFrame(qint32 vbiFrameNumber);
    bool setDiscTypeAndMaxMinFrameVbi(qint32 sourceNumber);
    qint32 convertVbiFrameNumberToSequential(qint32 vbiFrameNumber, qint32 sourceNumber);
};

#endif // TBCSOURCES_H
