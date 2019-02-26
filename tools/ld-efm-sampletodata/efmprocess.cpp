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

    // Initialise the PLL
    pll = new Pll_t(pllResult);
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

    // Main sample processing loop
    bool endOfFile = false;
    qint32 samplesProcessed = 0;
    qint32 framesProcessed = 0;
    while(!endOfFile) {
        qint32 readSamples = fillInputBuffer(inputStream, inputBuffer, bufferSize);

        // Apply the DC blocker filter
        //inputBuffer = filter.dcBlocker(inputBuffer);

        // Apply the channel equalizer filter
        inputBuffer = filter.channelEqualizer(inputBuffer);

        if (readSamples == 0) {
            endOfFile = true;
            qDebug() << "EfmProcess::process(): End of file";
        } else {
            // Perform ZC detection and feed the PLL
            performPll(inputBuffer);

            // Decode the EFM
            efmDecoder.process(pllResult);

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

    qreal totalFrames = efmDecoder.getPass() + efmDecoder.getFailed();
    qreal pass1Percent = (100.0 / totalFrames) * efmDecoder.getPass();
    qreal failedPercent = (100.0 / totalFrames) * efmDecoder.getFailed();

    qInfo() << "Decoding complete - Processed" << static_cast<qint32>(totalFrames) << "F3 frames with" <<
               efmDecoder.getPass() << "successful decodes and" <<
               efmDecoder.getFailed() << "failed decodes";
    qInfo() << pass1Percent << "% pass and" << failedPercent << "% failed.";
    qInfo() << efmDecoder.getSyncLoss() << "sync loss events";
    qInfo() << efmDecoder.getFailedEfmTranslations() << "EFM translations failed.";

    // Close the files
    closeInputSampleFile();
    closeOutputDataFile();

    // Successful
    return true;
}

// This method performs interpolated zero-crossing detection and stores the
// result a sample deltas (the number of samples between each
// zero-crossing).  Interpolation of the zero-crossing point provides a
// result with sub-sample resolution.
//
// Since the EFM data is NRZ-I (non-return to zero inverted) the polarity of the input
// signal is not important (only the frequency); therefore we can simply
// store the delta information.  The resulting delta information is fed to the
// phase-locked loop which is responsible for correcting jitter errors from the ZC
// detection process.
void EfmProcess::performPll(QVector<qint16> inputBuffer)
{
    // In order to hold state over buffer read boundaries, we keep
    // global track of the direction and delta information
    if (zcFirstRun) {
        zcFirstRun = false;

        zcPreviousInput = 0;
        prevDirection = false; // Down
        delta = 0;
    }

    for (qint32 i = 0; i < inputBuffer.size(); i++) {
        qint16 vPrev = zcPreviousInput;
        qint16 vCurr = inputBuffer[i];

        bool xup = false;
        bool xdn = false;

        // Possing zero-cross up or down?
        if (vPrev < 0 && vCurr >= 0) xup = true;
        if (vPrev > 0 && vCurr <= 0) xdn = true;

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

            // Feed the sub-sample accurate result to the PLL
            pll->pushEdge(delta + fraction);

            // Offset the next delta by the fractional part of the result
            // in order to maintain accuracy
            delta = 1.0 - fraction;
        } else {
            // No ZC, increase delta by 1 sample
            delta += 1.0;
        }

        // Keep the previous input (so we can work across buffer boundaries)
        zcPreviousInput = inputBuffer[i];
    }
}

// Method to fill the input buffer with samples
qint32 EfmProcess::fillInputBuffer(QDataStream &inputStream, QVector<qint16> &inputBuffer, qint32 samples)
{
    // Read the input sample data as 16-bit signed integers
    qint32 readSamples = 0;
    while((!inputStream.atEnd() && readSamples < samples)) {
        inputStream >> inputBuffer[readSamples];
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
