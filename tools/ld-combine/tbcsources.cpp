/************************************************************************

    tbcsources.cpp

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

#include "tbcsources.h"

TbcSources::TbcSources(QObject *parent) : QObject(parent)
{
    currentSource = 0;
    currentVbiFrameNumber = 1;
}

// Load a TBC source video; returns false on failure
bool TbcSources::loadSource(QString filename, bool reverse)
{
    // Check that source file isn't already loaded
    for (qint32 i = 0; i < sourceVideos.size(); i++) {
        if (filename == sourceVideos[i]->filename) {
            qCritical() << "Cannot load source - source is already loaded!";
            return false;
        }
    }

    bool loadSuccessful = true;
    sourceVideos.resize(sourceVideos.size() + 1);
    qint32 newSourceNumber = sourceVideos.size() - 1;
    sourceVideos[newSourceNumber] = new Source;
    LdDecodeMetaData::VideoParameters videoParameters;

    // Open the TBC metadata file
    qInfo() << "Processing input TBC JSON metadata...";
    if (!sourceVideos[newSourceNumber]->ldDecodeMetaData.read(filename + ".json")) {
        // Open failed
        qWarning() << "Open TBC JSON metadata failed for filename" << filename;
        qCritical() << "Cannot load source - JSON metadata could not be read!";

        delete sourceVideos[newSourceNumber];
        sourceVideos.remove(newSourceNumber);
        currentSource = 0;
        return false;
    }

    // Set the source as reverse field order if required
    if (reverse) sourceVideos[newSourceNumber]->ldDecodeMetaData.setIsFirstFieldFirst(false);

    // Get the video parameters from the metadata
    videoParameters = sourceVideos[newSourceNumber]->ldDecodeMetaData.getVideoParameters();

    // Ensure that the TBC file has been mapped
    if (!videoParameters.isMapped) {
        qWarning() << "New source video has not been mapped!";
        qCritical() << "Cannot load source - The TBC has not been mapped (please run ld-discmap on the source)!";
        loadSuccessful = false;
    }

    // Ensure that the video standard matches any existing sources
    if (loadSuccessful) {
        if ((sourceVideos.size() - 1 > 0) && (sourceVideos[0]->ldDecodeMetaData.getVideoParameters().isSourcePal != videoParameters.isSourcePal)) {
            qWarning() << "New source video standard does not match existing source(s)!";
            qCritical() << "Cannot load source - Mixing PAL and NTSC sources is not supported!";
            loadSuccessful = false;
        }
    }

    if (videoParameters.isSourcePal) qInfo() << "Video format is PAL"; else qInfo() << "Video format is NTSC";

    // Ensure that the video has VBI data
    if (loadSuccessful) {
        if (!sourceVideos[newSourceNumber]->ldDecodeMetaData.getFieldVbi(1).inUse) {
            qWarning() << "New source video does not contain VBI data!";
            qCritical() << "Cannot load source - No VBI data available. Please run ld-process-vbi before loading source!";
            loadSuccessful = false;
        }
    }

    // Determine the minimum and maximum VBI frame number and the disc type
    if (loadSuccessful) {
        qInfo() << "Determining input TBC disc type and VBI frame range...";
        if (!setDiscTypeAndMaxMinFrameVbi(newSourceNumber)) {
            // Failed
            qCritical() << "Cannot load source - Could not determine disc type and/or VBI frame range!";
            loadSuccessful = false;
        }
    }

    // Open the new source TBC video
    if (loadSuccessful) {
        qInfo() << "Loading input TBC video data...";
        if (!sourceVideos[newSourceNumber]->sourceVideo.open(filename, videoParameters.fieldWidth * videoParameters.fieldHeight)) {
           // Open failed
           qWarning() << "Open TBC file failed for filename" << filename;
           qCritical() << "Cannot load source - Error reading source TBC data file!";
           loadSuccessful = false;
        }
    }

    // Finish up
    if (loadSuccessful) {
        // Loading successful
        sourceVideos[newSourceNumber]->filename = filename;
        loadSuccessful = true;
    } else {
        // Loading unsuccessful - Remove the new source entry and default the current source
        sourceVideos[newSourceNumber]->sourceVideo.close();
        delete sourceVideos[newSourceNumber];
        sourceVideos.remove(newSourceNumber);
        currentSource = 0;
        return false;
    }

    // Select the new source
    currentSource = newSourceNumber;

    return true;
}

// Unload a source video and remove it's data
bool TbcSources::unloadSource()
{
    sourceVideos[currentSource]->sourceVideo.close();
    delete sourceVideos[currentSource];
    sourceVideos.remove(currentSource);
    currentSource = 0;

    return false;
}

// Get the number of available sources
qint32 TbcSources::getNumberOfAvailableSources()
{
    return sourceVideos.size();
}

// Get the minimum VBI frame number for all sources
qint32 TbcSources::getMinimumVbiFrameNumber()
{
    qint32 minimumFrameNumber = 1000000;
    for (qint32 i = 0; i < sourceVideos.size(); i++) {
        if (sourceVideos[i]->minimumVbiFrameNumber < minimumFrameNumber)
            minimumFrameNumber = sourceVideos[i]->minimumVbiFrameNumber;
    }

    return minimumFrameNumber;
}

// Get the maximum VBI frame number for all sources
qint32 TbcSources::getMaximumVbiFrameNumber()
{
    qint32 maximumFrameNumber = 0;
    for (qint32 i = 0; i < sourceVideos.size(); i++) {
        if (sourceVideos[i]->maximumVbiFrameNumber > maximumFrameNumber)
            maximumFrameNumber = sourceVideos[i]->maximumVbiFrameNumber;
    }

    return maximumFrameNumber;
}

// Save the combined sources
bool TbcSources::saveSource(QString outputFilename, qint32 vbiStartFrame, qint32 length, qint32 dodThreshold)
{
    // Open the target
    qInfo() << "Writing TBC target file and JSON...";

    // Open the target video
    QFile targetVideo(outputFilename);
    if (!targetVideo.open(QIODevice::WriteOnly)) {
        // Could not open target video file
        qInfo() << "Cannot save target - Error writing target TBC data file to" << outputFilename;
        return false;
    }

    // Create a target metadata object (using video and PCM audio settings from the source)
    LdDecodeMetaData targetMetadata;
    LdDecodeMetaData::VideoParameters targetVideoParameters = sourceVideos[0]->ldDecodeMetaData.getVideoParameters();

    // Set the number of sequential fields in the target TBC
    targetVideoParameters.numberOfSequentialFields = length * 2;

    // Indicate that the source has been mapped
    targetVideoParameters.isMapped = true;
    targetMetadata.setVideoParameters(targetVideoParameters);

    // Store the PCM audio parameters
    targetMetadata.setPcmAudioParameters(sourceVideos[0]->ldDecodeMetaData.getPcmAudioParameters());

    // Process the target
    for (qint32 vbiFrame = vbiStartFrame; vbiFrame < vbiStartFrame + length; vbiFrame++) {
        if ((vbiFrame % 100 == 0) || (vbiFrame == vbiStartFrame)) qInfo() << "Processing VBI frame" << vbiFrame;
        CombinedFrame combinedFrame = combineFrame(vbiFrame, dodThreshold);

        // Store the field metadata
        targetMetadata.appendField(combinedFrame.firstFieldMetadata);
        targetMetadata.appendField(combinedFrame.secondFieldMetadata);

        // Store the video data
        bool writeFail = false;
        if (!targetVideo.write(combinedFrame.firstFieldData.data(), combinedFrame.firstFieldData.size())) writeFail = true;
        if (!targetVideo.write(combinedFrame.secondFieldData.data(), combinedFrame.secondFieldData.size())) writeFail = true;

        // Was the write successful?
        if (writeFail) {
            // Could not write to target TBC file
            qInfo() << "Writing fields to the target TBC file failed!";
            targetVideo.close();
            return false;
        }
    }

    // Write the JSON metadata
    qInfo() << "Creating JSON metadata file for target TBC file";
    targetMetadata.write(outputFilename + ".json");

    // Close the target video file
    targetVideo.close();

    qInfo() << "Process complete";
    return true;
}

// Private methods ----------------------------------------------------------------------------------------------------

// Perform differential dropout detection to determine (for each source) which frame pixels are valid
// Perform frame combination using an average of all available (good) source pixels
// Pixels with no good source are marked as dropouts in the target TBC's metadata
TbcSources::CombinedFrame TbcSources::combineFrame(qint32 targetVbiFrame, qint32 threshold)
{
    CombinedFrame combinedFrame;

    // Range check the threshold
    if (threshold < 100) threshold = 100;
    if (threshold > 65435) threshold = 65435;

    // Check how many source frames are available for the current frame
    QVector<qint32> availableSourceFrames;
    for (qint32 sourceNumber = 0; sourceNumber < sourceVideos.size(); sourceNumber++) {
        if (targetVbiFrame >= sourceVideos[sourceNumber]->minimumVbiFrameNumber && targetVbiFrame <= sourceVideos[sourceNumber]->maximumVbiFrameNumber) {
            // Get the required field numbers
            qint32 firstFieldNumber = sourceVideos[sourceNumber]->ldDecodeMetaData.getFirstFieldNumber(convertVbiFrameNumberToSequential(targetVbiFrame, sourceNumber));
            qint32 secondFieldNumber = sourceVideos[sourceNumber]->ldDecodeMetaData.getSecondFieldNumber(convertVbiFrameNumberToSequential(targetVbiFrame, sourceNumber));

            // Ensure the frame is not a padded field (i.e. missing)
            if (!(sourceVideos[sourceNumber]->ldDecodeMetaData.getField(firstFieldNumber).pad &&
                  sourceVideos[sourceNumber]->ldDecodeMetaData.getField(secondFieldNumber).pad)) {
                availableSourceFrames.append(sourceNumber);
            }
        }
    }

    // If there are no frames available, output a dummy frame
    if (availableSourceFrames.size() == 0) {
        qInfo() << "No source frames are available - can not perform combination for VBI frame" << targetVbiFrame;

        // All available fields are dummy - so just use the first source
        qint32 firstFieldNumber = sourceVideos[0]->ldDecodeMetaData.getFirstFieldNumber(convertVbiFrameNumberToSequential(targetVbiFrame, 0));
        qint32 secondFieldNumber = sourceVideos[0]->ldDecodeMetaData.getSecondFieldNumber(convertVbiFrameNumberToSequential(targetVbiFrame, 0));

        combinedFrame.firstFieldData = sourceVideos[availableSourceFrames[0]]->sourceVideo.getVideoField(firstFieldNumber);
        combinedFrame.secondFieldData = sourceVideos[availableSourceFrames[0]]->sourceVideo.getVideoField(secondFieldNumber);
        combinedFrame.firstFieldMetadata = sourceVideos[availableSourceFrames[0]]->ldDecodeMetaData.getField(firstFieldNumber);
        combinedFrame.secondFieldMetadata = sourceVideos[availableSourceFrames[0]]->ldDecodeMetaData.getField(secondFieldNumber);

        return combinedFrame;
    }

    // Combination requires at least three source frames, if there are less then output the first source frame
    if (availableSourceFrames.size() < 3) {
        // Differential DOD requires at least 3 valid source frames
        qInfo() << "Only" << availableSourceFrames.size() << "source frames are available - can not perform combination for VBI frame" << targetVbiFrame;

        // Not enough frames to combine - so just use the first source
        qint32 firstFieldNumber = sourceVideos[0]->ldDecodeMetaData.getFirstFieldNumber(convertVbiFrameNumberToSequential(targetVbiFrame, 0));
        qint32 secondFieldNumber = sourceVideos[0]->ldDecodeMetaData.getSecondFieldNumber(convertVbiFrameNumberToSequential(targetVbiFrame, 0));

        combinedFrame.firstFieldData = sourceVideos[availableSourceFrames[0]]->sourceVideo.getVideoField(firstFieldNumber);
        combinedFrame.secondFieldData = sourceVideos[availableSourceFrames[0]]->sourceVideo.getVideoField(secondFieldNumber);
        combinedFrame.firstFieldMetadata = sourceVideos[availableSourceFrames[0]]->ldDecodeMetaData.getField(firstFieldNumber);
        combinedFrame.secondFieldMetadata = sourceVideos[availableSourceFrames[0]]->ldDecodeMetaData.getField(secondFieldNumber);

        return combinedFrame;
    }

    // Get the metadata for the video parameters (all sources are the same, so just grab from the first)
    LdDecodeMetaData::VideoParameters videoParameters = sourceVideos[0]->ldDecodeMetaData.getVideoParameters();
    qint32 firstFieldNumber = sourceVideos[0]->ldDecodeMetaData.getFirstFieldNumber(convertVbiFrameNumberToSequential(targetVbiFrame, 0));
    qint32 secondFieldNumber = sourceVideos[0]->ldDecodeMetaData.getSecondFieldNumber(convertVbiFrameNumberToSequential(targetVbiFrame, 0));
    combinedFrame.firstFieldMetadata = sourceVideos[0]->ldDecodeMetaData.getField(firstFieldNumber);
    combinedFrame.secondFieldMetadata = sourceVideos[0]->ldDecodeMetaData.getField(secondFieldNumber);

    // Resize the output field data buffers
    combinedFrame.firstFieldData.resize(sourceVideos[availableSourceFrames[0]]->sourceVideo.getVideoField(firstFieldNumber).size());
    combinedFrame.secondFieldData.resize(sourceVideos[availableSourceFrames[0]]->sourceVideo.getVideoField(secondFieldNumber).size());

    // Define the temp dropout metadata
    struct FrameDropOuts {
        LdDecodeMetaData::DropOuts firstFieldDropOuts;
        LdDecodeMetaData::DropOuts secondFieldDropOuts;
    };

    FrameDropOuts frameDropouts;

    // Get the data for all available source fields and copy locally
    QVector<QByteArray> firstFields;
    QVector<QByteArray> secondFields;
    firstFields.resize(availableSourceFrames.size());
    secondFields.resize(availableSourceFrames.size());

    QVector<quint16*> sourceFirstFieldPointer;
    QVector<quint16*> sourceSecondFieldPointer;
    sourceFirstFieldPointer.resize(availableSourceFrames.size());
    sourceSecondFieldPointer.resize(availableSourceFrames.size());

    for (qint32 sourcePointer = 0; sourcePointer < availableSourceFrames.size(); sourcePointer++) {
        qint32 firstFieldNumber = sourceVideos[availableSourceFrames[sourcePointer]]->
                ldDecodeMetaData.getFirstFieldNumber(convertVbiFrameNumberToSequential(targetVbiFrame, availableSourceFrames[sourcePointer]));
        qint32 secondFieldNumber = sourceVideos[availableSourceFrames[sourcePointer]]->
                ldDecodeMetaData.getSecondFieldNumber(convertVbiFrameNumberToSequential(targetVbiFrame, availableSourceFrames[sourcePointer]));

        firstFields[sourcePointer] = (sourceVideos[availableSourceFrames[sourcePointer]]->sourceVideo.getVideoField(firstFieldNumber));
        secondFields[sourcePointer] = (sourceVideos[availableSourceFrames[sourcePointer]]->sourceVideo.getVideoField(secondFieldNumber));

        sourceFirstFieldPointer[sourcePointer] = reinterpret_cast<quint16*>(firstFields[sourcePointer].data());
        sourceSecondFieldPointer[sourcePointer] = reinterpret_cast<quint16*>(secondFields[sourcePointer].data());
    }

    // Perform differential dropout detection
    //
    // This compares each available source against all other available sources to determine where the source differs.
    // If any of the frame's contents do not match that of the other sources, the frame's pixels are marked as dropouts.
    // Once diffDOD is performed (line by line) a target line is then produced by averaging the available source pixels together
    // (and ignoring sources with 'dropout' pixels to prevent outliers and errors disturbing the resulting frame).
    struct Diff {
        QVector<qint32> firstDiff;
        QVector<qint32> secondDiff;
    };

    QVector<Diff> diffs;
    diffs.resize(availableSourceFrames.size());

    // Process the frame one line at a time (both fields)
    for (qint32 y = 0; y < videoParameters.fieldHeight; y++) {
        qint32 startOfLinePointer = y * videoParameters.fieldWidth;

        for (qint32 i = 0; i < availableSourceFrames.size(); i++) {
            // Set all elements to zero
            diffs[i].firstDiff.fill(0, videoParameters.fieldWidth);
            diffs[i].secondDiff.fill(0, videoParameters.fieldWidth);
        }

        // Compare all combinations of source and target
        for (qint32 targetPointer = 0; targetPointer < availableSourceFrames.size(); targetPointer++) {
            for (qint32 sourcePointer = 0; sourcePointer < availableSourceFrames.size(); sourcePointer++) {
                if (sourcePointer != targetPointer) {
                    for (qint32 x = 0; x < videoParameters.fieldWidth; x++) {
                        // Get the 16-bit pixel values and diff them - First field
                        qint32 firstDifference = static_cast<qint32>(sourceFirstFieldPointer[targetPointer][x + startOfLinePointer]) -
                                static_cast<qint32>(sourceFirstFieldPointer[sourcePointer][x + startOfLinePointer]);

                        if (firstDifference < 0) firstDifference = -firstDifference;
                        if (firstDifference > threshold) diffs[targetPointer].firstDiff[x]++;

                        // Get the 16-bit pixel values and diff them - second field
                        qint32 secondDifference = static_cast<qint32>(sourceSecondFieldPointer[targetPointer][x + startOfLinePointer]) -
                                static_cast<qint32>(sourceSecondFieldPointer[sourcePointer][x + startOfLinePointer]);

                        if (secondDifference < 0) secondDifference = -secondDifference;
                        if (secondDifference > threshold) diffs[targetPointer].secondDiff[x]++;
                    }
                }
            }
        }

        // Now the value of diffs[source].firstDiff[x]/diffs[source].secondDiff[x] contains the number of other sources that differ
        // If this more than 1, the current source's x is a dropout/error

        // Sum all of the valid pixel data and keep track of the number of sources contributing to the sum
        QVector<qint32> firstSum;
        QVector<qint32> firstNumberOfSources;
        firstSum.fill(0, videoParameters.fieldWidth);
        firstNumberOfSources.fill(0, videoParameters.fieldWidth);

        QVector<qint32> secondSum;
        QVector<qint32> secondNumberOfSources;
        secondSum.fill(0, videoParameters.fieldWidth);
        secondNumberOfSources.fill(0, videoParameters.fieldWidth);

        for (qint32 sourceNo = 0; sourceNo < availableSourceFrames.size(); sourceNo++) {
             for (qint32 x = 0; x < videoParameters.fieldWidth; x++) {
                 // Only inclued the source data if it's not a dropout
                 if (diffs[sourceNo].firstDiff[x] <= 1) {
                     firstSum[x] += static_cast<qint32>(sourceFirstFieldPointer[sourceNo][x + startOfLinePointer]);
                     firstNumberOfSources[x]++;
                 }

                 if (diffs[sourceNo].secondDiff[x] <= 1) {
                     secondSum[x] += static_cast<qint32>(sourceSecondFieldPointer[sourceNo][x + startOfLinePointer]);
                     secondNumberOfSources[x]++;
                 }
             }
        }

        // Generate the output line by averaging and generate dropout records for unrecoverable pixels
        quint16* firstTargetFieldData = reinterpret_cast<quint16*>(combinedFrame.firstFieldData.data());
        quint16* secondTargetFieldData = reinterpret_cast<quint16*>(combinedFrame.secondFieldData.data());
        bool doInProgressFirst = false;
        bool doInProgressSecond = false;
        for (qint32 x = 0; x < videoParameters.fieldWidth; x++) {
            if (firstNumberOfSources[x] != 0) {
                qreal rAveragePixel = static_cast<qreal>(firstSum[x]) / static_cast<qreal>(firstNumberOfSources[x]);
                quint16 averagePixel = static_cast<quint16>(rAveragePixel);
                firstTargetFieldData[x + startOfLinePointer] = averagePixel;

                // Current X is not a metadata dropout
                if (doInProgressFirst) {
                    doInProgressFirst = false;
                    // Mark the previous x as the end of the dropout
                    frameDropouts.firstFieldDropOuts.endx.append(x - 1);
                }
            } else {
                // Uncorrectable Dropout (all sources differed) - just use the pixel value from the first source
                firstTargetFieldData[x + startOfLinePointer] = sourceFirstFieldPointer[0][x + startOfLinePointer];

                // Current X is a metadata dropout
                if (!doInProgressFirst) {
                    doInProgressFirst = true;
                    frameDropouts.firstFieldDropOuts.startx.append(x);
                    frameDropouts.firstFieldDropOuts.fieldLine.append(y + 1);
                }
            }

            if (secondNumberOfSources[x] != 0) {
                qreal rAveragePixel = static_cast<qreal>(secondSum[x]) / static_cast<qreal>(secondNumberOfSources[x]);
                quint16 averagePixel = static_cast<quint16>(rAveragePixel);
                secondTargetFieldData[x + startOfLinePointer] = averagePixel;

                // Current X is not a metadata dropout
                if (doInProgressSecond) {
                    doInProgressSecond = false;
                    // Mark the previous x as the end of the dropout
                    frameDropouts.secondFieldDropOuts.endx.append(x - 1);
                }
            } else {
                // Uncorrectable Dropout (all sources differed) - just use the pixel value from the first source
                secondTargetFieldData[x + startOfLinePointer] = sourceSecondFieldPointer[0][x + startOfLinePointer];

                // Current X is a metadata dropout
                if (!doInProgressSecond) {
                    doInProgressSecond = true;
                    frameDropouts.secondFieldDropOuts.startx.append(x);
                    frameDropouts.secondFieldDropOuts.fieldLine.append(y + 1);
                }
            }
        }

        // Ensure metadata dropouts end at the end of scan line (require by the fieldLine attribute)
        if (doInProgressFirst) {
            doInProgressFirst = false;
            frameDropouts.firstFieldDropOuts.endx.append(videoParameters.fieldWidth);
        }

        if (doInProgressSecond) {
            doInProgressSecond = false;
            frameDropouts.secondFieldDropOuts.endx.append(videoParameters.fieldWidth);
        }
    }

    // Store the target frame dropouts in the combined frame's metadata
    combinedFrame.firstFieldMetadata.dropOuts = frameDropouts.firstFieldDropOuts;
    combinedFrame.secondFieldMetadata.dropOuts = frameDropouts.secondFieldDropOuts;

    return combinedFrame;
}

bool TbcSources::setDiscTypeAndMaxMinFrameVbi(qint32 sourceNumber)
{
    sourceVideos[sourceNumber]->isSourceCav = false;

    // Determine the disc type and max/min VBI frame numbers
    VbiDecoder vbiDecoder;
    qint32 cavCount = 0;
    qint32 clvCount = 0;
    qint32 cavMin = 1000000;
    qint32 cavMax = 0;
    qint32 clvMin = 1000000;
    qint32 clvMax = 0;
    // Using sequential frame numbering starting from 1
    for (qint32 seqFrame = 1; seqFrame <= sourceVideos[sourceNumber]->ldDecodeMetaData.getNumberOfFrames(); seqFrame++) {
        // Get the VBI data and then decode
        QVector<qint32> vbi1 = sourceVideos[sourceNumber]->ldDecodeMetaData.getFieldVbi(sourceVideos[sourceNumber]->
                                                                                        ldDecodeMetaData.getFirstFieldNumber(seqFrame)).vbiData;
        QVector<qint32> vbi2 = sourceVideos[sourceNumber]->ldDecodeMetaData.getFieldVbi(sourceVideos[sourceNumber]->
                                                                                        ldDecodeMetaData.getSecondFieldNumber(seqFrame)).vbiData;
        VbiDecoder::Vbi vbi = vbiDecoder.decodeFrame(vbi1[0], vbi1[1], vbi1[2], vbi2[0], vbi2[1], vbi2[2]);

        // Look for a complete, valid CAV picture number or CLV time-code
        if (vbi.picNo > 0) {
            cavCount++;

            if (vbi.picNo < cavMin) cavMin = vbi.picNo;
            if (vbi.picNo > cavMax) cavMax = vbi.picNo;
        }

        if (vbi.clvHr != -1 && vbi.clvMin != -1 &&
                vbi.clvSec != -1 && vbi.clvPicNo != -1) {
            clvCount++;

            LdDecodeMetaData::ClvTimecode timecode;
            timecode.hours = vbi.clvHr;
            timecode.minutes = vbi.clvMin;
            timecode.seconds = vbi.clvSec;
            timecode.pictureNumber = vbi.clvPicNo;
            qint32 cvFrameNumber = sourceVideos[sourceNumber]->ldDecodeMetaData.convertClvTimecodeToFrameNumber(timecode);

            if (cvFrameNumber < clvMin) clvMin = cvFrameNumber;
            if (cvFrameNumber > clvMax) clvMax = cvFrameNumber;
        }
    }
    qDebug() << "TbcSources::getIsSourceCav(): Got" << cavCount << "CAV picture codes and" << clvCount << "CLV timecodes";

    // If the metadata has no picture numbers or time-codes, we cannot use the source
    if (cavCount == 0 && clvCount == 0) {
        qDebug() << "TbcSources::getIsSourceCav(): Source does not seem to contain valid CAV picture numbers or CLV time-codes - cannot process";
        return false;
    }

    // Determine disc type
    if (cavCount > clvCount) {
        sourceVideos[sourceNumber]->isSourceCav = true;
        qDebug() << "TbcSources::getIsSourceCav(): Got" << cavCount << "valid CAV picture numbers - source disc type is CAV";
        qInfo() << "Disc type is CAV";

        sourceVideos[sourceNumber]->maximumVbiFrameNumber = cavMax;
        sourceVideos[sourceNumber]->minimumVbiFrameNumber = cavMin;
    } else {
        sourceVideos[sourceNumber]->isSourceCav = false;;
        qDebug() << "TbcSources::getIsSourceCav(): Got" << clvCount << "valid CLV picture numbers - source disc type is CLV";
        qInfo() << "Disc type is CLV";

        sourceVideos[sourceNumber]->maximumVbiFrameNumber = clvMax;
        sourceVideos[sourceNumber]->minimumVbiFrameNumber = clvMin;
    }

    qInfo() << "VBI frame number range is" << sourceVideos[sourceNumber]->minimumVbiFrameNumber << "to" <<
        sourceVideos[sourceNumber]->maximumVbiFrameNumber;

    return true;
}

// Method to convert a VBI frame number to a sequential frame number
qint32 TbcSources::convertVbiFrameNumberToSequential(qint32 vbiFrameNumber, qint32 sourceNumber)
{
    // Offset the VBI frame number to get the sequential source frame number
    return vbiFrameNumber - sourceVideos[sourceNumber]->minimumVbiFrameNumber + 1;
}

















