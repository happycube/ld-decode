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
    currentFrameNumber = 1;
    backgroundLoadErrorMessage.clear();
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

// Get a QImage of the current source's current frame
QImage TbcSources::getCurrentFrameImage()
{
    // Get the metadata for the video parameters
    LdDecodeMetaData::VideoParameters videoParameters = sourceVideos[currentSource]->ldDecodeMetaData.getVideoParameters();

    // Calculate the frame height
    qint32 frameHeight = (videoParameters.fieldHeight * 2) - 1;

    // Create a QImage
    QImage frameImage = QImage(videoParameters.fieldWidth, frameHeight, QImage::Format_RGB888);

    // Get the required field numbers
    qint32 firstFieldNumber = sourceVideos[currentSource]->ldDecodeMetaData.getFirstFieldNumber(currentFrameNumber);
    qint32 secondFieldNumber = sourceVideos[currentSource]->ldDecodeMetaData.getSecondFieldNumber(currentFrameNumber);

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
    } else {
        // Frame is missing from source - return a dummy frame
        frameImage.fill(Qt::red);

        // Show debug information
        qDebug().nospace() << "TbcSources::getCurrentFrameImage(): Source frame is missing - generating dummy image (" <<
                              videoParameters.fieldWidth << "x" << frameHeight << ")";
    }

    return frameImage;
}

// Get the field greyscale data of the current source's current frame
TbcSources::RawFrame TbcSources::getCurrentFrameData()
{
    RawFrame rawFrame;

    // Get the required field numbers
    qint32 firstFieldNumber = sourceVideos[currentSource]->ldDecodeMetaData.getFirstFieldNumber(currentFrameNumber);
    qint32 secondFieldNumber = sourceVideos[currentSource]->ldDecodeMetaData.getSecondFieldNumber(currentFrameNumber);

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
qint32 TbcSources::getCurrentFrameNumber()
{
    if (sourceVideos.size() == 0) return -1;
    return currentFrameNumber;
}

// Set the current frame number of the current source
void TbcSources::setCurrentFrameNumber(qint32 frameNumber)
{
    if (sourceVideos.size() == 0) return;

    // Range check the request
    if (frameNumber < getMinimumFrameNumber()) {
        qDebug() << "TbcSources::setCurrentFrameNumber(): Request to set current frame number to" << frameNumber <<
                    "is out of bounds ( before start of" << getMinimumFrameNumber() << " )";
        frameNumber = getMinimumFrameNumber();
    }

    if (frameNumber > getMaximumFrameNumber()) {
        qDebug() << "TbcSources::setCurrentFrameNumber(): Request to set current frame number to" << frameNumber <<
                    "is out of bounds ( after end of" << getMaximumFrameNumber() << " )";
        frameNumber = getMaximumFrameNumber();
    }

    // Set the current frame number
    currentFrameNumber = frameNumber;
}

// Get the current source's filename
QString TbcSources::getCurrentSourceFilename()
{
    if (sourceVideos.size() == 0) return QString();
    return sourceVideos[currentSource]->filename;
}

// Get the map report for the current source
QStringList TbcSources::getCurrentMapReport()
{
    if (sourceVideos.size() == 0) return QStringList();
    return QStringList();
}

// Get the minimum frame number for all sources
qint32 TbcSources::getMinimumFrameNumber()
{
    qint32 minimumFrameNumber = 1000000;
    for (qint32 i = 0; i < sourceVideos.size(); i++) {
        if (sourceVideos[i]->minimumVbiFrameNumber < minimumFrameNumber)
            minimumFrameNumber = sourceVideos[i]->minimumVbiFrameNumber;
    }

    return minimumFrameNumber;
}

// Get the maximum frame number for all sources
qint32 TbcSources::getMaximumFrameNumber()
{
    qint32 maximumFrameNumber = 0;
    for (qint32 i = 0; i < sourceVideos.size(); i++) {
        if (sourceVideos[i]->maximumVbiFrameNumber > maximumFrameNumber)
            maximumFrameNumber = sourceVideos[i]->maximumVbiFrameNumber;
    }

    return maximumFrameNumber;
}

// Get the minimum frame number for the current source
qint32 TbcSources::getCurrentSourceMinimumFrameNumber()
{
    return sourceVideos[currentSource]->minimumVbiFrameNumber;
}

// Get the maximum frame number for the current source
qint32 TbcSources::getCurrentSourceMaxmumFrameNumber()
{
    return sourceVideos[currentSource]->maximumVbiFrameNumber;
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

    return true;
}