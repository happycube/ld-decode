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

// Thread handling methods --------------------------------------------------------------------------------------------

// Start processing the input EFM file
void EfmProcess::startProcessing(QString _inputFilename, QFile *_audioOutputFileHandle)
{
    QMutexLocker locker(&mutex);

    // Move all the parameters to be local
    inputFilename = _inputFilename;
    audioOutputFileHandle = _audioOutputFileHandle;

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

// Stop processing the input EFM file
void EfmProcess::stopProcessing()
{
    qDebug() << "EfmProcess::stopProcessing(): Called, Setting cancel flag";
    cancel = true;
}

// Quit the processing thread and clean up
void EfmProcess::quit()
{
    qDebug() << "EfmProcess::quit(): Called, setting thread abort flag";
    abort = true;
}

// Return statistics about the decoding process
EfmProcess::Statistics EfmProcess::getStatistics(void)
{
    // Gather statistics
    statistics.f3ToF2Frames = f3ToF2Frames.getStatistics();
    statistics.syncF3Frames = syncF3Frames.getStatistics();
    statistics.efmToF3Frames = efmToF3Frames.getStatistics();
    statistics.f2FramesToAudio = f2FramesToAudio.getStatistics();

    return statistics;
}

void EfmProcess::reset(void)
{
    efmToF3Frames.reset();
    syncF3Frames.reset();
    f3ToF2Frames.reset();
    f2FramesToAudio.reset();
}

// Primary processing loop for the thread
void EfmProcess::run()
{
    qDebug() << "EfmProcess::run(): Thread initial run";

    while(!abort) {
        qDebug() << "EfmProcess::run(): Thread wake up on restart";
        bool audioAvailable = false;
        bool dataAvailable = false;
        reset();

        // Lock and copy all parameters to 'thread-safe' variables
        mutex.lock();
        inputFilenameTs = this->inputFilename;
        audioOutputFileHandleTs = this->audioOutputFileHandle;
        mutex.unlock();

        bool readyToProcess = true;

        // Open EFM T-values input file for reading
        QFile efmTValuesInputFileHandle(inputFilenameTs);
        if (!efmTValuesInputFileHandle.open(QIODevice::ReadOnly)) {
            // Failed to open file
            qDebug() << "EfmProcess::run(): Could not open " << inputFilenameTs << "as EFM T-values input file";
            readyToProcess = false;
        } else {
            qDebug() << "EfmProcess::run(): EFM T-values input file is" << inputFilenameTs << "and is" <<
                        efmTValuesInputFileHandle.size() << "bytes in length";
        }

        // Open temporary file for F3 Frame data
        QTemporaryFile f3FramesOutputFileHandle;
        if (!f3FramesOutputFileHandle.open()) {
            // Failed to open file
            qDebug() << "EfmProcess::run(): Could not open F3 frame temporary file";
            readyToProcess = false;
        } else {
            qDebug() << "EfmProcess::run(): Opened F3 frame temporary file";
        }

        // Open temporary file for sync'd F3 Frame data
        QTemporaryFile syncF3FramesOutputFileHandle;
        if (!syncF3FramesOutputFileHandle.open()) {
            // Failed to open file
            qDebug() << "EfmProcess::run(): Could not open sync'd F3 frame temporary file";
            readyToProcess = false;
        } else {
            qDebug() << "EfmProcess::run(): Opened sync'd F3 frame temporary file";
        }

        // Open temporary file for F2 Frame data
        QTemporaryFile f2FramesOutputFileHandle;
        if (!f2FramesOutputFileHandle.open()) {
            // Failed to open file
            qDebug() << "EfmProcess::run(): Could not open F2 frame temporary file";
            readyToProcess = false;
        } else {
            qDebug() << "EfmProcess::run(): Opened F2 frame temporary file";
        }

        // Perform the decoding process (audio specific)
        if (readyToProcess) {
            // Perform EFM T-values to F3 frames decode
            qDebug() << "EfmProcess::run(): Performing EFM T-values to F3 frames decode";
            efmTValuesInputFileHandle.seek(0);
            efmToF3Frames.startProcessing(&efmTValuesInputFileHandle, &f3FramesOutputFileHandle);

            // Synchronise F3 Frames
            qDebug() << "EfmProcess::run(): Performing synchronisation of F3 frames";
            f3FramesOutputFileHandle.seek(0);
            syncF3Frames.startProcessing(&f3FramesOutputFileHandle, &syncF3FramesOutputFileHandle);

            // Decode synchronised F3 frames into F2 frames
            qDebug() << "EfmProcess::run(): Performing decode of synchronised F3 frames into F2 frames";
            syncF3FramesOutputFileHandle.seek(0);
            f3ToF2Frames.startProcessing(&syncF3FramesOutputFileHandle, &f2FramesOutputFileHandle);

            // Decode F2 frames into audio sample data
            qDebug() << "EfmProcess::run(): Performing decode of F2 frames into audio samples";
            f2FramesOutputFileHandle.seek(0);
            f2FramesToAudio.startProcessing(&f2FramesOutputFileHandle, audioOutputFileHandleTs);

            // Output decoder statistics
            efmToF3Frames.reportStatistics();
            syncF3Frames.reportStatistics();
            f3ToF2Frames.reportStatistics();
            f2FramesToAudio.reportStatistics();

            // Check if audio is available
            if (f2FramesToAudio.getStatistics().totalSamples > 0) audioAvailable = true;
        }

        // Close all files
        efmTValuesInputFileHandle.close();
        f3FramesOutputFileHandle.close();
        syncF3FramesOutputFileHandle.close();
        f2FramesOutputFileHandle.close();

        // Processing complete

        emit processingComplete(audioAvailable, dataAvailable);

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
