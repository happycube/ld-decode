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

    // Show the 0 and 100IRE points for the source
    qInfo() << "Source has 0IRE at" << videoParameters.black16bIre << "and 100IRE at" << videoParameters.white16bIre;

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
bool TbcSources::saveSources(qint32 vbiStartFrame, qint32 length, qint32 dodThreshold, bool lumaClip)
{
    // Process the sources frame by frame
    for (qint32 vbiFrame = vbiStartFrame; vbiFrame < vbiStartFrame + length; vbiFrame++) {
        if ((vbiFrame % 100 == 0) || (vbiFrame == vbiStartFrame)) qInfo() << "Processing VBI frame" << vbiFrame;

        // Process
        performFrameDiffDod(vbiFrame, dodThreshold, lumaClip);
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

// Verify that at least 3 sources are available for every VBI frame
void TbcSources::verifySources(qint32 vbiStartFrame, qint32 length)
{
    qint32 uncorrectableFrameCount = 0;

    // Process the sources frame by frame
    for (qint32 vbiFrame = vbiStartFrame; vbiFrame < vbiStartFrame + length; vbiFrame++) {
        // Check how many source frames are available for the current frame
        QVector<qint32> availableSourcesForFrame = getAvailableSourcesForFrame(vbiFrame);

        // DiffDOD requires at least three source frames.  If 3 sources are not available leave any existing DO records in place
        // and output a warning to the user
        if (availableSourcesForFrame.size() < 3) {
            // Differential DOD requires at least 3 valid source frames
            qInfo().nospace() << "Frame #" << vbiFrame << " has only " << availableSourcesForFrame.size() << " source frames available - cannot correct";
            uncorrectableFrameCount++;
        }
    }

    if (uncorrectableFrameCount != 0) {
        qInfo() << "Warning:" << uncorrectableFrameCount << "frame(s) cannot be corrected!";
    } else {
        qInfo() << "All frames have at least 3 sources available";
    }
}

// Private methods ----------------------------------------------------------------------------------------------------

// Perform differential dropout detection to determine (for each source) which frame pixels are valid
// Note: This method processes a single frame
void TbcSources::performFrameDiffDod(qint32 targetVbiFrame, qint32 dodThreshold, bool lumaClip)
{
    // Range check the diffDOD threshold percent
    if (dodThreshold < 1) dodThreshold = 1;
    if (dodThreshold > 100) dodThreshold = 100;

    // Get the field data for the current frame (from all available sources)
    QVector<SourceVideo::Data> firstFields = getFieldData(targetVbiFrame, true);
    QVector<SourceVideo::Data> secondFields = getFieldData(targetVbiFrame, false);

    // Create a differential map of the fields for the avaialble frames (based on the DOD threshold)
    QVector<QByteArray> firstFieldsDiff = getFieldErrorByMedian(targetVbiFrame, firstFields, dodThreshold);
    QVector<QByteArray> secondFieldsDiff = getFieldErrorByMedian(targetVbiFrame, secondFields, dodThreshold);

    // Perform luma clip check?
    if (lumaClip) {
        performLumaClip(targetVbiFrame, firstFields, firstFieldsDiff);
        performLumaClip(targetVbiFrame, secondFields, secondFieldsDiff);
    }

    // Create the drop-out metadata based on the differential map of the fields
    QVector<LdDecodeMetaData::DropOuts> firstFieldDropouts = getFieldDropouts(targetVbiFrame, firstFieldsDiff, true);
    QVector<LdDecodeMetaData::DropOuts> secondFieldDropouts = getFieldDropouts(targetVbiFrame, secondFieldsDiff, false);

    // Concatenate dropouts on the same line that are close together (to cut down on the
    // amount of generated metadata with noisy/bad sources)
    concatenateFieldDropouts(targetVbiFrame, firstFieldDropouts);
    concatenateFieldDropouts(targetVbiFrame, secondFieldDropouts);

    // Write the dropout metadata back to the sources
    writeDropoutMetadata(targetVbiFrame, firstFieldDropouts, secondFieldDropouts);
}

// Get the field data for the specified frame
QVector<SourceVideo::Data> TbcSources::getFieldData(qint32 targetVbiFrame, bool isFirstField)
{
    // Get the metadata for the video parameters (all sources are the same, so just grab from the first)
    LdDecodeMetaData::VideoParameters videoParameters = sourceVideos[0]->ldDecodeMetaData.getVideoParameters();

    // Check how many source frames are available for the current frame
    QVector<qint32> availableSourcesForFrame = getAvailableSourcesForFrame(targetVbiFrame);

    // Only display on first field (otherwise we will get 2 of the same debug)
    if (isFirstField) qDebug() << "Processing VBI Frame" << targetVbiFrame << "-" << availableSourcesForFrame.size() << "sources available";

    // Get the field data for the frame from all of the available sources and copy locally
    QVector<SourceVideo::Data> fields;
    fields.resize(getNumberOfAvailableSources());

    QVector<SourceVideo::Data*> sourceFirstFieldPointer;
    sourceFirstFieldPointer.resize(getNumberOfAvailableSources());

    for (qint32 sourcePointer = 0; sourcePointer < availableSourcesForFrame.size(); sourcePointer++) {
        qint32 sourceNo = availableSourcesForFrame[sourcePointer]; // Get the actual source
        qint32 fieldNumber = -1;
        if (isFirstField) fieldNumber = sourceVideos[sourceNo]->
                ldDecodeMetaData.getFirstFieldNumber(convertVbiFrameNumberToSequential(targetVbiFrame, sourceNo));
        else fieldNumber = sourceVideos[sourceNo]->
                ldDecodeMetaData.getSecondFieldNumber(convertVbiFrameNumberToSequential(targetVbiFrame, sourceNo));

        // Copy the data locally
        fields[sourceNo] = (sourceVideos[sourceNo]->sourceVideo.getVideoField(fieldNumber));

        // Filter out the chroma information from the fields leaving just luma
        Filters filters;
        if (videoParameters.isSourcePal) {
            filters.palLumaFirFilter(fields[sourceNo].data(), videoParameters.fieldWidth * videoParameters.fieldHeight);
        } else {
            filters.ntscLumaFirFilter(fields[sourceNo].data(), videoParameters.fieldWidth * videoParameters.fieldHeight);
        }

        // Remove the existing field dropout metadata for the field
        sourceVideos[sourceNo]->ldDecodeMetaData.clearFieldDropOuts(fieldNumber);
    }

    return fields;
}

// Create an error map of the fields based on median value differential analysis
QVector<QByteArray> TbcSources::getFieldErrorByMedian(qint32 targetVbiFrame, QVector<SourceVideo::Data> &fields, qint32 dodThreshold)
{
    // Get the metadata for the video parameters (all sources are the same, so just grab from the first)
    LdDecodeMetaData::VideoParameters videoParameters = sourceVideos[0]->ldDecodeMetaData.getVideoParameters();

    // Check how many source frames are available for the current frame
    QVector<qint32> availableSourcesForFrame = getAvailableSourcesForFrame(targetVbiFrame);

    // This method requires at least three source frames
    if (availableSourcesForFrame.size() < 3) {
        return QVector<QByteArray>();
    }

    // Normalize the % dodThreshold to 0.00-1.00
    double threshold = static_cast<double>(dodThreshold) / 100.0;

    // Make a vector to store the result of the diff
    QVector<QByteArray> fieldDiff;
    fieldDiff.resize(getNumberOfAvailableSources());

    // Resize the fieldDiff sub-vectors
    for (qint32 sourcePointer = 0; sourcePointer < getNumberOfAvailableSources(); sourcePointer++) {
        fieldDiff[sourcePointer].resize(videoParameters.fieldHeight * videoParameters.fieldWidth);
    }

    for (qint32 y = 0; y < videoParameters.fieldHeight; y++) {
        qint32 startOfLinePointer = y * videoParameters.fieldWidth;
        for (qint32 x = 0; x < videoParameters.fieldWidth; x++) {
            // Get the dot value from all of the sources
            QVector<qint32> dotValues(getNumberOfAvailableSources());
            for (qint32 sourcePointer = 0; sourcePointer < availableSourcesForFrame.size(); sourcePointer++) {
                qint32 sourceNo = availableSourcesForFrame[sourcePointer]; // Get the actual source
                dotValues[sourceNo] = static_cast<qint32>(fields[sourceNo][x + startOfLinePointer]);
            }

            // Compute the median of the dot values
            double vMedian = static_cast<double>(convertLinearToBrightness(median(dotValues), videoParameters.black16bIre, videoParameters.white16bIre, videoParameters.isSourcePal));

            for (qint32 sourcePointer = 0; sourcePointer < availableSourcesForFrame.size(); sourcePointer++) {
                qint32 sourceNo = availableSourcesForFrame[sourcePointer]; // Get the actual source
                double v = convertLinearToBrightness(dotValues[sourceNo], videoParameters.black16bIre, videoParameters.white16bIre, videoParameters.isSourcePal);
                if ((v - vMedian) > threshold) fieldDiff[sourceNo][x + startOfLinePointer] = 1;
                else fieldDiff[sourceNo][x + startOfLinePointer] = 0;
            }
        }
    }

    return fieldDiff;
}

// Perform a luma clip check on the field
void TbcSources::performLumaClip(qint32 targetVbiFrame, QVector<SourceVideo::Data> &fields, QVector<QByteArray> &fieldsDiff)
{
    // Get the metadata for the video parameters (all sources are the same, so just grab from the first)
    LdDecodeMetaData::VideoParameters videoParameters = sourceVideos[0]->ldDecodeMetaData.getVideoParameters();

    // Check how many source frames are available for the current frame
    QVector<qint32> availableSourcesForFrame = getAvailableSourcesForFrame(targetVbiFrame);

    // Process the fields one line at a time
    for (qint32 y = videoParameters.firstActiveFieldLine; y < videoParameters.lastActiveFieldLine; y++) {
        qint32 startOfLinePointer = y * videoParameters.fieldWidth;

        for (qint32 sourcePointer = 0; sourcePointer < availableSourcesForFrame.size(); sourcePointer++) {
            qint32 sourceNo = availableSourcesForFrame[sourcePointer]; // Get the actual source

            // Set the clipping levels
            qint32 blackClipLevel = videoParameters.black16bIre - 4000;
            qint32 whiteClipLevel = videoParameters.white16bIre + 4000;

            for (qint32 x = videoParameters.activeVideoStart; x < videoParameters.activeVideoEnd; x++) {
                // Get the IRE value for the source field, cast to 32 bit signed
                qint32 sourceIre = static_cast<qint32>(fields[sourceNo][x + startOfLinePointer]);

                // Check for a luma clip event
                if ((sourceIre < blackClipLevel) || (sourceIre > whiteClipLevel)) {
                    // Luma has clipped, scan back and forth looking for the start
                    // and end points of the event (i.e. the point where the event
                    // goes back into the expected IRE range)
                    qint32 range = 10; // maximum + and - scan range
                    qint32 minX = x - range;
                    if (minX < videoParameters.activeVideoStart) minX = videoParameters.activeVideoStart;
                    qint32 maxX = x + range;
                    if (maxX > videoParameters.activeVideoEnd) maxX = videoParameters.activeVideoEnd;

                    qint32 startX = x;
                    qint32 endX = x;

                    for (qint32 i = x; i > minX; i--) {
                        qint32 ire = static_cast<qint32>(fields[sourceNo][x + startOfLinePointer]);
                        if (ire < videoParameters.black16bIre || ire > videoParameters.white16bIre) {
                            startX = i;
                        }
                    }

                    for (qint32 i = x+1; i < maxX; i++) {
                        qint32 ire = static_cast<qint32>(fields[sourceNo][x + startOfLinePointer]);
                        if (ire < videoParameters.black16bIre || ire > videoParameters.white16bIre) {
                            endX = i;
                        }
                    }

                    // Mark the dropout
                    for (qint32 i = startX; i < endX; i++) {
                        fieldsDiff[sourceNo][i + startOfLinePointer] = 1;
                    }

                    x = x + range;
                }
            }
        }
    }
}

// Method to create the field drop-out metadata based on the differential map of the fields
// This method compares each available source against all other available sources to determine where the source differs.
// If any of the frame's contents do not match that of the other sources, the frame's pixels are marked as dropouts.
QVector<LdDecodeMetaData::DropOuts> TbcSources::getFieldDropouts(qint32 targetVbiFrame, QVector<QByteArray> &fieldsDiff, bool isFirstField)
{
    // Get the metadata for the video parameters (all sources are the same, so just grab from the first)
    LdDecodeMetaData::VideoParameters videoParameters = sourceVideos[0]->ldDecodeMetaData.getVideoParameters();

    // Check how many source frames are available for the current frame
    QVector<qint32> availableSourcesForFrame = getAvailableSourcesForFrame(targetVbiFrame);

    // Create and resize the return data vector
    QVector<LdDecodeMetaData::DropOuts> fieldDropouts;
    fieldDropouts.resize(getNumberOfAvailableSources());

    // This method requires at least three source frames
    if (availableSourcesForFrame.size() < 3) {
        // Not enough source frames, preserve the current dropout metadata
        for (qint32 sourcePointer = 0; sourcePointer < availableSourcesForFrame.size(); sourcePointer++) {
            qint32 sourceNo = availableSourcesForFrame[sourcePointer]; // Get the actual source

            // Get the required field number
            qint32 fieldNumber;
            if (isFirstField) fieldNumber = sourceVideos[sourceNo]->
                    ldDecodeMetaData.getFirstFieldNumber(convertVbiFrameNumberToSequential(targetVbiFrame, sourceNo));
            else fieldNumber = sourceVideos[sourceNo]->
                    ldDecodeMetaData.getSecondFieldNumber(convertVbiFrameNumberToSequential(targetVbiFrame, sourceNo));

            fieldDropouts[sourceNo] = sourceVideos[sourceNo]->ldDecodeMetaData.getFieldDropOuts(fieldNumber);
        }

        if (isFirstField) qInfo() << "Only" << availableSourcesForFrame.size() << "available sources for VBI frame" <<
                                     targetVbiFrame << "- preserving original dropout data";
        return fieldDropouts;
    }

    // Define the area in which DOD should be performed
    qint32 areaStart = videoParameters.colourBurstStart;
    qint32 areaEnd = videoParameters.activeVideoEnd;

    // Process the frame one line at a time (both fields)
    for (qint32 y = 0; y < videoParameters.fieldHeight; y++) {
        qint32 startOfLinePointer = y * videoParameters.fieldWidth;

        // Process each source line in turn
        for (qint32 sourcePointer = 0; sourcePointer < availableSourcesForFrame.size(); sourcePointer++) {
            qint32 sourceNo = availableSourcesForFrame[sourcePointer]; // Get the actual source

            // Mark the individual dropouts
            qint32 doCounter = 0;
            qint32 minimumDetectLength = 5;

            qint32 doStart = 0;
            qint32 doFieldLine = 0;

            // Only create dropouts between the start of the colour burst and the end of the
            // active video area
            for (qint32 x = areaStart; x < areaEnd; x++) {
                // Compare field dot to threshold
                if (static_cast<qint32>(fieldsDiff[sourceNo][x + startOfLinePointer]) == 0) {
                    // Current X is not a dropout
                    if (doCounter > 0) {
                        doCounter--;
                        if (doCounter == 0) {
                            // Mark the previous x as the end of the dropout
                            fieldDropouts[sourceNo].startx.append(doStart);
                            fieldDropouts[sourceNo].endx.append(x - 1);
                            fieldDropouts[sourceNo].fieldLine.append(doFieldLine);
                        }
                    }
                } else {
                    // Current X is a dropout
                    if (doCounter == 0) {
                        doCounter = minimumDetectLength;
                        doStart = x;
                        doFieldLine = y + 1;
                    }
                }
            }

            // Ensure metadata dropouts end at the end of the active video area
            if (doCounter > 0) {
                doCounter = 0;

                fieldDropouts[sourceNo].startx.append(doStart);
                fieldDropouts[sourceNo].endx.append(areaEnd);
                fieldDropouts[sourceNo].fieldLine.append(doFieldLine);
            }

        } // Next source
    } // Next line

    return fieldDropouts;
}

void TbcSources::writeDropoutMetadata(qint32 targetVbiFrame, QVector<LdDecodeMetaData::DropOuts> &firstFieldDropouts,
                          QVector<LdDecodeMetaData::DropOuts> &secondFieldDropouts)
{
    // Check how many source frames are available for the current frame
    QVector<qint32> availableSourcesForFrame = getAvailableSourcesForFrame(targetVbiFrame);

    // Write the first and second field line metadata back to the source
    for (qint32 sourcePointer = 0; sourcePointer < availableSourcesForFrame.size(); sourcePointer++) {
        qint32 sourceNo = availableSourcesForFrame[sourcePointer]; // Get the actual source

        // Get the required field numbers
        qint32 firstFieldNumber = sourceVideos[sourceNo]->
                ldDecodeMetaData.getFirstFieldNumber(convertVbiFrameNumberToSequential(targetVbiFrame, sourceNo));
        qint32 secondFieldNumber = sourceVideos[sourceNo]->
                ldDecodeMetaData.getSecondFieldNumber(convertVbiFrameNumberToSequential(targetVbiFrame, sourceNo));

        // Calculate the total number of dropouts detected for the frame
        qint32 totalFirstDropouts = firstFieldDropouts[sourceNo].startx.size();
        qint32 totalSecondDropouts = secondFieldDropouts[sourceNo].startx.size();

        qDebug() << "Writing source" << sourceNo <<
                    "frame" << targetVbiFrame << "fields" << firstFieldNumber << "/" << secondFieldNumber <<
                    "- Dropout records" << totalFirstDropouts << "/" << totalSecondDropouts;

        // Write the metadata
        sourceVideos[sourceNo]->ldDecodeMetaData.updateFieldDropOuts(firstFieldDropouts[sourceNo], firstFieldNumber);
        sourceVideos[sourceNo]->ldDecodeMetaData.updateFieldDropOuts(secondFieldDropouts[sourceNo], secondFieldNumber);
    }
}

// Method to concatenate dropouts on the same line that are close together
// (to cut down on the amount of generated metadata with noisy/bad sources)
void TbcSources::concatenateFieldDropouts(qint32 targetVbiFrame, QVector<LdDecodeMetaData::DropOuts> &dropouts)
{
    // Check how many source frames are available for the current frame
    QVector<qint32> availableSourcesForFrame = getAvailableSourcesForFrame(targetVbiFrame);

    // This variable controls the minimum allowed gap between dropouts
    // if the gap between the end of the last dropout and the start of
    // the next is less than minimumGap, the two dropouts will be
    // concatenated together
    qint32 minimumGap = 50;

    for (qint32 sourcePointer = 0; sourcePointer < availableSourcesForFrame.size(); sourcePointer++) {
        qint32 sourceNo = availableSourcesForFrame[sourcePointer]; // Get the actual source

        // Start from 1 as 0 has no previous dropout
        qint32 i = 1;
        while (i < dropouts[sourceNo].startx.size()) {
            // Is the current dropout on the same field line as the last?
            if (dropouts[sourceNo].fieldLine[i - 1] == dropouts[sourceNo].fieldLine[i]) {
                if ((dropouts[sourceNo].endx[i - 1] + minimumGap) > (dropouts[sourceNo].startx[i])) {
                    // Concatenate
                    dropouts[sourceNo].endx[i - 1] = dropouts[sourceNo].endx[i];

                    // Remove the current dropout
                    dropouts[sourceNo].startx.removeAt(i);
                    dropouts[sourceNo].endx.removeAt(i);
                    dropouts[sourceNo].fieldLine.removeAt(i);
                }
            }

            // Next dropout
            i++;
        }
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

// Method to work out the disc type (CAV or CLV) and the maximum and minimum
// VBI frame numbers for the source
bool TbcSources::setDiscTypeAndMaxMinFrameVbi(qint32 sourceNumber)
{
    sourceVideos[sourceNumber]->isSourceCav = false;

    // Determine the disc type
    VbiDecoder vbiDecoder;
    qint32 cavCount = 0;
    qint32 clvCount = 0;

    qint32 typeCountMax = 100;
    if (sourceVideos[sourceNumber]->ldDecodeMetaData.getNumberOfFrames() < typeCountMax)
        typeCountMax = sourceVideos[sourceNumber]->ldDecodeMetaData.getNumberOfFrames();

    // Using sequential frame numbering starting from 1
    for (qint32 seqFrame = 1; seqFrame <= typeCountMax; seqFrame++) {
        // Get the VBI data and then decode
        QVector<qint32> vbi1 = sourceVideos[sourceNumber]->ldDecodeMetaData.getFieldVbi(sourceVideos[sourceNumber]->
                                                                                        ldDecodeMetaData.getFirstFieldNumber(seqFrame)).vbiData;
        QVector<qint32> vbi2 = sourceVideos[sourceNumber]->ldDecodeMetaData.getFieldVbi(sourceVideos[sourceNumber]->
                                                                                        ldDecodeMetaData.getSecondFieldNumber(seqFrame)).vbiData;
        VbiDecoder::Vbi vbi = vbiDecoder.decodeFrame(vbi1[0], vbi1[1], vbi1[2], vbi2[0], vbi2[1], vbi2[2]);

        // Look for a complete, valid CAV picture number or CLV time-code
        if (vbi.picNo > 0) cavCount++;

        if (vbi.clvHr != -1 && vbi.clvMin != -1 &&
                vbi.clvSec != -1 && vbi.clvPicNo != -1) clvCount++;
    }
    qDebug() << "Got" << cavCount << "CAV picture codes and" << clvCount << "CLV timecodes";

    // If the metadata has no picture numbers or time-codes, we cannot use the source
    if (cavCount == 0 && clvCount == 0) {
        qDebug() << "Source does not seem to contain valid CAV picture numbers or CLV time-codes - cannot process";
        return false;
    }

    // Determine disc type
    if (cavCount > clvCount) {
        sourceVideos[sourceNumber]->isSourceCav = true;
        qDebug() << "Got" << cavCount << "valid CAV picture numbers - source disc type is CAV";
        qInfo() << "Disc type is CAV";
    } else {
        sourceVideos[sourceNumber]->isSourceCav = false;
        qDebug() << "Got" << clvCount << "valid CLV picture numbers - source disc type is CLV";
        qInfo() << "Disc type is CLV";

    }

    // Disc has been mapped, so we can use the first and last frame numbers as the
    // min and max range of VBI frame numbers in the input source
    QVector<qint32> vbi1 = sourceVideos[sourceNumber]->ldDecodeMetaData.getFieldVbi(sourceVideos[sourceNumber]->
                                                                                    ldDecodeMetaData.getFirstFieldNumber(1)).vbiData;
    QVector<qint32> vbi2 = sourceVideos[sourceNumber]->ldDecodeMetaData.getFieldVbi(sourceVideos[sourceNumber]->
                                                                                    ldDecodeMetaData.getSecondFieldNumber(1)).vbiData;
    VbiDecoder::Vbi vbi = vbiDecoder.decodeFrame(vbi1[0], vbi1[1], vbi1[2], vbi2[0], vbi2[1], vbi2[2]);

    if (sourceVideos[sourceNumber]->isSourceCav) {
        sourceVideos[sourceNumber]->minimumVbiFrameNumber = vbi.picNo;
    } else {
        LdDecodeMetaData::ClvTimecode timecode;
        timecode.hours = vbi.clvHr;
        timecode.minutes = vbi.clvMin;
        timecode.seconds = vbi.clvSec;
        timecode.pictureNumber = vbi.clvPicNo;
        sourceVideos[sourceNumber]->minimumVbiFrameNumber = sourceVideos[sourceNumber]->ldDecodeMetaData.convertClvTimecodeToFrameNumber(timecode);
    }

    vbi1 = sourceVideos[sourceNumber]->ldDecodeMetaData.getFieldVbi(sourceVideos[sourceNumber]->
                       ldDecodeMetaData.getFirstFieldNumber(sourceVideos[sourceNumber]->ldDecodeMetaData.getNumberOfFrames())).vbiData;
    vbi2 = sourceVideos[sourceNumber]->ldDecodeMetaData.getFieldVbi(sourceVideos[sourceNumber]->
                       ldDecodeMetaData.getSecondFieldNumber(sourceVideos[sourceNumber]->ldDecodeMetaData.getNumberOfFrames())).vbiData;
    vbi = vbiDecoder.decodeFrame(vbi1[0], vbi1[1], vbi1[2], vbi2[0], vbi2[1], vbi2[2]);

    if (sourceVideos[sourceNumber]->isSourceCav) {
        sourceVideos[sourceNumber]->maximumVbiFrameNumber = vbi.picNo;
    } else {
        LdDecodeMetaData::ClvTimecode timecode;
        timecode.hours = vbi.clvHr;
        timecode.minutes = vbi.clvMin;
        timecode.seconds = vbi.clvSec;
        timecode.pictureNumber = vbi.clvPicNo;
        sourceVideos[sourceNumber]->maximumVbiFrameNumber = sourceVideos[sourceNumber]->ldDecodeMetaData.convertClvTimecodeToFrameNumber(timecode);
    }

    if (sourceVideos[sourceNumber]->isSourceCav) {
        // If the source is CAV frame numbering should be a minimum of 1 (it
        // can be 0 for CLV sources)
        if (sourceVideos[sourceNumber]->minimumVbiFrameNumber < 1) {
            qCritical() << "CAV start frame of" << sourceVideos[sourceNumber]->minimumVbiFrameNumber << "is out of bounds (should be 1 or above)";
            return false;
        }
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

// Method to find the median of a vector of qint32s
qint32 TbcSources::median(QVector<qint32> v)
{
    size_t n = v.size() / 2;
    std::nth_element(v.begin(), v.begin()+n, v.end());
    return v[n];
}

// Method to convert a linear IRE to a logarithmic reflective brightness %
// Note: Follows the Rec. 709 OETF transfer function
double TbcSources::convertLinearToBrightness(quint16 value, quint16 black16bIre, quint16 white16bIre, bool isSourcePal)
{
    double v = 0;
    double l = static_cast<double>(value);

    // Factors to scale Y according to the black to white interval
    // (i.e. make the black level 0 and the white level 65535)
    qreal yScale = (1.0 / (black16bIre - white16bIre)) * -65535;

    if (!isSourcePal) {
        // NTSC uses a 75% white point; so here we scale the result by
        // 25% (making 100 IRE 25% over the maximum allowed white point)
        yScale *= 125.0 / 100.0;
    }

    // Scale the L to 0-65535 where 0 = blackIreLevel and 65535 = whiteIreLevel
    l = (l - black16bIre) * yScale;
    l = qBound(0.0, l, 65535.0);

    // Scale L to 0.00-1.00
    l = (1.0 / 65535.0) * l;

    // Rec. 709 - https://en.wikipedia.org/wiki/Rec._709#Transfer_characteristics
    if (l < 0.018) {
        v = 4.500 * l;
    } else {
        v = pow(1.099 * l, 0.45) - 0.099;
    }

    return v;
}

















