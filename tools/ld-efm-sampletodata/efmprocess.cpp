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

}

bool EfmProcess::process(QString inputFilename, QString outputFilename, qint32 maxF3Param, bool verboseDecodeParam)
{
    // Store the configuration parameters
    maxF3 = maxF3Param;
    verboseDecode = verboseDecodeParam;

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

    // Perform the actual processing
    processStateMachine();

    // Show the result
    qreal good = static_cast<qreal>(efmDecoder.getGoodDecodes());
    qreal bad = static_cast<qreal>(efmDecoder.getBadDecodes());
    qreal percent = (100.0 / (good + bad) * good);

    qInfo() << "Processed" << frameCounter << "F3 frames";
    qInfo() << "Total EFM words processed was" << efmDecoder.getGoodDecodes() + efmDecoder.getBadDecodes() << "with" <<
               efmDecoder.getGoodDecodes() << "good decodes and" << efmDecoder.getBadDecodes() << "bad decodes (success rate of" << percent << "%)";

    // Close the files
    closeInputSampleFile();
    closeOutputDataFile();

    return true;
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
QVector<qreal> EfmProcess::zeroCrossDetection(QVector<qint16> inputBuffer, QVector<qreal> &zcDeltas, qint32 &usedSamples)
{
    usedSamples = 0;

    qreal distance = 0;
    for (qint32 i = 1; i < inputBuffer.size(); i++) {
        // Is the preceeding sample below zero and the following above?
        if ((inputBuffer[i-1] < 0 && inputBuffer[i] >= 0) || (inputBuffer[i-1] > 0 && inputBuffer[i] <= 0)) {
            // Zero-cross detected

            // Interpolate to get the ZC sub-sample position fraction
            qreal previous = static_cast<qreal>(inputBuffer[i-1]);
            qreal current = static_cast<qreal>(inputBuffer[i]);
            qreal fraction = (-previous) / (current - previous);

            zcDeltas.append(distance + fraction);
            distance = 1.0 - fraction;
            usedSamples = i;
        } else {
            // No zero-cross detected
            distance += 1.0;
        }
    }

    return zcDeltas;
}

bool EfmProcess::fillWindowedBuffer(void)
{
    // Create a data stream from the input file
    QDataStream inputStream(inputFile);
    inputStream.setByteOrder(QDataStream::LittleEndian);

    // Read the input sample data
    inputBuffer.clear();
    qint32 readSamples = inputBuffer.size();
    qint16 x = 0;
    while((!inputStream.atEnd()) && (readSamples < ((1024 * 1024) / 2))) {
        inputStream >> x;
        inputBuffer.append(x);
        readSamples++;
    }

    // Did we get any input sample data?
    if (readSamples > 0) {
        // Apply the ISI correction filter to the input sample buffer
        inputBuffer = filter.channelEqualizer(inputBuffer);

        // Apply the DC offset correction filter to the input sample buffer
        inputBuffer = filter.dcBlocking(inputBuffer);

        // Append the filtered input data to the windowed buffer
        for (qint32 count = 0; count < inputBuffer.size(); count++) windowedBuffer.append(inputBuffer[count]);

        // Zero cross detect the sample data and convert to ZC sample deltas
        qint32 usedSamples = 0;
        zeroCrossDetection(windowedBuffer, zcDeltas, usedSamples);

        // Remove the used samples from the filtered input buffer
        if (usedSamples == windowedBuffer.size()) {
            windowedBuffer.clear();
        } else {
            // Since there are usually a lot of samples to remove, it's faster to do this
            // by copying rather than using the .removefirst QVector method...
            QVector<qint16> temp = windowedBuffer;
            windowedBuffer.clear();
            windowedBuffer.resize(temp.size() - usedSamples);
            qint32 pointer = 0;
            for (qint32 count = usedSamples; count < temp.size(); count++) {
                windowedBuffer[pointer] = temp[count];
                pointer++;
            }
        }

        return true;
    }

    return false;
}

// This method is based on US patent 6,118,393 which states that the T average
// within a frame is 5; therefore by dividing the frequency by 117 (588/5)
// you get the average length of an EFM frame based on the (unknown) clock
// speed of the EFM data
qreal EfmProcess::estimateInitialFrameWidth(QVector<qreal> zcDeltas)
{
    qreal approximateFrameWidth = 0;

    qint32 deltaPos = 0;
    while (deltaPos < 117) {
        approximateFrameWidth += zcDeltas[deltaPos];
        deltaPos++;
    }

    return approximateFrameWidth;
}

// This method finds the next sync transition.  Since the sync pulse is two T11 intervals
// we can find it by summing pairs of transition deltas and looking for the longest combined
// delta.  Using an estimation of the frame length means we shouldn't see two sync patterns
// in the same data set.
qint32 EfmProcess::findSyncTransition(qreal approximateFrameWidth)
{
    qreal totalTime = 0;
    qreal longestInterval = 0;
    qint32 syncPosition = -1;
    qint32 deltaPos = 0;

    while (totalTime < approximateFrameWidth) {
        qreal interval = zcDeltas[deltaPos] + zcDeltas[deltaPos + 1];

        // Ignore the first 2 delta positions (so we don't trigger on the start
        // of frame sync pattern)
        if (interval > longestInterval && deltaPos > 1) {
            longestInterval = interval;
            syncPosition = deltaPos;
        }

        totalTime += zcDeltas[deltaPos];
        deltaPos++;

        if (deltaPos == (zcDeltas.size() - 1)) {
            // Not enough data - give up
            syncPosition = -1;
            qDebug() << "EfmDecoder::findSyncTransition(): Available data is too short; need more data to process";
            break;
        }
    }

    return syncPosition;
}

// Method to remove deltas from the start of the buffer
void EfmProcess::removeZcDeltas(qint32 number)
{
    if (number > zcDeltas.size()) {
        zcDeltas.clear();
    } else {
        for (qint32 count = 0; count < number; count++) zcDeltas.removeFirst();
    }
}


void EfmProcess::processStateMachine(void)
{
    // Initialise the state machine
    currentState = state_initial;
    nextState = currentState;
    frameCounter = 0;

    while (currentState != state_complete) {
        currentState = nextState;

        switch (currentState) {
        case state_initial:
            nextState = sm_state_initial();
            break;
        case state_getDataFirstSync:
            nextState = sm_state_getDataFirstSync();
            break;
        case state_getDataSecondSync:
            nextState = sm_state_getDataSecondSync();
            break;
        case state_findFirstSync:
            nextState = sm_state_findFirstSync();
            break;
        case state_findSecondSync:
            nextState = sm_state_findSecondSync();
            break;
        case state_processFrame:
            nextState = sm_state_processFrame();
            break;
        case state_complete:
            nextState = sm_state_complete();
            break;
        }
    }
}

EfmProcess::StateMachine EfmProcess::sm_state_initial(void)
{
    //qDebug() << "Current state: state_initial";

    return state_getDataFirstSync;
}

EfmProcess::StateMachine EfmProcess::sm_state_getDataFirstSync(void)
{
    qDebug() << "Current state: state_getDataFirstSync";

    if (fillWindowedBuffer()) return state_findFirstSync;

    // No more data
    qDebug() << "EfmProcess::sm_state_getDataFirstSync(): No more data available from input sample";
    return state_complete;
}

EfmProcess::StateMachine EfmProcess::sm_state_getDataSecondSync(void)
{
    qDebug() << "Current state: state_getDataSecondSync";

    if (fillWindowedBuffer()) return state_findSecondSync;

    // No more data
    qDebug() << "EfmProcess::sm_state_getDataSecondSync(): No more data available from input sample";
    return state_complete;
}

EfmProcess::StateMachine EfmProcess::sm_state_findFirstSync(void)
{
    qDebug() << "Current state: state_findFirstSync";

    minimumFrameWidthInSamples = estimateInitialFrameWidth(zcDeltas);
    lastFrameWidth = estimateInitialFrameWidth(zcDeltas);
    qint32 startSyncTransition = findSyncTransition(lastFrameWidth * 1.5);

    if (startSyncTransition == -1) {
        qDebug() << "EfmDecoder::sm_state_findFirstSync(): No initial sync found!";

        // Discard the transitions already tested and try again
        removeZcDeltas(265); // 117 * 1.5

        // Try again
        if (zcDeltas.size() < 250) return state_getDataFirstSync;
        return state_findFirstSync;
    }

    qDebug() << "EfmDecoder::sm_state_findFirstSync(): Initial sync found at transition" << startSyncTransition;

    // Discard all transitions up to the sync start (so the first delta in
    // zcDeltaTime is the start of the frame)
    removeZcDeltas(startSyncTransition);

    return state_findSecondSync;
}

EfmProcess::StateMachine EfmProcess::sm_state_findSecondSync(void)
{
    //qDebug() << "Current state: state_findSecondSync";

    endSyncTransition = findSyncTransition(lastFrameWidth * 1.5);

    if (endSyncTransition == -1) {
        // Did we fail due to lack of data?
        if (zcDeltas.size() < 250) return state_getDataSecondSync;

        qDebug() << "EfmDecoder::sm_state_findSecondSync(): Could not find second sync!";
        return state_findFirstSync;
    }

    //qDebug() << "EfmDecoder::sm_state_findSecondSync(): End of packet found at transition" << endSyncTransition;

    // Calculate the length of the frame in samples
    qreal endDelta = 0;
    for (qint32 deltaPos = 0; deltaPos < endSyncTransition; deltaPos++) {
        endDelta += zcDeltas[deltaPos];
    }

    // Store the previous frame width
    lastFrameWidth = endDelta;

    // Recover from a false positive frame sync pattern
    if (lastFrameWidth < minimumFrameWidthInSamples) {
        lastFrameWidth = minimumFrameWidthInSamples;
        qDebug() << "EfmDecoder::sm_state_findSecondSync(): Frame width is below the minimum expected length!";
    }

    return state_processFrame;
}

EfmProcess::StateMachine EfmProcess::sm_state_processFrame(void)
{
    //qDebug() << "Current state: state_processFrame";



    // Calculate the samples per bit based on the frame's sync to sync length
    qreal frameSampleLength = 0;
    for (qint32 delta = 0; delta < endSyncTransition; delta++) {
        frameSampleLength += zcDeltas[delta];
    }
    qreal samplesPerBit = frameSampleLength / 588.0;

    // Quantize the delta's based on the expected T1 clock and store the
    // T values for the F3 frame

    QVector<qint32> frameT;
    qint32 tTotal = 0;

    for (qint32 delta = 0; delta < endSyncTransition; delta++) {
        qreal tValue = zcDeltas[delta] / samplesPerBit;

        // T11 Sync RL push
        if ((delta < 2) && (tValue < 11.0)) tValue = 11.0;

        // T2 RL push
        if (tValue < 3.0) tValue = 3.0;

        // T12 RL push
        if (tValue > 11.0) tValue = 11.0;

        // Calculate distance to nearest T bit clock
        qreal newDelta = qRound(tValue) * samplesPerBit;
        qreal sampError = (newDelta) - (zcDeltas[delta]);

        if (verboseDecode) qDebug() << "Delta #" << delta << "tValue =" << tValue << "zcDelta[] =" << zcDeltas[delta] << "new delta =" << newDelta << "sampError =" << sampError;

        // Update the delta values
        zcDeltas[delta] = newDelta;
        if (delta < endSyncTransition) zcDeltas[delta+1] -= sampError;

        // Now store the resulting T value
        qreal tCorrectedValue = zcDeltas[delta] / samplesPerBit;
        tTotal += tCorrectedValue;
        frameT.append(static_cast<qint32>(tCorrectedValue));

        // Output verbose decoding debug?
        if (verboseDecode) qDebug() << "EfmProcess::sm_state_processFrame(): Delta #" << delta << "T =" << tCorrectedValue;
    }

    // Note: The 40.0 in the following is a sample rate of 40MSPS
    qInfo() << "F3 frame #" << frameCounter << "with a sample length of" << frameSampleLength << "(" << 40.0 / samplesPerBit << "MHz ) - T total was" << tTotal;

    frameCounter++;

    // Apply a processing frame limit
    if (maxF3 != -1) {
        if (frameCounter >= maxF3) {
            qDebug() << "EfmProcess::sm_state_processFrame(): Hit maximum number of frames requested by --maxf3";
            return state_complete;
        }
    }

    // Decode the T values into a bit-stream
    QByteArray outputData = efmDecoder.convertTvaluesToData(frameT);

    // Write the bit-stream to the output data file
    outputFile->write(outputData);

    // Discard all transitions up to the sync end
    removeZcDeltas(endSyncTransition);

    return state_findSecondSync;
}

EfmProcess::StateMachine EfmProcess::sm_state_complete(void)
{
    qDebug() << "Current state: state_complete";
    return state_complete;
}
