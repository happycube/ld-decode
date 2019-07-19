/************************************************************************

    f2framestoaudio.cpp

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

#include "f2framestoaudio.h"

F2FramesToAudio::F2FramesToAudio()
{
    debugOn = false;
    reset();
}

// Public methods -----------------------------------------------------------------------------------------------------

// Method to feed the audio processing state-machine with F2Frames
QVector<AudioSampleFrame> F2FramesToAudio::process(QVector<F2Frame> f2FramesIn, bool _padInitialDiscTime,
                                    bool debugState)
{
    debugOn = debugState;
    padInitialDiscTime = _padInitialDiscTime;

    // Clear the output buffer
    audioSamplesOut.clear();

    if (f2FramesIn.isEmpty()) return audioSamplesOut;

    // Append input data to the processing buffer
    f2FrameBuffer.append(f2FramesIn);

    waitingForData = false;
    while (!waitingForData) {
        currentState = nextState;

        switch (currentState) {
        case state_initial:
            nextState = sm_state_initial();
            break;
        case state_getInitialDiscTime:
            nextState = sm_state_getInitialDiscTime();
            break;
        case state_processSection:
            nextState = sm_state_processSection();
            break;
        }
    }

    return audioSamplesOut;
}

// Get method - retrieve statistics
F2FramesToAudio::Statistics F2FramesToAudio::getStatistics()
{
    return statistics;
}

// Method to report decoding statistics to qInfo
void F2FramesToAudio::reportStatistics()
{
    qInfo() << "";
    qInfo() << "F2 Frames to audio samples:";
    qInfo() << "            Valid samples:" << statistics.validSamples;
    qInfo() << "          Corrupt samples:" << statistics.corruptSamples;
    qInfo() << "  Missing section samples:" << statistics.missingSectionSamples << "(" << statistics.missingSectionSamples / 6 << "F3 Frames )";
    qInfo() << "      Encoder off samples:" << statistics.encoderOffSamples;
    qInfo() << "            TOTAL samples:" << statistics.totalSamples;
    qInfo() << "";
    qInfo().noquote() << "        Sample start time:" << statistics.sampleStart.getTimeAsQString();
    qInfo().noquote() << "          Sample end time:" << statistics.sampleCurrent.getTimeAsQString();

    qint32 sampleFrameLength = statistics.sampleCurrent.getDifference(statistics.sampleStart.getTime());
    TrackTime sampleLength;
    sampleLength.setTime(0, 0, 0);
    sampleLength.addFrames(sampleFrameLength);
    qInfo().noquote() << "          Sample duration:" << sampleLength.getTimeAsQString();
    qInfo().noquote() << "      Sample frame length:" << sampleFrameLength << "(" << sampleFrameLength / 75.0 << "seconds )";
}

// Method to reset the class
void F2FramesToAudio::reset()
{
    // Initialise variables to track the disc time
    lastDiscTime.setTime(0, 0, 0);

    f2FrameBuffer.clear();
    audioSamplesOut.clear();
    waitingForData = false;
    currentState = state_initial;
    nextState = currentState;

    clearStatistics();
}

// Private methods ----------------------------------------------------------------------------------------------------

// Method to clear the statistics counters
void F2FramesToAudio::clearStatistics()
{
    statistics.validSamples = 0;
    statistics.missingSectionSamples = 0;
    statistics.encoderOffSamples = 0;
    statistics.totalSamples = 0;
    statistics.corruptSamples = 0;

    statistics.sampleStart.setTime(0, 0, 0);
    statistics.sampleCurrent.setTime(0, 0, 0);
}

// State-machine methods ----------------------------------------------------------------------------------------------

F2FramesToAudio::StateMachine F2FramesToAudio::sm_state_initial()
{
    if (debugOn) qDebug() << "F2FramesToAudio::sm_state_initial(): Called";
    return state_getInitialDiscTime;
}

// Get the initial disc time
F2FramesToAudio::StateMachine F2FramesToAudio::sm_state_getInitialDiscTime()
{
    lastDiscTime = f2FrameBuffer[0].getDiscTime();
    statistics.sampleStart = lastDiscTime;
    statistics.sampleCurrent = lastDiscTime;
    if (debugOn) qDebug() << "F2FramesToAudio::sm_state_getInitialDiscTime(): Initial disc time is" << lastDiscTime.getTimeAsQString();

    // Should we pad based on the initial disc time seen?
    if (padInitialDiscTime) {
        // Set the startDiscTime to 00:00.00
        TrackTime startDiscTime;
        startDiscTime.setTime(0, 0, 0);

        // Check that this section is one frame difference from the previous
        // and pad the output sample data if sections are missing
        qint32 sectionFrameGap = lastDiscTime.getDifference(startDiscTime.getTime());
        if (sectionFrameGap > 1) {
            if (debugOn) qDebug().noquote() << "F2FramesToAudio::sm_state_getInitialDiscTime(): Initial disc time gap - Adding" <<
                                               sectionFrameGap - 1 << "section(s) of padding (" << (sectionFrameGap - 1) * 98 * 6 << "samples )";

            // Pad the output sample file according to the gap
            AudioSampleFrame audioSampleFrame;

            // Loop per section
            for (qint32 p = 0; p < sectionFrameGap - 1; p++) {
                // 98 Audio frames per section
                lastDiscTime.addFrames(1);

                for (qint32 s = 0; s < 98; s++) {
                    audioSamplesOut.append(AudioSampleFrame());
                }

                // Add filled section to statistics
                statistics.missingSectionSamples += 98 * 6;
                statistics.totalSamples += 98 * 6;
            }
        }
    }

    // To make sure the current time is processed correctly we have to
    // set the last disc time to -1 frame
    lastDiscTime.subtractFrames(1);

    return state_processSection;
}

F2FramesToAudio::StateMachine F2FramesToAudio::sm_state_processSection()
{
    // Get the current disc time for the section
    TrackTime currentDiscTime = f2FrameBuffer[0].getDiscTime();
    //if (debugOn) qDebug() << "F2FramesToAudio::sm_state_processSection(): Current disc time is" << currentDiscTime.getTimeAsQString();

    // Check that this section is one frame difference from the previous
    // and pad the output sample data if sections are missing
    qint32 sectionFrameGap = currentDiscTime.getDifference(lastDiscTime.getTime());
    if (sectionFrameGap > 1) {
        if (debugOn) qDebug().noquote() << "F2FramesToAudio::sm_state_processSection(): Section gap - Last seen time was" << lastDiscTime.getTimeAsQString() <<
                                 "current disc time is" << currentDiscTime.getTimeAsQString() <<
                                 "Adding" << sectionFrameGap - 1 << "section(s) of padding (" << (sectionFrameGap - 1) * 98 * 6 << "samples )";

        // Pad the output sample file according to the gap
        AudioSampleFrame audioSampleFrame;

        // Loop per section
        for (qint32 p = 0; p < sectionFrameGap - 1; p++) {
            // 98 Audio frames per section
            lastDiscTime.addFrames(1);

            for (qint32 s = 0; s < 98; s++) {
                audioSamplesOut.append(AudioSampleFrame());
            }

            // Add filled section to statistics
            statistics.missingSectionSamples += 98 * 6;
            statistics.totalSamples += 98 * 6;
        }
    }

    // Store the current disc time as the last disc time for the next cycle of processing
    lastDiscTime = currentDiscTime;
    statistics.sampleCurrent = currentDiscTime;

    // Determine if the section is flagged as encoder on or off (using a threshold to prevent false-negatives)
    bool sectionEncoderState = false;
    qint32 encoderStateCount = 0;
    for (qint32 i = 0; i < 98; i++) {
        if (f2FrameBuffer[i].getIsEncoderRunning()) encoderStateCount++;
    }
    if (encoderStateCount > 10) sectionEncoderState = true; else sectionEncoderState = false;

    // Output the F2 Frames as samples
    for (qint32 i = 0; i < 98; i++) {
        audioSamplesOut.append(AudioSampleFrame(f2FrameBuffer[i]));

        // Update the statistics
        if (sectionEncoderState && !f2FrameBuffer[i].isFrameCorrupt()) {
            // Encoder is running and data is valid
            statistics.validSamples += 6;
            statistics.totalSamples += 6;
        } else if (!sectionEncoderState) {
            // Section encoding is off, so no data loss (even if the sample data is invalid
            // we don't need to use it)
            statistics.encoderOffSamples += 6;
            statistics.totalSamples += 6;
        } else {
            // Actual audio data loss has occurred (encoder is on and data is invalid)
            statistics.corruptSamples += 6;
            statistics.totalSamples += 6;
        }
    }

    // Remove the processed section from the F2 frame buffer
    f2FrameBuffer.remove(0, 98);

    // Request more F2 frame data if required
    if (f2FrameBuffer.size() < 98) waitingForData = true;

    return state_processSection;
}



