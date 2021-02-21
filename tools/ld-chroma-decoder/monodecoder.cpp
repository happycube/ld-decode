/************************************************************************

    monodecoder.cpp

    ld-chroma-decoder - Colourisation filter for ld-decode
    Copyright (C) 2019 Adam Sampson

    This file is part of ld-decode-tools.

    ld-chroma-decoder is free software: you can redistribute it and/or
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

#include "monodecoder.h"

#include "comb.h"
#include "decoderpool.h"
#include "palcolour.h"

MonoDecoder::MonoDecoder(const MonoDecoder::Configuration &monoConfig)
{
    config = monoConfig;
}

bool MonoDecoder::configure(const LdDecodeMetaData::VideoParameters &videoParameters) {
    // This decoder works for both PAL and NTSC.

    // Compute cropping parameters
    setVideoParameters(config, videoParameters);

    return true;
}

const char *MonoDecoder::getPixelName() const
{
    return config.outputYCbCr ? "GRAY16" : "RGB48";
}

QThread *MonoDecoder::makeThread(QAtomicInt& abort, DecoderPool& decoderPool) {
    return new MonoThread(abort, decoderPool, config);
}

MonoThread::MonoThread(QAtomicInt& _abort, DecoderPool& _decoderPool,
                     const MonoDecoder::Configuration &_config, QObject *parent)
    : DecoderThread(_abort, _decoderPool, parent), config(_config)
{
    // Resize and clear the output buffers
    const qint32 frameHeight = (config.videoParameters.fieldHeight * 2) - 1;
    if (config.outputYCbCr) {
        outputFrame.Y.resize(config.videoParameters.fieldWidth * frameHeight);
        outputFrame.Y.fill(16 * 256);
        outputFrame.Cb.resize(0);
        outputFrame.Cr.resize(0);
    } else {
        outputFrame.RGB.resize(config.videoParameters.fieldWidth * frameHeight * 3);
        outputFrame.RGB.fill(0);
    }
}

void MonoThread::decodeFrames(const QVector<SourceField> &inputFields, qint32 startIndex, qint32 endIndex,
                              QVector<OutputFrame> &outputFrames)
{
    // Work out black-white scaling factors
    const LdDecodeMetaData::VideoParameters &videoParameters = config.videoParameters;
    const quint16 blackOffset = videoParameters.black16bIre;

    for (qint32 fieldIndex = startIndex, frameIndex = 0; fieldIndex < endIndex; fieldIndex += 2, frameIndex++) {
        // Interlace the active lines of the two input fields to produce an output frame
        for (qint32 y = config.videoParameters.firstActiveFrameLine; y < config.videoParameters.lastActiveFrameLine; y++) {
            const SourceVideo::Data &inputFieldData = (y % 2) == 0 ? inputFields[fieldIndex].data : inputFields[fieldIndex + 1].data;
            const quint16 *inputLine = inputFieldData.data() + ((y / 2) * videoParameters.fieldWidth);
            if (config.outputYCbCr) {
                const double whiteScale = 219.0 * 257.0 / (videoParameters.white16bIre - blackOffset);
                for (qint32 x = videoParameters.activeVideoStart; x < videoParameters.activeVideoEnd; x++) {
                    quint16 value = static_cast<quint16>(qBound(1.0 * 256.0, (inputLine[x] - blackOffset) * whiteScale + 16 * 256, 254.75 * 256.0));
                    quint16 *outputLine = outputFrame.Y.data() + (y * videoParameters.fieldWidth);
                    outputLine[x] = value;
                }
            } else {
                // Each quint16 input becomes three RGB quint16 outputs
                const double whiteScale = 65535.0 / (videoParameters.white16bIre - blackOffset);
                for (qint32 x = videoParameters.activeVideoStart; x < videoParameters.activeVideoEnd; x++) {
                    quint16 value = static_cast<quint16>(qBound(0.0, (inputLine[x] - blackOffset) * whiteScale, 65535.0));
                    quint16 *outputLine = outputFrame.RGB.data() + (y * videoParameters.fieldWidth * 3);
                    const qint32 outputPos = x * 3;
                    outputLine[outputPos] = value;
                    outputLine[outputPos + 1] = value;
                    outputLine[outputPos + 2] = value;
                }
            }
        }

        // Crop the frame to just the active area
        outputFrames[frameIndex] = MonoDecoder::cropOutputFrame(config, outputFrame);
    }
}
