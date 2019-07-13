/************************************************************************

    audiosampleframestopcm.cpp

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

#include "audiosampleframestopcm.h"

AudioSampleFramesToPcm::AudioSampleFramesToPcm()
{
    debugOn = false;
    reset();
}

// Public methods -----------------------------------------------------------------------------------------------------

// Reset the object
void AudioSampleFramesToPcm::reset()
{
    audioSampleFrameBuffer.clear();
    pcmOutputBuffer.clear();
    waitingForData = false;
    currentState = state_initial;
    nextState = currentState;
}

// Method to feed the audio processing state-machine with audio sample frames
QByteArray AudioSampleFramesToPcm::process(QVector<AudioSampleFrame> audioSampleFrames, ErrorTreatment _errorTreatment,
                                           ConcealType _concealType, bool debugState)
{
    debugOn = debugState;
    errorTreatment = _errorTreatment;
    concealType = _concealType;

    // Clear the output buffer
    pcmOutputBuffer.clear();

    if (audioSampleFrames.isEmpty()) return pcmOutputBuffer;

    // Append input data to the processing buffer
    audioSampleFrameBuffer.append(audioSampleFrames);

    waitingForData = false;
    while (!waitingForData) {
        currentState = nextState;

        switch (currentState) {
        case state_initial:
            nextState = sm_state_initial();
            break;
        case state_processFrame:
            nextState = sm_state_processFrame();
            break;
        case state_findEndOfError:
            nextState = sm_state_findEndOfError();
            break;
        }
    }

    return pcmOutputBuffer;
}

// State-machine methods ----------------------------------------------------------------------------------------------

AudioSampleFramesToPcm::StateMachine AudioSampleFramesToPcm::sm_state_initial()
{
    if (debugOn) qDebug() << "AudioSampleFramesToPcm::sm_state_initial(): Called";
    return state_processFrame;
}

// Process the waiting audio frames into PCM data
AudioSampleFramesToPcm::StateMachine AudioSampleFramesToPcm::sm_state_processFrame()
{
    // If error treatment is silence or pass-though, use a fast, simple method
    if (errorTreatment == ErrorTreatment::silence || errorTreatment == ErrorTreatment::passThrough) {
        for (qint32 i = 0; i < audioSampleFrameBuffer.size(); i++) {
            // If error correction is silence, set corrupt samples to silence
            if (audioSampleFrameBuffer[i].getMetadata().sampleType == AudioSampleFrame::SampleType::corrupt) {
                if (errorTreatment == ErrorTreatment::silence) audioSampleFrameBuffer[i].setSampleToSilence();
            }

            // Append the audio sample's frame data to the output buffer
            pcmOutputBuffer.append(QByteArray(reinterpret_cast<char*>(audioSampleFrameBuffer[i].getSampleFrame()), 24));
        }

        // Remove the consumed audio frames from the buffer
        audioSampleFrameBuffer.clear();

        waitingForData = true;
        return state_processFrame;
    }

    // Error treatment is conceal
    qint32 bufferPosition = 0;
    while (bufferPosition < audioSampleFrameBuffer.size()) {
        if (audioSampleFrameBuffer[bufferPosition].getMetadata().sampleType != AudioSampleFrame::SampleType::corrupt) {
            // Append the audio sample's frame data to the output buffer
            pcmOutputBuffer.append(QByteArray(reinterpret_cast<char*>(audioSampleFrameBuffer[bufferPosition].getSampleFrame()), 24));

            // Store the frame as the last good frame seen (as the last known good
            // might be in the previously consumed buffer with the start error at the
            // start of the new buffer)
            lastGoodFrame = audioSampleFrameBuffer[bufferPosition];
        } else {
            // Corrupt frame detected
            errorStartPosition = bufferPosition;
            return state_findEndOfError;
        }
        bufferPosition++;
    }

    // We only get here if there is no more data in the input buffer.
    // Remove the consumed audio frames from the buffer and request more
    audioSampleFrameBuffer.clear();
    waitingForData = true;
    return state_processFrame;
}

// Find the end of an error run
AudioSampleFramesToPcm::StateMachine AudioSampleFramesToPcm::sm_state_findEndOfError()
{
    qint32 bufferPosition = errorStartPosition;
    errorStopPosition = -1;
    while (bufferPosition < audioSampleFrameBuffer.size() && errorStopPosition == -1) {
        if (audioSampleFrameBuffer[bufferPosition].getMetadata().sampleType != AudioSampleFrame::SampleType::corrupt) {
            errorStopPosition = bufferPosition - 1; // Last corrupt frame
        }
        bufferPosition++;
    }

    // If we didn't find the end of the error in the buffer, we need to
    // request more data and then try again
    if (errorStopPosition == -1) {
        if (debugOn) qDebug() << "AudioSampleFramesToPcm::sm_state_findEndOfError(): End of the error run not in buffer - requesting more data";
        waitingForData = true;
        return state_findEndOfError;
    }

    // Report the location of the error to debug
    if (debugOn) qDebug() << "AudioSampleFramesToPcm::sm_state_findEndOfError():" <<
                             "Found error run from section" << audioSampleFrameBuffer[errorStartPosition].getMetadata().discTime.getTimeAsQString() <<
                             "to section" << audioSampleFrameBuffer[errorStopPosition].getMetadata().discTime.getTimeAsQString() <<
                             "which is" << errorStopPosition - errorStartPosition + 1 << "frame(s) long." <<
                             "Buffer start" << errorStartPosition << "to end" << errorStopPosition;

    // Mark the next good frame
    nextGoodFrame = audioSampleFrameBuffer[errorStopPosition + 1];

    // Perform concealment
    switch (concealType) {
    case ConcealType::linear:
        linearInterpolationConceal();
        break;
    case ConcealType::prediction:
        predictiveInterpolationConceal();
        break;
    }

    // Write the frames to the output buffer
    for (qint32 i = errorStartPosition; i <= errorStopPosition; i++) {
        pcmOutputBuffer.append(QByteArray(reinterpret_cast<char*>(audioSampleFrameBuffer[i].getSampleFrame()), 24));
    }

    // Remove the contents of the input buffer (up to the error start)
    audioSampleFrameBuffer.remove(0, errorStopPosition + 1);

    // Make sure the buffer isn't completely empty
    if (audioSampleFrameBuffer.size() == 0) waitingForData = true;
    return state_processFrame;
}

// Conceal audio error using simple linear interpolation (draws a straight 'line' between
// the start and end sample values)
void AudioSampleFramesToPcm::linearInterpolationConceal()
{
    // Get the start and end values from the last and next known-good frames
    qint16 leftChannelStartValue = lastGoodFrame.getSampleValues().leftSamples[5];
    qint16 leftChannelEndValue = nextGoodFrame.getSampleValues().leftSamples[0];
    qint16 rightChannelStartValue = lastGoodFrame.getSampleValues().rightSamples[5];
    qint16 rightChannelEndValue = nextGoodFrame.getSampleValues().rightSamples[0];

    qint32 framesToGenerate = errorStopPosition - errorStartPosition + 1;
    qint32 samplesToGenerate = framesToGenerate * 6; // Per stereo channel

    // Create some temporary buffers
    QVector<qint16> leftSamples;
    QVector<qint16> rightSamples;
    leftSamples.resize(samplesToGenerate);
    rightSamples.resize(samplesToGenerate);

    // Calculate sample step values and initial values
    qreal leftStep = (static_cast<qreal>(leftChannelEndValue) -
                      static_cast<qreal>(leftChannelStartValue)) / static_cast<qreal>(samplesToGenerate);
    qreal leftValue = static_cast<qreal>(leftChannelStartValue);

    qreal rightStep = (static_cast<qreal>(rightChannelEndValue) -
                       static_cast<qreal>(rightChannelStartValue)) / static_cast<qreal>(samplesToGenerate);
    qreal rightValue = static_cast<qreal>(rightChannelStartValue);

    // Generate the interpolated samples
    for (qint32 i = 0; i < samplesToGenerate; i++) {
        leftValue += leftStep;
        leftSamples[i] = static_cast<qint16>(leftValue);
        rightValue += rightStep;
        rightSamples[i] = static_cast<qint16>(rightValue);
    }

    // Copy the interpolated sample values into the frame(s)
    qint32 samplePointer = 0;
    for (qint32 i = 0; i < framesToGenerate; i++) {
        AudioSampleFrame::SampleValues sampleValues;

        for (qint32 x = 0; x < 6; x++) {
            sampleValues.leftSamples[x] = leftSamples[samplePointer];
            sampleValues.rightSamples[x] = rightSamples[samplePointer];
            samplePointer++;
        }
        audioSampleFrameBuffer[errorStartPosition + i].setSampleValues(sampleValues);
    }
}

// Conceal audio error using Interpolated error prediction - this is a custom
// form of (experimental) concealment
void AudioSampleFramesToPcm::predictiveInterpolationConceal()
{
    // Error threshold (in 16-bit signed sample amplitude units)
    qint32 errorThreshold = 1024;

    // Get the start and end values from the last and next known-good frames
    qint16 leftChannelStartValue = lastGoodFrame.getSampleValues().leftSamples[5];
    qint16 leftChannelEndValue = nextGoodFrame.getSampleValues().leftSamples[0];
    qint16 rightChannelStartValue = lastGoodFrame.getSampleValues().rightSamples[5];
    qint16 rightChannelEndValue = nextGoodFrame.getSampleValues().rightSamples[0];

    qint32 framesToGenerate = errorStopPosition - errorStartPosition + 1;
    qint32 samplesToGenerate = framesToGenerate * 6; // Per stereo channel

    // Create some temporary buffers
    QVector<qint16> leftSamples;
    QVector<qint16> rightSamples;
    leftSamples.resize(samplesToGenerate);
    rightSamples.resize(samplesToGenerate);

    // Calculate sample step values and initial values
    qreal leftStep = (static_cast<qreal>(leftChannelEndValue) -
                      static_cast<qreal>(leftChannelStartValue)) / static_cast<qreal>(samplesToGenerate);
    qreal leftValue = static_cast<qreal>(leftChannelStartValue);

    qreal rightStep = (static_cast<qreal>(rightChannelEndValue) -
                       static_cast<qreal>(rightChannelStartValue)) / static_cast<qreal>(samplesToGenerate);
    qreal rightValue = static_cast<qreal>(rightChannelStartValue);

    // Generate the interpolated samples
    for (qint32 i = 0; i < samplesToGenerate; i++) {
        leftValue += leftStep;
        leftSamples[i] = static_cast<qint16>(leftValue);
        rightValue += rightStep;
        rightSamples[i] = static_cast<qint16>(rightValue);
    }

    // Copy the interpolated sample values into the frame(s) if the threshold is exceeded
    // otherwise use the original sample value
    qint32 samplePointer = 0;
    for (qint32 i = 0; i < framesToGenerate; i++) {
        AudioSampleFrame::SampleValues sampleValues;

        for (qint32 x = 0; x < 6; x++) {
            qint32 leftDifference = abs(leftSamples[samplePointer] - audioSampleFrameBuffer[errorStartPosition + i].getSampleValues().leftSamples[x]);
            qint32 rightDifference = abs(rightSamples[samplePointer] - audioSampleFrameBuffer[errorStartPosition + i].getSampleValues().rightSamples[x]);

            if (leftDifference <= errorThreshold) sampleValues.leftSamples[x] = audioSampleFrameBuffer[errorStartPosition + i].getSampleValues().leftSamples[x];
            else sampleValues.leftSamples[x] = leftSamples[samplePointer];

            if (rightDifference <= errorThreshold) sampleValues.rightSamples[x] = audioSampleFrameBuffer[errorStartPosition + i].getSampleValues().rightSamples[x];
            else sampleValues.rightSamples[x] = rightSamples[samplePointer];

            samplePointer++;
        }
        audioSampleFrameBuffer[errorStartPosition + i].setSampleValues(sampleValues);
    }
}
