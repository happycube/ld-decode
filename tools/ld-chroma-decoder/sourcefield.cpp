/************************************************************************

    sourcefield.cpp

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

#include "sourcefield.h"

#include "sourcevideo.h"

void SourceField::loadFields(SourceVideo &sourceVideo, LdDecodeMetaData &ldDecodeMetaData,
                             qint32 firstFrameNumber, qint32 numFrames,
                             qint32 lookBehindFrames, qint32 lookAheadFrames,
                             QVector<SourceField> &fields, qint32 &startIndex, qint32 &endIndex)
{
    // Work out indexes.
    // fields will contain {lookbehind fields... [startIndex] real fields... [endIndex] lookahead fields...}.
    startIndex = 2 * lookBehindFrames;
    endIndex = startIndex + (2 * numFrames);
    fields.resize(endIndex + (2 * lookAheadFrames));

    // Populate fields
    const qint32 numInputFrames = ldDecodeMetaData.getNumberOfFrames();
    qint32 frameNumber = firstFrameNumber - lookBehindFrames;
    for (qint32 i = 0; i < fields.size(); i += 2) {

        // Is this frame outside the bounds of the input file?
        // If so, use real metadata (from frame 1) and black fields.
        const bool useBlankFrame = frameNumber < 1 || frameNumber > numInputFrames;

        // Get the first frame from the file (using frame 1 if outside bounds)
        qint32 firstFieldNumber = ldDecodeMetaData.getFirstFieldNumber(useBlankFrame ? 1 : frameNumber);
        qint32 secondFieldNumber = ldDecodeMetaData.getSecondFieldNumber(useBlankFrame ? 1 : frameNumber);

        // Fetch the input metadata
        fields[i].field = ldDecodeMetaData.getField(firstFieldNumber);
        fields[i + 1].field = ldDecodeMetaData.getField(secondFieldNumber);

        if (useBlankFrame) {
            // Fill both fields with black
            const quint16 black = ldDecodeMetaData.getVideoParameters().black16bIre;
            fields[i].data.fill(black, sourceVideo.getFieldLength());
            fields[i + 1].data.fill(black, sourceVideo.getFieldLength());
        } else {
            // Fetch the input fields
            fields[i].data = sourceVideo.getVideoField(firstFieldNumber);
            fields[i + 1].data = sourceVideo.getVideoField(secondFieldNumber);
        }

        frameNumber++;
    }
}
