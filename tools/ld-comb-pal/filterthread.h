/************************************************************************

    filterthread.h

    ld-comb-pal - PAL colourisation filter for ld-decode
    Copyright (C) 2018 Simon Inns

    This file is part of ld-decode-tools.

    ld-comb-pal is free software: you can redistribute it and/or
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

#ifndef FILTERTHREAD_H
#define FILTERTHREAD_H

#include <QObject>
#include <QThread>
#include <QMutex>
#include <QWaitCondition>
#include <QDebug>

#include "sourcevideo.h"
#include "lddecodemetadata.h"
#include "palcolour.h"

class FilterThread : public QThread
{
    Q_OBJECT
public:
    explicit FilterThread(LdDecodeMetaData::VideoParameters videoParametersParam, QObject *parent = nullptr);
    ~FilterThread() override;

    void startFilter(QByteArray topFieldParam, QByteArray bottomFieldParam, qreal burstMedianIreParam, bool blackAndWhiteParam);
    QByteArray getResult(void);
    bool isBusy(void);

signals:

protected:
    void run() override;

private:
    // Thread control
    QMutex mutex;
    QWaitCondition condition;
    bool isProcessing;
    bool abort;

    // PAL colour object
    PalColour palColour;
    LdDecodeMetaData::VideoParameters videoParameters;

    // Video extent for cropping
    qint32 firstActiveScanLine;
    qint32 lastActiveScanLine;
    qint32 videoStart;
    qint32 videoEnd;

    // Input data buffers
    QByteArray firstFieldData;
    QByteArray secondFieldData;
    QByteArray tsFirstFieldData;
    QByteArray tsSecondFieldData;
    QByteArray outputData;
    QByteArray rgbOutputData;

    // Burst level data
    qreal burstMedianIre;

    // Flags
    bool blackAndWhite;
};

#endif // FILTERTHREAD_H
