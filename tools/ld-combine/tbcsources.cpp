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
    // Get the required field numbers
    qint32 firstFieldNumber = sourceVideos[currentSource]->ldDecodeMetaData.getFirstFieldNumber(
                sourceVideos[currentSource]->currentFrameNumber);
    qint32 secondFieldNumber = sourceVideos[currentSource]->ldDecodeMetaData.getSecondFieldNumber(
                sourceVideos[currentSource]->currentFrameNumber);

    // Get the metadata for the video parameters
    LdDecodeMetaData::VideoParameters videoParameters = sourceVideos[currentSource]->ldDecodeMetaData.getVideoParameters();

    // Get the video field data
    QByteArray firstFieldData = sourceVideos[currentSource]->sourceVideo.getVideoField(firstFieldNumber);
    QByteArray secondFieldData = sourceVideos[currentSource]->sourceVideo.getVideoField(secondFieldNumber);

    // Calculate the frame height
    qint32 frameHeight = (videoParameters.fieldHeight * 2) - 1;

    // Show debug information
    qDebug().nospace() << "TbcSources::getCurrentFrameImage(): Generating a source image from field pair " << firstFieldNumber <<
                "/" << secondFieldNumber << " (" << videoParameters.fieldWidth << "x" <<
                frameHeight << ")";

    // Create a QImage
    QImage frameImage = QImage(videoParameters.fieldWidth, frameHeight, QImage::Format_RGB888);

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

    return frameImage;
}

// Get the field greyscale data of the current source's current frame
TbcSources::RawFrame TbcSources::getCurrentFrameData()
{
    RawFrame rawFrame;

    // Get the required field numbers
    qint32 firstFieldNumber = sourceVideos[currentSource]->ldDecodeMetaData.getFirstFieldNumber(
                sourceVideos[currentSource]->currentFrameNumber);
    qint32 secondFieldNumber = sourceVideos[currentSource]->ldDecodeMetaData.getSecondFieldNumber(
                sourceVideos[currentSource]->currentFrameNumber);

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
qint32 TbcSources::getNumberOfFrames()
{
    if (sourceVideos.size() == 0) return -1;
    return sourceVideos[currentSource]->ldDecodeMetaData.getNumberOfFrames();
}

// Get the currently selected frame number of the current source
qint32 TbcSources::getCurrentFrameNumber()
{
    if (sourceVideos.size() == 0) return -1;
    return sourceVideos[currentSource]->currentFrameNumber;
}

// Set the current frame number of the current source
void TbcSources::setCurrentFrameNumber(qint32 frameNumber)
{
    if (sourceVideos.size() == 0) return;

    // Range check the request
    if (frameNumber < 1) frameNumber = 1;
    if (frameNumber > sourceVideos[currentSource]->ldDecodeMetaData.getNumberOfFrames())
        frameNumber = sourceVideos[currentSource]->ldDecodeMetaData.getNumberOfFrames();

    // Set the current frame number
    sourceVideos[currentSource]->currentFrameNumber = frameNumber;
}

// Get the current source's filename
QString TbcSources::getCurrentSourceFilename()
{
    if (sourceVideos.size() == 0) return QString();
    return sourceVideos[currentSource]->filename;
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

    backgroundLoadSuccessful = false;
    sourceVideos.resize(sourceVideos.size() + 1);
    qint32 newSourceNumber = sourceVideos.size() - 1;
    sourceVideos[newSourceNumber] = new Source;

    // Open the TBC metadata file
    qDebug() << "TbcSources::performBackgroundLoad(): Processing JSON metadata...";
    emit setBusy("Processing JSON metadata...", false, 0);
    if (!sourceVideos[newSourceNumber]->ldDecodeMetaData.read(filename + ".json")) {
        // Open failed
        qWarning() << "Open TBC JSON metadata failed for filename" << filename;
        backgroundLoadErrorMessage = "Cannot load source - JSON metadata could not be read!";
        backgroundLoadSuccessful = false;
    } else {
        // Get the video parameters from the metadata
        LdDecodeMetaData::VideoParameters videoParameters = sourceVideos[newSourceNumber]->ldDecodeMetaData.getVideoParameters();

        // Ensure that the video standard matches any existing sources
        if ((sourceVideos.size() - 1 > 0) && (sourceVideos[0]->ldDecodeMetaData.getVideoParameters().isSourcePal != videoParameters.isSourcePal)) {
            qWarning() << "New source video standard does not match existing source(s)!";
            backgroundLoadErrorMessage = "Cannot load source - Mixing PAL and NTSC sources is not supported!";
            backgroundLoadSuccessful = false;
        } else {
            // Open the new source video
            qDebug() << "TbcSources::loadSource(): Loading TBC file...";
            emit setBusy("Loading TBC file...", false, 0);
            if (!sourceVideos[newSourceNumber]->sourceVideo.open(filename, videoParameters.fieldWidth * videoParameters.fieldHeight)) {
                // Open failed
                qWarning() << "Open TBC file failed for filename" << filename;
                backgroundLoadErrorMessage = "Cannot load source - Error reading source TBC data file!";
                backgroundLoadSuccessful = false;
            } else {
                // Both the video and metadata files are now open
                sourceVideos[newSourceNumber]->filename = filename;
                sourceVideos[newSourceNumber]->currentFrameNumber = 1;
                backgroundLoadSuccessful = true;
            }
        }
    }

    // Deal with any issues
    if (!backgroundLoadSuccessful) {
        // Remove the new source entry and default the current source
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
