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
    backgroundLoadErrorMessage.clear();
    dropoutsOn = false;
}

// Load a TBC source video; returns updated current source number or -1 on failure
void TbcSources::loadSource(QString filename)
{
    // Set up and fire-off the background loading thread
    qDebug() << "TbcSources::loadSource(): Setting up background loader thread";
    connect(&watcher, SIGNAL(finished()), this, SLOT(finishBackgroundLoad()));
    future = QtConcurrent::run(this, &TbcSources::performBackgroundLoad, filename);
    watcher.setFuture(future);
}

// Returns the last recorded loading message (for error boxes, etc.)
QString TbcSources::getLoadingMessage()
{
    return backgroundLoadErrorMessage;
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

// Set the currently active source number
bool TbcSources::setCurrentSource(qint32 sourceNumber)
{
    if (sourceNumber > (sourceVideos.size() - 1)) {
        qDebug() << "TbcSources::setCurrentSource(): Invalid source number of" << sourceNumber << "requested!";
        return false;
    }

    currentSource = sourceNumber;
    qDebug() << "TbcSources::setCurrentSource(): Current source set to " << sourceNumber;
    return true;
}

// Get the currently active source number
qint32 TbcSources::getCurrentSource()
{
    return currentSource;
}

// Get the number of available sources
qint32 TbcSources::getNumberOfAvailableSources()
{
    return sourceVideos.size();
}

// Get a list of the available sources in order of source number
QVector<QString> TbcSources::getListOfAvailableSources()
{
    QVector<QString> sourceIds;

    for (qint32 i = 0; i < sourceVideos.size(); i++) {
        QFileInfo fileInfo(sourceVideos[i]->filename);
        QString idText = "#" + QString::number(i) + " - " + fileInfo.fileName();
        sourceIds.append(idText);
    }

    return sourceIds;
}

// Perform diffDOD in a background thread
void TbcSources::performDiffDod()
{
    // Set up and fire-off the background diffDOD thread
    qDebug() << "TbcSources::performDiffDod(): Setting up background diffDOD thread";
    connect(&watcher, SIGNAL(finished()), this, SLOT(finishBackgroundDiffDod()));
    future = QtConcurrent::run(this, &TbcSources::performBackgroundDiffDod);
    watcher.setFuture(future);
}

// Get a QImage of the current source's current frame
QImage TbcSources::getCurrentFrameImage()
{
    // Get the metadata for the video parameters
    LdDecodeMetaData::VideoParameters videoParameters = sourceVideos[currentSource]->ldDecodeMetaData.getVideoParameters();

    // Calculate the frame height
    qint32 frameHeight = (videoParameters.fieldHeight * 2) - 1;

    // Create a QImage
    QImage frameImage = QImage(videoParameters.fieldWidth, frameHeight, QImage::Format_RGB888);

    // Check that the current source is in range of the require frame number
    if (currentVbiFrameNumber < sourceVideos[currentSource]->minimumVbiFrameNumber || currentVbiFrameNumber > sourceVideos[currentSource]->maximumVbiFrameNumber) {
        // Out of range of the current source - return a dummy frame
        frameImage.fill(Qt::blue);

        // Show debug information
        qDebug().nospace() << "TbcSources::getCurrentFrameImage(): Source frame is out of range - generating dummy image (" <<
                              videoParameters.fieldWidth << "x" << frameHeight << ")";
    } else {
        // Offset the VBI frame number to get the sequential source frame number
        qint32 frameNumber = convertVbiFrameNumberToSequential(currentVbiFrameNumber, currentSource);
        qDebug() << "TbcSources::getCurrentFrameImage(): Request for VBI frame number" << currentVbiFrameNumber << "translated to frame number" << frameNumber;

        // Get the required field numbers
        qint32 firstFieldNumber = sourceVideos[currentSource]->ldDecodeMetaData.getFirstFieldNumber(frameNumber);
        qint32 secondFieldNumber = sourceVideos[currentSource]->ldDecodeMetaData.getSecondFieldNumber(frameNumber);

        // Ensure the frame is not a padded field (i.e. missing)
        if (!(sourceVideos[currentSource]->ldDecodeMetaData.getField(firstFieldNumber).pad &&
              sourceVideos[currentSource]->ldDecodeMetaData.getField(secondFieldNumber).pad)) {

            // Get the video field data
            QByteArray firstFieldData = sourceVideos[currentSource]->sourceVideo.getVideoField(firstFieldNumber);
            QByteArray secondFieldData = sourceVideos[currentSource]->sourceVideo.getVideoField(secondFieldNumber);

            // Show debug information
            qDebug().nospace() << "TbcSources::getCurrentFrameImage(): Generating a source image from field pair " << firstFieldNumber <<
                        "/" << secondFieldNumber << " (" << videoParameters.fieldWidth << "x" <<
                        frameHeight << ")";

            // Define the data buffers
            QByteArray firstLineData;
            QByteArray secondLineData;

            // Copy the raw 16-bit grayscale data into the RGB888 QImage
            for (qint32 y = 0; y < frameHeight; y++) {
                // Extract the current scan line data from the frame
                qint32 startPointer = (y / 2) * videoParameters.fieldWidth * 2;
                qint32 length = videoParameters.fieldWidth * 2;

                firstLineData = firstFieldData.mid(startPointer, length);
                secondLineData = secondFieldData.mid(startPointer, length);

                for (qint32 x = 0; x < videoParameters.fieldWidth; x++) {
                    // Take just the MSB of the input data
                    qint32 dp = x * 2;
                    uchar pixelValue;
                    if (y % 2) {
                        pixelValue = static_cast<uchar>(secondLineData[dp + 1]);
                    } else {
                        pixelValue = static_cast<uchar>(firstLineData[dp + 1]);
                    }

                    qint32 xpp = x * 3;
                    *(frameImage.scanLine(y) + xpp + 0) = static_cast<uchar>(pixelValue); // R
                    *(frameImage.scanLine(y) + xpp + 1) = static_cast<uchar>(pixelValue); // G
                    *(frameImage.scanLine(y) + xpp + 2) = static_cast<uchar>(pixelValue); // B
                }
            }

            // Highlight dropouts
            if (dropoutsOn) {
                // Create a painter object
                QPainter imagePainter;
                imagePainter.begin(&frameImage);

                // Draw the drop out data for the first field
                imagePainter.setPen(Qt::red);
                LdDecodeMetaData::DropOuts firstFieldDropouts = sourceVideos[currentSource]->ldDecodeMetaData.getFieldDropOuts(firstFieldNumber);
                for (qint32 dropOutIndex = 0; dropOutIndex < firstFieldDropouts.startx.size(); dropOutIndex++) {
                    qint32 startx = firstFieldDropouts.startx[dropOutIndex];
                    qint32 endx = firstFieldDropouts.endx[dropOutIndex];
                    qint32 fieldLine = firstFieldDropouts.fieldLine[dropOutIndex];

                    imagePainter.drawLine(startx, ((fieldLine - 1) * 2), endx, ((fieldLine - 1) * 2));
                }

                // Draw the drop out data for the second field
                imagePainter.setPen(Qt::blue);
                LdDecodeMetaData::DropOuts secondFieldDropouts = sourceVideos[currentSource]->ldDecodeMetaData.getFieldDropOuts(secondFieldNumber);
                for (qint32 dropOutIndex = 0; dropOutIndex < secondFieldDropouts.startx.size(); dropOutIndex++) {
                    qint32 startx = secondFieldDropouts.startx[dropOutIndex];
                    qint32 endx = secondFieldDropouts.endx[dropOutIndex];
                    qint32 fieldLine = secondFieldDropouts.fieldLine[dropOutIndex];

                    imagePainter.drawLine(startx, ((fieldLine - 1) * 2) + 1, endx, ((fieldLine - 1) * 2) + 1);
                }

                qDebug() << "TbcSources::getCurrentFrameImage(): Highlighting dropouts -" << firstFieldDropouts.startx.size() << "first field and" <<
                            secondFieldDropouts.startx.size() << "second field";

                // End the painter object
                imagePainter.end();
            }
        } else {
            // Frame is missing from source - return a dummy frame
            frameImage.fill(Qt::red);

            // Show debug information
            qDebug().nospace() << "TbcSources::getCurrentFrameImage(): Source frame is missing/padded - generating dummy image (" <<
                                  videoParameters.fieldWidth << "x" << frameHeight << ")";
        }
    }

    return frameImage;
}

// Get the field greyscale data of the current source's current frame
TbcSources::RawFrame TbcSources::getCurrentFrameData()
{
    RawFrame rawFrame;

    // Get the required field numbers
    qint32 firstFieldNumber = sourceVideos[currentSource]->ldDecodeMetaData.getFirstFieldNumber(currentVbiFrameNumber);
    qint32 secondFieldNumber = sourceVideos[currentSource]->ldDecodeMetaData.getSecondFieldNumber(currentVbiFrameNumber);

    // Get the metadata for the video parameters
    LdDecodeMetaData::VideoParameters videoParameters = sourceVideos[currentSource]->ldDecodeMetaData.getVideoParameters();

    // Get the video field data
    rawFrame.firstFieldData = sourceVideos[currentSource]->sourceVideo.getVideoField(firstFieldNumber);
    rawFrame.secondFieldData = sourceVideos[currentSource]->sourceVideo.getVideoField(secondFieldNumber);
    rawFrame.fieldHeight = videoParameters.fieldHeight;
    rawFrame.fieldWidth = videoParameters.fieldWidth;

    return rawFrame;
}

// Get the number of frames available from the current source
qint32 TbcSources::getCurrentSourceNumberOfFrames()
{
    if (sourceVideos.size() == 0) return -1;
    return sourceVideos[currentSource]->ldDecodeMetaData.getNumberOfFrames();
}

// Get the currently selected frame number of the current source
qint32 TbcSources::getCurrentVbiFrameNumber()
{
    if (sourceVideos.size() == 0) return -1;
    return currentVbiFrameNumber;
}

// Set the current frame number of the current source
void TbcSources::setCurrentVbiFrameNumber(qint32 frameNumber)
{
    if (sourceVideos.size() == 0) return;

    // Range check the request
    if (frameNumber < getMinimumVbiFrameNumber()) {
        qDebug() << "TbcSources::setCurrentFrameNumber(): Request to set current frame number to" << frameNumber <<
                    "is out of bounds ( before start of" << getMinimumVbiFrameNumber() << " ) - Frame number set to" << getMinimumVbiFrameNumber();
        frameNumber = getMinimumVbiFrameNumber();
    }

    if (frameNumber > getMaximumVbiFrameNumber()) {
        qDebug() << "TbcSources::setCurrentFrameNumber(): Request to set current frame number to" << frameNumber <<
                    "is out of bounds ( after end of" << getMaximumVbiFrameNumber() << " ) - Frame number set to" << getMaximumVbiFrameNumber();
        frameNumber = getMaximumVbiFrameNumber();
    }

    // Set the current frame number
    currentVbiFrameNumber = frameNumber;
}

// Get the current source's filename
QString TbcSources::getCurrentSourceFilename()
{
    if (sourceVideos.size() == 0) return QString();
    return sourceVideos[currentSource]->filename;
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

// Get the minimum VBI frame number for the current source
qint32 TbcSources::getCurrentSourceMinimumVbiFrameNumber()
{
    return sourceVideos[currentSource]->minimumVbiFrameNumber;
}

// Get the maximum VBI frame number for the current source
qint32 TbcSources::getCurrentSourceMaximumVbiFrameNumber()
{
    return sourceVideos[currentSource]->maximumVbiFrameNumber;
}

// Method to set the highlight dropouts mode (true = dropouts highlighted)
void TbcSources::setHighlightDropouts(bool _state)
{
    dropoutsOn = _state;
}

// Private methods ----------------------------------------------------------------------------------------------------

// Method to load a new source in the background
void TbcSources::performBackgroundLoad(QString filename)
{
    // Set the parent's busy state
    emit setBusy("Please wait loading...", false, 0);

    // Check that source file isn't already loaded
    for (qint32 i = 0; i < sourceVideos.size(); i++) {
        if (filename == sourceVideos[i]->filename) {
            qDebug() << "TbcSources::performBackgroundLoad(): Cannot load source - already loaded!";
            backgroundLoadErrorMessage = "Cannot load source - source is already loaded!";
            backgroundLoadSuccessful = false;
            return;
        }
    }

    backgroundLoadSuccessful = true;
    sourceVideos.resize(sourceVideos.size() + 1);
    qint32 newSourceNumber = sourceVideos.size() - 1;
    sourceVideos[newSourceNumber] = new Source;
    LdDecodeMetaData::VideoParameters videoParameters;

    // Open the TBC metadata file
    qDebug() << "TbcSources::performBackgroundLoad(): Processing JSON metadata...";
    emit setBusy("Processing JSON metadata...", false, 0);
    if (!sourceVideos[newSourceNumber]->ldDecodeMetaData.read(filename + ".json")) {
        // Open failed
        qWarning() << "Open TBC JSON metadata failed for filename" << filename;
        backgroundLoadErrorMessage = "Cannot load source - JSON metadata could not be read!";
        backgroundLoadSuccessful = false;
    }

    // Get the video parameters from the metadata
    if (backgroundLoadSuccessful) {
        videoParameters = sourceVideos[newSourceNumber]->ldDecodeMetaData.getVideoParameters();

        // Ensure that the TBC file has been mapped
        if (!videoParameters.isMapped) {
            qWarning() << "New source video has not been mapped!";
            backgroundLoadErrorMessage = "Cannot load source - The TBC has not been mapped (please run ld-discmap on the source)!";
            backgroundLoadSuccessful = false;
        }
    }

    // Ensure that the video standard matches any existing sources
    if (backgroundLoadSuccessful) {
        if ((sourceVideos.size() - 1 > 0) && (sourceVideos[0]->ldDecodeMetaData.getVideoParameters().isSourcePal != videoParameters.isSourcePal)) {
            qWarning() << "New source video standard does not match existing source(s)!";
            backgroundLoadErrorMessage = "Cannot load source - Mixing PAL and NTSC sources is not supported!";
            backgroundLoadSuccessful = false;
        }
    }

    // Ensure that the video has VBI data
    if (backgroundLoadSuccessful) {
        if (!sourceVideos[newSourceNumber]->ldDecodeMetaData.getFieldVbi(1).inUse) {
            qWarning() << "New source video does not contain VBI data!";
            backgroundLoadErrorMessage = "Cannot load source - No VBI data available. Please run ld-process-vbi before loading source!";
            backgroundLoadSuccessful = false;
        }
    }

    // Determine the minimum and maximum VBI frame number and the disc type
    if (backgroundLoadSuccessful) {
        qDebug() << "TbcSources::loadSource(): Determining disc type and VBI frame range...";
        emit setBusy("Determining disc type and VBI frame range...", false, 0);
        if (!setDiscTypeAndMaxMinFrameVbi(newSourceNumber)) {
            // Failed
            qWarning() << "Could not determine disc type or VBI range";
            backgroundLoadErrorMessage = "Cannot load source - Could not determine disc type and/or VBI frame range!";
            backgroundLoadSuccessful = false;
        }
    }

    // Open the new source TBC video
    if (backgroundLoadSuccessful) {
        qDebug() << "TbcSources::loadSource(): Loading TBC file...";
        emit setBusy("Loading TBC file...", false, 0);

        if (!sourceVideos[newSourceNumber]->sourceVideo.open(filename, videoParameters.fieldWidth * videoParameters.fieldHeight)) {
           // Open failed
           qWarning() << "Open TBC file failed for filename" << filename;
           backgroundLoadErrorMessage = "Cannot load source - Error reading source TBC data file!";
           backgroundLoadSuccessful = false;
        }
    }

    // Finish up
    if (backgroundLoadSuccessful) {
        // Loading successful
        sourceVideos[newSourceNumber]->filename = filename;
        backgroundLoadSuccessful = true;
    } else {
        // Loading unsuccessful - Remove the new source entry and default the current source
        sourceVideos[newSourceNumber]->sourceVideo.close();
        delete sourceVideos[newSourceNumber];
        sourceVideos.remove(newSourceNumber);
        currentSource = 0;
        return;
    }

    // Select the new source
    currentSource = newSourceNumber;

    // Exit with success
    backgroundLoadErrorMessage = "";
    return;
}

// Method to handle background source loading finished
void TbcSources::finishBackgroundLoad()
{
    qDebug() << "TbcSources::finishBackgroundLoad(): Called - clearing busy and updating sources";

    // Disconnect the finished signal
    disconnect(&watcher, SIGNAL(finished()), this, SLOT(finishBackgroundLoad()));

    if (backgroundLoadSuccessful) qDebug() << "TbcSources::finishBackgroundLoad(): Background load was successful";
    else qDebug() << "TbcSources::finishBackgroundLoad(): Background load failed!";

    // Clear the parent's busy state
    emit clearBusy();

    // Tell the parent to update the sources
    emit updateSources(backgroundLoadSuccessful);
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
        QVector<qint32> vbi1 = sourceVideos[sourceNumber]->ldDecodeMetaData.getFieldVbi(sourceVideos[sourceNumber]->ldDecodeMetaData.getFirstFieldNumber(seqFrame)).vbiData;
        QVector<qint32> vbi2 = sourceVideos[sourceNumber]->ldDecodeMetaData.getFieldVbi(sourceVideos[sourceNumber]->ldDecodeMetaData.getSecondFieldNumber(seqFrame)).vbiData;
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

        sourceVideos[sourceNumber]->maximumVbiFrameNumber = cavMax;
        sourceVideos[sourceNumber]->minimumVbiFrameNumber = cavMin;
    } else {
        sourceVideos[sourceNumber]->isSourceCav = false;;
        qDebug() << "TbcSources::getIsSourceCav(): Got" << clvCount << "valid CLV picture numbers - source disc type is CLV";

        sourceVideos[sourceNumber]->maximumVbiFrameNumber = clvMax;
        sourceVideos[sourceNumber]->minimumVbiFrameNumber = clvMin;
    }

    qDebug() << "TbcSources::setDiscTypeAndMaxMinFrameVbi(): Minimum VBI frame number is" << sourceVideos[sourceNumber]->minimumVbiFrameNumber;
    qDebug() << "TbcSources::setDiscTypeAndMaxMinFrameVbi(): Maximum VBI frame number is" << sourceVideos[sourceNumber]->maximumVbiFrameNumber;

    return true;
}

// Perform the background diffDOD of the current source
void TbcSources::performBackgroundDiffDod()
{
    // Set the parent's busy state
    emit setBusy("Please wait performing diffDOD...", false, 0);

    for (qint32 vbiFrameNumber = sourceVideos[currentSource]->minimumVbiFrameNumber; vbiFrameNumber <= sourceVideos[currentSource]->maximumVbiFrameNumber; vbiFrameNumber++) {

        diffDodFrame(vbiFrameNumber, 6000);

        if (vbiFrameNumber % 10 == 0) {
            QString updateString = "Processing VBI frame #" + QString::number(vbiFrameNumber);
            emit setBusy(updateString, false, 0);
        }
    }
}

// Finish the diffDOD background task
void TbcSources::finishBackgroundDiffDod()
{
    qDebug() << "TbcSources::finishBackgroundDiffDod(): Called - clearing busy";

    // Disconnect the finished signal
    disconnect(&watcher, SIGNAL(finished()), this, SLOT(finishBackgroundDiffDod()));

    // Clear the parent's busy state
    emit clearBusy();
}

// Perform differential dropout detection and update the current source's metadata
// Threshold is best around 6000-10000
// targetSource + targetVbiFrame is the source and frame to generate dropout data for
void TbcSources::diffDodFrame(qint32 targetVbiFrame, qint32 threshold)
{
    // Range check the threshold
    if (threshold < 100) threshold = 100;
    if (threshold > 16284) threshold = 16284;

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

    // Differential DOD requires at least three frames (including the current frame)
    if (availableSourceFrames.size() < 3) {
        // Differential DOD requires at least 3 valid source frames
        qDebug() << "TbcSources::performDifferentialDropoutDetection(): Only" << availableSourceFrames.size() << "source frames are available - can not perform DOD";
        return;
    }

    // Get the metadata for the video parameters (all sources are the same, so just grab from the first)
    LdDecodeMetaData::VideoParameters videoParameters = sourceVideos[0]->ldDecodeMetaData.getVideoParameters();

    // Perform the diffDOD

    // Define the temp dropout metadata
    struct FrameDropOuts {
        LdDecodeMetaData::DropOuts firstFieldDropOuts;
        LdDecodeMetaData::DropOuts secondFieldDropOuts;
    };

    QVector<FrameDropOuts> frameDropouts;
    frameDropouts.resize(availableSourceFrames.size());

    QVector<QByteArray> firstFields;
    QVector<QByteArray> secondFields;
    firstFields.resize(availableSourceFrames.size());
    secondFields.resize(availableSourceFrames.size());

    QVector<quint16*> sourceFirstFieldPointer;
    QVector<quint16*> sourceSecondFieldPointer;
    sourceFirstFieldPointer.resize(availableSourceFrames.size());
    sourceSecondFieldPointer.resize(availableSourceFrames.size());

    for (qint32 sourcePointer = 0; sourcePointer < availableSourceFrames.size(); sourcePointer++) {
        qint32 firstFieldNumber = sourceVideos[availableSourceFrames[sourcePointer]]->ldDecodeMetaData.getFirstFieldNumber(convertVbiFrameNumberToSequential(targetVbiFrame, availableSourceFrames[sourcePointer]));
        qint32 secondFieldNumber = sourceVideos[availableSourceFrames[sourcePointer]]->ldDecodeMetaData.getSecondFieldNumber(convertVbiFrameNumberToSequential(targetVbiFrame, availableSourceFrames[sourcePointer]));

        firstFields[sourcePointer] = (sourceVideos[availableSourceFrames[sourcePointer]]->sourceVideo.getVideoField(firstFieldNumber));
        secondFields[sourcePointer] = (sourceVideos[availableSourceFrames[sourcePointer]]->sourceVideo.getVideoField(secondFieldNumber));

        sourceFirstFieldPointer[sourcePointer] = reinterpret_cast<quint16*>(firstFields[sourcePointer].data());
        sourceSecondFieldPointer[sourcePointer] = reinterpret_cast<quint16*>(secondFields[sourcePointer].data());
    }

    QVector<qint32> firstDiff;
    QVector<qint32> secondDiff;
    for (qint32 y = 0; y < videoParameters.fieldHeight; y++) {
        qint32 startOfLinePointer = y * videoParameters.fieldWidth;

        for (qint32 targetPointer = 0; targetPointer < availableSourceFrames.size(); targetPointer++) {
            // Declare first and second field diff and set all elements to zero
            firstDiff.fill(0, videoParameters.fieldWidth);
            secondDiff.fill(0, videoParameters.fieldWidth);

            for (qint32 sourcePointer = 0; sourcePointer < availableSourceFrames.size(); sourcePointer++) {
                if (sourcePointer != targetPointer) {
                    for (qint32 x = 0; x < videoParameters.fieldWidth; x++) {
                        // Get the 16-bit pixel values and diff them - First field
                        qint32 firstDifference = static_cast<qint32>(sourceFirstFieldPointer[targetPointer][x + startOfLinePointer]) -
                                static_cast<qint32>(sourceFirstFieldPointer[sourcePointer][x + startOfLinePointer]);

                        if (firstDifference < 0) firstDifference = -firstDifference;
                        if (firstDifference > threshold) firstDiff[x]++;

                        // Get the 16-bit pixel values and diff them - second field
                        qint32 secondDifference = static_cast<qint32>(sourceSecondFieldPointer[targetPointer][x + startOfLinePointer]) -
                                static_cast<qint32>(sourceSecondFieldPointer[sourcePointer][x + startOfLinePointer]);

                        if (secondDifference < 0) secondDifference = -secondDifference;
                        if (secondDifference > threshold) secondDiff[x]++;
                    }
                }
            }

            // Now the value of diff[x] contains the number of sources that are different to the current source
            // If this more than 1, the current source's x is a dropout/error
            bool doInProgressFirst = false;
            bool doInProgressSecond = false;
            for (qint32 x = 0; x < videoParameters.fieldWidth; x++) {
                if (firstDiff[x] > 1) {
                    // Current X is a dropout
                    if (!doInProgressFirst) {
                        doInProgressFirst = true;
                        frameDropouts[targetPointer].firstFieldDropOuts.startx.append(x);
                        frameDropouts[targetPointer].firstFieldDropOuts.fieldLine.append(y + 1);
                    }
                } else {
                    // Current X is not a dropout
                    if (doInProgressFirst) {
                        doInProgressFirst = false;
                        // Mark the previous x as the end of the dropout
                        frameDropouts[targetPointer].firstFieldDropOuts.endx.append(x - 1);
                    }
                }

                if (secondDiff[x] > 1) {
                    // Current X is a dropout
                    if (!doInProgressSecond) {
                        doInProgressSecond = true;
                        frameDropouts[targetPointer].secondFieldDropOuts.startx.append(x);
                        frameDropouts[targetPointer].secondFieldDropOuts.fieldLine.append(y + 1);
                    }
                } else {
                    // Current X is not a dropout
                    if (doInProgressSecond) {
                        doInProgressSecond = false;
                        // Mark the previous x as the end of the dropout
                        frameDropouts[targetPointer].secondFieldDropOuts.endx.append(x - 1);
                    }
                }
            }

            // Ensure dropout ends at the end of scan line
            if (doInProgressFirst) {
                doInProgressFirst = false;
                frameDropouts[targetPointer].firstFieldDropOuts.endx.append(videoParameters.fieldWidth);
            }

            if (doInProgressSecond) {
                doInProgressSecond = false;
                frameDropouts[targetPointer].secondFieldDropOuts.endx.append(videoParameters.fieldWidth);
            }
        }
    }

    // Store the frame's dropouts in the metadata
    for (qint32 targetPointer = 0; targetPointer < availableSourceFrames.size(); targetPointer++) {
        // Store the new dropout data to the field's metadata
        qint32 firstFieldNumber = sourceVideos[availableSourceFrames[targetPointer]]->ldDecodeMetaData.getFirstFieldNumber(convertVbiFrameNumberToSequential(targetVbiFrame, availableSourceFrames[targetPointer]));
        qint32 secondFieldNumber = sourceVideos[availableSourceFrames[targetPointer]]->ldDecodeMetaData.getSecondFieldNumber(convertVbiFrameNumberToSequential(targetVbiFrame, availableSourceFrames[targetPointer]));

        sourceVideos[availableSourceFrames[targetPointer]]->ldDecodeMetaData.updateFieldDropOuts(frameDropouts[targetPointer].firstFieldDropOuts, firstFieldNumber);
        sourceVideos[availableSourceFrames[targetPointer]]->ldDecodeMetaData.updateFieldDropOuts(frameDropouts[targetPointer].secondFieldDropOuts, secondFieldNumber);
    }
}

// Method to convert a VBI frame number to a sequential frame number
qint32 TbcSources::convertVbiFrameNumberToSequential(qint32 vbiFrameNumber, qint32 sourceNumber)
{
    // Offset the VBI frame number to get the sequential source frame number
    return vbiFrameNumber - sourceVideos[sourceNumber]->minimumVbiFrameNumber + 1;
}

















