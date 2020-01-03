/************************************************************************

    discmap.cpp

    ld-discmap - TBC and VBI alignment and correction
    Copyright (C) 2019 Simon Inns

    This file is part of ld-decode-tools.

    ld-discmap is free software: you can redistribute it and/or
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

// Process the disc
bool DiscMap::process(QString inputFilename, QString outputFilename, bool reverse, bool mapOnly)
{
    if (!loadSource(inputFilename, reverse)) return false;
    if (!mapSource()) return false;
    if (!mapOnly) {
        if (!saveSource(outputFilename)) return false;
    }
    return true;
}

// Load the source TBC and JSON
bool DiscMap::loadSource(QString filename, bool reverse)
{
    LdDecodeMetaData::VideoParameters videoParameters;

    // Open the TBC metadata file
    qInfo() << "Loading JSON metadata...";
    if (!sourceMetaData.read(filename + ".json")) {
        // Open failed
        qInfo() << "Cannot load source - JSON metadata could not be read from" << filename;
        return false;
    }

    // Get the video parameters from the metadata
    videoParameters = sourceMetaData.getVideoParameters();

    // Ensure that the TBC metadata has VBI data
    if (!sourceMetaData.getFieldVbi(1).inUse) {
        qInfo() << "Cannot load source - No VBI data available. Please run ld-process-vbi before loading source!";
        return false;
    }

    // Open the source TBC video
    qInfo() << "Loading TBC file...";
    if (!sourceVideo.open(filename, videoParameters.fieldWidth * videoParameters.fieldHeight)) {
       // Open failed
       qInfo() << "Cannot load source - Error reading source TBC data file from" << filename;
       return false;
    }

    // If source is reverse-field order, set it up
    if (reverse) sourceMetaData.setIsFirstFieldFirst(false);
    else sourceMetaData.setIsFirstFieldFirst(true);

    return true;
}

// Map the source
bool DiscMap::mapSource()
{
    return vbiMapper.create(sourceMetaData);
}

// Save the target TBC and JSON
bool DiscMap::saveSource(QString filename)
{
    // Write the target files
    qInfo();
    qInfo() << "Writing TBC target file and JSON...";

    // Open the target video
    QFile targetVideo(filename);
    if (!targetVideo.open(QIODevice::WriteOnly)) {
            // Could not open target video file
            qInfo() << "Cannot save target - Error writing target TBC data file to" << filename;
            sourceVideo.close();
            return false;
    }

    // Generate the missing field dummy data
    QByteArray missingFieldData;
    missingFieldData.fill(0, sourceVideo.getFieldByteLength());

    // Create a target metadata object (using video and PCM audio settings from the source)
    LdDecodeMetaData targetMetadata;
    LdDecodeMetaData::VideoParameters sourceVideoParameters = sourceMetaData.getVideoParameters();

    // Indicate that the source has been mapped
    sourceVideoParameters.isMapped = true;
    targetMetadata.setVideoParameters(sourceVideoParameters);

    // Store the PCM audio parameters
    targetMetadata.setPcmAudioParameters(sourceMetaData.getPcmAudioParameters());

    // Process the fields
    QByteArray firstSourceField;
    QByteArray secondSourceField;
    bool writeFail = false;
    qint32 previousFrameNumber = -1;
    for (qint32 frameElement = 0; frameElement < vbiMapper.getNumberOfFrames(); frameElement++) {
        // Get the source frame field data
        if (vbiMapper.getFrame(frameElement).isMissing) {
            // Missing frame - generate dummy output
            if (!targetVideo.write(missingFieldData.data(), missingFieldData.size())) writeFail = true;
            if (!targetVideo.write(missingFieldData.data(), missingFieldData.size())) writeFail = true;

            // Generate dummy target field metadata
            LdDecodeMetaData::Field firstSourceMetadata;
            LdDecodeMetaData::Field secondSourceMetadata;
            firstSourceMetadata.isFirstField = true;
            secondSourceMetadata.isFirstField = false;
            firstSourceMetadata.pad = true;
            secondSourceMetadata.pad = true;

            // Generate VBI data for the dummy output frame
            if (vbiMapper.isDiscCav()) {
                // Disc is CAV - add a frame number
                // The frame number is hex 0xF12345 (where 1,2,3,4,5 are hex digits 0-9)
                // inserted into VBI lines 17 and 18 of the first field
                firstSourceMetadata.vbi.inUse = true;
                firstSourceMetadata.vbi.vbiData.resize(3);
                firstSourceMetadata.vbi.vbiData[0] = 0;
                firstSourceMetadata.vbi.vbiData[1] = convertFrameToVbi(vbiMapper.getFrame(frameElement).vbiFrameNumber);
                firstSourceMetadata.vbi.vbiData[2] = convertFrameToVbi(vbiMapper.getFrame(frameElement).vbiFrameNumber);
            } else {
                // Disc is CLV - add a timecode
                firstSourceMetadata.vbi.inUse = true;
                firstSourceMetadata.vbi.vbiData.resize(3);
                firstSourceMetadata.vbi.vbiData[0] = convertFrameToClvPicNo(vbiMapper.getFrame(frameElement).vbiFrameNumber);
                firstSourceMetadata.vbi.vbiData[1] = convertFrameToClvTimeCode(vbiMapper.getFrame(frameElement).vbiFrameNumber);
                firstSourceMetadata.vbi.vbiData[2] = convertFrameToClvTimeCode(vbiMapper.getFrame(frameElement).vbiFrameNumber);
            }

            targetMetadata.appendField(firstSourceMetadata);
            targetMetadata.appendField(secondSourceMetadata);
        } else {
            // Normal frame - get the data from the source video
            qint32 firstFieldNumber = vbiMapper.getFrame(frameElement).firstField;
            qint32 secondFieldNumber = vbiMapper.getFrame(frameElement).secondField;
            firstSourceField = sourceVideo.getVideoField(firstFieldNumber);
            secondSourceField = sourceVideo.getVideoField(secondFieldNumber);

            // Get the source metadata for the fields
            LdDecodeMetaData::Field firstSourceMetadata = sourceMetaData.getField(firstFieldNumber);
            LdDecodeMetaData::Field secondSourceMetadata = sourceMetaData.getField(secondFieldNumber);

            // Check if VBI is valid
            if (vbiMapper.getFrame(frameElement).isCorruptVbi) {
                // Generate new VBI data for the frame
                if (!firstSourceMetadata.vbi.inUse) {
                    firstSourceMetadata.vbi.inUse = true;
                    firstSourceMetadata.vbi.vbiData.resize(3);
                } 

                qDebug() << "Writing new VBI data for sequential frame" << frameElement <<
                            "- new VBI frame number is" << vbiMapper.getFrame(frameElement).vbiFrameNumber;
                if (vbiMapper.isDiscCav()) {
                    firstSourceMetadata.vbi.vbiData[0] = 0;
                    firstSourceMetadata.vbi.vbiData[1] = convertFrameToVbi(vbiMapper.getFrame(frameElement).vbiFrameNumber);
                    firstSourceMetadata.vbi.vbiData[2] = convertFrameToVbi(vbiMapper.getFrame(frameElement).vbiFrameNumber);
                } else {
                    firstSourceMetadata.vbi.vbiData[0] = convertFrameToClvPicNo(vbiMapper.getFrame(frameElement).vbiFrameNumber);
                    firstSourceMetadata.vbi.vbiData[1] = convertFrameToClvTimeCode(vbiMapper.getFrame(frameElement).vbiFrameNumber);
                    firstSourceMetadata.vbi.vbiData[2] = convertFrameToClvTimeCode(vbiMapper.getFrame(frameElement).vbiFrameNumber);
                }
            }

            // Write the fields into the output TBC file in the same order as the source file
            if (firstFieldNumber < secondFieldNumber) {
                // Save the first field and then second field to the output file
                if (!targetVideo.write(firstSourceField.data(), firstSourceField.size())) writeFail = true;
                if (!targetVideo.write(secondSourceField.data(), secondSourceField.size())) writeFail = true;

                // Add the metadata
                targetMetadata.appendField(firstSourceMetadata);
                targetMetadata.appendField(secondSourceMetadata);
            } else {
                // Save the second field and then first field to the output file
                if (!targetVideo.write(secondSourceField.data(), secondSourceField.size())) writeFail = true;
                if (!targetVideo.write(firstSourceField.data(), firstSourceField.size())) writeFail = true;

                // Add the metadata
                targetMetadata.appendField(secondSourceMetadata);
                targetMetadata.appendField(firstSourceMetadata);
            }
        }

        // Was the write successful?
        if (writeFail) {
            // Could not write to target TBC file
            qInfo() << "Writing fields to the target TBC file failed for sequential frame#" << frameElement;
            targetVideo.close();
            sourceVideo.close();
            return false;
        }

        // Check frames are sequential
        if (frameElement > 1) {
            if (vbiMapper.getFrame(frameElement).vbiFrameNumber != previousFrameNumber + 1) {
                qInfo() << "Warning! VBI frame numbers are not sequential - something has gone wrong";
            }
        }
        previousFrameNumber = vbiMapper.getFrame(frameElement).vbiFrameNumber;

        if (frameElement % 500 == 0) {
            if (vbiMapper.isDiscCav()) {
                qInfo().nospace() << "Written frame# " << frameElement << " (with VBI frame# " << vbiMapper.getFrame(frameElement).vbiFrameNumber << ")";
            } else {
                LdDecodeMetaData::ClvTimecode timecode = sourceMetaData.convertFrameNumberToClvTimecode(vbiMapper.getFrame(frameElement).vbiFrameNumber);
                qInfo().nospace().noquote() << "Written frame# " << frameElement << " (with VBI time code " <<
                                     QString("%1").arg(timecode.hours, 1, 10, QChar('0')) << ":" <<
                                     QString("%1").arg(timecode.minutes, 2, 10, QChar('0')) << ":" <<
                                     QString("%1").arg(timecode.seconds, 2, 10, QChar('0')) << "." <<
                                     QString("%1").arg(timecode.pictureNumber, 2, 10, QChar('0')) << ")";
            }
        }
    }

    // Write the JSON metadata
    qInfo() << "Creating JSON metadata file for target TBC file";
    targetMetadata.write(filename + ".json");

    // Close the source and target video files
    targetVideo.close();
    sourceVideo.close();

    qInfo() << "Process complete";

    return true;
}

// Convert a frame number to the VBI hex frame number representation
// See the IEC specification for details of the VBI format
qint32 DiscMap::convertFrameToVbi(qint32 frameNumber)
{
    // Generate a string containing the required number
    QString number = "00F" + QString("%1").arg(frameNumber, 5, 10, QChar('0'));
    bool ok;
    qint32 returnValue = number.toInt(&ok, 16);
    if (!ok) returnValue = 0;

    return returnValue;
}

// Convert a frame number to a VBI CLV picture number
// See the IEC specification for details of the VBI format
qint32 DiscMap::convertFrameToClvPicNo(qint32 frameNumber)
{
    // Convert the frame number into a CLV timecode
    LdDecodeMetaData::ClvTimecode timecode = sourceMetaData.convertFrameNumberToClvTimecode(frameNumber);

    // Generate the seconds
    qint32 secondsX1;
    if (timecode.seconds % 10 == 0) secondsX1 = timecode.seconds;
    else secondsX1 = (timecode.seconds - (timecode.seconds % 10));
    qint32 secondsX3 = timecode.seconds - secondsX1;
    secondsX1 = ((secondsX1 + 10) / 10) + 9;

    // Generate a string containing the required number
    QString number = "008" + QString("%1").arg(secondsX1, 1, 16, QChar('0')) + "E" +
            QString("%1").arg(secondsX3, 1, 10, QChar('0')) +
            QString("%1").arg(timecode.pictureNumber, 2, 10, QChar('0'));
    bool ok;
    qint32 returnValue = number.toInt(&ok, 16);
    if (!ok) returnValue = 0;

//    qInfo().nospace().noquote() << "Replaced picture number VBI - Frame number is " << frameNumber << " CLV time code is " <<
//                         QString("%1").arg(timecode.hours, 2, 10, QChar('0')) << ":" <<
//                         QString("%1").arg(timecode.minutes, 2, 10, QChar('0')) << ":" <<
//                         QString("%1").arg(timecode.seconds, 2, 10, QChar('0')) << "." <<
//                         QString("%1").arg(timecode.pictureNumber, 2, 10, QChar('0')) <<
//                         " VBI data is " << returnValue;

    return returnValue;
}

// Convert a frame number to a CLV programme time code
// See the IEC specification for details of the VBI format
qint32 DiscMap::convertFrameToClvTimeCode(qint32 frameNumber)
{
    // Convert the frame number into a CLV timecode
    LdDecodeMetaData::ClvTimecode timecode = sourceMetaData.convertFrameNumberToClvTimecode(frameNumber);

    // Generate a string containing the required number
    QString number = "00F" + QString("%1").arg(timecode.hours, 1, 10, QChar('0')) + "DD" +
            QString("%1").arg(timecode.minutes, 2, 10, QChar('0'));
    bool ok;
    qint32 returnValue = number.toInt(&ok, 16);
    if (!ok) returnValue = 0;

//    qInfo().nospace().noquote() << "Replaced CLV timecode VBI - Frame number is " << frameNumber << " CLV time code is " <<
//                         QString("%1").arg(timecode.hours, 2, 10, QChar('0')) << ":" <<
//                         QString("%1").arg(timecode.minutes, 2, 10, QChar('0')) << ":" <<
//                         QString("%1").arg(timecode.seconds, 2, 10, QChar('0')) << "." <<
//                         QString("%1").arg(timecode.pictureNumber, 2, 10, QChar('0')) <<
//                         " VBI data is " << returnValue;

    return returnValue;
}
