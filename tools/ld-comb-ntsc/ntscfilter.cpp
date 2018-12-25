/************************************************************************

    ntscfilter.cpp

    ld-comb-ntsc - NTSC colourisation filter for ld-decode
    Copyright (C) 2018 Chad Page
    Copyright (C) 2018 Simon Inns

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
                         qint32 startFrame, qint32 length,
                         qint32 filterDepth, bool blackAndWhite,
                         bool adaptive2d, bool opticalFlow,
                         bool cropOutput, qint32 overrideBlack16Ire)
{
    // Open the source video metadata
    if (!ldDecodeMetaData.read(inputFileName + ".json")) {
        qInfo() << "Unable to open ld-decode metadata file";
        return false;
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
    qint32 firstActiveScanLine = 43;
    qint32 lastActiveScanLine = 525;

    // Calculate the LaserDisc crop video extents (visible area extent reduced by 1%)
    qreal tCropFirstActiveScanLine = firstActiveScanLine + ((frameHeight / 100) * 1.0);
    qreal tCropLastActiveScanLine = lastActiveScanLine - ((frameHeight / 100) * 1.0);
    qreal tCropVideoStart = videoParameters.activeVideoStart + ((videoParameters.fieldWidth / 100) * 1.0);
    qreal tCropVideoEnd = videoParameters.activeVideoEnd - ((videoParameters.fieldWidth / 100) * 1.0);

    // Default to standard output size
    qint32 cropFirstActiveScanLine = firstActiveScanLine;
    qint32 cropLastActiveScanLine = lastActiveScanLine;
    qint32 cropVideoStart = videoParameters.activeVideoStart;
    qint32 cropVideoEnd = videoParameters.activeVideoEnd;

    // Include additional cropping if required
    if (cropOutput) {
        cropFirstActiveScanLine = static_cast<qint32>(tCropFirstActiveScanLine);
        cropLastActiveScanLine = static_cast<qint32>(tCropLastActiveScanLine);
        cropVideoStart = static_cast<qint32>(tCropVideoStart);
        cropVideoEnd = static_cast<qint32>(tCropVideoEnd);
    }

    // Make sure output height is even (better for ffmpeg processing)
    if (((cropLastActiveScanLine - cropFirstActiveScanLine) % 2) != 0) {
        cropLastActiveScanLine--;
    }

    // Make sure output width is even (better for ffmpeg processing)
    if (((cropVideoEnd - cropVideoStart) % 2) != 0) {
        cropVideoEnd++;
    }

    // Show output information to the user
    qInfo() << "Input video of" << videoParameters.fieldWidth << "x" << frameHeight <<
               "will be colourised and trimmed to" << static_cast<qint32>(cropVideoEnd) - static_cast<qint32>(cropVideoStart) << "x" <<
               static_cast<qint32>(cropLastActiveScanLine) - static_cast<qint32>(cropFirstActiveScanLine);

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
    if (!targetVideo.open(QIODevice::WriteOnly)) {
            // Failed to open output file
            qCritical() << "Could not open " << outputFileName << "as RGB output file";
            sourceVideo.close();
            return false;
    }

    // Create the comb filter object
    Comb comb;

    // Get the default configuration for the comb filter
    Comb::Configuration configuration = comb.getConfiguration();

    // Set the comb filter configuration
    configuration.filterDepth = filterDepth;
    configuration.blackAndWhite = blackAndWhite;
    configuration.adaptive2d = adaptive2d;
    configuration.opticalflow = opticalFlow;

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
    if (overrideBlack16Ire != -1) configuration.blackIre = overrideBlack16Ire;

    // Update the comb filter object's configuration
    comb.setConfiguration(configuration);

    // Show the filter type being used
    if (configuration.filterDepth == 1) qInfo() << "Processing with 1D filter";
    else if (configuration.filterDepth == 2) qInfo() << "Processing with 2D filter";
    else if (configuration.filterDepth == 3) qInfo() << "Processing with 3D filter";
    else {
        qCritical() << "Error: Filter depth is invalid!";
        return false;
    }

    // Show the filter configuration
    qInfo() << "Filter configuration: Black & white output =" << blackAndWhite;
    qInfo() << "Filter configuration: Adaptive 2D =" << adaptive2d;
    qInfo() << "Filter configuration: Optical flow =" << opticalFlow;

    if (overrideBlack16Ire != -1) qInfo() << "Overriding JSON Black16IRE with" << overrideBlack16Ire;

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

        // Check the output data isn't empty (the first two 3D processed frames are empty)
        if (!rgbOutputData.isEmpty()) {
            // The NTSC filter outputs the whole frame, so here we crop it to the required dimensions
            QByteArray croppedOutputData;

            for (qint32 y = static_cast<qint32>(cropFirstActiveScanLine); y < static_cast<qint32>(cropLastActiveScanLine); y++) {
                croppedOutputData.append(rgbOutputData.mid((y * videoParameters.fieldWidth * 6) + (static_cast<qint32>(cropVideoStart) * 6),
                                                        ((static_cast<qint32>(cropVideoEnd) - static_cast<qint32>(cropVideoStart)) * 6)));
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

    // Close the input and output files
    sourceVideo.close();
    targetVideo.close();

    return true;
}

