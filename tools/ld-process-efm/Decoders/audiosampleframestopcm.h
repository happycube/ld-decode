/************************************************************************

    audiosampleframestopcm.h

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

#ifndef AUDIOSAMPLEFRAMESTOPCM_H
#define AUDIOSAMPLEFRAMESTOPCM_H

#include <QCoreApplication>
#include <QDebug>

#include "Datatypes/audiosampleframe.h"

class AudioSampleFramesToPcm
{
public:
    AudioSampleFramesToPcm();

    // Options for the treatment of audio errors
    enum ErrorTreatment {
        conceal,
        silence,
        passThrough
    };

    // Options for concealment of audio errors
    enum ConcealType {
        linear,
        prediction
    };

    void reset();
    QByteArray process(QVector<AudioSampleFrame> audioSampleFrames, ErrorTreatment _errorTreatment, ConcealType _concealType, bool debugState);

public:
    bool debugOn;

    // State-machine variables
    enum StateMachine {
        state_initial,
        state_processFrame,
        state_findEndOfError
    };

    StateMachine currentState;
    StateMachine nextState;
    QByteArray pcmOutputBuffer;
    QVector<AudioSampleFrame> audioSampleFrameBuffer;
    bool waitingForData;
    ErrorTreatment errorTreatment;
    ConcealType concealType;

    AudioSampleFrame lastGoodFrame;
    AudioSampleFrame nextGoodFrame;
    qint32 errorStartPosition;
    qint32 errorStopPosition;

    StateMachine sm_state_initial();
    StateMachine sm_state_processFrame();
    StateMachine sm_state_findEndOfError();

    // Concealment methods
    void linearInterpolationConceal();
    void quadraticInterpolationConceal();
    void predictiveInterpolationConceal();
};

#endif // AUDIOSAMPLEFRAMESTOPCM_H
