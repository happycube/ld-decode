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
    do {
        // Read the T value EFM data
        efmData = readEfmData(10240 * 4); // 40Kbytes

        if (efmData.size() > 0) {
            // Frame the EFM data into F3 frames
            f3Framer.process(efmData, frameDebug);

            qint32 availableFrames = f3Framer.f3FramesReady();
            if (availableFrames > 0) {
                // F3 frames are ready for processing...
                QByteArray f3Frames = f3Framer.getF3Frames();

                // Process the available frames
                for (qint32 i = 0; i < availableFrames; i++) {
                    QByteArray f3Frame = f3Frames.mid(i * 34, 34);

                    // Decode the subcode channels
                    decodeSubcode.process(f3Frame);

                    // Decode the audio data
                    decodeAudio.process(f3Frame);

                    // Get any available audio data
                    QByteArray audioData = decodeAudio.getOutputData();
                    if (!audioData.isEmpty()) {
                        // Save the audio data as little-endian stereo LLRRLLRR etc
                        for (qint32 byteC = 0; byteC < 24; byteC += 4) {
                            // 1 0 3 2
                            outStream << static_cast<uchar>(audioData[byteC + 1])
                             << static_cast<uchar>(audioData[byteC + 0])
                             << static_cast<uchar>(audioData[byteC + 3])
                             << static_cast<uchar>(audioData[byteC + 2]);
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
    qInfo() << "F3 Framing results:" << pass1Percent << "% correct frame lengths and" << failedPercent << "% incorrect.";
    qInfo() << "F3 Framing results:" << f3Framer.getSyncLoss() << "sync loss events";
    qInfo() << "F3 Framing results:" << f3Framer.getFailedEfmTranslations() << "EFM 14 to 8-bit translation failures.";

    // Display the results from the audio decoding process
    qInfo() << "";
    qInfo() << "Audio decode results: Total processed C1s:" << decodeAudio.getValidC1Count() + decodeAudio.getInvalidC1Count() <<
               "(with" << decodeAudio.getInvalidC1Count() << "CIRC failures)";
    qInfo() << "Audio decode results: Total processed C2s:" << decodeAudio.getValidC2Count() + decodeAudio.getInvalidC2Count() <<
               "(with" << decodeAudio.getInvalidC2Count() << "CIRC failures)";
    qInfo() << "Audio decode results: Total audio samples:" << decodeAudio.getValidAudioSamplesCount() + decodeAudio.getInvalidAudioSamplesCount() <<
               "(with" << decodeAudio.getInvalidAudioSamplesCount() << "unrecoverable samples)";

    qInfo() << "";
    qInfo() << "Processing complete";

    // Close the input file
    closeInputFile();

    return true;
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
