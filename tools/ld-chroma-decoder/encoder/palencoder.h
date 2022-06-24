/************************************************************************

    palencoder.h

    ld-chroma-encoder - Composite video encoder
    Copyright (C) 2019-2022 Adam Sampson

    This file is part of ld-decode-tools.

    ld-chroma-encoder is free software: you can redistribute it and/or
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

#include <QFile>
#include <QVector>

#include "lddecodemetadata.h"

#include "encoder.h"

class PALEncoder : public Encoder
{
public:
    PALEncoder(QFile &rgbFile, QFile &tbcFile, LdDecodeMetaData &metaData, bool scLocked);

private:
    virtual void getFieldMetadata(qint32 fieldNo, LdDecodeMetaData::Field &fieldData);
    virtual void encodeLine(qint32 fieldNo, qint32 frameLine, const quint16 *rgbData, QVector<quint16> &outputLine);

    bool scLocked;

    QVector<double> Y;
    QVector<double> U;
    QVector<double> V;
};

#endif
