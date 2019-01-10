/************************************************************************

    vbicorrector.cpp

    ld-process-vbi - VBI and IEC NTSC specific processor for ld-decode
    Copyright (C) 2018-2019 Simon Inns

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

    // Get the sound mode of the first frame
    LdDecodeMetaData::VbiSoundModes firstFieldSoundMode = ldDecodeMetaData.getField(firstField).vbi.soundMode;
    LdDecodeMetaData::VbiSoundModes secondFieldSoundMode = ldDecodeMetaData.getField(secondField).vbi.soundMode;

    bool correctSoundMode = true;
    if (firstFieldSoundMode != secondFieldSoundMode) {
        qInfo() << "Cannot determine the sound mode of the first frame - will not correct sound mode";
        correctSoundMode = false;
    }

    // Store the current sound mode
    LdDecodeMetaData::VbiSoundModes currentSoundMode = firstFieldSoundMode;

    // Create a back-up of the JSON metadata
    qInfo() << "This feature is experimental; creating a back-up of the JSON metadata...";
    QString outputFileName = inputFileName + ".json.bup";
    ldDecodeMetaData.write(outputFileName);

    // Check for any frames that are out of sequence (or have missing frame numbers) and try to guess the
    // frame number based on the adjacent frames
    // Note: Will not work correctly for NTSC will pull down (as the pull down frames have no frame number)
    qInfo() << "Checking for frame numbers that are out of sequence:";
    qint32 correctedFrameNumber;
    qint32 videoErrorCount = 0;
    qint32 audioErrorCount = 0;
    for (qint32 seqNumber = 2; seqNumber < ldDecodeMetaData.getNumberOfFrames(); seqNumber++) {
        firstField = ldDecodeMetaData.getFirstFieldNumber(seqNumber);
        secondField = ldDecodeMetaData.getSecondFieldNumber(seqNumber);

        LdDecodeMetaData::Field firstFieldData = ldDecodeMetaData.getField(firstField);
        LdDecodeMetaData::Field secondFieldData = ldDecodeMetaData.getField(secondField);

        // Video frame number correction
        // Try up to a distance of 5 frames to find the sequence
        for (qint32 gap = 1; gap < 5; gap++) {
            if (getFrameNumber(seqNumber) != (getFrameNumber(seqNumber - 1) + 1)) {
                if (getFrameNumber(seqNumber - 1) == (getFrameNumber(seqNumber + gap) - (gap + 1))) {
                    correctedFrameNumber = getFrameNumber(seqNumber - 1) + 1;

                    qInfo() << "Correction to seq. frame" << seqNumber << "[" << firstField
                            << "/" << secondField << "]:";
                    qInfo() << "  Seq. frame" << seqNumber - 1 << "has a VBI frame number of" << getFrameNumber(seqNumber -1);
                    qInfo() << "  Seq. frame" << seqNumber << "has a VBI frame number of" << getFrameNumber(seqNumber);
                    qInfo() << "  Seq. frame" << seqNumber + gap << "has a VBI frame number of" << getFrameNumber(seqNumber + gap);

                    qInfo() << "  VBI frame number corrected to" << correctedFrameNumber;
                    setFrameNumber(seqNumber, correctedFrameNumber);

                    videoErrorCount++;
                    break; // done
                }
            }
        }

        // Audio sound mode correction
        if (correctSoundMode) {
            firstFieldSoundMode = firstFieldData.vbi.soundMode;
            secondFieldSoundMode = secondFieldData.vbi.soundMode;

            // Do both fields have the same sound mode?
            if (firstFieldSoundMode != secondFieldSoundMode) {
                if (firstFieldData.vbi.soundMode == currentSoundMode) {
                    qInfo() << "  Seq. frame" << seqNumber << " does not have matching sound modes - using firstField data (matches current sound mode)";
                    secondFieldData.vbi.soundMode = firstFieldData.vbi.soundMode;

                    // Update the metadata
                    ldDecodeMetaData.updateField(secondFieldData, secondField);
                } else if (secondFieldData.vbi.soundMode == currentSoundMode) {
                    qInfo() << "  Seq. frame" << seqNumber << " does not have matching sound modes - using secondField data (matches current sound mode)";
                    firstFieldData.vbi.soundMode = secondFieldData.vbi.soundMode;

                    // Update the metadata
                    ldDecodeMetaData.updateField(firstFieldData, firstField);
                } else {
                    qInfo() << "  Seq. frame" << seqNumber << " does not have matching sound modes - using firstField data only (neither field matches current sound mode)";
                    secondFieldData.vbi.soundMode = firstFieldData.vbi.soundMode;

                    // Update the metadata
                    ldDecodeMetaData.updateField(secondFieldData, secondField);
                }

                audioErrorCount++;
            }

            // Does the current frame's sound mode match the previous frame's?
            if (firstFieldData.vbi.soundMode != currentSoundMode) {
                qInfo() << "  Seq. frame" << seqNumber << " sound mode does not match previous frame";

                // If the sound mode doesn't match it can be for one of two reasons; either the
                // sound mode has changed (which is very likely to remain changed for many frames) or
                // there is a glitch in the VBI data in which case the sound mode will jump around
                // randomly for a few frames.  Here we correct by taking the current fields's sound
                // mode and comparing it to a number of subsequent fields; if it is not consistent
                // we correct based on the sound mode of the previous frame.

                qint32 fieldsToCheck = 20;
                if ((seqNumber + fieldsToCheck) > ldDecodeMetaData.getNumberOfFields()) {
                    // We don't have enough remaining fields to do a full check
                    fieldsToCheck = ldDecodeMetaData.getNumberOfFields() - seqNumber;
                }

                qint32 matches = 0;
                for (qint32 counter = 1; counter < fieldsToCheck; counter++) {
                    if (ldDecodeMetaData.getField(firstField + counter).vbi.soundMode == firstFieldSoundMode) matches++;
                }

                if (matches > (fieldsToCheck / 2)) {
                    // Matched, change sound mode
                    currentSoundMode = firstFieldSoundMode;
                } else {
                    // Did not match, correct current sound mode
                    firstFieldData.vbi.soundMode = currentSoundMode;
                    secondFieldData.vbi.soundMode = currentSoundMode;

                    // Update the metadata
                    ldDecodeMetaData.updateField(firstFieldData, firstField);
                    ldDecodeMetaData.updateField(secondFieldData, secondField);

                    qInfo() << "  Seq. frame" << seqNumber << "corrected sound mode";

                    audioErrorCount++;
                }
            }
        }
    }

    // Only write out the new JSON file if frames were corrected
    if (videoErrorCount != 0 || audioErrorCount != 0) {
        qInfo() << "Corrected" << videoErrorCount << "VBI frame numbers and" << audioErrorCount << "sound modes - writing new JSON metadata file...";

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
