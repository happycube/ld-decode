/************************************************************************

    tbcsource.cpp

    ld-analyse - TBC output analysis
    Copyright (C) 2018-2022 Simon Inns
    Copyright (C) 2021-2022 Adam Sampson

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
    resetState();

    // Configure the chroma decoder
    palConfiguration = palColour.getConfiguration();
    palConfiguration.chromaFilter = PalColour::transform2DFilter;
    ntscConfiguration = ntscColour.getConfiguration();
    outputConfiguration.pixelFormat = OutputWriter::PixelFormat::RGB48;
    outputConfiguration.paddingAmount = 1;
}

// Public methods -----------------------------------------------------------------------------------------------------

// Method to load a TBC source file
void TbcSource::loadSource(QString sourceFilename)
{
    resetState();

    // Set the current file name
    QFileInfo inFileInfo(sourceFilename);
    currentSourceFilename = inFileInfo.fileName();
    qDebug() << "TbcSource::loadSource(): Opening TBC source file:" << currentSourceFilename;

    // Set up and fire-off background loading thread
    qDebug() << "TbcSource::loadSource(): Setting up background loader thread";
    disconnect(&watcher, &QFutureWatcher<bool>::finished, nullptr, nullptr);
    connect(&watcher, &QFutureWatcher<bool>::finished, this, &TbcSource::finishBackgroundLoad);
#if QT_VERSION < QT_VERSION_CHECK(6, 0, 0)
    future = QtConcurrent::run(this, &TbcSource::startBackgroundLoad, sourceFilename);
#else
    future = QtConcurrent::run(&TbcSource::startBackgroundLoad, this, sourceFilename);
#endif
    watcher.setFuture(future);
}

// Method to unload a TBC source file
void TbcSource::unloadSource()
{
    sourceVideo.close();
    if (sourceMode != ONE_SOURCE) chromaSourceVideo.close();
    resetState();
}

// Start saving the JSON file for the current source
void TbcSource::saveSourceJson()
{
    // Start a background saving thread
    qDebug() << "TbcSource::saveSourceJson(): Starting background save thread";
    disconnect(&watcher, &QFutureWatcher<bool>::finished, nullptr, nullptr);
    connect(&watcher, &QFutureWatcher<bool>::finished, this, &TbcSource::finishBackgroundSave);
#if QT_VERSION < QT_VERSION_CHECK(6, 0, 0)
    future = QtConcurrent::run(this, &TbcSource::startBackgroundSave, currentJsonFilename);
#else
    future = QtConcurrent::run(&TbcSource::startBackgroundSave, this, currentJsonFilename);
#endif
    watcher.setFuture(future);
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

// Return a description of the last IO error
QString TbcSource::getLastIOError()
{
    return lastIOError;
}

// Method to set the highlight dropouts mode (true = dropouts highlighted)
void TbcSource::setHighlightDropouts(bool _state)
{
    invalidateFrameCache();
    dropoutsOn = _state;
}

// Method to set the chroma decoder mode (true = on)
void TbcSource::setChromaDecoder(bool _state)
{
    invalidateFrameCache();
    chromaOn = _state;
}

// Method to set the field order (true = reversed, false = normal)
void TbcSource::setFieldOrder(bool _state)
{
    invalidateFrameCache();
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

// Method to get the field order
bool TbcSource::getFieldOrder()
{
    return reverseFoOn;
}

// Return the source mode
TbcSource::SourceMode TbcSource::getSourceMode()
{
    return sourceMode;
}

// Set the source mode
void TbcSource::setSourceMode(TbcSource::SourceMode _sourceMode)
{
    if (sourceMode == ONE_SOURCE) return;

    invalidateFrameCache();
    sourceMode = _sourceMode;
}

// Load the metadata for a frame
void TbcSource::loadFrame(qint32 frameNumber)
{
    // If there's no source, or we've already loaded that frame, nothing to do
    if (!sourceReady || loadedFrameNumber == frameNumber) return;
    loadedFrameNumber = frameNumber;
    inputFieldsValid = false;
    invalidateFrameCache();

    // Get the required field numbers
    firstFieldNumber = ldDecodeMetaData.getFirstFieldNumber(frameNumber);
    secondFieldNumber = ldDecodeMetaData.getSecondFieldNumber(frameNumber);

    // Make sure we have a valid response from the frame determination
    if (firstFieldNumber == -1 || secondFieldNumber == -1) {
        qCritical() << "Could not determine field numbers!";

        // Jump back one frame
        if (frameNumber != 1) {
            frameNumber--;

            firstFieldNumber = ldDecodeMetaData.getFirstFieldNumber(frameNumber);
            secondFieldNumber = ldDecodeMetaData.getSecondFieldNumber(frameNumber);
        }
        qDebug() << "TbcSource::loadFrame(): Jumping back one frame due to error";
    }

    // Get the field metadata
    firstField = ldDecodeMetaData.getField(firstFieldNumber);
    secondField = ldDecodeMetaData.getField(secondFieldNumber);
}

// Method to get a QImage from a frame number
QImage TbcSource::getFrameImage()
{
    if (loadedFrameNumber == -1) return QImage();

    // Check cached QImage
    if (frameCacheValid) return frameCache;

    // Get a QImage for the frame
    QImage frameImage = generateQImage();

    // Highlight dropouts
    if (dropoutsOn) {
        // Create a painter object
        QPainter imagePainter;
        imagePainter.begin(&frameImage);

        // Draw the drop out data for the first field
        imagePainter.setPen(Qt::red);
        for (qint32 dropOutIndex = 0; dropOutIndex < firstField.dropOuts.size(); dropOutIndex++) {
            qint32 startx = firstField.dropOuts.startx(dropOutIndex);
            qint32 endx = firstField.dropOuts.endx(dropOutIndex);
            qint32 fieldLine = firstField.dropOuts.fieldLine(dropOutIndex);

            imagePainter.drawLine(startx, ((fieldLine - 1) * 2), endx, ((fieldLine - 1) * 2));
        }

        // Draw the drop out data for the second field
        imagePainter.setPen(Qt::blue);
        for (qint32 dropOutIndex = 0; dropOutIndex < secondField.dropOuts.size(); dropOutIndex++) {
            qint32 startx = secondField.dropOuts.startx(dropOutIndex);
            qint32 endx = secondField.dropOuts.endx(dropOutIndex);
            qint32 fieldLine = secondField.dropOuts.fieldLine(dropOutIndex);

            imagePainter.drawLine(startx, ((fieldLine - 1) * 2) + 1, endx, ((fieldLine - 1) * 2) + 1);
        }

        // End the painter object
        imagePainter.end();
    }

    frameCache = frameImage;
    frameCacheValid = true;
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

// Method returns true if the TBC source is anamorphic (false for 4:3)
bool TbcSource::getIsWidescreen()
{
    if (!sourceReady) return false;
    return ldDecodeMetaData.getVideoParameters().isWidescreen;
}

// Return the source's VideoSystem
VideoSystem TbcSource::getSystem()
{
    if (!sourceReady) return NTSC;
    return ldDecodeMetaData.getVideoParameters().system;
}

// Return the source's VideoSystem description
QString TbcSource::getSystemDescription()
{
    if (!sourceReady) return "None";
    return ldDecodeMetaData.getVideoSystemDescription();
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
QVector<double> TbcSource::getBlackSnrGraphData()
{
    return blackSnrGraphData;
}

// Get white SNR data for graphing
QVector<double> TbcSource::getWhiteSnrGraphData()
{
    return whiteSnrGraphData;
}

// Get dropout data for graphing
QVector<double> TbcSource::getDropOutGraphData()
{
    return dropoutGraphData;
}

// Get visible dropout data for graphing
QVector<double> TbcSource::getVisibleDropOutGraphData()
{
    return visibleDropoutGraphData;
}

// Method to get the size of the graphing data
qint32 TbcSource::getGraphDataSize()
{
    // All data vectors are the same size, just return the size on one
    return dropoutGraphData.size();
}

// Method returns true if frame contains dropouts
bool TbcSource::getIsDropoutPresent()
{
    if (loadedFrameNumber == -1) return false;

    if (firstField.dropOuts.size() > 0) return true;
    if (secondField.dropOuts.size() > 0) return true;
    return false;
}

// Get the decoded ComponentFrame for the current frame
const ComponentFrame &TbcSource::getComponentFrame()
{
    // Load and decode SourceFields for the current frame
    loadInputFields();
    decodeFrame();

    return componentFrames[0];
}

// Get the VideoParameters for the current source
const LdDecodeMetaData::VideoParameters &TbcSource::getVideoParameters()
{
    return ldDecodeMetaData.getVideoParameters();
}

// Update the VideoParameters for the current source
void TbcSource::setVideoParameters(const LdDecodeMetaData::VideoParameters &videoParameters)
{
    invalidateFrameCache();

    // Update the metadata
    ldDecodeMetaData.setVideoParameters(videoParameters);

    // Reconfigure the chroma decoder
    configureChromaDecoder();
}

// Get scan line data from the frame
TbcSource::ScanLineData TbcSource::getScanLineData(qint32 scanLine)
{
    if (loadedFrameNumber == -1) return ScanLineData();

    ScanLineData scanLineData;
    LdDecodeMetaData::VideoParameters videoParameters = ldDecodeMetaData.getVideoParameters();

    // Set the system and line number
    scanLineData.systemDescription = ldDecodeMetaData.getVideoSystemDescription();
    scanLineData.lineNumber = LineNumber::fromFrame1(scanLine, videoParameters.system);
    const LineNumber &lineNumber = scanLineData.lineNumber;

    // Set the video parameters
    scanLineData.blackIre = videoParameters.black16bIre;
    scanLineData.whiteIre = videoParameters.white16bIre;
    scanLineData.fieldWidth = videoParameters.fieldWidth;
    scanLineData.colourBurstStart = videoParameters.colourBurstStart;
    scanLineData.colourBurstEnd = videoParameters.colourBurstEnd;
    scanLineData.activeVideoStart = videoParameters.activeVideoStart;
    scanLineData.activeVideoEnd = videoParameters.activeVideoEnd;

    // Is this line part of the active region?
    scanLineData.isActiveLine = (scanLine - 1) >= videoParameters.firstActiveFrameLine
                                && (scanLine -1) < videoParameters.lastActiveFrameLine;

    // Get the field video and dropout data
    const SourceVideo::Data &fieldData = lineNumber.isFirstField() ? inputFields[inputStartIndex].data
                                                                   : inputFields[inputStartIndex + 1].data;
    const ComponentFrame &componentFrame = getComponentFrame();
    DropOuts &dropouts = lineNumber.isFirstField() ? firstField.dropOuts
                                                   : secondField.dropOuts;

    scanLineData.composite.resize(videoParameters.fieldWidth);
    scanLineData.luma.resize(videoParameters.fieldWidth);
    scanLineData.isDropout.resize(videoParameters.fieldWidth);

    for (qint32 xPosition = 0; xPosition < videoParameters.fieldWidth; xPosition++) {
        // Get the 16-bit composite value for the current pixel (frame data is numbered 0-624 or 0-524)
        scanLineData.composite[xPosition] = fieldData[(lineNumber.field0() * videoParameters.fieldWidth) + xPosition];

        // Get the decoded luma value for the current pixel (only computed in the active region)
        scanLineData.luma[xPosition] = static_cast<qint32>(componentFrame.y(scanLine - 1)[xPosition]);

        scanLineData.isDropout[xPosition] = false;
        for (qint32 doCount = 0; doCount < dropouts.size(); doCount++) {
            if (dropouts.fieldLine(doCount) == lineNumber.field1()) {
                if (xPosition >= dropouts.startx(doCount) && xPosition <= dropouts.endx(doCount)) scanLineData.isDropout[xPosition] = true;
            }
        }
    }

    return scanLineData;
}

// Method to return the decoded VBI data for the frame
VbiDecoder::Vbi TbcSource::getFrameVbi()
{
    if (loadedFrameNumber == -1) return VbiDecoder::Vbi();

    return vbiDecoder.decodeFrame(firstField.vbi.vbiData[0], firstField.vbi.vbiData[1], firstField.vbi.vbiData[2],
                                  secondField.vbi.vbiData[0], secondField.vbi.vbiData[1], secondField.vbi.vbiData[2]);
}

// Method returns true if the VBI is valid for the frame
bool TbcSource::getIsFrameVbiValid()
{
    if (loadedFrameNumber == -1) return false;

    if (firstField.vbi.vbiData[0] == -1 || firstField.vbi.vbiData[1] == -1 || firstField.vbi.vbiData[2] == -1) return false;
    if (secondField.vbi.vbiData[0] == -1 || secondField.vbi.vbiData[1] == -1 || secondField.vbi.vbiData[2] == -1) return false;

    return true;
}

// Method to return the decoded VITC data for the frame
VitcDecoder::Vitc TbcSource::getFrameVitc()
{
    if (loadedFrameNumber == -1) return VitcDecoder::Vitc();

    const VideoSystem system = ldDecodeMetaData.getVideoParameters().system;
    if (firstField.vitc.inUse) return vitcDecoder.decode(firstField.vitc.vitcData, system);
    if (secondField.vitc.inUse) return vitcDecoder.decode(secondField.vitc.vitcData, system);

    return VitcDecoder::Vitc();
}

// Method returns true if the VITC is valid for the frame
bool TbcSource::getIsFrameVitcValid()
{
    if (loadedFrameNumber == -1) return false;

    return firstField.vitc.inUse || secondField.vitc.inUse;
}

// Method to get the field number of the first field of the frame
qint32 TbcSource::getFirstFieldNumber()
{
    if (loadedFrameNumber == -1) return 0;
    return firstFieldNumber;
}

// Method to get the field number of the second field of the frame
qint32 TbcSource::getSecondFieldNumber()
{
    if (loadedFrameNumber == -1) return 0;
    return secondFieldNumber;
}

qint32 TbcSource::getCcData0()
{
    if (loadedFrameNumber == -1) return 0;

    if (firstField.ntsc.ccData0 != -1) return firstField.ntsc.ccData0;
    return secondField.ntsc.ccData0;
}

qint32 TbcSource::getCcData1()
{
    if (loadedFrameNumber == -1) return 0;

    if (firstField.ntsc.ccData1 != -1) return firstField.ntsc.ccData1;
    return secondField.ntsc.ccData1;
}

void TbcSource::setChromaConfiguration(const PalColour::Configuration &_palConfiguration,
                                       const Comb::Configuration &_ntscConfiguration,
                                       const OutputWriter::Configuration &_outputConfiguration)
{
    invalidateFrameCache();

    palConfiguration = _palConfiguration;
    ntscConfiguration = _ntscConfiguration;
    outputConfiguration = _outputConfiguration;

    configureChromaDecoder();
}

const PalColour::Configuration &TbcSource::getPalConfiguration()
{
    return palConfiguration;
}

const Comb::Configuration &TbcSource::getNtscConfiguration()
{
    return ntscConfiguration;
}

const OutputWriter::Configuration &TbcSource::getOutputConfiguration()
{
    return outputConfiguration;
}

// Return the frame number of the start of the next chapter
qint32 TbcSource::startOfNextChapter(qint32 currentFrameNumber)
{
    // Do we have a chapter map?
    if (chapterMap.size() == 0) return getNumberOfFrames();

    qint32 mapLocation = -1;
    for (qint32 i = 0; i < chapterMap.size(); i++) {
        if (chapterMap[i] > currentFrameNumber) {
            mapLocation = i;
            break;
        }
    }

    // Found?
    if (mapLocation != -1) {
        return chapterMap[mapLocation];
    }

    return getNumberOfFrames();
}

// Return the frame number of the start of the current chapter
qint32 TbcSource::startOfChapter(qint32 currentFrameNumber)
{
    // Do we have a chapter map?
    if (chapterMap.size() == 0) return 1;

    qint32 mapLocation = -1;
    for (qint32 i = chapterMap.size() - 1; i >= 0; i--) {
        if (chapterMap[i] < currentFrameNumber) {
            mapLocation = i;
            break;
        }
    }

    // Found?
    if (mapLocation != -1) {
        return chapterMap[mapLocation];
    }

    return 1;
}


// Private methods ----------------------------------------------------------------------------------------------------

// Re-initialise state for a new source video
void TbcSource::resetState()
{
    // Default frame image options
    chromaOn = false;
    dropoutsOn = false;
    reverseFoOn = false;
    sourceReady = false;
    sourceMode = ONE_SOURCE;

    // Cache state
    loadedFrameNumber = -1;
    inputFieldsValid = false;
    decodedFrameValid = false;
    frameCacheValid = false;
}

// Mark any cached data for the current frame as invalid
void TbcSource::invalidateFrameCache()
{
    // Note this includes the input fields, because the number of fields we
    // load depends on the decoder parameters
    inputFieldsValid = false;
    decodedFrameValid = false;
    frameCacheValid = false;
}

// Configure the chroma decoder for its settings and the VideoParameters
void TbcSource::configureChromaDecoder()
{
    // Configure the chroma decoder
    LdDecodeMetaData::VideoParameters videoParameters = ldDecodeMetaData.getVideoParameters();
    if (videoParameters.system == PAL || videoParameters.system == PAL_M) {
        palColour.updateConfiguration(videoParameters, palConfiguration);
    } else {
        ntscColour.updateConfiguration(videoParameters, ntscConfiguration);
    }

    // Configure the OutputWriter.
    // Because we have padding disabled, this won't change the VideoParameters.
    outputWriter.updateConfiguration(videoParameters, outputConfiguration);
}

// Ensure the SourceFields for the current frame are loaded
void TbcSource::loadInputFields()
{
    if (inputFieldsValid) return;

    // Work out how many frames ahead/behind we need to fetch
    qint32 lookBehind, lookAhead;
    if (getSystem() == PAL || getSystem() == PAL_M) {
        lookBehind = palConfiguration.getLookBehind();
        lookAhead = palConfiguration.getLookAhead();
    } else {
        lookBehind = ntscConfiguration.getLookBehind();
        lookAhead = ntscConfiguration.getLookAhead();
    }

    if (sourceMode == CHROMA_SOURCE) {
        // Load chroma directly into inputFields
        SourceField::loadFields(chromaSourceVideo, ldDecodeMetaData,
                                loadedFrameNumber, 1, lookBehind, lookAhead,
                                inputFields, inputStartIndex, inputEndIndex);
    } else {
        // Load the only source, or luma, into inputFields
        SourceField::loadFields(sourceVideo, ldDecodeMetaData,
                                loadedFrameNumber, 1, lookBehind, lookAhead,
                                inputFields, inputStartIndex, inputEndIndex);
    }

    if (sourceMode == BOTH_SOURCES) {
        // Load chroma into chromaInputFields
        SourceField::loadFields(chromaSourceVideo, ldDecodeMetaData,
                                loadedFrameNumber, 1, lookBehind, lookAhead,
                                chromaInputFields, inputStartIndex, inputEndIndex);

        // Separate chroma is offset (see chroma_to_u16 in vhsdecode/chroma.py)
        static constexpr qint32 CHROMA_OFFSET = 32767;

        // Add chroma to luma, removing the offset
        for (qint32 fieldIndex = inputStartIndex; fieldIndex < inputEndIndex; fieldIndex++) {
            auto &sourceData = inputFields[fieldIndex].data;
            const auto &chromaData = chromaInputFields[fieldIndex].data;

            for (qint32 i = 0; i < sourceData.size(); i++) {
                qint32 sum = static_cast<qint32>(sourceData[i]) + static_cast<qint32>(chromaData[i]) - CHROMA_OFFSET;
                sourceData[i] = static_cast<quint16>(qBound(0, sum, 65535));
            }
        }
    }

    inputFieldsValid = true;
}

// Ensure the current frame has been decoded
void TbcSource::decodeFrame()
{
    if (decodedFrameValid) return;

    loadInputFields();

    // Decode the current frame to components
    componentFrames.resize(1);
    if (getSystem() == PAL || getSystem() == PAL_M) {
        // PAL source
        palColour.decodeFrames(inputFields, inputStartIndex, inputEndIndex, componentFrames);
    } else {
        // NTSC source
        ntscColour.decodeFrames(inputFields, inputStartIndex, inputEndIndex, componentFrames);
    }

    decodedFrameValid = true;
}

// Method to create a QImage for a source video frame
QImage TbcSource::generateQImage()
{
    // Get the metadata for the video parameters
    LdDecodeMetaData::VideoParameters videoParameters = ldDecodeMetaData.getVideoParameters();

    // Calculate the frame height
    qint32 frameHeight = (videoParameters.fieldHeight * 2) - 1;

    // Show debug information
    if (chromaOn) {
        qDebug().nospace() << "TbcSource::generateQImage(): Generating a chroma image from frame " << loadedFrameNumber <<
                    " (" << videoParameters.fieldWidth << "x" << frameHeight << ")";
    } else {
        qDebug().nospace() << "TbcSource::generateQImage(): Generating a source image from frame " << loadedFrameNumber <<
                    " (" << videoParameters.fieldWidth << "x" << frameHeight << ")";
    }

    // Create a QImage
    QImage frameImage = QImage(videoParameters.fieldWidth, frameHeight, QImage::Format_RGB888);

    if (chromaOn) {
        // Chroma decode the current frame
        decodeFrame();

        // Convert component video to RGB
        OutputFrame outputFrame;
        outputWriter.convert(componentFrames[0], outputFrame);

        // Get a pointer to the RGB data
        const quint16 *rgbPointer = outputFrame.data();

        // Fill the QImage with black
        frameImage.fill(Qt::black);

        // Copy the RGB16-16-16 data into the RGB888 QImage
        const qint32 activeHeight = videoParameters.lastActiveFrameLine - videoParameters.firstActiveFrameLine;
        const qint32 activeWidth = videoParameters.activeVideoEnd - videoParameters.activeVideoStart;
        for (qint32 y = 0; y < activeHeight; y++) {
            const quint16 *inputLine = rgbPointer + (y * activeWidth * 3);
            uchar *outputLine = frameImage.scanLine(y + videoParameters.firstActiveFrameLine)
                                + (videoParameters.activeVideoStart * 3);

            // Take just the MSB of the RGB input data
            for (qint32 i = 0; i < activeWidth * 3; i++) {
                *outputLine++ = static_cast<uchar>((*inputLine++) / 256);
            }
        }
    } else {
        // Load SourceFields for the current frame
        loadInputFields();

        // Get pointers to the 16-bit greyscale data
        const quint16 *firstFieldPointer = inputFields[inputStartIndex].data.data();
        const quint16 *secondFieldPointer = inputFields[inputStartIndex + 1].data.data();

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

// Generate the data points for the Drop-out and SNR analysis graphs, and the chapter map.
// We do these all at the same time to reduce calls to the metadata.
void TbcSource::generateData()
{
    dropoutGraphData.clear();
    visibleDropoutGraphData.clear();
    blackSnrGraphData.clear();
    whiteSnrGraphData.clear();

    dropoutGraphData.resize(ldDecodeMetaData.getNumberOfFrames());
    visibleDropoutGraphData.resize(ldDecodeMetaData.getNumberOfFrames());
    blackSnrGraphData.resize(ldDecodeMetaData.getNumberOfFrames());
    whiteSnrGraphData.resize(ldDecodeMetaData.getNumberOfFrames());

    bool ignoreChapters = false;
    qint32 lastChapter = -1;
    qint32 giveUpCounter = 0;
    chapterMap.clear();

    const qint32 numFrames = ldDecodeMetaData.getNumberOfFrames();
    for (qint32 frameNumber = 0; frameNumber < numFrames; frameNumber++) {
        double doLength = 0;
        double visibleDoLength = 0;
        double blackSnrTotal = 0;
        double whiteSnrTotal = 0;

        // SNR data may be missing in some fields, so we count the points to prevent
        // the frame average from being thrown-off by missing data
        double blackSnrPoints = 0;
        double whiteSnrPoints = 0;

        const LdDecodeMetaData::Field &firstField = ldDecodeMetaData.getField(ldDecodeMetaData.getFirstFieldNumber(frameNumber + 1));
        const LdDecodeMetaData::Field &secondField = ldDecodeMetaData.getField(ldDecodeMetaData.getSecondFieldNumber(frameNumber + 1));

        // Get the first field DOs
        if (firstField.dropOuts.size() > 0) {
            // Calculate the total length of the dropouts
            for (qint32 i = 0; i < firstField.dropOuts.size(); i++) {
                doLength += static_cast<double>(firstField.dropOuts.endx(i) - firstField.dropOuts.startx(i));
            }
        }

        // Get the second field DOs
        if (secondField.dropOuts.size() > 0) {
            // Calculate the total length of the dropouts
            for (qint32 i = 0; i < secondField.dropOuts.size(); i++) {
                doLength += static_cast<double>(secondField.dropOuts.endx(i) - secondField.dropOuts.startx(i));
            }
        }

        // Get the first field visible DOs
        const LdDecodeMetaData::VideoParameters &videoParameters = ldDecodeMetaData.getVideoParameters();

        if (firstField.dropOuts.size() > 0) {
            // Calculate the total length of the visible dropouts
            for (qint32 i = 0; i < firstField.dropOuts.size(); i++) {
                // Does the drop out start in the visible area?
                if ((firstField.dropOuts.fieldLine(i) >= videoParameters.firstActiveFieldLine) &&
                    (firstField.dropOuts.fieldLine(i) <= videoParameters.lastActiveFieldLine)) {
                    if (firstField.dropOuts.startx(i) >= videoParameters.activeVideoStart) {
                        qint32 startx = firstField.dropOuts.startx(i);
                        qint32 endx;
                        if (firstField.dropOuts.endx(i) < videoParameters.activeVideoEnd) endx = firstField.dropOuts.endx(i);
                        else endx = videoParameters.activeVideoEnd;

                        visibleDoLength += static_cast<double>(endx - startx);
                    }
                }
            }
        }

        // Get the second field visible DOs
        if (secondField.dropOuts.size() > 0) {
            // Calculate the total length of the visible dropouts
            for (qint32 i = 0; i < secondField.dropOuts.size(); i++) {
                // Does the drop out start in the visible area?
                if ((secondField.dropOuts.fieldLine(i) >= videoParameters.firstActiveFieldLine) &&
                    (secondField.dropOuts.fieldLine(i) <= videoParameters.lastActiveFieldLine)) {
                    if (secondField.dropOuts.startx(i) >= videoParameters.activeVideoStart) {
                        qint32 startx = secondField.dropOuts.startx(i);
                        qint32 endx;
                        if (secondField.dropOuts.endx(i) < videoParameters.activeVideoEnd) endx = secondField.dropOuts.endx(i);
                        else endx = videoParameters.activeVideoEnd;

                        visibleDoLength += static_cast<double>(endx - startx);
                    }
                }
            }
        }

        // Get the first field SNRs
        if (firstField.vitsMetrics.inUse) {
            if (firstField.vitsMetrics.bPSNR > 0) {
                blackSnrTotal += firstField.vitsMetrics.bPSNR;
                blackSnrPoints++;
            }
            if (firstField.vitsMetrics.wSNR > 0) {
                whiteSnrTotal += firstField.vitsMetrics.wSNR;
                whiteSnrPoints++;
            }
        }

        // Get the second field SNRs
        if (secondField.vitsMetrics.inUse) {
            if (secondField.vitsMetrics.bPSNR > 0) {
                blackSnrTotal += secondField.vitsMetrics.bPSNR;
                blackSnrPoints++;
            }
            if (secondField.vitsMetrics.wSNR > 0) {
                whiteSnrTotal += secondField.vitsMetrics.wSNR;
                whiteSnrPoints++;
            }
        }

        // Add the result to the vectors
        dropoutGraphData[frameNumber] = doLength;
        visibleDropoutGraphData[frameNumber] = visibleDoLength;
        blackSnrGraphData[frameNumber] = blackSnrTotal / blackSnrPoints; // Calc average for frame
        whiteSnrGraphData[frameNumber] = whiteSnrTotal / whiteSnrPoints; // Calc average for frame

        if (ignoreChapters) continue;

        // Decode the VBI
        VbiDecoder::Vbi vbi = vbiDecoder.decodeFrame(
            firstField.vbi.vbiData[0], firstField.vbi.vbiData[1], firstField.vbi.vbiData[2],
            secondField.vbi.vbiData[0], secondField.vbi.vbiData[1], secondField.vbi.vbiData[2]);

        // Get the chapter number
        qint32 currentChapter = vbi.chNo;
        if (currentChapter != -1) {
            if (currentChapter != lastChapter) {
                lastChapter = currentChapter;
                chapterMap.append(frameNumber);
            } else giveUpCounter++;
        }

        if (frameNumber == 100 && giveUpCounter < 50) {
            qDebug() << "Not seeing valid chapter numbers, giving up chapter mapping";
            ignoreChapters = true;
        }
    }
}

bool TbcSource::startBackgroundLoad(QString sourceFilename)
{
    // Open the TBC metadata file
    qDebug() << "TbcSource::startBackgroundLoad(): Processing JSON metadata...";
    emit busy("Processing JSON metadata...");

    QString jsonFileName = sourceFilename + ".json";

    const bool isChromaTbc = sourceFilename.endsWith("_chroma.tbc");
    if (isChromaTbc && !QFileInfo::exists(jsonFileName)) {
        // The user specified a _chroma.tbc file, and it doesn't have a .json.

        // The corresponding luma file should have a .json, so use that.
        QString baseFilename = sourceFilename;
        baseFilename.chop(11);
        jsonFileName = baseFilename + ".tbc.json";

        // But does the luma file itself exist?
        QString lumaFilename = baseFilename + ".tbc";
        if (QFileInfo::exists(lumaFilename)) {
            // Yes. Open both of them, defaulting to the chroma view.
            sourceFilename = lumaFilename;
        }
    }

    if (!ldDecodeMetaData.read(jsonFileName)) {
        // Open failed
        qWarning() << "Open TBC JSON metadata failed for filename" << sourceFilename;
        currentSourceFilename.clear();

        // Show an error to the user and give up
        lastIOError = "Could not load source TBC JSON metadata file";
        return false;
    }

    // Get the video parameters from the metadata
    LdDecodeMetaData::VideoParameters videoParameters = ldDecodeMetaData.getVideoParameters();

    // Open the new source video
    qDebug() << "TbcSource::startBackgroundLoad(): Loading TBC file...";
    emit busy("Loading TBC file...");
    if (!sourceVideo.open(sourceFilename, videoParameters.fieldWidth * videoParameters.fieldHeight)) {
        // Open failed
        qWarning() << "Open TBC file failed for filename" << sourceFilename;
        currentSourceFilename.clear();

        // Show an error to the user and give up
        lastIOError = "Could not open source TBC data file";
        return false;
    }

    // Is there a separate _chroma.tbc file?
    QString chromaSourceFilename = sourceFilename;
    chromaSourceFilename.chop(4);
    chromaSourceFilename += "_chroma.tbc";
    if (QFileInfo::exists(chromaSourceFilename)) {
        // Yes! Open it.
        qDebug() << "TbcSource::startBackgroundLoad(): Loading chroma TBC file...";
        emit busy("Loading chroma TBC file...");
        if (!chromaSourceVideo.open(chromaSourceFilename, videoParameters.fieldWidth * videoParameters.fieldHeight)) {
            // Open failed
            qWarning() << "Open chroma TBC file failed for filename" << chromaSourceFilename;
            currentSourceFilename.clear();
            sourceVideo.close();

            // Show an error to the user and give up
            lastIOError = "Could not open source chroma TBC data file";
            return false;
        }

        sourceMode = isChromaTbc ? CHROMA_SOURCE : BOTH_SOURCES;
    }

    // Both the video and metadata files are now open
    sourceReady = true;
    currentSourceFilename = sourceFilename;
    currentJsonFilename = jsonFileName;

    // Configure the chroma decoder
    if (videoParameters.system == PAL || videoParameters.system == PAL_M) {
        palColour.updateConfiguration(videoParameters, palConfiguration);
    } else {
        if (isChromaTbc || sourceMode != ONE_SOURCE) {
            // Enable phase compensation by default, since this is probably a videotape source
            ntscConfiguration.phaseCompensation = true;
        }
        ntscColour.updateConfiguration(videoParameters, ntscConfiguration);
    }

    // Analyse the metadata
    emit busy("Generating graph data and chapter map...");
    generateData();

    return true;
}

void TbcSource::finishBackgroundLoad()
{
    // Send a finished loading message to the main window
    emit finishedLoading(future.result());
}

bool TbcSource::startBackgroundSave(QString jsonFilename)
{
    qDebug() << "TbcSource::startBackgroundSave(): Saving to" << jsonFilename;
    emit busy("Saving JSON metadata...");

    // The general idea here is that decoding takes a long time -- so we want
    // to be careful not to destroy the user's only copy of their JSON file if
    // something goes wrong!

    // Write the metadata out to a new temporary file
    QString newJsonFilename = jsonFilename + ".new";
    if (!ldDecodeMetaData.write(newJsonFilename)) {
        // Writing failed
        lastIOError = "Could not write to new JSON file";
        return false;
    }

    // If there isn't already a .bup backup file, rename the existing file to that name
    // (matching the behaviour of ld-process-vbi)
    QString backupFilename = jsonFilename + ".bup";
    if (!QFile::exists(backupFilename)) {
        if (!QFile::rename(jsonFilename, jsonFilename + ".bup")) {
            // Renaming failed
            lastIOError = "Could not rename existing JSON file to backup";
            return false;
        }
    } else {
        // There is a backup, so it's safe to remove the existing file
        if (!QFile::remove(jsonFilename)) {
            // Deleting failed
            lastIOError = "Could not remove existing JSON file";
            return false;
        }
    }

    // Rename the new file to the target name
    if (!QFile::rename(newJsonFilename, jsonFilename)) {
        // Renaming failed
        lastIOError = "Could not rename new JSON file to target name";
        return false;
    }

    qDebug() << "TbcSource::startBackgroundSave(): Save complete";
    return true;
}

void TbcSource::finishBackgroundSave()
{
    // Send a finished saving message to the main window
    emit finishedSaving(future.result());
}
