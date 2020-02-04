/************************************************************************

    sources.cpp

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

#include "sources.h"

Sources::Sources(QVector<QString> inputFilenames, bool reverse,
                 qint32 dodThreshold, bool lumaClip,
                 qint32 startVbi, qint32 lengthVbi,
                 qint32 maxThreads, QObject *parent)
    : QObject(parent), m_inputFilenames(inputFilenames), m_reverse(reverse),
      m_dodThreshold(dodThreshold), m_lumaClip(lumaClip), m_startVbi(startVbi),
      m_lengthVbi(lengthVbi), m_maxThreads(maxThreads)
{
    // Used to track the sources as they are loaded
    currentSource = 0;
}

bool Sources::process()
{
    // Show input filenames
    qInfo() << "Processing" << m_inputFilenames.size() << "input TBC files:";
    for (qint32 i = 0; i < m_inputFilenames.size(); i++) qInfo().nospace() << "  Source #" << i << ": " << m_inputFilenames[i];

    // And then show the rest...
    qInfo() << "Using" << m_maxThreads << "threads to process sources";
    if (m_reverse) qInfo() << "Using reverse field order"; else qInfo() << "Using normal field order";
    qInfo().nospace() << "Dropout detection threshold is " << m_dodThreshold << "% difference";
    if (m_lumaClip) qInfo() << "Performing luma clip detection"; else qInfo() << "Not performing luma clip detection";
    qInfo() << "";

    // Load the input TBC files ---------------------------------------------------------------------------------------
    if (!loadInputTbcFiles(m_inputFilenames, m_reverse)) {
        qCritical() << "Error: Unable to load input TBC files - cannot continue!";
        return false;
    }

    // Show disc and video information
    qInfo() << "";
    qInfo() << "Sources have VBI frame number range of" << getMinimumVbiFrameNumber() <<
               "to" << getMaximumVbiFrameNumber();

    // Check start and length
    qint32 vbiStartFrame = m_startVbi;
    if (vbiStartFrame < getMinimumVbiFrameNumber())
        vbiStartFrame = getMinimumVbiFrameNumber();

    qint32 length = m_lengthVbi;
    if (length > (getMaximumVbiFrameNumber() - vbiStartFrame + 1))
        length = getMaximumVbiFrameNumber() - vbiStartFrame + 1;
    if (length == -1) length = getMaximumVbiFrameNumber() - getMinimumVbiFrameNumber() + 1;

    // Verify frame source availablity
    qInfo() << "";
    qInfo() << "Verifying VBI frame multi-source availablity...";
    verifySources(vbiStartFrame, length);

    // Process the sources --------------------------------------------------------------------------------------------
    inputFrameNumber = vbiStartFrame;
    lastFrameNumber = vbiStartFrame + length;

    qInfo() << "";
    qInfo() << "Beginning multi-threaded diffDOD processing...";
    qInfo() << "Processing" << length << "frames - from VBI frame" << inputFrameNumber << "to" << lastFrameNumber;
    totalTimer.start();

    // Start a vector of decoding threads to process the video
    qInfo() << "Beginning multi-threaded dropout correction process...";
    QVector<QThread *> threads;
    threads.resize(m_maxThreads);
    for (qint32 i = 0; i < m_maxThreads; i++) {
        threads[i] = new DiffDod(abort, *this);
        threads[i]->start(QThread::LowPriority);
    }

    // Wait for the workers to finish
    for (qint32 i = 0; i < m_maxThreads; i++) {
        threads[i]->wait();
        delete threads[i];
    }

    // Did any of the threads abort?
    if (abort) {
        qCritical() << "Threads aborted!  Cleaning up...";
        unloadInputTbcFiles();
        return false;
    }

    // Show the processing speed to the user
    float totalSecs = (static_cast<float>(totalTimer.elapsed()) / 1000.0);
    qInfo().nospace() << "DiffDOD complete - " << length << " frames in " << totalSecs << " seconds (" <<
               length / totalSecs << " FPS)";

    // Save the sources -----------------------------------------------------------------------------------------------
    qInfo() << "";
    qInfo() << "Saving sources...";
    saveSources();

    // Unload the input sources
    qInfo() << "";
    qInfo() << "Cleaning up...";
    unloadInputTbcFiles();

    return true;
}

// Provide a frame to the threaded processing
bool Sources::getInputFrame(qint32& targetVbiFrame,
                            QVector<SourceVideo::Data>& firstFields, QVector<SourceVideo::Data>& secondFields,
                            LdDecodeMetaData::VideoParameters& videoParameters,
                            QVector<qint32>& availableSourcesForFrame,
                            qint32& dodThreshold, bool& lumaClip)
{
    QMutexLocker locker(&inputMutex);

    if (inputFrameNumber > lastFrameNumber) {
        // No more input frames
        return false;
    }

    targetVbiFrame = inputFrameNumber;
    inputFrameNumber++;

    // Get the metadata for the video parameters (all sources are the same, so just grab from the first)
    videoParameters = sourceVideos[0]->ldDecodeMetaData.getVideoParameters();

    // Get the number of available sources for the current frame
    availableSourcesForFrame = getAvailableSourcesForFrame(targetVbiFrame);

    // Get the field data for the current frame (from all available sources)
    firstFields = getFieldData(targetVbiFrame, true, videoParameters, availableSourcesForFrame);
    secondFields = getFieldData(targetVbiFrame, false, videoParameters, availableSourcesForFrame);

    // Set the other miscellaneous parameters
    dodThreshold = m_dodThreshold;
    lumaClip = m_lumaClip;

    return true;
}

// Receive a frame from the threaded processing
bool Sources::setOutputFrame(qint32 targetVbiFrame,
                             QVector<LdDecodeMetaData::DropOuts> firstFieldDropouts,
                             QVector<LdDecodeMetaData::DropOuts> secondFieldDropouts,
                             QVector<qint32> availableSourcesForFrame)
{
    QMutexLocker locker(&outputMutex);

    // Write the first and second field line metadata back to the source
    for (qint32 sourcePointer = 0; sourcePointer < availableSourcesForFrame.size(); sourcePointer++) {
        qint32 sourceNo = availableSourcesForFrame[sourcePointer]; // Get the actual source

        // Get the required field numbers
        qint32 firstFieldNumber = sourceVideos[sourceNo]->
                ldDecodeMetaData.getFirstFieldNumber(convertVbiFrameNumberToSequential(targetVbiFrame, sourceNo));
        qint32 secondFieldNumber = sourceVideos[sourceNo]->
                ldDecodeMetaData.getSecondFieldNumber(convertVbiFrameNumberToSequential(targetVbiFrame, sourceNo));

        // Calculate the total number of dropouts detected for the frame
        qint32 totalFirstDropouts = 0;
        qint32 totalSecondDropouts = 0;
        if (firstFieldDropouts.size() > 0) totalFirstDropouts = firstFieldDropouts[sourceNo].startx.size();
        if (secondFieldDropouts.size() > 0) totalSecondDropouts = secondFieldDropouts[sourceNo].startx.size();

        qDebug() << "Writing source" << sourceNo <<
                    "frame" << targetVbiFrame << "fields" << firstFieldNumber << "/" << secondFieldNumber <<
                    "- Dropout records" << totalFirstDropouts << "/" << totalSecondDropouts;

        // Only replace the existing metadata if it was possible to create new metadata
        if (availableSourcesForFrame.size() >= 3) {
            // Remove the existing field dropout metadata for the field
            sourceVideos[sourceNo]->ldDecodeMetaData.clearFieldDropOuts(firstFieldNumber);
            sourceVideos[sourceNo]->ldDecodeMetaData.clearFieldDropOuts(secondFieldNumber);

            // Write the new field dropout metadata
            sourceVideos[sourceNo]->ldDecodeMetaData.updateFieldDropOuts(firstFieldDropouts[sourceNo], firstFieldNumber);
            sourceVideos[sourceNo]->ldDecodeMetaData.updateFieldDropOuts(secondFieldDropouts[sourceNo], secondFieldNumber);
        }
    }

    return true;
}

// Load all available input sources
bool Sources::loadInputTbcFiles(QVector<QString> inputFilenames, bool reverse)
{
    for (qint32 i = 0; i < inputFilenames.size(); i++) {
        qInfo().nospace() << "Loading TBC input source #" << i << " - Filename: " << inputFilenames[i];
        if (!loadSource(inputFilenames[i], reverse)) {
            return false;
        }
    }

    return true;
}

// Unload the input sources
void Sources::unloadInputTbcFiles()
{
    for (qint32 sourceNo = 0; sourceNo < getNumberOfAvailableSources(); sourceNo++) {
        delete sourceVideos[sourceNo];
        sourceVideos.removeFirst();
    }
}

// Load a TBC source video; returns false on failure
bool Sources::loadSource(QString filename, bool reverse)
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
        if ((sourceVideos.size() - 1 > 0) && (sourceVideos[0]->ldDecodeMetaData.getVideoParameters().isSourcePal
                                              != videoParameters.isSourcePal)) {
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

// Method to work out the disc type (CAV or CLV) and the maximum and minimum
// VBI frame numbers for the source
bool Sources::setDiscTypeAndMaxMinFrameVbi(qint32 sourceNumber)
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

// Get the minimum VBI frame number for all sources
qint32 Sources::getMinimumVbiFrameNumber()
{
    qint32 minimumFrameNumber = 1000000;
    for (qint32 i = 0; i < sourceVideos.size(); i++) {
        if (sourceVideos[i]->minimumVbiFrameNumber < minimumFrameNumber)
            minimumFrameNumber = sourceVideos[i]->minimumVbiFrameNumber;
    }

    return minimumFrameNumber;
}

// Get the maximum VBI frame number for all sources
qint32 Sources::getMaximumVbiFrameNumber()
{
    qint32 maximumFrameNumber = 0;
    for (qint32 i = 0; i < sourceVideos.size(); i++) {
        if (sourceVideos[i]->maximumVbiFrameNumber > maximumFrameNumber)
            maximumFrameNumber = sourceVideos[i]->maximumVbiFrameNumber;
    }

    return maximumFrameNumber;
}

// Verify that at least 3 sources are available for every VBI frame
void Sources::verifySources(qint32 vbiStartFrame, qint32 length)
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

// Method that returns a vector of the sources that contain data for the required VBI frame number
QVector<qint32> Sources::getAvailableSourcesForFrame(qint32 vbiFrameNumber)
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

// Method to convert a VBI frame number to a sequential frame number
qint32 Sources::convertVbiFrameNumberToSequential(qint32 vbiFrameNumber, qint32 sourceNumber)
{
    // Offset the VBI frame number to get the sequential source frame number
    return vbiFrameNumber - sourceVideos[sourceNumber]->minimumVbiFrameNumber + 1;
}

// Get the number of available sources
qint32 Sources::getNumberOfAvailableSources()
{
    return sourceVideos.size();
}

// Method to write the source metadata to disc
void Sources::saveSources()
{
    // Save the sources' metadata
    for (qint32 sourceNo = 0; sourceNo < sourceVideos.size(); sourceNo++) {
        // Write the JSON metadata
        qInfo() << "Writing JSON metadata file for TBC file" << sourceNo;
        sourceVideos[sourceNo]->ldDecodeMetaData.write(sourceVideos[sourceNo]->filename + ".json");
    }
}

// Get the field data for the specified frame
QVector<SourceVideo::Data> Sources::getFieldData(qint32 targetVbiFrame, bool isFirstField, LdDecodeMetaData::VideoParameters videoParameters,
                                                 QVector<qint32> &availableSourcesForFrame)
{
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
    }

    return fields;
}
