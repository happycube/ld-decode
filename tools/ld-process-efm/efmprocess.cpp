/************************************************************************

    efmprocess.cpp

    ld-process-efm - EFM data decoder
    Copyright (C) 2019 Simon Inns

    This file is part of ld-decode-tools.

    ld-process-efm is free software: you can redistribute it and/or
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

#include "efmprocess.h"

EfmProcess::EfmProcess(QObject *parent) : QThread(parent)
{
    // Thread control variables
    restart = false; // Setting this to true starts processing
    cancel = false; // Setting this to true cancels the processing in progress
    abort = false; // Setting this to true ends the thread process
}

EfmProcess::~EfmProcess()
{
    mutex.lock();
    abort = true;
    condition.wakeOne();
    mutex.unlock();

    wait();
}

// Reset the conversion classes
void EfmProcess::reset(void)
{
    efmToF3Frames.reset();
    f3ToF2Frames.reset();
    f2ToF1Frames.reset();
    f2FramesToAudio.reset();
    f3ToSections.reset();
    f1ToSectors.reset();
    sectorsToData.reset();

    sectionToMeta.reset();
    sectorsToMeta.reset();

    resetStatistics();
}

// Statistics
void EfmProcess::resetStatistics(void)
{
    efmToF3Frames.resetStatistics();
    f3ToF2Frames.resetStatistics();
    f2FramesToAudio.resetStatistics();
    sectorsToData.resetStatistics();
}

EfmProcess::Statistics EfmProcess::getStatistics(void)
{
    // Gather statistics
    statistics.efmToF3Frames_statistics = efmToF3Frames.getStatistics();
    statistics.f3ToF2Frames_statistics = f3ToF2Frames.getStatistics();
    statistics.f2FramesToAudio_statistics = f2FramesToAudio.getStatistics();
    statistics.sectorsToData_statistics = sectorsToData.getStatistics();

    return statistics;
}

// Thread handling methods --------------------------------------------------------------------------------------------

// Process the specified input file.  This thread wrapper passes the parameters
// to the object and restarts the run() function
void EfmProcess::startProcessing(QString inputFilename, QFile *audioOutputFile, QFile *dataOutputFile,
                                 QFile *audioMetaOutputFile, QFile *dataMetaOutputFile)
{
    QMutexLocker locker(&mutex);

    // Move all the parameters to be local
    this->inputFilename = inputFilename;
    this->audioOutputFile = audioOutputFile;
    this->dataOutputFile = dataOutputFile;
    this->audioMetaOutputFile = audioMetaOutputFile;
    this->dataMetaOutputFile = dataMetaOutputFile;

    // Is the run process already running?
    if (!isRunning()) {
        // Yes, start with low priority
        start(LowPriority);
    } else {
        // No, set the restart condition
        restart = true;
        cancel = false;
        condition.wakeOne();
    }
}

// Primary processing loop for the thread
void EfmProcess::run()
{
    qDebug() << "EfmProcess::run(): Thread initial run";

    while(!abort) {
        qDebug() << "EfmProcess::run(): Thread wake up on restart";

        // Lock and copy all parameters to 'thread-safe' variables
        mutex.lock();
        inputFilenameTs = this->inputFilename;
        audioOutputFileTs = this->audioOutputFile;
        dataOutputFileTs = this->dataOutputFile;
        audioMetaOutputFileTs = this->audioMetaOutputFile;
        dataMetaOutputFileTs = this->dataMetaOutputFile;
        mutex.unlock();

        // Open the EFM input file
        if (!openInputFile(inputFilenameTs)) {
            qCritical("Could not open input EFM file!");

            // Emit a signal showing the processing is complete
            emit completed();

            return;
        }

        if (!audioOutputFileTs->isOpen()) {
            qCritical("Audio output file is not open!");

            // Emit a signal showing the processing is complete
            emit completed();

            return;
        }

        if (!dataOutputFileTs->isOpen()) {
            qCritical("Data output file is not open!");

            // Emit a signal showing the processing is complete
            emit completed();

            return;
        }

        if (!audioMetaOutputFileTs->isOpen()) {
            qCritical("Audio metadata output file is not open!");

            // Emit a signal showing the processing is complete
            emit completed();

            return;
        }

        if (!dataMetaOutputFileTs->isOpen()) {
            qCritical("Data metadata output file is not open!");

            // Emit a signal showing the processing is complete
            emit completed();

            return;
        }

        bool processAudio = true;
        bool processData = true;

        // Open the audio output file
        if (processAudio) f2FramesToAudio.setOutputFile(audioOutputFileTs);

        // Open the data decode output file
        if (processData) sectorsToData.setOutputFile(dataOutputFile);

        // Open the metadata JSON file
        if (processAudio) sectionToMeta.setOutputFile(audioMetaOutputFileTs);
        if (processData) sectorsToMeta.setOutputFile(dataMetaOutputFileTs);

        qint64 inputFileSize = inputFileHandle->size();
        qint64 inputBytesProcessed = 0;
        qint32 lastPercent = 0;

        QByteArray efmBuffer;
        while(((efmBuffer = readEfmData()).size() != 0) && !cancel) { // Note: this doesn't allow the buffer processing to complete before stopping...
            inputBytesProcessed += efmBuffer.size();

            // Convert the EFM buffer data into F3 frames
            QVector<F3Frame> f3Frames = efmToF3Frames.convert(efmBuffer);

            // Convert the F3 frames into F2 frames
            QVector<F2Frame> f2Frames = f3ToF2Frames.convert(f3Frames);

            // Convert the F2 frames into F1 frames
            QVector<F1Frame> f1Frames = f2ToF1Frames.convert(f2Frames);

            if (processData) {
                // Convert the F1 frames to data sectors
                QVector<Sector> sectors = f1ToSectors.convert(f1Frames);

                // Write the sectors as data
                sectorsToData.convert(sectors);

                // Process the sector meta data
                sectorsToMeta.process(sectors);
            }

            // Convert the F2 frames into audio
            if (processAudio) f2FramesToAudio.convert(f2Frames);

            // Convert the F3 frames into subcode sections
            QVector<Section> sections = f3ToSections.convert(f3Frames);

            // Process the sections to audio metadata
            if (processAudio) sectionToMeta.process(sections);

            // Show EFM processing progress update to user
            qreal percent = (100.0 / static_cast<qreal>(inputFileSize)) * static_cast<qreal>(inputBytesProcessed);
            if (static_cast<qint32>(percent) > lastPercent) {
                emit percentageProcessed(static_cast<qint32>(percent));
            }
            lastPercent = static_cast<qint32>(percent);
        }

        // Show the cancel flag
        if (cancel) qDebug() << "EfmProcess::run(): Conversion cancelled";
        cancel = false;

        // Flush the metadata to the temporary files
        if (processAudio) sectionToMeta.flushMetadata();
        if (processData) sectorsToMeta.flushMetadata();

        // Emit a signal showing the processing is complete
        emit completed();

        // Report on the status of the various processes
        reportStatus(processAudio, processData);

        // Close the input file
        closeInputFile();

        // Sleep the thread until we are restarted
        mutex.lock();
        if (!restart && !abort) {
            qDebug() << "EfmProcess::run(): Thread sleeping pending restart";
            condition.wait(&mutex);
        }
        restart = false;
        mutex.unlock();
    }
    qDebug() << "EfmProcess::run(): Thread aborted";
}

// Function sets the cancel flag (which terminates the conversion if in progress)
void EfmProcess::cancelProcessing()
{
    qDebug() << "EfmProcess::cancelConversion(): Setting cancel conversion flag";
    cancel = true;
}

// Function sets the abort flag (which terminates the run() loop if in progress)
void EfmProcess::quit()
{
    qDebug() << "EfmProcess::quit(): Setting thread abort flag";
    abort = true;
}

// Method to open the input file for reading
bool EfmProcess::openInputFile(QString inputFilename)
{
    // Open input file for reading
    inputFileHandle = new QFile(inputFilename);
    if (!inputFileHandle->open(QIODevice::ReadOnly)) {
        // Failed to open source sample file
        qDebug() << "EfmProcess::openInputFile(): Could not open " << inputFilename << "as input file";
        return false;
    }
    qDebug() << "EfmProcess::openInputFile(): 10-bit input file is" << inputFilename << "and is" <<
                inputFileHandle->size() << "bytes in length";

    // Exit with success
    return true;
}

// Method to close the input file
void EfmProcess::closeInputFile(void)
{
    // Is an input file open?
    if (inputFileHandle != nullptr) {
        inputFileHandle->close();
    }

    // Clear the file handle pointer
    delete inputFileHandle;
    inputFileHandle = nullptr;
}

// Method to read EFM T value data from the input file
QByteArray EfmProcess::readEfmData(void)
{
    // Read EFM data in 64K blocks
    qint32 bufferSize = 1024 * 64;

    QByteArray outputData;
    outputData.resize(bufferSize);

    qint64 bytesRead = inputFileHandle->read(outputData.data(), outputData.size());
    if (bytesRead != bufferSize) outputData.resize(static_cast<qint32>(bytesRead));

    return outputData;
}

// Method to write status information to qInfo
void EfmProcess::reportStatus(bool processAudio, bool processData)
{
    efmToF3Frames.reportStatus();
    qInfo() << "";
    f3ToF2Frames.reportStatus();
    qInfo() << "";
    f2ToF1Frames.reportStatus();
    qInfo() << "";

    if (processData) {
        f1ToSectors.reportStatus();
        qInfo() << "";
        sectorsToData.reportStatus();
        qInfo() << "";
        sectorsToMeta.reportStatus();
        qInfo() << "";
    }

    if (processAudio) {
        f2FramesToAudio.reportStatus();
        qInfo() << "";
    }

    f3ToSections.reportStatus();
    qInfo() << "";

    sectionToMeta.reportStatus();
}
