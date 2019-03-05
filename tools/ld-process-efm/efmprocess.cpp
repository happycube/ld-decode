/************************************************************************

    efmprocess.cpp

    ld-process-efm - EFM data decoder
    Copyright (C) 2019 Simon Inns

    This file is part of ld-decode-tools.

    ld-ldstoefm is free software: you can redistribute it and/or
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

EfmProcess::EfmProcess()
{

}

// The general process is as follows:
//
// 1. Convert the incoming 14-bit EFM data into 8-bit F3 frames
// 2. Convert the F3 frames into subcode blocks
// 3. Decode the subcode Q-channel (to determine the nature of the block's payload)
// 4. Decode the block as audio or data based on the Q-channel block type
// 5. Output the data or audio to file
// 6. Rinse and repeat

bool EfmProcess::process(QString inputFilename, QString outputFilename, bool frameDebug)
{
    // Open the input file
    if (!openInputFile(inputFilename)) {
        qCritical("Could not open input file!");
        return false;
    }

    // Open the output data file
    if (!openOutputDataFile(outputFilename)) {
        qCritical() << "Could not open data output file!";
        return false;
    }
    QDataStream outStream(outputFileHandle);
    outStream.setByteOrder(QDataStream::LittleEndian);

    QByteArray efmData;
    DecodeSubcode::QDecodeResult previousResult = DecodeSubcode::QDecodeResult::invalid;
    do {
        // Read the T value EFM data
        efmData = readEfmData(10240 * 4); // 40Kbytes

        if (efmData.size() > 0) {
            // Frame the EFM data into F3 frames
            f3Framer.process(efmData, frameDebug);

            qint32 availableFrames = f3Framer.f3FramesReady();
            if (availableFrames > 0) {
                // F3 frames are ready for processing...
                QByteArray f3FrameBuffer;
                QByteArray f3ErasureBuffer;
                f3Framer.getF3Frames(f3FrameBuffer, f3ErasureBuffer);

                // Process the available frames
                for (qint32 i = 0; i < availableFrames; i++) {
                    // Get a frame of data
                    QByteArray f3Frame = f3FrameBuffer.mid(i * 34, 34);
                    QByteArray f3Erasures = f3ErasureBuffer.mid(i * 34, 34);

                    // Process the F3 frames into subcode blocks
                    subcodeBlock.process(f3Frame, f3Erasures);

                    // Is a subcode block ready?
                    if (subcodeBlock.blockReady()) {
                        SubcodeBlock::Block block = subcodeBlock.getBlock();

                        // Decode the subcode data
                        DecodeSubcode::QDecodeResult qResult = decodeSubcode.decodeBlock(block.subcode);

                        // Check for failure
                        if (qResult == DecodeSubcode::QDecodeResult::invalid) {
                            // Q channel decode failed... we need to decide if we treat the block as
                            // valid data/audio, or if we drop the block

                            // Was the block sync valid?
                            if (block.sync0 || block.sync1) {
                                // If there was a sync, we probably have valid EFM
                                qDebug() << "EfmProcess::process(): Q Channel was invalid, but sync was good.  Using previous result";
                                qResult = previousResult;
                            } else {
                                // Force loss of block decoding sync
                                qDebug() << "EfmProcess::process(): Q Channel was invalid and sync was missing. Forcing loss of block sync (invalid EFM?)";
                                subcodeBlock.forceSyncLoss();
                            }
                        } else {
                            previousResult = qResult;
                        }

                        // QMode 4 (video audio)?
                        if (qResult == DecodeSubcode::QDecodeResult::qMode4) {
                            // Decode
                            qint32 c1Failures = decodeAudio.decodeBlock(block.data, block.erasures);
                            if (c1Failures > (98 / 2)) {
                                qDebug() << "EfmProcess::process(): Too many C1 failures from block - Input EFM was garbage (" << c1Failures << "C1 errors caused ) - Forcing loss of block sync (invalid EFM)?";
                                subcodeBlock.forceSyncLoss();
                            }

                            // Save any available sample data
                            saveAudioData(outStream);
                        }
                    }
                }
            }
        }
    } while (efmData.size() > 0);

    // Display the results from the F3 framing process
    qreal totalFrames = f3Framer.getPass() + f3Framer.getFailed();
    qreal pass1Percent = (100.0 / totalFrames) * f3Framer.getPass();
    qreal failedPercent = (100.0 / totalFrames) * f3Framer.getFailed();
    qInfo() << "F3 Framing results: Processed" << static_cast<qint32>(totalFrames) << "F3 frames with" <<
               f3Framer.getPass() << "successful decodes and" <<
               f3Framer.getFailed() << "decodes with invalid frame length";
    qInfo() << "                   " << pass1Percent << "% correct frame lengths and" << failedPercent << "% incorrect.";
    qInfo() << "                   " << f3Framer.getSyncLoss() << "sync loss events";
    qInfo() << "                   " << f3Framer.getFailedEfmTranslations() << "EFM 14 to 8-bit translation failures.";

    // Display the results from the subcode block process
    qInfo() << "";
    qInfo() << "Subcode block results:" << subcodeBlock.getTotalBlocks() << "blocks processed";
    qInfo() << "                      " << subcodeBlock.getPoorSyncs() << "blocks missing SYNC0 and/or SYNC1";
    qInfo() << "                      " << subcodeBlock.getSyncLosses() << "sync loss events";

    // Display the results from the audio decoding process
    qInfo() << "";
    qInfo() << "Audio decode results: Total processed C1s:" << decodeAudio.getValidC1Count() + decodeAudio.getInvalidC1Count() <<
               "(with" << decodeAudio.getInvalidC1Count() << "CIRC failures)";
    qInfo() << "                      Total processed C2s:" << decodeAudio.getValidC2Count() + decodeAudio.getInvalidC2Count() <<
               "(with" << decodeAudio.getInvalidC2Count() << "CIRC failures)";
    qInfo() << "                      Total audio samples:" << decodeAudio.getValidAudioSamplesCount() + decodeAudio.getInvalidAudioSamplesCount() <<
               "(with" << decodeAudio.getInvalidAudioSamplesCount() << "unrecoverable samples)";

    qInfo() << "";
    qInfo() << "Processing complete";

    // Close the input file
    closeInputFile();

    return true;
}

// Method to save any available audio data to file
void EfmProcess::saveAudioData(QDataStream &outStream)
{
    // Get any available audio sample data
    QByteArray audioData = decodeAudio.getOutputData();

    // This test should never fail... but, hey, software...
    if ((audioData.size() % 4) != 0) {
        qCritical() << "EfmProcess::saveAudioData(): Audio data has an invalid length and will not save correctly.";
        exit(1);
    }

    if (!audioData.isEmpty()) {
        // Save the audio data as little-endian stereo LLRRLLRR etc
        for (qint32 byteC = 0; byteC < audioData.size(); byteC += 4) {
            // 1 0 3 2
            outStream << static_cast<uchar>(audioData[byteC + 1])
             << static_cast<uchar>(audioData[byteC + 0])
             << static_cast<uchar>(audioData[byteC + 3])
             << static_cast<uchar>(audioData[byteC + 2]);
        }
    }
}

// Method to open the input file for reading
bool EfmProcess::openInputFile(QString inputFileName)
{
    // Open input file for reading
    inputFileHandle = new QFile(inputFileName);
    if (!inputFileHandle->open(QIODevice::ReadOnly)) {
        // Failed to open source sample file
        qDebug() << "Could not open " << inputFileName << "as input file";
        return false;
    }
    qDebug() << "LdsProcess::openInputFile(): 10-bit input file is" << inputFileName << "and is" <<
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
QByteArray EfmProcess::readEfmData(qint32 bufferSize)
{
    QByteArray outputData;
    outputData.resize(bufferSize);

    qint64 bytesRead = inputFileHandle->read(outputData.data(), outputData.size());
    if (bytesRead != bufferSize) outputData.resize(static_cast<qint32>(bytesRead));

    return outputData;
}

// Method to open the output data file for writing
bool EfmProcess::openOutputDataFile(QString filename)
{
    // Open the output file
    outputFileHandle = new QFile(filename);
    if (!outputFileHandle->open(QIODevice::WriteOnly)) {
        // Failed to open output file
        qDebug() << "EfmProcess::openOutputDataFile(): Could not open " << filename << "as output data file";
        return false;
    }

    return true;
}

// Method to close the output data file
void EfmProcess::closeOutputDataFile(void)
{
    // Close the output file
    outputFileHandle->close();
}
