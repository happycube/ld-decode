/************************************************************************

    palencoder.h

    ld-chroma-encoder - PAL encoder for testing
    Copyright (C) 2019 Adam Sampson

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

#ifndef PALENCODER_H
#define PALENCODER_H

#include <QByteArray>
#include <QFile>
#include <QVector>

#include "lddecodemetadata.h"

class PALEncoder
{
public:
    PALEncoder(QFile &rgbFile, QFile &tbcFile, LdDecodeMetaData &metaData);

    // Encode RGB stream to PAL.
    // Returns true on success; on failure, prints an error and returns false.
    bool encode();

private:
    qint32 encodeFrame(qint32 frameNo);
    bool encodeField(qint32 fieldNo);
    void encodeLine(qint32 fieldNo, qint32 frameLine, const quint16 *rgbData, QVector<quint16> &outputLine);

    QFile &rgbFile;
    QFile &tbcFile;
    LdDecodeMetaData &metaData;

    LdDecodeMetaData::VideoParameters videoParameters;
    double fSC;
    qint32 activeWidth;
    qint32 activeHeight;
    qint32 activeLeft;
    qint32 activeTop;

    QByteArray rgbFrame;
    QVector<double> Y;
    QVector<double> U;
    QVector<double> V;
};

#endif
