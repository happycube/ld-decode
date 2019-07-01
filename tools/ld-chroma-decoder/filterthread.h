/************************************************************************

    filterthread.h

    ld-chroma-decoder - Colourisation filter for ld-decode
    Copyright (C) 2018-2019 Simon Inns

    This file is part of ld-decode-tools.

    ld-chroma-decoder is free software: you can redistribute it and/or
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
#include <QAtomicInt>
#include <QThread>
#include <QDebug>

#include "sourcevideo.h"
#include "lddecodemetadata.h"
#include "palcolour.h"

class PalCombFilter;

class FilterThread : public QThread
{
    Q_OBJECT
public:
    explicit FilterThread(QAtomicInt& abortParam, PalCombFilter& combFilterParam, LdDecodeMetaData::VideoParameters videoParametersParam, bool blackAndWhiteParam, QObject *parent = nullptr);

signals:

protected:
    void run() override;

private:
    // Manager
    QAtomicInt& abort;
    PalCombFilter& combFilter;

    // PAL colour object
    PalColour palColour;
    LdDecodeMetaData::VideoParameters videoParameters;
    bool blackAndWhite;

    // Video extent for cropping
    qint32 firstActiveScanLine;
    qint32 lastActiveScanLine;
    qint32 videoStart;
    qint32 videoEnd;

    // Temporary output buffer
    QByteArray outputData;
};

#endif // FILTERTHREAD_H
