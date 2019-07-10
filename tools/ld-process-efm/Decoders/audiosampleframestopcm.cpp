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

}

// Just a dummy function at the moment waiting for the conceal option to be implemented
QByteArray AudioSampleFramesToPcm::process(QVector<AudioSampleFrame> audioSampleFrames, ErrorTreatment errorTreatment, bool isDebugOn)
{
    pcmOutputBuffer.clear();

    for (qint32 i = 0; i < audioSampleFrames.size(); i++) {
        // If error correction is silence, set corrupt samples to silence
        if (audioSampleFrames[i].getMetadata().sampleType == AudioSampleFrame::SampleType::corrupt) {
            if (errorTreatment == ErrorTreatment::silence) audioSampleFrames[i].setSampleToSilence();
        }

        // Append the audio sample's frame data to the output buffer
        pcmOutputBuffer.append(QByteArray(reinterpret_cast<char*>(audioSampleFrames[i].getSampleFrame()), 24));
    }
    if (isDebugOn) qDebug() << "AudioSampleFramesToPcm::process(): Processed" << audioSampleFrames.size() << "audio sample frames";

    return pcmOutputBuffer;
}
