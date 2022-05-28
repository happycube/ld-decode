/************************************************************************

    efmprocess.cpp

    ld-process-efm - EFM data decoder
    Copyright (C) 2019-2022 Simon Inns

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

    debug_efmToF3Frames = false;
    debug_syncF3Frames = false;
    debug_f3ToF2Frames = false;
    debug_f2ToF1Frame = false;
    debug_f1ToAudio = false;
    debug_f1ToData = false;

    padInitialDiscTime = false;

    decodeAsAudio = true;
    decodeAsData = false;
    noTimeStamp = false;
}

EfmProcess::~EfmProcess()
{
    mutex.lock();
    abort = true;
    condition.wakeOne();
    mutex.unlock();

    wait();
}

// Set the debug output flags
void EfmProcess::setDebug(bool _debug_efmToF3Frames, bool _debug_syncF3Frames,
                          bool _debug_f3ToF2Frames, bool _debug_f2ToF1Frames,
                          bool _debug_f1ToAudio, bool _debug_f1ToData)
{
    debug_efmToF3Frames = _debug_efmToF3Frames;
    debug_syncF3Frames = _debug_syncF3Frames;
    debug_f3ToF2Frames = _debug_f3ToF2Frames;
    debug_f2ToF1Frame = _debug_f2ToF1Frames;
    debug_f1ToAudio = _debug_f1ToAudio;
    debug_f1ToData = _debug_f1ToData;
}

// Set the audio error treatment type
void EfmProcess::setAudioErrorTreatment(F1ToAudio::ErrorTreatment _errorTreatment,
                                        F1ToAudio::ConcealType _concealType)
{
    errorTreatment = _errorTreatment;
    concealType = _concealType;

    switch (errorTreatment) {
    case F1ToAudio::ErrorTreatment::conceal:
        qDebug() << "EfmProcess::setAudioErrorTreatment(): Audio error treatment set to conceal";
        break;
    case F1ToAudio::ErrorTreatment::silence:
        qDebug() << "EfmProcess::setAudioErrorTreatment(): Audio error treatment set to silence";
        break;
    case F1ToAudio::ErrorTreatment::passThrough:
        qDebug() << "EfmProcess::setAudioErrorTreatment(): Audio error treatment set to pass-through";
        break;
    }

    if (errorTreatment == F1ToAudio::ErrorTreatment::conceal) {
        switch (concealType) {
        case F1ToAudio::ConcealType::linear:
            qDebug() << "EfmProcess::setAudioErrorTreatment(): Conceal type set to linear interpolation";
            break;
        case F1ToAudio::ConcealType::prediction:
            qDebug() << "EfmProcess::setAudioErrorTreatment(): Conceal type set to interpolated error prediction (experimental)";
            break;
        }
    }
}

// Set the decoder options
void EfmProcess::setDecoderOptions(bool _padInitialDiscTime, bool _decodeAsData, bool _noTimeStamp)
{
    qDebug() << "EfmProcess::setDecoderOptions(): Pad initial disc time is" << _padInitialDiscTime;
    qDebug() << "EfmProcess::setDecoderOptions(): Decode as data is" << _decodeAsData;
    qDebug() << "EfmProcess::setDecoderOptions(): No time-stamp is" << _noTimeStamp;
    padInitialDiscTime = _padInitialDiscTime;

    if (_decodeAsData) {
        decodeAsAudio = false;
        decodeAsData = true;
    } else {
        decodeAsAudio = true;
        decodeAsData = false;
    }

    noTimeStamp = _noTimeStamp;
}

// Output the result of the decode to qInfo
void EfmProcess::reportStatistics()
{
    efmToF3Frames.reportStatistics();
    syncF3Frames.reportStatistics();
    f3ToF2Frames.reportStatistics();
    f2ToF1Frames.reportStatistics();
    f1ToAudio.reportStatistics();
    f1ToData.reportStatistics();
}

// Thread handling methods --------------------------------------------------------------------------------------------

// Start processing the input EFM file
void EfmProcess::startProcessing(QFile* _inputFileHandle, QFile* _outputFileHandle)
{
    QMutexLocker locker(&mutex);

    // Move all the parameters to be local
    efmInputFileHandle = _inputFileHandle;
    audioOutputFileHandle = _outputFileHandle; // Only one will be used
    dataOutputFileHandle = _outputFileHandle;  // Only one will be used

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
    statistics.f2ToF1Frames = f2ToF1Frames.getStatistics();
    statistics.f1ToAudio = f1ToAudio.getStatistics();
    statistics.f1ToData = f1ToData.getStatistics();

    return statistics;
}

// Method to reset decoding classes
void EfmProcess::reset()
{
    efmToF3Frames.reset();
    syncF3Frames.reset();
    f3ToF2Frames.reset();
    f2ToF1Frames.reset();
    f1ToAudio.reset();
    f1ToData.reset();
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
        efmInputFileHandleTs = this->efmInputFileHandle;
        audioOutputFileHandleTs = this->audioOutputFileHandle;
        dataOutputFileHandleTs = this->dataOutputFileHandle;
        mutex.unlock();

        qint64 initialInputFileSize = efmInputFileHandleTs->bytesAvailable();
        qint32 lastPercent = 0;
        while(efmInputFileHandle->bytesAvailable() > 0 && !abort && !cancel) {
            // Get a buffer of EFM data
            QByteArray inputEfmBuffer;
            inputEfmBuffer = readEfmData();

            // Perform processing
            QVector<F3Frame> initialF3Frames = efmToF3Frames.process(inputEfmBuffer, debug_efmToF3Frames);
            QVector<F3Frame> syncedF3Frames = syncF3Frames.process(initialF3Frames, debug_syncF3Frames);
            QVector<F2Frame> f2Frames = f3ToF2Frames.process(syncedF3Frames, debug_f3ToF2Frames, noTimeStamp);
            QVector<F1Frame> f1Frames = f2ToF1Frames.process(f2Frames, debug_f2ToF1Frame, noTimeStamp);

            if (decodeAsAudio) {
                audioOutputFileHandle->write(f1ToAudio.process(f1Frames, padInitialDiscTime, errorTreatment, concealType, debug_f1ToAudio));
            }

            if (decodeAsData) {
                dataOutputFileHandle->write(f1ToData.process(f1Frames, debug_f1ToData));
            }

            // Report progress to parent
            qreal percent = 100 - (100.0 / static_cast<qreal>(initialInputFileSize)) * static_cast<qreal>(efmInputFileHandle->bytesAvailable());
            if (static_cast<qint32>(percent) > lastPercent) {
                emit percentProcessed(static_cast<qint32>(percent));
            }
            lastPercent = static_cast<qint32>(percent);
        }

        // Check if audio is available
        if (f1ToAudio.getStatistics().totalSamples > 0) audioAvailable = true;
        if (f1ToData.getStatistics().totalSectors > 0) dataAvailable = true;

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

// Method to read EFM T value data from the input file
QByteArray EfmProcess::readEfmData(void)
{
    // Read EFM data in 256K blocks
    qint32 bufferSize = 1024 * 256;

    QByteArray outputData;
    outputData.resize(bufferSize);

    qint64 bytesRead = efmInputFileHandleTs->read(outputData.data(), outputData.size());
    if (bytesRead != bufferSize) outputData.resize(static_cast<qint32>(bytesRead));

    return outputData;
}
