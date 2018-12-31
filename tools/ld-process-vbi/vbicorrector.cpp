/************************************************************************

    vbicorrector.cpp

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

#include "vbicorrector.h"

VbiCorrector::VbiCorrector(QObject *parent) : QObject(parent)
{

}

bool VbiCorrector::process(QString inputFileName)
{
    // Open the source video metadata
    if (!ldDecodeMetaData.read(inputFileName + ".json")) {
        qInfo() << "Unable to open ld-decode metadata file";
        return false;
    }

    LdDecodeMetaData::VideoParameters videoParameters = ldDecodeMetaData.getVideoParameters();

    qDebug() << "VbiCorrector::process(): Input source is" << videoParameters.fieldWidth << "x" << videoParameters.fieldHeight << "filename" << inputFileName;

    // There must be at least 2 frames to process in the input TBC
    if (ldDecodeMetaData.getNumberOfFrames() < 2) {
        qCritical() << "The source TBC contains less than 2 frames... Cannot perform correction!";
        return false;
    }

    // Get the first frame number

    // Get the first and second field numbers for the frame
    qint32 firstField = ldDecodeMetaData.getFirstFieldNumber(1);
    qint32 secondField = ldDecodeMetaData.getSecondFieldNumber(1);

    // Determine the field number from the VBI
    LdDecodeMetaData::Field firstFieldData = ldDecodeMetaData.getField(firstField);
    LdDecodeMetaData::Field secondFieldData = ldDecodeMetaData.getField(secondField);

    qint32 firstFrameNumber;
    if (firstFieldData.vbi.inUse && firstFieldData.vbi.picNo != -1) {
        // Got frame number from the first field
        firstFrameNumber = ldDecodeMetaData.getField(firstField).vbi.picNo;
    } else if (secondFieldData.vbi.inUse && secondFieldData.vbi.picNo != -1) {
        // Got frame number from the second field
        firstFrameNumber = ldDecodeMetaData.getField(secondField).vbi.picNo;
    } else {
        // No frame number was found...
        qCritical() << "Unable to get initial frame number (no VBI data in JSON metadata?)... Cannot perform correction!";
        return false;
    }
    qInfo() << "Determined first frame number to be #" << firstFrameNumber;

    // Create a back-up of the JSON metadata
    qInfo() << "This feature is experimental; creating a back-up of the JSON metadata...";
    QString outputFileName = inputFileName + ".json.bup";
    ldDecodeMetaData.write(outputFileName);

    // Check for any frames that are out of sequence (or have missing frame numbers) and try to guess the
    // frame number based on the adjacent frames
    // Note: Will not work correctly for NTSC will pull down (as the pull down frames have no frame number)
    qInfo() << "Checking for frame numbers that are out of sequence:";
    qint32 correctedFrameNumber;
    qint32 errorCount = 0;
    for (qint32 seqNumber = 2; seqNumber < ldDecodeMetaData.getNumberOfFrames(); seqNumber++) {
        // Try up to a distance of 5 frames to find the sequence
        for (qint32 gap = 1; gap < 5; gap++) {
            if (getFrameNumber(seqNumber) != (getFrameNumber(seqNumber - 1) + 1)) {
                if (getFrameNumber(seqNumber - 1) == (getFrameNumber(seqNumber + gap) - (gap + 1))) {
                    correctedFrameNumber = getFrameNumber(seqNumber - 1) + 1;

                    qInfo() << "Correction to seq. frame" << seqNumber << "[" << ldDecodeMetaData.getFirstFieldNumber(seqNumber)
                            << "/" << ldDecodeMetaData.getSecondFieldNumber(seqNumber) << "]:";
                    qInfo() << "  Seq. frame" << seqNumber - 1 << "has a VBI frame number of" << getFrameNumber(seqNumber -1);
                    qInfo() << "  Seq. frame" << seqNumber << "has a VBI frame number of" << getFrameNumber(seqNumber);
                    qInfo() << "  Seq. frame" << seqNumber + gap << "has a VBI frame number of" << getFrameNumber(seqNumber + gap);

                    qInfo() << "  VBI frame number corrected to" << correctedFrameNumber;
                    setFrameNumber(seqNumber, correctedFrameNumber);

                    errorCount++;
                    break; // done
                }
            }
        }
    }

    // Only write out the new JSON file if frames were corrected
    if (errorCount != 0) {
        qInfo() << "Corrected" << errorCount << "VBI frame numbers - writing new JSON metadata file...";

        // Back-up the metadata file
        outputFileName = inputFileName + ".json";
        ldDecodeMetaData.write(outputFileName);
    } else {
        qInfo() << "No VBI frame numbers were corrected.";
    }

    qInfo() << "Processing complete";
    return true;
}

// Method to get the VBI frame number based on the sequential frame number (of the .tbc file)
qint32 VbiCorrector::getFrameNumber(qint32 frameSeqNumber)
{
    // Get the first and second field numbers for the frame
    qint32 firstField = ldDecodeMetaData.getFirstFieldNumber(frameSeqNumber);
    qint32 secondField = ldDecodeMetaData.getSecondFieldNumber(frameSeqNumber);

    // Determine the field number from the VBI
    LdDecodeMetaData::Field firstFieldData = ldDecodeMetaData.getField(firstField);
    LdDecodeMetaData::Field secondFieldData = ldDecodeMetaData.getField(secondField);

    qint32 frameNumber = -1;
    if (firstFieldData.vbi.inUse && firstFieldData.vbi.picNo != -1) {
        // Got frame number from the first field
        frameNumber = ldDecodeMetaData.getField(firstField).vbi.picNo;
    } else if (secondFieldData.vbi.inUse && secondFieldData.vbi.picNo != -1) {
        // Got frame number from the second field
        frameNumber = ldDecodeMetaData.getField(secondField).vbi.picNo;
    } else {
        // Couldn't get a frame number for the sequential frame number
        frameNumber = -1;
    }

    return frameNumber;
}

// Method to set the VBI frame number based on the sequential frame number (of the .tbc file)
void VbiCorrector::setFrameNumber(qint32 frameSeqNumber, qint32 vbiFrameNumber)
{
    // Get the first and second field numbers for the frame
    qint32 firstField = ldDecodeMetaData.getFirstFieldNumber(frameSeqNumber);
    qint32 secondField = ldDecodeMetaData.getSecondFieldNumber(frameSeqNumber);

    // Determine the field number from the VBI
    LdDecodeMetaData::Field firstFieldData = ldDecodeMetaData.getField(firstField);
    LdDecodeMetaData::Field secondFieldData = ldDecodeMetaData.getField(secondField);

    if (firstFieldData.vbi.inUse && firstFieldData.vbi.picNo != -1) {
        // VBI Frame number is in the first field
        firstFieldData.vbi.picNo = vbiFrameNumber;
    } else if (secondFieldData.vbi.inUse && secondFieldData.vbi.picNo != -1) {
        // VBI Frame number is in the second field
        secondFieldData.vbi.picNo = vbiFrameNumber;
    } else {
        // Couldn't get a frame number for the sequential frame number
        // So we'll use isFirstField to identify the most likely target field
        if (firstFieldData.isFirstField) firstFieldData.vbi.picNo = vbiFrameNumber;
        else secondFieldData.vbi.picNo = vbiFrameNumber;
    }

    // Update the metadata
    ldDecodeMetaData.updateField(firstFieldData, firstField);
    ldDecodeMetaData.updateField(secondFieldData, secondField);
}
