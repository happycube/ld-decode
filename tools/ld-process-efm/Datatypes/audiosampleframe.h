/************************************************************************

    audiosampleframe.h

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

#ifndef AUDIOSAMPLEFRAME_H
#define AUDIOSAMPLEFRAME_H

#include <QCoreApplication>
#include <QDebug>

#include "Datatypes/tracktime.h"
#include "Datatypes/f2frame.h"

class AudioSampleFrame
{
public:
    enum SampleType {
        audio,
        silence,
        corrupt
    };

    struct SampleValues {
        qint16 leftSamples[6];
        qint16 rightSamples[6];
    };

    struct Metadata {
        TrackTime discTime;
        TrackTime trackTime;
        qint32 trackNumber;
        SampleType sampleType;
    };

    struct Sample {
        uchar sampleFrame[24];
        SampleValues sampleValues;
        Metadata metadata;
    };

    AudioSampleFrame();
    AudioSampleFrame(F2Frame f2Frame);

    void setDataFromF2Frame(F2Frame f2Frame);

    Metadata getMetadata();
    void setMetadata(Metadata _metadata);

    void setSampleFrame(uchar* _sampleFrame);
    uchar* getSampleFrame();

    void setSampleValues(AudioSampleFrame::SampleValues _sampleValues);
    SampleValues getSampleValues();

    void setSampleToSilence();

private:
    Sample sample;

    bool isEncoderRunning;

    void createSampleValuesFromFrame();
    void createSampleFrameFromValues();
    void silenceSample();
};

#endif // AUDIOSAMPLEFRAME_H
