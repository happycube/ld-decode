/************************************************************************

    tbcsource.cpp

    ld-analyse - TBC output analysis
    Copyright (C) 2018-2019 Simon Inns

    This file is part of ld-decode-tools.

    ld-analyse is free software: you can redistribute it and/or
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

#include "tbcsource.h"

#include "sourcefield.h"

TbcSource::TbcSource(QObject *parent) : QObject(parent)
{
    // Default frame image options
    chromaOn = false;
    lpfOn = false;
    dropoutsOn = false;
    reverseFoOn = false;
    sourceReady = false;
    fieldsPerGraphDataPoint = 0;
    frameCacheFrameNumber = -1;

    // Set the PALcolour configuration to default
    palColourConfiguration = palColour.getConfiguration();
    palColourConfiguration.chromaFilter = PalColour::transform2DFilter;
    decoderConfigurationChanged = false;
}

// Public methods -----------------------------------------------------------------------------------------------------

// Method to load a TBC source file
void TbcSource::loadSource(QString sourceFilename)
{
    // Default frame options
    chromaOn = false;
    lpfOn = false;
    dropoutsOn = false;
    reverseFoOn = false;
    sourceReady = false;
    fieldsPerGraphDataPoint = 0;
    frameCacheFrameNumber = -1;

    // Set the current file name
    QFileInfo inFileInfo(sourceFilename);
    currentSourceFilename = inFileInfo.fileName();
    qDebug() << "TbcSource::startBackgroundLoad(): Opening TBC source file:" << currentSourceFilename;

    // Set up and fire-off background loading thread
    qDebug() << "TbcSource::loadSource(): Setting up background loader thread";
    connect(&watcher, SIGNAL(finished()), this, SLOT(finishBackgroundLoad()));
    future = QtConcurrent::run(this, &TbcSource::startBackgroundLoad, sourceFilename);
    watcher.setFuture(future);
}

// Method to unload a TBC source file
void TbcSource::unloadSource()
{
    sourceVideo.close();
    sourceReady = false;
}

// Method returns true is a TBC source is loaded
bool TbcSource::getIsSourceLoaded()
{
    return sourceReady;
}

// Method returns the filename of the current TBC source
QString TbcSource::getCurrentSourceFilename()
{
    if (!sourceReady) return QString();

    return currentSourceFilename;
}

// Method to set the highlight dropouts mode (true = dropouts highlighted)
void TbcSource::setHighlightDropouts(bool _state)
{
    frameCacheFrameNumber = -1;
    dropoutsOn = _state;
}

// Method to set the chroma decoder mode (true = on)
void TbcSource::setChromaDecoder(bool _state)
{
    frameCacheFrameNumber = -1;
    chromaOn = _state;

    // Turn off LPF if chroma is selected
    if (chromaOn) lpfOn = false;
}

// Method to set the LPF mode (true = on)
void TbcSource::setLpfMode(bool _state)
{
    frameCacheFrameNumber = -1;
    lpfOn = _state;

    // Turn off chroma if LPF is selected
    if (lpfOn) chromaOn = false;
}

// Method to set the field order (true = reversed, false = normal)
void TbcSource::setFieldOrder(bool _state)
{
    frameCacheFrameNumber = -1;
    reverseFoOn = _state;

    if (reverseFoOn) ldDecodeMetaData.setIsFirstFieldFirst(false);
    else ldDecodeMetaData.setIsFirstFieldFirst(true);
}

// Method to get the state of the highlight dropouts mode
bool TbcSource::getHighlightDropouts()
{
    return dropoutsOn;
}

// Method to get the state of the chroma decoder mode
bool TbcSource::getChromaDecoder()
{
    return chromaOn;
}

// Method to get the state of the LPF mode
bool TbcSource::getLpfMode()
{
    return lpfOn;
}

// Method to get the field order
bool TbcSource::getFieldOrder()
{
    return reverseFoOn;
}

// Method to get a QImage from a frame number
QImage TbcSource::getFrameImage(qint32 frameNumber)
{
    if (!sourceReady) return QImage();

    // Check cached QImage
    if (frameCacheFrameNumber == frameNumber && !decoderConfigurationChanged) return frameCache;
    else {
        frameCacheFrameNumber = frameNumber;
        decoderConfigurationChanged = false;
    }

    // Get the required field numbers
    qint32 firstFieldNumber = ldDecodeMetaData.getFirstFieldNumber(frameNumber);
    qint32 secondFieldNumber = ldDecodeMetaData.getSecondFieldNumber(frameNumber);

    // Make sure we have a valid response from the frame determination
    if (firstFieldNumber == -1 || secondFieldNumber == -1) {
        qCritical() << "Could not determine field numbers!";

        // Jump back one frame
        if (frameNumber != 1) {
            frameNumber--;

            firstFieldNumber = ldDecodeMetaData.getFirstFieldNumber(frameNumber);
            secondFieldNumber = ldDecodeMetaData.getSecondFieldNumber(frameNumber);
        }
        qDebug() << "TbcSource::getFrameImage(): Jumping back one frame due to error";
    }

    // Get a QImage for the frame
    QImage frameImage = generateQImage(firstFieldNumber, secondFieldNumber);

    // Get the field metadata
    LdDecodeMetaData::Field firstField = ldDecodeMetaData.getField(firstFieldNumber);
    LdDecodeMetaData::Field secondField = ldDecodeMetaData.getField(secondFieldNumber);

    // Highlight dropouts
    if (dropoutsOn) {
        // Create a painter object
        QPainter imagePainter;
        imagePainter.begin(&frameImage);

        // Draw the drop out data for the first field
        imagePainter.setPen(Qt::red);
        for (qint32 dropOutIndex = 0; dropOutIndex < firstField.dropOuts.startx.size(); dropOutIndex++) {
            qint32 startx = firstField.dropOuts.startx[dropOutIndex];
            qint32 endx = firstField.dropOuts.endx[dropOutIndex];
            qint32 fieldLine = firstField.dropOuts.fieldLine[dropOutIndex];

            imagePainter.drawLine(startx, ((fieldLine - 1) * 2), endx, ((fieldLine - 1) * 2));
        }

        // Draw the drop out data for the second field
        imagePainter.setPen(Qt::blue);
        for (qint32 dropOutIndex = 0; dropOutIndex < secondField.dropOuts.startx.size(); dropOutIndex++) {
            qint32 startx = secondField.dropOuts.startx[dropOutIndex];
            qint32 endx = secondField.dropOuts.endx[dropOutIndex];
            qint32 fieldLine = secondField.dropOuts.fieldLine[dropOutIndex];

            imagePainter.drawLine(startx, ((fieldLine - 1) * 2) + 1, endx, ((fieldLine - 1) * 2) + 1);
        }

        // End the painter object
        imagePainter.end();
    }

    frameCache = frameImage;
    return frameImage;
}

// Method to get the number of available frames
qint32 TbcSource::getNumberOfFrames()
{
    if (!sourceReady) return 0;
    return ldDecodeMetaData.getNumberOfFrames();
}

// Method to get the number of available fields
qint32 TbcSource::getNumberOfFields()
{
    if (!sourceReady) return 0;
    return ldDecodeMetaData.getNumberOfFields();
}

// Method returns true if the TBC source is PAL (false for NTSC)
bool TbcSource::getIsSourcePal()
{
    if (!sourceReady) return false;
    return ldDecodeMetaData.getVideoParameters().isSourcePal;
}

// Method to get the frame height in scanlines
qint32 TbcSource::getFrameHeight()
{
    if (!sourceReady) return 0;

    // Get the metadata for the fields
    LdDecodeMetaData::VideoParameters videoParameters = ldDecodeMetaData.getVideoParameters();

    // Calculate the frame height
    return (videoParameters.fieldHeight * 2) - 1;
}

// Method to get the frame width in dots
qint32 TbcSource::getFrameWidth()
{
    if (!sourceReady) return 0;

    // Get the metadata for the fields
    LdDecodeMetaData::VideoParameters videoParameters = ldDecodeMetaData.getVideoParameters();

    // Return the frame width
    return (videoParameters.fieldWidth);
}

// Get black SNR data for graphing
QVector<qreal> TbcSource::getBlackSnrGraphData()
{
    return blackSnrGraphData;
}

// Get white SNR data for graphing
QVector<qreal> TbcSource::getWhiteSnrGraphData()
{
    return whiteSnrGraphData;
}

// Get dropout data for graphing
QVector<qreal> TbcSource::getDropOutGraphData()
{
    return dropoutGraphData;
}

// Get CQI data for graphing
QVector<qreal> TbcSource::getCaptureQualityIndexGraphData()
{
    return cqiGraphData;
}

// Method to get the size of the graphing data
qint32 TbcSource::getGraphDataSize()
{
    // All data vectors are the same size, just return the size on one
    return dropoutGraphData.size();
}

// Method to get the number of fields averaged into each graphing data point
qint32 TbcSource::getFieldsPerGraphDataPoint()
{
    return fieldsPerGraphDataPoint;
}

// Method returns true if frame contains dropouts
bool TbcSource::getIsDropoutPresent(qint32 frameNumber)
{
    if (!sourceReady) return false;

    bool dropOutsPresent = false;

    // Determine the first and second fields for the frame number
    qint32 firstFieldNumber = ldDecodeMetaData.getFirstFieldNumber(frameNumber);
    qint32 secondFieldNumber = ldDecodeMetaData.getSecondFieldNumber(frameNumber);

    if (ldDecodeMetaData.getFieldDropOuts(firstFieldNumber).startx.size() > 0) dropOutsPresent = true;
    if (ldDecodeMetaData.getFieldDropOuts(secondFieldNumber).startx.size() > 0) dropOutsPresent = true;

    return dropOutsPresent;
}

// Get scan line data from a frame
TbcSource::ScanLineData TbcSource::getScanLineData(qint32 frameNumber, qint32 scanLine)
{
    if (!sourceReady) return ScanLineData();

    // Determine the first and second fields for the frame number
    qint32 firstFieldNumber = ldDecodeMetaData.getFirstFieldNumber(frameNumber);
    qint32 secondFieldNumber = ldDecodeMetaData.getSecondFieldNumber(frameNumber);

    ScanLineData scanLineData;
    LdDecodeMetaData::VideoParameters videoParameters = ldDecodeMetaData.getVideoParameters();

    // Convert the scan line into field and field line
    bool isFieldTop = true;
    qint32 fieldLine = 0;

    if (scanLine % 2 == 0) isFieldTop = false;
    else isFieldTop = true;

    if (isFieldTop) {
        fieldLine = (scanLine / 2) + 1;
    } else {
        fieldLine = (scanLine / 2);
    }

    // Set the video parameters
    scanLineData.blackIre = videoParameters.black16bIre;
    scanLineData.whiteIre = videoParameters.white16bIre;
    scanLineData.colourBurstStart = videoParameters.colourBurstStart;
    scanLineData.colourBurstEnd = videoParameters.colourBurstEnd;
    scanLineData.activeVideoStart = videoParameters.activeVideoStart;
    scanLineData.activeVideoEnd = videoParameters.activeVideoEnd;
    scanLineData.isSourcePal = videoParameters.isSourcePal;

    // Get the field video and dropout data
    SourceVideo::Data fieldData;
    LdDecodeMetaData::DropOuts dropouts;
    if (isFieldTop) {
        fieldData = sourceVideo.getVideoField(firstFieldNumber);
        dropouts = ldDecodeMetaData.getFieldDropOuts(firstFieldNumber);
    } else {
        fieldData = sourceVideo.getVideoField(secondFieldNumber);
        dropouts = ldDecodeMetaData.getFieldDropOuts(secondFieldNumber);
    }

    scanLineData.data.resize(videoParameters.fieldWidth);
    scanLineData.isDropout.resize(videoParameters.fieldWidth);
    for (qint32 xPosition = 0; xPosition < videoParameters.fieldWidth; xPosition++) {
        // Get the 16-bit YC value for the current pixel (frame data is numbered 0-624 or 0-524)
        scanLineData.data[xPosition] = fieldData[((fieldLine - 1) * videoParameters.fieldWidth) + xPosition];

        scanLineData.isDropout[xPosition] = false;
        for (qint32 doCount = 0; doCount < dropouts.startx.size(); doCount++) {
            if (dropouts.fieldLine[doCount] == fieldLine) {
                if (xPosition >= dropouts.startx[doCount] && xPosition <= dropouts.endx[doCount]) scanLineData.isDropout[xPosition] = true;
            }
        }
    }

    return scanLineData;
}

// Method to return the decoded VBI data for a frame
VbiDecoder::Vbi TbcSource::getFrameVbi(qint32 frameNumber)
{
    if (!sourceReady) return VbiDecoder::Vbi();

    // Get the required field numbers
    qint32 firstFieldNumber = ldDecodeMetaData.getFirstFieldNumber(frameNumber);
    qint32 secondFieldNumber = ldDecodeMetaData.getSecondFieldNumber(frameNumber);

    // Get the field metadata
    LdDecodeMetaData::Field firstField = ldDecodeMetaData.getField(firstFieldNumber);
    LdDecodeMetaData::Field secondField = ldDecodeMetaData.getField(secondFieldNumber);

    qint32 vbi16_1, vbi17_1, vbi18_1;
    qint32 vbi16_2, vbi17_2, vbi18_2;

    vbi16_1 = firstField.vbi.vbiData[0];
    vbi17_1 = firstField.vbi.vbiData[1];
    vbi18_1 = firstField.vbi.vbiData[2];
    vbi16_2 = secondField.vbi.vbiData[0];
    vbi17_2 = secondField.vbi.vbiData[1];
    vbi18_2 = secondField.vbi.vbiData[2];

    return vbiDecoder.decodeFrame(vbi16_1, vbi17_1, vbi18_1, vbi16_2, vbi17_2, vbi18_2);
}

// Method returns true if the VBI is valid for the specified frame number
bool TbcSource::getIsFrameVbiValid(qint32 frameNumber)
{
    if (!sourceReady) return false;

    // Get the required field numbers
    qint32 firstFieldNumber = ldDecodeMetaData.getFirstFieldNumber(frameNumber);
    qint32 secondFieldNumber = ldDecodeMetaData.getSecondFieldNumber(frameNumber);

    // Get the field metadata
    LdDecodeMetaData::Field firstField = ldDecodeMetaData.getField(firstFieldNumber);
    LdDecodeMetaData::Field secondField = ldDecodeMetaData.getField(secondFieldNumber);

    qint32 vbi16_1, vbi17_1, vbi18_1;
    qint32 vbi16_2, vbi17_2, vbi18_2;

    vbi16_1 = firstField.vbi.vbiData[0];
    vbi17_1 = firstField.vbi.vbiData[1];
    vbi18_1 = firstField.vbi.vbiData[2];
    vbi16_2 = secondField.vbi.vbiData[0];
    vbi17_2 = secondField.vbi.vbiData[1];
    vbi18_2 = secondField.vbi.vbiData[2];

    if (vbi16_1 == -1 || vbi17_1 == -1 || vbi18_1 == -1) return false;
    if (vbi16_2 == -1 || vbi17_2 == -1 || vbi18_2 == -1) return false;

    return true;
}

// Method to get the field number of the first field of the specified frame
qint32 TbcSource::getFirstFieldNumber(qint32 frameNumber)
{
    if (!sourceReady) return 0;

    return ldDecodeMetaData.getFirstFieldNumber(frameNumber);
}

// Method to get the field number of the second field of the specified frame
qint32 TbcSource::getSecondFieldNumber(qint32 frameNumber)
{
    if (!sourceReady) return 0;

    return ldDecodeMetaData.getSecondFieldNumber(frameNumber);
}

qint32 TbcSource::getCcData0(qint32 frameNumber)
{
    if (!sourceReady) return false;

    // Get the required field numbers
    qint32 firstFieldNumber = ldDecodeMetaData.getFirstFieldNumber(frameNumber);
    qint32 secondFieldNumber = ldDecodeMetaData.getSecondFieldNumber(frameNumber);

    // Get the field metadata
    LdDecodeMetaData::Field firstField = ldDecodeMetaData.getField(firstFieldNumber);
    LdDecodeMetaData::Field secondField = ldDecodeMetaData.getField(secondFieldNumber);

    if (firstField.ntsc.ccData0 != -1) return firstField.ntsc.ccData0;
    return secondField.ntsc.ccData0;
}

qint32 TbcSource::getCcData1(qint32 frameNumber)
{
    if (!sourceReady) return false;

    // Get the required field numbers
    qint32 firstFieldNumber = ldDecodeMetaData.getFirstFieldNumber(frameNumber);
    qint32 secondFieldNumber = ldDecodeMetaData.getSecondFieldNumber(frameNumber);

    // Get the field metadata
    LdDecodeMetaData::Field firstField = ldDecodeMetaData.getField(firstFieldNumber);
    LdDecodeMetaData::Field secondField = ldDecodeMetaData.getField(secondFieldNumber);

    if (firstField.ntsc.ccData1 != -1) return firstField.ntsc.ccData1;
    return secondField.ntsc.ccData1;
}

void TbcSource::setPalColourConfiguration(const PalColour::Configuration &_palColourConfiguration)
{
    palColourConfiguration = _palColourConfiguration;

    // Get the video parameters
    LdDecodeMetaData::VideoParameters videoParameters = ldDecodeMetaData.getVideoParameters();

    // Configure the chroma decoder
    palColour.updateConfiguration(videoParameters, palColourConfiguration);

    decoderConfigurationChanged = true;
}

const PalColour::Configuration &TbcSource::getPalColourConfiguration()
{
    return palColourConfiguration;
}

// Private methods ----------------------------------------------------------------------------------------------------

// Method to create a QImage for a source video frame
QImage TbcSource::generateQImage(qint32 firstFieldNumber, qint32 secondFieldNumber)
{
    // Get the metadata for the video parameters
    LdDecodeMetaData::VideoParameters videoParameters = ldDecodeMetaData.getVideoParameters();

    // Calculate the frame height
    qint32 frameHeight = (videoParameters.fieldHeight * 2) - 1;

    // Show debug information
    if (chromaOn) {
        qDebug().nospace() << "TbcSource::generateQImage(): Generating a chroma image from field pair " << firstFieldNumber <<
                    "/" << secondFieldNumber << " (" << videoParameters.fieldWidth << "x" <<
                    frameHeight << ")";
    } else if (lpfOn) {
        qDebug().nospace() << "TbcSource::generateQImage(): Generating a LPF image from field pair " << firstFieldNumber <<
                    "/" << secondFieldNumber << " (" << videoParameters.fieldWidth << "x" <<
                    frameHeight << ")";
    } else {
        qDebug().nospace() << "TbcSource::generateQImage(): Generating a source image from field pair " << firstFieldNumber <<
                    "/" << secondFieldNumber << " (" << videoParameters.fieldWidth << "x" <<
                    frameHeight << ")";
    }

    // Create a QImage
    QImage frameImage = QImage(videoParameters.fieldWidth, frameHeight, QImage::Format_RGB888);

    // Define the data buffers
    QByteArray firstLineData;
    QByteArray secondLineData;

    if (chromaOn) {
        // Chroma decode the current frame and display

        // Get the two fields and their metadata and contain in the chroma-decoder's
        // source field class
        SourceField firstField, secondField;
        firstField.field = ldDecodeMetaData.getField(firstFieldNumber);
        secondField.field = ldDecodeMetaData.getField(secondFieldNumber);
        firstField.data = sourceVideo.getVideoField(firstFieldNumber);
        secondField.data = sourceVideo.getVideoField(secondFieldNumber);

        qint32 firstActiveLine, lastActiveLine;
        RGBFrame rgbFrame;

        // Decode colour for the current frame, to RGB 16-16-16 interlaced output
        if (videoParameters.isSourcePal) {
            // PAL source

            firstActiveLine = palColourConfiguration.firstActiveLine;
            lastActiveLine = palColourConfiguration.lastActiveLine;

            rgbFrame = palColour.decodeFrame(firstField, secondField);
        } else {
            // NTSC source

            firstActiveLine = ntscColour.getConfiguration().firstActiveLine;
            lastActiveLine = ntscColour.getConfiguration().lastActiveLine;

            rgbFrame = ntscColour.decodeFrame(firstField, secondField);
        }

        // Get a pointer to the RGB data
        const quint16 *rgbPointer = rgbFrame.data();

        // Fill the QImage with black
        frameImage.fill(Qt::black);

        // Copy the RGB16-16-16 data into the RGB888 QImage
        for (qint32 y = firstActiveLine; y < lastActiveLine; y++) {
            for (qint32 x = videoParameters.activeVideoStart; x < videoParameters.activeVideoEnd; x++) {
                qint32 pixelOffset = ((y * videoParameters.fieldWidth) + x) * 3;

                // Take just the MSB of the input data
                qint32 xpp = x * 3;
                *(frameImage.scanLine(y) + xpp + 0) = static_cast<uchar>(rgbPointer[pixelOffset + 0] / 256); // R
                *(frameImage.scanLine(y) + xpp + 1) = static_cast<uchar>(rgbPointer[pixelOffset + 1] / 256); // G
                *(frameImage.scanLine(y) + xpp + 2) = static_cast<uchar>(rgbPointer[pixelOffset + 2] / 256); // B
            }
        }
    } else if (lpfOn) {
        // Display the current frame as LPF only

        // Get the field data
        SourceVideo::Data firstField = sourceVideo.getVideoField(firstFieldNumber);
        SourceVideo::Data secondField = sourceVideo.getVideoField(secondFieldNumber);

        // Generate pointers to the 16-bit greyscale data.
        // Since we're taking a non-const pointer here, this will detach from
        // the original copy of the data (which is what we want, because we're
        // going to filter it in place).
        quint16 *firstFieldPointer = firstField.data();
        quint16 *secondFieldPointer = secondField.data();

        // Generate a filter object
        Filters filters;

        // Filter out the Chroma information
        if (videoParameters.isSourcePal) {
            qDebug() << "TbcSource::generateQImage(): Applying FIR LPF to PAL image data";
            filters.palLumaFirFilter(firstFieldPointer, videoParameters.fieldWidth * videoParameters.fieldHeight);
            filters.palLumaFirFilter(secondFieldPointer, videoParameters.fieldWidth * videoParameters.fieldHeight);
        } else {
            qDebug() << "TbcSource::generateQImage(): Applying FIR LPF to NTSC image data";
            filters.ntscLumaFirFilter(firstFieldPointer, videoParameters.fieldWidth * videoParameters.fieldHeight);
            filters.ntscLumaFirFilter(secondFieldPointer, videoParameters.fieldWidth * videoParameters.fieldHeight);
        }

        // Copy the raw 16-bit grayscale data into the RGB888 QImage
        for (qint32 y = 0; y < frameHeight; y++) {
            for (qint32 x = 0; x < videoParameters.fieldWidth; x++) {
                qint32 pixelOffset = (videoParameters.fieldWidth * (y / 2)) + x;
                qreal pixelValue32;
                if (y % 2) {
                    pixelValue32 = static_cast<qreal>(secondFieldPointer[pixelOffset]);
                } else {
                    pixelValue32 = static_cast<qreal>(firstFieldPointer[pixelOffset]);
                }

                if (pixelValue32 < videoParameters.black16bIre) pixelValue32 = videoParameters.black16bIre;
                if (pixelValue32 > videoParameters.white16bIre) pixelValue32 = videoParameters.white16bIre;

                // Scale the IRE value to a 16 bit greyscale value
                qreal scaledValue = ((pixelValue32 - static_cast<qreal>(videoParameters.black16bIre)) /
                                     (static_cast<qreal>(videoParameters.white16bIre)
                                      - static_cast<qreal>(videoParameters.black16bIre))) * 65535.0;
                pixelValue32 = static_cast<qint32>(scaledValue);

                // Convert to 8-bit for RGB888
                uchar pixelValue = static_cast<uchar>(pixelValue32 / 256);

                qint32 xpp = x * 3;
                *(frameImage.scanLine(y) + xpp + 0) = static_cast<uchar>(pixelValue); // R
                *(frameImage.scanLine(y) + xpp + 1) = static_cast<uchar>(pixelValue); // G
                *(frameImage.scanLine(y) + xpp + 2) = static_cast<uchar>(pixelValue); // B
            }
        }
    } else {
        // Display the current frame as source data

        // Get the field data
        SourceVideo::Data firstField = sourceVideo.getVideoField(firstFieldNumber);
        SourceVideo::Data secondField = sourceVideo.getVideoField(secondFieldNumber);

        // Get pointers to the 16-bit greyscale data
        const quint16 *firstFieldPointer = firstField.data();
        const quint16 *secondFieldPointer = secondField.data();

        // Copy the raw 16-bit grayscale data into the RGB888 QImage
        for (qint32 y = 0; y < frameHeight; y++) {
            for (qint32 x = 0; x < videoParameters.fieldWidth; x++) {
                // Take just the MSB of the input data
                qint32 pixelOffset = (videoParameters.fieldWidth * (y / 2)) + x;
                uchar pixelValue;
                if (y % 2) {
                    pixelValue = static_cast<uchar>(secondFieldPointer[pixelOffset] / 256);
                } else {
                    pixelValue = static_cast<uchar>(firstFieldPointer[pixelOffset] / 256);
                }

                qint32 xpp = x * 3;
                *(frameImage.scanLine(y) + xpp + 0) = static_cast<uchar>(pixelValue); // R
                *(frameImage.scanLine(y) + xpp + 1) = static_cast<uchar>(pixelValue); // G
                *(frameImage.scanLine(y) + xpp + 2) = static_cast<uchar>(pixelValue); // B
            }
        }
    }

    return frameImage;
}

// Generate the data points for the Drop-out and SNR analysis graphs
// We do these both at the same time to reduce calls to the metadata
void TbcSource::generateData(qint32 _targetDataPoints)
{
    dropoutGraphData.clear();
    blackSnrGraphData.clear();
    whiteSnrGraphData.clear();
    cqiGraphData.clear();

    qreal targetDataPoints = static_cast<qreal>(_targetDataPoints);
    qreal averageWidth = qRound(ldDecodeMetaData.getNumberOfFields() / targetDataPoints);
    if (averageWidth < 1) averageWidth = 1; // Ensure we don't divide by zero
    qint32 dataPoints = ldDecodeMetaData.getNumberOfFields() / static_cast<qint32>(averageWidth);
    fieldsPerGraphDataPoint = ldDecodeMetaData.getNumberOfFields() / dataPoints;
    if (fieldsPerGraphDataPoint < 1) fieldsPerGraphDataPoint = 1;

    // Get the total number of dots per field
    qint32 totalDotsPerField = ldDecodeMetaData.getVideoParameters().fieldHeight + ldDecodeMetaData.getVideoParameters().fieldWidth;

    qint32 fieldNumber = 1;
    for (qint32 dpCount = 0; dpCount < dataPoints; dpCount++) {
        qreal doLength = 0;
        qreal blackSnrTotal = 0;
        qreal whiteSnrTotal = 0;
        qreal syncConf = 0;

        // SNR data may be missing in some fields, so we count the points to prevent
        // the average from being thrown-off by missing data
        qreal blackSnrPoints = 0;
        qreal whiteSnrPoints = 0;
        for (qint32 avCount = 0; avCount < fieldsPerGraphDataPoint; avCount++) {
            LdDecodeMetaData::Field field = ldDecodeMetaData.getField(fieldNumber);

            // Get the DOs
            if (field.dropOuts.startx.size() > 0) {
                // Calculate the total length of the dropouts
                for (qint32 i = 0; i < field.dropOuts.startx.size(); i++) {
                    doLength += field.dropOuts.endx[i] - field.dropOuts.startx[i];
                }
            }

            // Get the SNRs
            if (field.vitsMetrics.inUse) {
                if (field.vitsMetrics.bPSNR > 0) {
                    blackSnrTotal += field.vitsMetrics.bPSNR;
                    blackSnrPoints++;
                }
                if (field.vitsMetrics.wSNR > 0) {
                    whiteSnrTotal += field.vitsMetrics.wSNR;
                    whiteSnrPoints++;
                }
            }

            // Get the sync confidence
            syncConf += static_cast<qreal>(ldDecodeMetaData.getField(fieldNumber).syncConf);

            // Next field...
            fieldNumber++;
        }

        // Calculate the average
        doLength = doLength / static_cast<qreal>(fieldsPerGraphDataPoint);
        blackSnrTotal = blackSnrTotal / blackSnrPoints;
        whiteSnrTotal = whiteSnrTotal / whiteSnrPoints;
        syncConf = syncConf / static_cast<qreal>(fieldsPerGraphDataPoint);

        // Calculate the Capture Quality Index
        qreal fieldDoPercent = 100.0 - (static_cast<qreal>(doLength) / static_cast<qreal>(totalDotsPerField * fieldsPerGraphDataPoint));
        qreal snrPercent = 0;
        if (whiteSnrTotal != 0) snrPercent = (100.0 / 90.0) * (blackSnrTotal + whiteSnrTotal);
        else snrPercent = (100.0 / 45.0) * (blackSnrTotal);
        if (snrPercent > 100.0) snrPercent = 100.0;

        // Note: The weighting is 1000:1:1 - this is just because dropouts have a greater visual effect
        // on the resulting capture than SNR.
        qreal captureQualityIndex = ((fieldDoPercent * 1000.0) + snrPercent + syncConf) / 1002.0;

        // Add the result to the vectors
        dropoutGraphData.append(doLength);
        blackSnrGraphData.append(blackSnrTotal);
        whiteSnrGraphData.append(whiteSnrTotal);
        cqiGraphData.append(captureQualityIndex);
    }
}

void TbcSource::startBackgroundLoad(QString sourceFilename)
{
    // Open the TBC metadata file
    qDebug() << "TbcSource::startBackgroundLoad(): Processing JSON metadata...";
    emit busyLoading("Processing JSON metadata...");
    if (!ldDecodeMetaData.read(sourceFilename + ".json")) {
        // Open failed
        qWarning() << "Open TBC JSON metadata failed for filename" << sourceFilename;
        currentSourceFilename.clear();

        // Show an error to the user
        lastLoadError = "Could not open TBC JSON metadata file for the TBC input file!";
    } else {
        // Get the video parameters from the metadata
        LdDecodeMetaData::VideoParameters videoParameters = ldDecodeMetaData.getVideoParameters();

        // Open the new source video
        qDebug() << "TbcSource::startBackgroundLoad(): Loading TBC file...";
        emit busyLoading("Loading TBC file...");
        if (!sourceVideo.open(sourceFilename, videoParameters.fieldWidth * videoParameters.fieldHeight)) {
            // Open failed
            qWarning() << "Open TBC file failed for filename" << sourceFilename;
            currentSourceFilename.clear();

            // Show an error to the user
            lastLoadError = "Could not open TBC data file!";
        } else {
            // Both the video and metadata files are now open
            sourceReady = true;
            currentSourceFilename = sourceFilename;
        }
    }

    // Get the video parameters
    LdDecodeMetaData::VideoParameters videoParameters = ldDecodeMetaData.getVideoParameters();

    // Configure the chroma decoder
    if (videoParameters.isSourcePal) {
        palColour.updateConfiguration(videoParameters, palColourConfiguration);
    } else {
        Comb::Configuration configuration;
        ntscColour.updateConfiguration(videoParameters, configuration);
    }

    // Generate the graph data for the source
    emit busyLoading("Generating graph data...");
    generateData(2000);
}

void TbcSource::finishBackgroundLoad()
{
    // Send a finished loading message to the main window
    emit finishedLoading();
}
