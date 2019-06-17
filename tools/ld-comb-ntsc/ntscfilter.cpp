/************************************************************************

    ntscfilter.cpp

    ld-comb-ntsc - NTSC colourisation filter for ld-decode
    Copyright (C) 2018 Chad Page
    Copyright (C) 2018-2019 Simon Inns

    This file is part of ld-decode-tools.

    ld-comb-ntsc is free software: you can redistribute it and/or
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

#include "ntscfilter.h"

NtscFilter::NtscFilter(QObject *parent) : QObject(parent)
{

}

bool NtscFilter::process(QString inputFileName, QString outputFileName,
                         qint32 startFrame, qint32 length, bool reverse,
                         bool blackAndWhite, bool whitePoint, bool use3D,
                         bool showOpticalFlowMap)
{
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

    // Ensure the source video is NTSC
    if (videoParameters.isSourcePal) {
        qInfo() << "This colour filter is for NTSC video sources only";
        return false;
    }

    // Calculate the frame height
    qint32 frameHeight = (videoParameters.fieldHeight * 2) - 1;

    // Set the first and last active scan line
    qint32 firstActiveScanLine = 40;
    qint32 lastActiveScanLine = 525;

    // Default to standard output size
    qint32 videoStart = videoParameters.activeVideoStart;
    qint32 videoEnd = videoParameters.activeVideoEnd;

    // Make sure output width is divisible by 8 (better for ffmpeg processing)
    while (((videoEnd - videoStart) % 8) != 0) {
        videoEnd++;
    }

    // Show output information to the user
    qInfo() << "Input video of" << videoParameters.fieldWidth << "x" << frameHeight <<
               "will be colourised and trimmed to" << static_cast<qint32>(videoEnd) - static_cast<qint32>(videoStart) << "x 488";

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

    // Open the output RGB file
    QFile targetVideo(outputFileName);
    if (outputFileName.isNull()) {
        // No output filename, use stdout instead
        if (!targetVideo.open(stdout, QIODevice::WriteOnly)) {
            // Failed to open stdout
            qCritical() << "Could not open stdout for RGB output";
            sourceVideo.close();
            return false;
        }
        qInfo() << "Using stdout as RGB output";
    } else {
        // Open output file
        if (!targetVideo.open(QIODevice::WriteOnly)) {
            // Failed to open output file
            qCritical() << "Could not open " << outputFileName << "as RGB output file";
            sourceVideo.close();
            return false;
        }
    }

    // Create the comb filter object
    Comb comb;

    // Get the default configuration for the comb filter
    Comb::Configuration configuration = comb.getConfiguration();

    // Set the comb filter configuration
    configuration.blackAndWhite = blackAndWhite;
    configuration.whitePoint100 = whitePoint;

    // Set the input buffer dimensions configuration
    configuration.fieldWidth = videoParameters.fieldWidth;
    configuration.fieldHeight = videoParameters.fieldHeight;

    // Set the active video range
    configuration.activeVideoStart = videoParameters.activeVideoStart;
    configuration.activeVideoEnd = videoParameters.activeVideoEnd;

    // Set the first frame scan line which contains active video
    configuration.firstVisibleFrameLine = firstActiveScanLine;

    // Set the IRE levels
    configuration.blackIre = videoParameters.black16bIre;
    configuration.whiteIre = videoParameters.white16bIre;

    // Set the filter type
    configuration.use3D = use3D;
    configuration.showOpticalFlowMap = showOpticalFlowMap;

    // Update the comb filter object's configuration
    comb.setConfiguration(configuration);

    // Show the filter configuration
    qInfo() << "Filter configuration: Black & white output =" << blackAndWhite;
    qInfo() << "Filter configuration: Use 75% white-point =" << whitePoint;

    // Process the frames
    QElapsedTimer totalTimer;
    totalTimer.start();
    for (qint32 frameNumber = startFrame; frameNumber <= length + (startFrame - 1); frameNumber++) {
        QElapsedTimer timer;
        timer.start();

        // Determine the top and bottom fields for the frame number
        qint32 firstFieldNumber = ldDecodeMetaData.getFirstFieldNumber(frameNumber);
        qint32 secondFieldNumber = ldDecodeMetaData.getSecondFieldNumber(frameNumber);

        // Filter the frame
        QByteArray rgbOutputData = comb.process(sourceVideo.getVideoField(firstFieldNumber)->getFieldData(), sourceVideo.getVideoField(secondFieldNumber)->getFieldData(),
                                                ldDecodeMetaData.getField(firstFieldNumber).medianBurstIRE,
                                                ldDecodeMetaData.getField(firstFieldNumber).fieldPhaseID,
                                                ldDecodeMetaData.getField(secondFieldNumber).fieldPhaseID);

        // Check the output data isn't empty
        if (!rgbOutputData.isEmpty()) {
            // The NTSC filter outputs the whole frame, so here we crop it to the required dimensions
            QByteArray croppedOutputData;

            // Add additional output lines to ensure the output height is 488 lines
            QByteArray blankLine;
            blankLine.resize((videoEnd - videoStart) * 6 );
            blankLine.fill(0);
            for (qint32 y = 0; y < 488 - (lastActiveScanLine - firstActiveScanLine); y++) {
                croppedOutputData.append(blankLine);
            }

            for (qint32 y = static_cast<qint32>(firstActiveScanLine); y < static_cast<qint32>(lastActiveScanLine); y++) {
                croppedOutputData.append(rgbOutputData.mid((y * videoParameters.fieldWidth * 6) + (static_cast<qint32>(videoStart) * 6),
                                                        ((static_cast<qint32>(videoEnd) - static_cast<qint32>(videoStart)) * 6)));
            }

            // Save the frame data to the output file
            if (!targetVideo.write(croppedOutputData.data(), croppedOutputData.size())) {
                // Could not write to target video file
                qInfo() << "Writing to the output video file failed";
                targetVideo.close();
                sourceVideo.close();
                return false;
            }
        } else {
            qDebug() << "NtscFilter::process(): No RGB video data was returned by the comb filter";
        }

        // Show an update to the user
        qreal fps = 1.0 / (static_cast<qreal>(timer.elapsed()) / 1000.0);
        qInfo() << "Processed Frame number" << frameNumber << "( fields" << firstFieldNumber <<
                    "/" << secondFieldNumber << ") -" << fps << "FPS";
    }

    // Show processing summary
    qInfo() << "Processed" << length << "frames into" <<
               static_cast<qint32>(videoEnd) - static_cast<qint32>(videoStart) << "x 488 RGB16-16-16 frames";

    // Close the input and output files
    sourceVideo.close();
    targetVideo.close();

    return true;
}

