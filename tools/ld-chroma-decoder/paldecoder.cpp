/************************************************************************

    paldecoder.cpp

    ld-chroma-decoder - Colourisation filter for ld-decode
    Copyright (C) 2018-2019 Simon Inns
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

#include "paldecoder.h"

#include "decoderpool.h"

PalDecoder::PalDecoder(bool blackAndWhiteParam)
{
    config.blackAndWhite = blackAndWhiteParam;
}

bool PalDecoder::configure(const LdDecodeMetaData::VideoParameters &videoParameters) {
    // Ensure the source video is PAL
    if (!videoParameters.isSourcePal) {
        qCritical() << "This decoder is for PAL video sources only";
        return false;
    }

    config.videoParameters = videoParameters;

    // Set the first and last active scan line
    config.firstActiveScanLine = 44;
    config.lastActiveScanLine = 620;

    // Default to standard output size
    config.outputHeight = 576;

    // Make sure output width is divisible by 8 (better for ffmpeg processing)
    while (true) {
        const qint32 width = config.videoParameters.activeVideoEnd - config.videoParameters.activeVideoStart;
        if ((width % 8) == 0) {
            break;
        }

        // Add pixels to the right and left sides in turn, to keep the active area centred
        if ((width % 2) == 0) {
            config.videoParameters.activeVideoEnd++;
        } else {
            config.videoParameters.activeVideoStart--;
        }
    }

    // Show output information to the user
    const qint32 frameHeight = (videoParameters.fieldHeight * 2) - 1;
    const qint32 outputWidth = config.videoParameters.activeVideoEnd - config.videoParameters.activeVideoStart;
    qInfo() << "Input video of" << config.videoParameters.fieldWidth << "x" << frameHeight <<
               "will be colourised and trimmed to" << outputWidth << "x" << config.outputHeight << "RGB 16-16-16 frames";

    return true;
}

QThread *PalDecoder::makeThread(QAtomicInt& abort, DecoderPool& decoderPool) {
    return new PalThread(abort, decoderPool, config);
}

PalThread::PalThread(QAtomicInt& abortParam, DecoderPool& decoderPoolParam,
                     const PalDecoder::Configuration &configParam, QObject *parent)
    : QThread(parent), abort(abortParam), decoderPool(decoderPoolParam), config(configParam)
{
    // Configure PALcolour
    palColour.updateConfiguration(config.videoParameters);
}

void PalThread::run()
{
    qint32 frameNumber;

    // Input data buffers
    QByteArray firstFieldData;
    QByteArray secondFieldData;

    // Frame metadata
    qint32 firstFieldPhaseID; // not used in PAL
    qint32 secondFieldPhaseID; // not used in PAL
    qreal burstMedianIre;

    while(!abort) {
        // Get the next frame to process from the input file
        if (!decoderPool.getInputFrame(frameNumber, firstFieldData, secondFieldData,
                                       firstFieldPhaseID, secondFieldPhaseID, burstMedianIre)) {
            // No more input frames -- exit
            break;
        }

        // Calculate the saturation level from the burst median IRE
        // Note: This code works as a temporary MTF compensator whilst ld-decode gets
        // real MTF compensation added to it.
        qreal tSaturation = 125.0 + ((100.0 / 20.0) * (20.0 - burstMedianIre));

        // Perform the PALcolour filtering
        QByteArray outputData = palColour.performDecode(firstFieldData, secondFieldData, 100,
                                                        static_cast<qint32>(tSaturation), config.blackAndWhite);

        // The PALcolour library outputs the whole frame, so here we have to strip all the non-visible stuff to just get the
        // actual required image - it would be better if PALcolour gave back only the required RGB, but it's not my library.
        QByteArray croppedData;

        // Add additional output lines to ensure the output height is 576 lines
        const qint32 activeVideoStart = config.videoParameters.activeVideoStart;
        const qint32 activeVideoEnd = config.videoParameters.activeVideoEnd;
        QByteArray blankLine;
        blankLine.resize((activeVideoEnd - activeVideoStart) * 6);
        blankLine.fill(0);
        for (qint32 y = 0; y < config.outputHeight - (config.lastActiveScanLine - config.firstActiveScanLine); y++) {
            croppedData.append(blankLine);
        }

        // Since PALcolour uses +-3 scan-lines to colourise, the final lines before the non-visible area may not come out quite
        // right, but we're including them here anyway.
        for (qint32 y = config.firstActiveScanLine; y < config.lastActiveScanLine; y++) {
            croppedData.append(outputData.mid((y * config.videoParameters.fieldWidth * 6) + (activeVideoStart * 6),
                                              ((activeVideoEnd - activeVideoStart) * 6)));
        }

        // Write the result to the output file
        if (!decoderPool.putOutputFrame(frameNumber, croppedData)) {
            abort = true;
            break;
        }
    }
}
