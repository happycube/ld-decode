/************************************************************************

    discmap.cpp

    ld-combine - TBC combination and enhancement tool
    Copyright (C) 2019 Simon Inns

    This file is part of ld-decode-tools.

    ld-combine is free software: you can redistribute it and/or
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

#include "discmap.h"

DiscMap::DiscMap(QObject *parent) : QObject(parent)
{

}

// Public methods -----------------------------------------------------------------------------------------------------

bool DiscMap::create(LdDecodeMetaData &ldDecodeMetaData)
{
    if (!sanityCheck(ldDecodeMetaData)) return false;
    createInitialMap(ldDecodeMetaData);
    correctFrameNumbering(ldDecodeMetaData);
    removeDuplicateFrames(ldDecodeMetaData);
    detectMissingFrames(ldDecodeMetaData);

    return true;
}

// Private methods ----------------------------------------------------------------------------------------------------

bool DiscMap::sanityCheck(LdDecodeMetaData &ldDecodeMetaData)
{
    return true;
}

bool DiscMap::createInitialMap(LdDecodeMetaData &ldDecodeMetaData)
{
    qDebug() << "DiscMap::createInitialMap(): Creating initial map...";
    VbiDecoder vbiDecoder;
    qint32 missingFrameNumbers = 0;
    qint32 leadInOrOutFrames = 0;

    for (qint32 i = 1; i <= ldDecodeMetaData.getNumberOfFrames(); i++) {
        Frame frame;
        // Get the required field numbers
        frame.firstField = ldDecodeMetaData.getFirstFieldNumber(i);
        frame.secondField = ldDecodeMetaData.getSecondFieldNumber(i);

        // Default the other parameters
        frame.isMissing = false;
        frame.isLeadInOrOut = false;

        // Get the VBI data and then decode
        QVector<qint32> vbi1 = ldDecodeMetaData.getFieldVbi(frame.firstField).vbiData;
        QVector<qint32> vbi2 = ldDecodeMetaData.getFieldVbi(frame.secondField).vbiData;
        VbiDecoder::Vbi vbi = vbiDecoder.decodeFrame(vbi1[0], vbi1[1], vbi1[2], vbi2[0], vbi2[1], vbi2[2]);

        // Check for lead in or out frame
        if (vbi.leadIn || vbi.leadOut) {
            frame.isLeadInOrOut = true;
            frame.vbiFrameNumber = -1;
            leadInOrOutFrames++;
        } else {
            // Check if we have a valid CAV picture number, if not, translated the CLV
            // timecode into a frame number (we only want to deal with one frame identifier in
            // the disc map)
            if (vbi.picNo > 0) {
                // Valid CAV picture number
                frame.vbiFrameNumber = vbi.picNo;
            } else {
                // Attempt to translate the CLV timecode into a frame number
                LdDecodeMetaData::ClvTimecode clvTimecode;
                clvTimecode.hours = vbi.clvHr;
                clvTimecode.minutes = vbi.clvMin;
                clvTimecode.seconds = vbi.clvSec;
                clvTimecode.pictureNumber = vbi.clvPicNo;

                frame.vbiFrameNumber = ldDecodeMetaData.convertClvTimecodeToFrameNumber(clvTimecode);

                // If this fails the frame number will be -1 to indicate that it's not valid,
                // but just in case
                if (frame.vbiFrameNumber < 1) frame.vbiFrameNumber = -1;

                // Count the missing frame numbers
                if (frame.vbiFrameNumber < 1) missingFrameNumbers++;
            }
        }
    }

    qDebug() << "DiscMap::createInitialMap(): Initial map created.  Got" << ldDecodeMetaData.getNumberOfFrames() <<
                "frames with" << missingFrameNumbers << "missing frame numbers and" <<
                leadInOrOutFrames << "Lead in/out frames";
    return true;
}

void DiscMap::correctFrameNumbering(LdDecodeMetaData &ldDecodeMetaData)
{

}

void DiscMap::removeDuplicateFrames(LdDecodeMetaData &ldDecodeMetaData)
{

}

void DiscMap::detectMissingFrames(LdDecodeMetaData &ldDecodeMetaData)
{

}
