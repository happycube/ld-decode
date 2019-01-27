/************************************************************************

    fmcode.h

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

#ifndef FMCODE_H
#define FMCODE_H

#include <QObject>

#include "sourcevideo.h"
#include "lddecodemetadata.h"

class FmCode : public QObject
{
    Q_OBJECT
public:
    struct FmDecode {
        quint64 receiverClockSyncBits;
        quint64 videoFieldIndicator;
        quint64 leadingDataRecognitionBits;
        quint64 data;
        quint64 dataParityBit;
        quint64 trailingDataRecognitionBits;
    };

    explicit FmCode(QObject *parent = nullptr);

    FmCode::FmDecode fmDecoder(QByteArray lineData, LdDecodeMetaData::VideoParameters videoParameters);

signals:

public slots:

private:
    bool isEvenParity(quint64 data);
    QVector<bool> getTransitionMap(QByteArray lineData, qint32 zcPoint);
};

#endif // FMCODE_H
