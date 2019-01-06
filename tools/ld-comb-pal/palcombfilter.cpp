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

bool PalCombFilter::process(QString inputFileName, QString outputFileName, qint32 startFrame, qint32 length, bool reverse)
{
    qint32 maxThreads = 16;

    // Open the source video metadata
    if (!ldDecodeMetaData.read(inputFileName + ".json")) {
        qInfo() << "Unable to open ld-decode metadata file";
        return false;
    }

    // Reverse field order if required
    if (reverse) {
        qInfo() << "Expected field order is reversed to second field/first field";
        ldDecodeMetaData.setIsFirstFieldFirst(false);
    }

    LdDecodeMetaData::VideoParameters videoParameters = ldDecodeMetaData.getVideoParameters();

    // Ensure the source video is PAL
    if (!videoParameters.isSourcePal) {
        qInfo() << "This colour filter is for PAL video sources only";
        return false;
    }

    // Calculate the frame height
    qint32 frameHeight = (videoParameters.fieldHeight * 2) - 1;

    // Set the width of the active scan line
    qint32 videoStart = videoParameters.activeVideoStart;
    qint32 videoEnd = videoParameters.activeVideoEnd;

    // Make sure output width is even (better for ffmpeg processing)
    if (((videoEnd - videoStart) % 2) != 0) {
       videoEnd++;
    }

    // Show output information to the user
    qInfo() << "Input video of" << videoParameters.fieldWidth << "x" << frameHeight <<
                   "will be colourised and trimmed to" << videoEnd - videoStart << "x 576";

    // Define a vector of filtering threads to process the video
    QVector<FilterThread*> filterThreads;
    filterThreads.resize(maxThreads);
    for (qint32 i = 0; i < maxThreads; i++) {
        filterThreads[i] = new FilterThread(videoParameters);
    }

    // Open the source video file
    if (!sourceVideo.open(inputFileName, videoParameters.fieldWidth * videoParameters.fieldHeight)) {
        // Could not open source video file
        qInfo() << "Unable to open ld-decode video file";
        return false;
    }

    // If no startFrame parameter was specified, set the start frame to 1
    if (startFrame == -1) startFrame = 1;

    if (startFrame > ldDecodeMetaData.getNumberOfFrames()) {
        qInfo() << "Specified start frame is out of bounds, only" << ldDecodeMetaData.getNumberOfFrames() << "frames available";
        return false;
    }

    // If no length parameter was specified set the length to the number of available frames
    if (length == -1) {
        length = ldDecodeMetaData.getNumberOfFrames() - (startFrame - 1);
    } else {
        if (length + (startFrame - 1) > ldDecodeMetaData.getNumberOfFrames()) {
            qInfo() << "Specified length of" << length << "exceeds the number of available frames, setting to" << ldDecodeMetaData.getNumberOfFrames() - (startFrame - 1);
            length = ldDecodeMetaData.getNumberOfFrames() - (startFrame - 1);
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
            qint32 firstFieldNumber = ldDecodeMetaData.getFirstFieldNumber(frameNumber + i);
            qint32 secondFieldNumber = ldDecodeMetaData.getSecondFieldNumber(frameNumber + i);

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

    // Show processing summary
    qInfo() << "Processed" << length + (startFrame - 1) << "frames into" <<
               videoEnd - videoStart << "x 576" <<
               "RGB16-16-16 frames";

    // Close the source video
    sourceVideo.close();

    // Close the target video
    targetVideo.close();

    return true;
}
