/************************************************************************

    f2framestoaudio.h

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

#ifndef F2FRAMESTOAUDIO_H
#define F2FRAMESTOAUDIO_H

#include <QCoreApplication>
#include <QDebug>

#include "Datatypes/f2frame.h"
#include "Datatypes/audiosampleframe.h"

class F2FramesToAudio
{
public:
    F2FramesToAudio();

    // Statistics
    struct Statistics {
        qint32 totalSamples;
        qint32 validSamples;
        qint32 corruptSamples;
        qint32 missingSectionSamples;
        qint32 encoderOffSamples;
        TrackTime sampleStart;
        TrackTime sampleCurrent;
    };

    QVector<AudioSampleFrame> process(QVector<F2Frame> f2FramesIn, bool _padInitialDiscTime, bool debugState);
    Statistics getStatistics();
    void reportStatistics();
    void reset();

private:
    bool debugOn;
    Statistics statistics;
    bool padInitialDiscTime;

    // State-machine variables
    enum StateMachine {
        state_initial,
        state_getInitialDiscTime,
        state_processSection
    };

    StateMachine currentState;
    StateMachine nextState;
    QVector<F2Frame> f2FrameBuffer;
    QVector<AudioSampleFrame> audioSamplesOut;
    bool waitingForData;
    TrackTime lastDiscTime;

    StateMachine sm_state_initial();
    StateMachine sm_state_getInitialDiscTime();
    StateMachine sm_state_bufferF2Frames();
    StateMachine sm_state_processSection();

    void clearStatistics();
};

#endif // F2FRAMESTOAUDIO_H
