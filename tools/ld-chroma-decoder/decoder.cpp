/************************************************************************

    decoder.cpp

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

#include "decoder.h"

#include "decoderpool.h"

qint32 Decoder::getLookBehind() const
{
    return 0;
}

qint32 Decoder::getLookAhead() const
{
    return 0;
}

void Decoder::setVideoParameters(Decoder::Configuration &config, const LdDecodeMetaData::VideoParameters &videoParameters) {
    config.videoParameters = videoParameters;
    config.topPadLines = 0;
    config.bottomPadLines = 0;

    // Both width and height should be divisible by 8, as video codecs expect this.
    // Expand horizontal active region so the width is divisible by 8.
    qint32 outputWidth;
    while (true) {
        outputWidth = config.videoParameters.activeVideoEnd - config.videoParameters.activeVideoStart;
        if ((outputWidth % 8) == 0) {
            break;
        }

        // Add pixels to the right and left sides in turn, to keep the active area centred
        if ((outputWidth % 2) == 0) {
            config.videoParameters.activeVideoEnd++;
        } else {
            config.videoParameters.activeVideoStart--;
        }
    }

    // Insert empty padding lines so the height is divisible by 8
    qint32 outputHeight;
    while (true) {
        const qint32 numActiveLines = videoParameters.lastActiveFrameLine - videoParameters.firstActiveFrameLine;
        outputHeight = config.topPadLines + numActiveLines + config.bottomPadLines;
        if ((outputHeight % 8) == 0) {
            break;
        }

        // Add lines to the bottom and top in turn, to keep the active area centred
        if ((outputHeight % 2) == 0) {
            config.bottomPadLines++;
        } else {
            config.topPadLines++;
        }
    }

    // Show output information to the user
    const qint32 frameHeight = (videoParameters.fieldHeight * 2) - 1;
    qInfo() << "Input video of" << config.videoParameters.fieldWidth << "x" << frameHeight <<
               "will be colourised and trimmed to" << outputWidth << "x" << outputHeight << (config.outputYCbCr ? "YCbCr" : "RGB") << "frames";
}

OutputFrame Decoder::cropOutputFrame(const Decoder::Configuration &config, const OutputFrame &outputData) {
    const qint32 activeVideoStart = config.videoParameters.activeVideoStart;
    const qint32 activeVideoEnd = config.videoParameters.activeVideoEnd;
    qint32 outputLineLength = (activeVideoEnd - activeVideoStart);

    OutputFrame croppedData;
    switch (config.pixelFormat) {
    case RGB48:
        outputLineLength *= 3;
        // Insert padding at the top
        if (config.topPadLines > 0) {
            croppedData.RGB.insert(croppedData.RGB.begin(), config.topPadLines * outputLineLength, 0);
        }
        // Copy the active region from the decoded image
        for (qint32 y = config.videoParameters.firstActiveFrameLine; y < config.videoParameters.lastActiveFrameLine; y++) {
            croppedData.RGB.append(outputData.RGB.mid((y * config.videoParameters.fieldWidth * 3) + (activeVideoStart * 3),
                                                outputLineLength));
        }
        // Insert padding at the bottom
        if (config.bottomPadLines > 0) {
            croppedData.RGB.insert(croppedData.RGB.end(), config.bottomPadLines * outputLineLength, 0);
        }
        break;
    case YUV444P16:
        if (config.topPadLines > 0) {
            croppedData.Y.insert(croppedData.Y.begin(), config.topPadLines * outputLineLength, 16 * 256);
            croppedData.Cb.insert(croppedData.Cb.begin(), config.topPadLines * outputLineLength, 128 * 256);
            croppedData.Cr.insert(croppedData.Cr.begin(), config.topPadLines * outputLineLength, 128 * 256);
        }
        for (qint32 y = config.videoParameters.firstActiveFrameLine; y < config.videoParameters.lastActiveFrameLine; y++) {
            croppedData.Y.append(outputData.Y.mid((y * config.videoParameters.fieldWidth) + activeVideoStart, outputLineLength));
            croppedData.Cb.append(outputData.Cb.mid((y * config.videoParameters.fieldWidth) + activeVideoStart, outputLineLength));
            croppedData.Cr.append(outputData.Cr.mid((y * config.videoParameters.fieldWidth) + activeVideoStart, outputLineLength));
        }
        if (config.bottomPadLines > 0) {
            croppedData.Y.insert(croppedData.Y.end(), config.bottomPadLines * outputLineLength, 16 * 256);
            croppedData.Cb.insert(croppedData.Cb.end(), config.bottomPadLines * outputLineLength, 128 * 256);
            croppedData.Cr.insert(croppedData.Cr.end(), config.bottomPadLines * outputLineLength, 128 * 256);
        }
        break;
    case GRAY16:
        if (config.topPadLines > 0) {
            croppedData.Y.insert(croppedData.Y.begin(), config.topPadLines * outputLineLength, 16 * 256);
        }
        for (qint32 y = config.videoParameters.firstActiveFrameLine; y < config.videoParameters.lastActiveFrameLine; y++) {
            croppedData.Y.append(outputData.Y.mid((y * config.videoParameters.fieldWidth) + activeVideoStart, outputLineLength));
        }
        if (config.bottomPadLines > 0) {
            croppedData.Y.insert(croppedData.Y.end(), config.bottomPadLines * outputLineLength, 16 * 256);
        }
        break;
    }

    return croppedData;
}

DecoderThread::DecoderThread(QAtomicInt& _abort, DecoderPool& _decoderPool, QObject *parent)
    : QThread(parent), abort(_abort), decoderPool(_decoderPool)
{
}

void DecoderThread::run()
{
    // Input and output data
    QVector<SourceField> inputFields;
    QVector<OutputFrame> outputFrames;

    while (!abort) {
        // Get the next batch of fields to process
        qint32 startFrameNumber, startIndex, endIndex;
        if (!decoderPool.getInputFrames(startFrameNumber, inputFields, startIndex, endIndex)) {
            // No more input frames -- exit
            break;
        }

        // Adjust the output to the right size
        outputFrames.resize((endIndex - startIndex) / 2);

        // Decode the fields to frames
        decodeFrames(inputFields, startIndex, endIndex, outputFrames);

        // Write the frames to the output file
        if (!decoderPool.putOutputFrames(startFrameNumber, outputFrames)) {
            abort = true;
            break;
        }
    }
}
