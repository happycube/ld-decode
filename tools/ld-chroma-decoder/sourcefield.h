/************************************************************************

    sourcefield.h

    ld-chroma-decoder - Colourisation filter for ld-decode
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

#ifndef SOURCEFIELD_H
#define SOURCEFIELD_H

#include <QByteArray>

#include "lddecodemetadata.h"

class SourceVideo;

// A field read from the input, with metadata and data
struct SourceField {
    LdDecodeMetaData::Field field;
    QByteArray data;

    // Load a sequence of frames from the input files.
    //
    // fields will contain {lookbehind fields... [startIndex] real fields... [endIndex] lookahead fields...}.
    // Fields requested outside the bounds of the file will have dummy metadata and black data.
    static void loadFields(SourceVideo &sourceVideo, LdDecodeMetaData &ldDecodeMetaData,
                           qint32 firstFrameNumber, qint32 numFrames,
                           qint32 lookBehindFrames, qint32 lookAheadFrames,
                           QVector<SourceField> &fields, qint32 &startIndex, qint32 &endIndex);

    // Return the vertical offset of this field within the interlaced frame
    // (i.e. 0 for the top field, 1 for the bottom field).
    qint32 getOffset() const {
        return field.isFirstField ? 0 : 1;
    }

    // Return the first/last active line numbers within this field's data,
    // given the first/last frame line numbers.
    qint32 getFirstActiveLine(qint32 firstActiveFrameLine) const {
        return (firstActiveFrameLine + 1 - getOffset()) / 2;
    }
    qint32 getLastActiveLine(qint32 lastActiveFrameLine) const {
        return (lastActiveFrameLine + 1 - getOffset()) / 2;
    }
};

#endif
