/************************************************************************

    diffdod.h

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

#ifndef DIFFDOD_H
#define DIFFDOD_H

#include <QObject>
#include <QElapsedTimer>
#include <QAtomicInt>
#include <QThread>
#include <QDebug>
#include <QtMath>

// TBC library includes
#include "sourcevideo.h"
#include "lddecodemetadata.h"
#include "vbidecoder.h"
#include "filters.h"

class Sources;

class DiffDod : public QThread
{
    Q_OBJECT
public:
    explicit DiffDod(QAtomicInt& abort, Sources& sources, QObject *parent = nullptr);

protected:
    void run() override;

private:
    // Decoder pool
    QAtomicInt& m_abort;
    Sources& m_sources;

    // Processing methods
    QVector<QByteArray> getFieldErrorByMedian(QVector<SourceVideo::Data> &fields, qint32 dodThreshold, LdDecodeMetaData::VideoParameters videoParameters, QVector<qint32> availableSourcesForFrame);
    void performLumaClip(QVector<SourceVideo::Data> &fields, QVector<QByteArray> &fieldsDiff,
                                     LdDecodeMetaData::VideoParameters videoParameters,
                                     QVector<qint32> availableSourcesForFrame);
    QVector<LdDecodeMetaData::DropOuts> getFieldDropouts(QVector<QByteArray> &fieldsDiff,
                                                                     LdDecodeMetaData::VideoParameters videoParameters,
                                                                     QVector<qint32> availableSourcesForFrame);

    void concatenateFieldDropouts(QVector<LdDecodeMetaData::DropOuts> &dropouts, QVector<qint32> availableSourcesForFrame);

    qint32 median(QVector<qint32> v);
    float convertLinearToBrightness(quint16 value, quint16 black16bIre, quint16 white16bIre, bool isSourcePal);
};

#endif // DIFFDOD_H
