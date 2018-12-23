/************************************************************************

    palcombfilter.cpp

    ld-comb-pal - PAL colourisation filter for ld-decode
    Copyright (C) 2018 Simon Inns

    This file is part of ld-decode-tools.

    ld-comb-pal is free software: you can redistribute it and/or
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

#include "palcombfilter.h"

PalCombFilter::PalCombFilter(QObject *parent) : QObject(parent)
{

}

// Method to get the available number of frames
qint32 PalCombFilter::getAvailableNumberOfFrames(void)
{
    qint32 frameOffset = 0;

    // It's possible that the TBC file will start on the wrong field, so we have to allow for
    // that here by skipping a field if the order isn't right
    if (!ldDecodeMetaData.getField(1).isFirstField) frameOffset++;

    return (sourceVideo.getNumberOfAvailableFields() / 2) - frameOffset;
}

// Method to get the first and second field numbers based on the frame number
qint32 PalCombFilter::getFirstFieldNumber(qint32 frameNumber)
{
    // Point at the first field in the TBC file (according to the current frame number)
    qint32 firstFieldNumber = (frameNumber * 2) - 1;
    qint32 secondFieldNumber = firstFieldNumber + 1;

    // It's possible that the TBC file will start on the wrong field, so we have to allow for
    // that here by skipping a field if the order isn't right
    if (!ldDecodeMetaData.getField(firstFieldNumber).isFirstField) {
        firstFieldNumber++;
        secondFieldNumber++;
        qDebug() << "PalCombFilter::getFirstFieldNumber(): TBC file has an extra field at the start (out of field order) - skipping";
    }

    // Range check the field number
    if (firstFieldNumber > sourceVideo.getNumberOfAvailableFields()) {
        qCritical() << "PalCombFilter::getFirstFieldNumber(): First field number exceed the available number of fields!";
        return 1;
    }

    // Range check the field number
    if (secondFieldNumber > sourceVideo.getNumberOfAvailableFields()) {
        qCritical() << "PalCombFilter::getFirstFieldNumber(): Second field number exceed the available number of fields!";
        return 2;
    }

    return firstFieldNumber;
}

qint32 PalCombFilter::getSecondFieldNumber(qint32 frameNumber)
{
    // Point at the first field in the TBC file (according to the current frame number)
    qint32 firstFieldNumber = (frameNumber * 2) - 1;
    qint32 secondFieldNumber = firstFieldNumber + 1;

    // It's possible that the TBC file will start on the wrong field, so we have to allow for
    // that here by skipping a field if the order isn't right
    if (!ldDecodeMetaData.getField(firstFieldNumber).isFirstField) {
        firstFieldNumber++;
        secondFieldNumber++;
        qDebug() << "PalCombFilter::getSecondFieldNumber(): TBC file has an extra field at the start (out of field order) - skipping";
    }

    // Range check the field number
    if (firstFieldNumber > sourceVideo.getNumberOfAvailableFields()) {
        qCritical() << "PalCombFilter::getSecondFieldNumber(): First field number exceed the available number of fields!";
        return 1;
    }

    // Range check the field number
    if (secondFieldNumber > sourceVideo.getNumberOfAvailableFields()) {
        qCritical() << "PalCombFilter::getSecondFieldNumber(): Second field number exceed the available number of fields!";
        return 2;
    }

    return secondFieldNumber;
}

bool PalCombFilter::process(QString inputFileName, QString outputFileName, qint32 startFrame, qint32 length, bool isVP415CropSet)
{
    qint32 maxThreads = 16;

    // Open the source video metadata
    if (!ldDecodeMetaData.read(inputFileName + ".json")) {
        qInfo() << "Unable to open ld-decode metadata file";
        return false;
    }

    LdDecodeMetaData::VideoParameters videoParameters = ldDecodeMetaData.getVideoParameters();

    // Ensure the source video is PAL
    if (!videoParameters.isSourcePal) {
        qInfo() << "This colour filter is for PAL video sources only";
        return false;
    }

    // Calculate the frame height
    qint32 frameHeight = (videoParameters.fieldHeight * 2) - 1;

    // Set the first and last active scan line
    qint32 firstActiveScanLine = 44;
    qint32 lastActiveScanLine = 617;
    qint32 videoStart = videoParameters.activeVideoStart;
    qint32 videoEnd = videoParameters.activeVideoEnd;

    // Calculate the VP415 video extents
    qreal vp415FirstActiveScanLine = firstActiveScanLine + ((frameHeight / 100) * 1.0);
    qreal vp415LastActiveScanLine = lastActiveScanLine - ((frameHeight / 100) * 1.0);
    qreal vp415VideoStart = videoParameters.activeVideoStart + ((videoParameters.fieldWidth / 100) * 1.0);
    qreal vp415VideoEnd = videoParameters.activeVideoEnd - ((videoParameters.fieldWidth / 100) * 1.0);

    if (isVP415CropSet) {
        firstActiveScanLine = static_cast<qint32>(vp415FirstActiveScanLine);
        lastActiveScanLine = static_cast<qint32>(vp415LastActiveScanLine);
        videoStart = static_cast<qint32>(vp415VideoStart);
        videoEnd = static_cast<qint32>(vp415VideoEnd);
    }

    // Make sure output height is even (better for ffmpeg processing)
    if (((lastActiveScanLine - firstActiveScanLine) % 2) != 0) {
       lastActiveScanLine--;
    }

    // Make sure output width is even (better for ffmpeg processing)
    if (((videoEnd - videoStart) % 2) != 0) {
       videoEnd++;
    }

    // Show output information to the user
    qInfo() << "Input video of" << videoParameters.fieldWidth << "x" << frameHeight <<
                   "will be colourised and trimmed to" << videoEnd - videoStart << "x" <<
                   lastActiveScanLine - firstActiveScanLine;

    // Define a vector of filtering threads to process the video
    QVector<FilterThread*> filterThreads;
    filterThreads.resize(maxThreads);
    for (qint32 i = 0; i < maxThreads; i++) {
        filterThreads[i] = new FilterThread(videoParameters, isVP415CropSet);
    }

    // Open the source video file
    if (!sourceVideo.open(inputFileName, videoParameters.fieldWidth * videoParameters.fieldHeight)) {
        // Could not open source video file
        qInfo() << "Unable to open ld-decode video file";
        return false;
    }

    // If no startFrame parameter was specified, set the start frame to 1
    if (startFrame == -1) startFrame = 1;

    if (startFrame > getAvailableNumberOfFrames()) {
        qInfo() << "Specified start frame is out of bounds, only" << getAvailableNumberOfFrames() << "frames available";
        return false;
    }

    // If no length parameter was specified set the length to the number of available frames
    if (length == -1) {
        length = getAvailableNumberOfFrames() - (startFrame - 1);
    } else {
        if (length + (startFrame - 1) > getAvailableNumberOfFrames()) {
            qInfo() << "Specified length of" << length << "exceeds the number of available frames, setting to" << getAvailableNumberOfFrames() - (startFrame - 1);
            length = getAvailableNumberOfFrames() - (startFrame - 1);
        }
    }

    qInfo() << "Processing from start frame #" << startFrame << "with a length of" << length << "frames";

    // Open the target video file (RGB)
    QFile targetVideo(outputFileName);
    if (!targetVideo.open(QIODevice::WriteOnly)) {
            // Could not open target video file
            qInfo() << "Unable to open output video file";
            sourceVideo.close();
            return false;
    }

    // Process the frames
    QElapsedTimer totalTimer;
    totalTimer.start();
    for (qint32 frameNumber = startFrame; frameNumber <= length + (startFrame - 1); frameNumber += maxThreads) {
        QElapsedTimer timer;
        timer.start();

        // Ensure we don't overflow the maximum number of frames to process
        // (limit the available number of threads to the remaining number of frames)
        if ((frameNumber +  maxThreads) > length + (startFrame - 1)) maxThreads = (length + startFrame) - frameNumber;

        QByteArray rgbOutputData;
        QVector<SourceField*> sourceFirstFields;
        QVector<SourceField*> sourceSecondFields;
        QVector<qreal> burstMedianIre;
        sourceFirstFields.resize(maxThreads);
        sourceSecondFields.resize(maxThreads);
        burstMedianIre.resize(maxThreads);

        // Perform filtering
        for (qint32 i = 0; i < maxThreads; i++) {
            // Determine the first and second fields for the frame number
            qint32 firstFieldNumber = getFirstFieldNumber(frameNumber + i);
            qint32 secondFieldNumber = getSecondFieldNumber(frameNumber + i);

            // Show what we are about to process
            qDebug() << "PalCombFilter::process(): Frame number" << frameNumber + i << "has a first-field of" << firstFieldNumber <<
                        "and a second field of" << secondFieldNumber;

            sourceFirstFields[i] = sourceVideo.getVideoField(firstFieldNumber);
            sourceSecondFields[i] = sourceVideo.getVideoField(secondFieldNumber);
            burstMedianIre[i] = ldDecodeMetaData.getField(firstFieldNumber).medianBurstIRE;
            filterThreads[i]->startFilter(sourceFirstFields[i]->getFieldData(), sourceSecondFields[i]->getFieldData(), burstMedianIre[i]);
        }

        for (qint32 i = 0; i < maxThreads; i++) {
            while (filterThreads[i]->isBusy());
            rgbOutputData = filterThreads[i]->getResult();

            // Save the frame data to the output file
            if (!targetVideo.write(rgbOutputData.data(), rgbOutputData.size())) {
                // Could not write to target video file
                qInfo() << "Writing to the output video file failed";
                targetVideo.close();
                sourceVideo.close();
                return false;
            }
        }

        // Show an update to the user
        qreal fps = maxThreads / (static_cast<qreal>(timer.elapsed()) / 1000.0);
        qInfo() << frameNumber + maxThreads - 1 << "frames processed -" << fps << "FPS";
    }

    qreal totalSecs = (static_cast<qreal>(totalTimer.elapsed()) / 1000.0);
    qInfo() << "Processing complete -" << length + (startFrame - 1) << "frames in" << totalSecs << "seconds (" <<
               (length + (startFrame - 1)) / totalSecs << "FPS )";

    // Close the source video
    sourceVideo.close();

    // Close the target video
    targetVideo.close();

    return true;
}
