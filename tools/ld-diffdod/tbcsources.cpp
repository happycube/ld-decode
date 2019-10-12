/************************************************************************

    tbcsources.cpp

    ld-diffdod - TBC Differential Drop-Out Detection tool
    Copyright (C) 2019 Simon Inns

    This file is part of ld-decode-tools.

    ld-diffdod is free software: you can redistribute it and/or
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

// Save TBC source video metadata for all sources; returns false on failure
bool TbcSources::saveSources(qint32 vbiStartFrame, qint32 length, qint32 dodThreshold, bool noLumaClip)
{
    // Process the sources frame by frame
    for (qint32 vbiFrame = vbiStartFrame; vbiFrame < vbiStartFrame + length; vbiFrame++) {
        if ((vbiFrame % 100 == 0) || (vbiFrame == vbiStartFrame)) qInfo() << "Processing VBI frame" << vbiFrame;

        // Process
        performFrameDiffDod(vbiFrame, dodThreshold, noLumaClip);
    }

    // Save the sources' metadata
    for (qint32 sourceNo = 0; sourceNo < sourceVideos.size(); sourceNo++) {
        // Write the JSON metadata
        qInfo() << "Writing JSON metadata file for TBC file" << sourceNo;
        sourceVideos[sourceNo]->ldDecodeMetaData.write(sourceVideos[sourceNo]->filename + ".json");
    }

    return true;
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

// Private methods ----------------------------------------------------------------------------------------------------

// Perform differential dropout detection to determine (for each source) which frame pixels are valid
// Note: This method processes a single frame
void TbcSources::performFrameDiffDod(qint32 targetVbiFrame, qint32 dodThreshold, bool noLumaClip)
{
    // Range check the diffDOD threshold
    if (dodThreshold < 100) dodThreshold = 100;
    if (dodThreshold > 65435) dodThreshold = 65435;

    // Set the first and last active lines in the field
    qint32 firstActiveLine;
    qint32 lastActiveLine;
    if (sourceVideos[0]->ldDecodeMetaData.getVideoParameters().isSourcePal) {
        // PAL
        firstActiveLine = 10;
        lastActiveLine = 308;
    } else {
        // NTSC
        firstActiveLine = 10;
        lastActiveLine = 262;
    }

    // Get the metadata for the video parameters (all sources are the same, so just grab from the first)
    LdDecodeMetaData::VideoParameters videoParameters = sourceVideos[0]->ldDecodeMetaData.getVideoParameters();

    // Check how many source frames are available for the current frame
    QVector<qint32> availableSourcesForFrame = getAvailableSourcesForFrame(targetVbiFrame);

    // DiffDOD requires at least three source frames.  If 3 sources are not available leave any existing DO records in place
    // and output a warning to the user
    if (availableSourcesForFrame.size() < 3) {
        // Differential DOD requires at least 3 valid source frames
        qInfo() << "Only" << availableSourcesForFrame.size() << "source frames are available - can not perform diffDOD for VBI frame" << targetVbiFrame;
        return;
    }
    qDebug() << "TbcSources::performFrameDiffDod(): Processing VBI Frame" << targetVbiFrame << "-" << availableSourcesForFrame.size() << "sources available";

    // Get the field data for the frame from all of the available sources and copy locally ----------------------------
    QVector<QByteArray> firstFields;
    QVector<QByteArray> secondFields;
    firstFields.resize(availableSourcesForFrame.size());
    secondFields.resize(availableSourcesForFrame.size());

    QVector<quint16*> sourceFirstFieldPointer;
    QVector<quint16*> sourceSecondFieldPointer;
    sourceFirstFieldPointer.resize(availableSourcesForFrame.size());
    sourceSecondFieldPointer.resize(availableSourcesForFrame.size());

    for (qint32 sourceNo = 0; sourceNo < availableSourcesForFrame.size(); sourceNo++) {
        qint32 firstFieldNumber = sourceVideos[availableSourcesForFrame[sourceNo]]->
                ldDecodeMetaData.getFirstFieldNumber(convertVbiFrameNumberToSequential(targetVbiFrame, availableSourcesForFrame[sourceNo]));
        qint32 secondFieldNumber = sourceVideos[availableSourcesForFrame[sourceNo]]->
                ldDecodeMetaData.getSecondFieldNumber(convertVbiFrameNumberToSequential(targetVbiFrame, availableSourcesForFrame[sourceNo]));

        // Copy the data locally
        firstFields[sourceNo] = (sourceVideos[availableSourcesForFrame[sourceNo]]->sourceVideo.getVideoField(firstFieldNumber));
        secondFields[sourceNo] = (sourceVideos[availableSourcesForFrame[sourceNo]]->sourceVideo.getVideoField(secondFieldNumber));

        // Define a pointer to the data
        sourceFirstFieldPointer[sourceNo] = reinterpret_cast<quint16*>(firstFields[sourceNo].data());
        sourceSecondFieldPointer[sourceNo] = reinterpret_cast<quint16*>(secondFields[sourceNo].data());

        // Filter out the chroma information from the fields leaving just luma
        Filters filters;
        if (videoParameters.isSourcePal) {
            filters.palLumaFirFilter(sourceFirstFieldPointer[sourceNo], videoParameters.fieldWidth * videoParameters.fieldHeight);
            filters.palLumaFirFilter(sourceSecondFieldPointer[sourceNo], videoParameters.fieldWidth * videoParameters.fieldHeight);
        } else {
            filters.ntscLumaFirFilter(sourceFirstFieldPointer[sourceNo], videoParameters.fieldWidth * videoParameters.fieldHeight);
            filters.ntscLumaFirFilter(sourceSecondFieldPointer[sourceNo], videoParameters.fieldWidth * videoParameters.fieldHeight);
        }

        // Remove the existing field dropout metadata for the frame
        sourceVideos[availableSourcesForFrame[sourceNo]]->ldDecodeMetaData.clearFieldDropOuts(firstFieldNumber);
        sourceVideos[availableSourcesForFrame[sourceNo]]->ldDecodeMetaData.clearFieldDropOuts(secondFieldNumber);
    }

    // Create a differential map of all the available sources for the VBI frame ---------------------------------------
    QVector<FrameDiff> fieldDiff;
    fieldDiff.resize(availableSourcesForFrame.size());

    for (qint32 sourceCounter = 0; sourceCounter < availableSourcesForFrame.size(); sourceCounter++) {
        fieldDiff[sourceCounter].firstFieldDiff.fill(0, videoParameters.fieldHeight * videoParameters.fieldWidth);
        fieldDiff[sourceCounter].secondFieldDiff.fill(0, videoParameters.fieldHeight * videoParameters.fieldWidth);
    }

    // Process the frame one line at a time (both fields)
    for (qint32 y = 0; y < videoParameters.fieldHeight; y++) {
        qint32 startOfLinePointer = y * videoParameters.fieldWidth;

        // Compare all combinations of source and target field lines
        // Note: the source is the field line we are building a DO map for, target is the field line we are
        // comparing the source to.  The differential map is written to the local copy of the line data for
        // the source
        for (qint32 sourceCounter = 0; sourceCounter < availableSourcesForFrame.size(); sourceCounter++) {
            for (qint32 targetCounter = 0; targetCounter < availableSourcesForFrame.size(); targetCounter++) {
                if (sourceCounter != targetCounter) {
                    for (qint32 x = 0; x < videoParameters.fieldWidth; x++) {
                        // Get the 16-bit IRE values for target and source, first and second fields
                        qint32 targetIreFirst = static_cast<qint32>(sourceFirstFieldPointer[targetCounter][x + startOfLinePointer]);
                        qint32 sourceIreFirst = static_cast<qint32>(sourceFirstFieldPointer[sourceCounter][x + startOfLinePointer]);
                        qint32 targetIreSecond = static_cast<qint32>(sourceSecondFieldPointer[targetCounter][x + startOfLinePointer]);
                        qint32 sourceIreSecond = static_cast<qint32>(sourceSecondFieldPointer[sourceCounter][x + startOfLinePointer]);

                        // Calculate the luma clip levels
                        qint32 blackClipPoint = videoParameters.black16bIre - 2000;
                        qint32 whiteClipPoint = videoParameters.white16bIre + 2000;

                        // Diff the 16-bit pixel values of the first fields
                        qint32 firstDifference = targetIreFirst - sourceIreFirst;

                        // Compare the difference between source and target
                        if (firstDifference < 0) firstDifference = -firstDifference;
                        if (firstDifference > dodThreshold) {
                            fieldDiff[sourceCounter].firstFieldDiff[x + startOfLinePointer] = fieldDiff[sourceCounter].firstFieldDiff[x + startOfLinePointer] + 1;
                        } else if (!noLumaClip){
                            if (x >= videoParameters.activeVideoStart && x <= videoParameters.activeVideoEnd &&
                                    y >= firstActiveLine && y <= lastActiveLine) {
                                // Check for luma level clipping
                                if (sourceIreFirst < blackClipPoint || sourceIreFirst > whiteClipPoint) {
                                    fieldDiff[sourceCounter].firstFieldDiff[x + startOfLinePointer] = fieldDiff[sourceCounter].firstFieldDiff[x + startOfLinePointer] + 1;
                                }
                            }
                        }

                        // Diff the 16-bit pixel values of the second fields
                        qint32 secondDifference = targetIreSecond - sourceIreSecond;

                        // Compare the difference between source and target
                        if (secondDifference < 0) secondDifference = -secondDifference;
                        if (secondDifference > dodThreshold) {
                            fieldDiff[sourceCounter].secondFieldDiff[x + startOfLinePointer] = fieldDiff[sourceCounter].secondFieldDiff[x + startOfLinePointer] + 1;
                        } else if (!noLumaClip){
                            if (x >= videoParameters.activeVideoStart && x <= videoParameters.activeVideoEnd &&
                                    y >= firstActiveLine && y <= lastActiveLine) {
                                // Check for luma level clipping
                                if (sourceIreSecond < blackClipPoint || sourceIreSecond > whiteClipPoint) {
                                    fieldDiff[sourceCounter].secondFieldDiff[x + startOfLinePointer] = fieldDiff[sourceCounter].secondFieldDiff[x + startOfLinePointer] + 1;
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    // Based on the diffential value - mark the data as a drop-out if required ----------------------------------------

    // This compares each available source against all other available sources to determine where the source differs.
    // If any of the frame's contents do not match that of the other sources, the frame's pixels are marked as dropouts.
    QVector<FrameDropOuts> frameDropouts;
    frameDropouts.resize(availableSourcesForFrame.size());

    // Process the frame one line at a time (both fields)
    for (qint32 y = 0; y < videoParameters.fieldHeight; y++) {
        qint32 startOfLinePointer = y * videoParameters.fieldWidth;

        // Now the value of diffs[source].firstDiff[x]/diffs[source].secondDiff[x] contains the number of other target fields
        // that differ from the source field line.

        // The minimum number of sources for diffDOD is 3, and when comparing 3 sources, each source has to
        // match at least 2 other sources.  As the sources increase, so does the required number of matches
        // (i.e. for 4 sources, 3 should match and so on).  This makes the diffDOD better and better as the
        // number of available sources increase.
        qint32 diffCompareThreshold = availableSourcesForFrame.size() - 2;

        // Process each source line in turn
        for (qint32 sourceNo = 0; sourceNo < availableSourcesForFrame.size(); sourceNo++) {
            qint32 doCounterFirst = 0;
            qint32 doCounterSecond = 0;
            qint32 minimumDetectLength = 3;

            for (qint32 x = 0; x < videoParameters.fieldWidth; x++) {
                // First field - Compare to threshold
                if (static_cast<qint32>(fieldDiff[sourceNo].firstFieldDiff[x + startOfLinePointer]) <= diffCompareThreshold) {
                    // Current X is not a dropout
                    if (doCounterFirst > 0) {
                        doCounterFirst--;
                        if (doCounterFirst == 0) {
                            // Mark the previous x as the end of the dropout
                            frameDropouts[sourceNo].firstFieldDropOuts.endx.append(x - 1);
                        }
                    }
                } else {
                    // Current X is a dropout
                    if (doCounterFirst == 0) {
                        doCounterFirst = minimumDetectLength;
                        frameDropouts[sourceNo].firstFieldDropOuts.startx.append(x);
                        frameDropouts[sourceNo].firstFieldDropOuts.fieldLine.append(y + 1);
                    }
                }

                // Second field
                if (static_cast<qint32>(fieldDiff[sourceNo].secondFieldDiff[x + startOfLinePointer]) <= diffCompareThreshold) {
                    // Current X is not a dropout
                    if (doCounterSecond > 0) {
                        doCounterSecond--;

                        if (doCounterSecond == 0) {
                            // Mark the previous x as the end of the dropout
                            frameDropouts[sourceNo].secondFieldDropOuts.endx.append(x - 1);
                        }
                    }
                } else {
                    // Current X is a dropout
                    if (doCounterSecond == 0) {
                        doCounterSecond = minimumDetectLength;
                        frameDropouts[sourceNo].secondFieldDropOuts.startx.append(x);
                        frameDropouts[sourceNo].secondFieldDropOuts.fieldLine.append(y + 1);
                    }
                }
            }

            // Ensure metadata dropouts end at the end of scan line (require by the fieldLine attribute)
            if (doCounterFirst > 0) {
                doCounterFirst = 0;
                frameDropouts[sourceNo].firstFieldDropOuts.endx.append(videoParameters.fieldWidth);
            }

            if (doCounterSecond > 0) {
                doCounterSecond = 0;
                frameDropouts[sourceNo].secondFieldDropOuts.endx.append(videoParameters.fieldWidth);
            }
        } // Next source
    } // Next line

    // Write the first and second field line metadata back to the source
    for (qint32 sourceNo = 0; sourceNo < availableSourcesForFrame.size(); sourceNo++) {
        // Get the required field numbers
        qint32 firstFieldNumber = sourceVideos[availableSourcesForFrame[sourceNo]]->ldDecodeMetaData.getFirstFieldNumber(convertVbiFrameNumberToSequential(targetVbiFrame, sourceNo));
        qint32 secondFieldNumber = sourceVideos[availableSourcesForFrame[sourceNo]]->ldDecodeMetaData.getSecondFieldNumber(convertVbiFrameNumberToSequential(targetVbiFrame, sourceNo));

        // Calculate the total number of dropouts detected for the frame
        qint32 totalFirstDropouts = frameDropouts[sourceNo].firstFieldDropOuts.startx.size();
        qint32 totalSecondDropouts = frameDropouts[sourceNo].secondFieldDropOuts.startx.size();

        qDebug() << "TbcSources::performFrameDiffDod(): Writing source" << availableSourcesForFrame[sourceNo] <<
                    "frame" << targetVbiFrame << "fields" << firstFieldNumber << "/" << secondFieldNumber <<
                    "- Dropout records" << totalFirstDropouts << "/" << totalSecondDropouts;

        // Write the metadata
        sourceVideos[availableSourcesForFrame[sourceNo]]->ldDecodeMetaData.updateFieldDropOuts(frameDropouts[sourceNo].firstFieldDropOuts, firstFieldNumber);
        sourceVideos[availableSourcesForFrame[sourceNo]]->ldDecodeMetaData.updateFieldDropOuts(frameDropouts[sourceNo].secondFieldDropOuts, secondFieldNumber);
    }
}

// Method that returns a vector of the sources that contain data for the required VBI frame number
QVector<qint32> TbcSources::getAvailableSourcesForFrame(qint32 vbiFrameNumber)
{
    QVector<qint32> availableSourcesForFrame;
    for (qint32 sourceNo = 0; sourceNo < sourceVideos.size(); sourceNo++) {
        if (vbiFrameNumber >= sourceVideos[sourceNo]->minimumVbiFrameNumber && vbiFrameNumber <= sourceVideos[sourceNo]->maximumVbiFrameNumber) {
            // Get the field numbers for the frame
            qint32 firstFieldNumber = sourceVideos[sourceNo]->ldDecodeMetaData.getFirstFieldNumber(convertVbiFrameNumberToSequential(vbiFrameNumber, sourceNo));
            qint32 secondFieldNumber = sourceVideos[sourceNo]->ldDecodeMetaData.getSecondFieldNumber(convertVbiFrameNumberToSequential(vbiFrameNumber, sourceNo));

            // Ensure the frame is not a padded field (i.e. missing)
            if (!(sourceVideos[sourceNo]->ldDecodeMetaData.getField(firstFieldNumber).pad &&
                  sourceVideos[sourceNo]->ldDecodeMetaData.getField(secondFieldNumber).pad)) {
                availableSourcesForFrame.append(sourceNo);
            }
        }
    }

    return availableSourcesForFrame;
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
        sourceVideos[sourceNumber]->isSourceCav = false;
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

















