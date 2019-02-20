/************************************************************************

    efmprocess.cpp

    ld-efm-sampletodata - EFM sample to data processor for ld-decode
    Copyright (C) 2019 Simon Inns

    This file is part of ld-decode-tools.

    ld-efm-sampletodata is free software: you can redistribute it and/or
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
    // Default ZC detector state
    zcFirstRun = true;
    zcPreviousInput = 0;
}

bool EfmProcess::process(QString inputFilename, QString outputFilename)
{
    Filter filter;
    EfmDecoder efmDecoder;

    // Open the input EFM sample file
    if (!openInputSampleFile(inputFilename)) {
        qCritical() << "Could not open sampled EFM input file!";
        return false;
    }

    // Open the output data file
    if (!openOutputDataFile(outputFilename)) {
        qCritical() << "Could not open data output file!";
        return false;
    }

    // Create a data stream for both input and output
    QDataStream inputStream(inputFile);
    inputStream.setByteOrder(QDataStream::LittleEndian);

    // Define the buffer size for input reads
    qint32 bufferSize = 1024 * 1024;
    QVector<qint16> inputBuffer;
    inputBuffer.resize(bufferSize);
    QVector<qint16> zeroBuffer;
    zeroBuffer.resize(bufferSize);

    // Vector to store the resulting zero-cross detected transition deltas
    QVector<qreal> zcDeltas;

    // Fill the filter with samples (to align input data with filter output), if there is a filter delay
    if (filter.getLpFilterDelay() > 0) {
        qint32 readSamples = fillInputBuffer(inputStream, inputBuffer, filter.getLpFilterDelay());
        if (readSamples < filter.getLpFilterDelay()) {
            qDebug() << "Input sample file too small to process!";
            return false;
        }
        // Apply the channel equalizer filter
        inputBuffer = filter.channelEqualizer(inputBuffer);

        // Apply the low-pass filter to get the zero values for the input sample
        zeroBuffer = filter.lpFilter(inputBuffer);
    }

    // Main sample processing loop
    bool endOfFile = false;
    qint32 samplesProcessed = 0;
    qint32 framesProcessed = 0;
    while(!endOfFile) {
        qint32 readSamples = fillInputBuffer(inputStream, inputBuffer, bufferSize);

        // Apply the channel equalizer filter
        inputBuffer = filter.channelEqualizer(inputBuffer);

        if (readSamples == 0) {
            endOfFile = true;
            qDebug() << "EfmProcess::process(): End of file";
        } else {
            // Apply the low-pass filter to get the zero values for the input sample
            zeroBuffer = filter.lpFilter(inputBuffer);

            // Perform ZC detection
            zeroCrossDetection(inputBuffer, zeroBuffer, zcDeltas);
            qDebug() << "Number of buffered deltas =" << zcDeltas.size();

            // Decode the EFM
            efmDecoder.process(zcDeltas);

            // F3 Frame ready for writing?
            if (efmDecoder.f3FramesReady() > 0) {
                framesProcessed += efmDecoder.f3FramesReady();

                // Write the F3 frames to the output file
                QByteArray framesToWrite = efmDecoder.getF3Frames();
                outputFile->write(framesToWrite, framesToWrite.size());
            }

            samplesProcessed += readSamples;
            qInfo() << "Processed" << samplesProcessed << "samples into" << framesProcessed << "F3 frames";
        }
    }

    qreal totalFrames = efmDecoder.getPass1() + efmDecoder.getPass2() + efmDecoder.getFailed();
    qreal pass1Percent = (100.0 / totalFrames) * efmDecoder.getPass1();
    qreal pass2Percent = (100.0 / totalFrames) * efmDecoder.getPass2();
    qreal failedPercent = (100.0 / totalFrames) * efmDecoder.getFailed();

    qInfo() << "Decoding complete - Processed" << static_cast<qint32>(totalFrames) << "F3 frames with" <<
               efmDecoder.getPass1() << "pass 1 decodes and" << efmDecoder.getPass2() << "pass 2 decodes and" <<
               efmDecoder.getFailed() << "failed decodes";
    qInfo() << pass1Percent << "% pass 1," << pass2Percent << "% pass 2 and" << failedPercent << "% failed.";
    qInfo() << efmDecoder.getFailedEfmTranslations() << "EFM translations failed.";

    // Close the files
    closeInputSampleFile();
    closeOutputDataFile();

    // Successful
    return true;
}

// This method performs interpolated zero-crossing detection and stores the
// result as an array of sample deltas (the number of samples between each
// zero-crossing).  Interpolation of the zero-crossing point provides a
// result with sub-sample resolution.
//
// Since the EFM data is NRZI (non-return to zero inverted) the polarity of the input
// signal is not important (only the frequency); therefore we can simply
// store the delta information.  Storing the information as deltas allows
// us to maintain sample data resolution without the need to interpolate to
// achieve a higher sample rate (so this method is both accurate and
// extremely processor and memory efficient)
void EfmProcess::zeroCrossDetection(QVector<qint16> inputBuffer, QVector<qint16> zeroBuffer, QVector<qreal> &zcDeltas)
{
    if (zcFirstRun) {
        zcPreviousInput = 0;
        zcFirstRun = false;
        prevDirection = false; // Down
    }

    qreal distance = 0;
    for (qint32 i = 0; i < inputBuffer.size(); i++) {
        qint16 vPrev = zcPreviousInput;
        qint16 vCurr = inputBuffer[i];
        //qint16 vNext = inputBuffer[i+1];

        bool xup = false;
        bool xdn = false;

        // Possing zero-cross up or down?
        if (vPrev < zeroBuffer[i] && vCurr >= zeroBuffer[i]) xup = true;
        if (vPrev > zeroBuffer[i] && vCurr <= zeroBuffer[i]) xdn = true;

        // Check ZC direction against previous
        if (prevDirection && xup) xup = false;
        if (!prevDirection && xdn) xdn = false;

        // Store the current direction as the previous
        if (xup) prevDirection = true;
        if (xdn) prevDirection = false;

        if (xup || xdn) {
            // Interpolate to get the ZC sub-sample position fraction
            qreal prev = static_cast<qreal>(vPrev);
            qreal curr = static_cast<qreal>(vCurr);
            qreal fraction = (-prev) / (curr - prev);

            zcDeltas.append(distance + fraction);
            distance = 1.0 - fraction;
        } else {
            // No ZC, increase delta by 1 sample
            distance += 1.0;
        }

        // Keep the previous input (so we can work across buffer boundaries)
        zcPreviousInput = inputBuffer[i];
    }
}

// Method to fill the input buffer with samples
qint32 EfmProcess::fillInputBuffer(QDataStream &inputStream, QVector<qint16> &inputBuffer, qint32 samples)
{
    // Read the input sample data
    qint32 readSamples = 0;
    qint16 x = 0;
    while((!inputStream.atEnd() && readSamples < samples)) {
        inputStream >> x;
        inputBuffer[readSamples] = x;
        readSamples++;
    }

    return readSamples;
}

// Method to open the input EFM sample for reading
bool EfmProcess::openInputSampleFile(QString filename)
{
    // Open the input file
    inputFile = new QFile(filename);
    if (!inputFile->open(QIODevice::ReadOnly)) {
        // Failed to open input file
        qDebug() << "EfmProcess::openInputSampleFile(): Could not open " << filename << "as sampled EFM input file";
        return false;
    }

    return true;
}

// Method to close the EFM input sample file
void EfmProcess::closeInputSampleFile(void)
{
    // Close the input file
    inputFile->close();
}

// Method to open the output data file for writing
bool EfmProcess::openOutputDataFile(QString filename)
{
    // Open the output file
    outputFile = new QFile(filename);
    if (!outputFile->open(QIODevice::WriteOnly)) {
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
    outputFile->close();
}
