/************************************************************************

    ntscencoder.h

    ld-chroma-encoder - NTSC encoder for testing
    Copyright (C) 2019 Adam Sampson
    Copyright (C) 2022 Phillip Blucas

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

#ifndef NTSCENCODER_H
#define NTSCENCODER_H

#include <QByteArray>
#include <QFile>
#include <QVector>

#include "lddecodemetadata.h"

enum ChromaMode {
    WIDEBAND_YUV = 0,   // Y'UV
    WIDEBAND_YIQ,       // Y'IQ
};

class NTSCEncoder
{
public:
    NTSCEncoder(QFile &rgbFile, QFile &tbcFile, LdDecodeMetaData &metaData, ChromaMode &chromaMode, bool &addSetup);

    // Encode RGB stream to NTSC.
    // Returns true on success; on failure, prints an error and returns false.
    bool encode();

private:
    qint32 encodeFrame(qint32 frameNo);
    bool encodeField(qint32 fieldNo);
    void encodeLine(qint32 fieldNo, qint32 frameLine, const quint16 *rgbData, QVector<quint16> &outputLine);

    const qint32 blankingIre = 0x3C00;
    const qint32 setupIreOffset = 0x0A80; // 10.5 * 256

    QFile &rgbFile;
    QFile &tbcFile;
    LdDecodeMetaData &metaData;
    ChromaMode chromaMode;
    bool addSetup;

    LdDecodeMetaData::VideoParameters videoParameters;
    qint32 activeWidth;
    qint32 activeHeight;
    qint32 activeLeft;
    qint32 activeTop;

    QByteArray rgbFrame;
    QVector<double> Y;
    QVector<double> C1;
    QVector<double> C2;
};

#endif
