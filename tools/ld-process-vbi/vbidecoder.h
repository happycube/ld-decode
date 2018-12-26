/************************************************************************

    vbidecoder.h

    ld-process-vbi - VBI and IEC NTSC specific processor for ld-decode
    Copyright (C) 2018 Simon Inns

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

#ifndef VBIDECODER_H
#define VBIDECODER_H

#include <QObject>

#include "sourcevideo.h"
#include "lddecodemetadata.h"
#include "fmcode.h"
#include "whiteflag.h"

class VbiDecoder : public QObject
{
    Q_OBJECT
public:
    // Public methods
    explicit VbiDecoder(QObject *parent = nullptr);
    bool process(QString inputFileName);

signals:

public slots:

private:
    QByteArray getActiveVideoLine(SourceField *sourceFrame, qint32 scanLine, LdDecodeMetaData::VideoParameters videoParameters);
    LdDecodeMetaData::Vbi translateVbi(qint32 vbi16, qint32 vbi17, qint32 vbi18);
    quint32 hammingCode(quint32 x4, quint32 x5);
    qint32 manchesterDecoder(QByteArray lineData, qint32 zcPoint, LdDecodeMetaData::VideoParameters videoParameters);
    QVector<bool> getTransitionMap(QByteArray lineData, qint32 zcPoint);
};

#endif // VBIDECODER_H
