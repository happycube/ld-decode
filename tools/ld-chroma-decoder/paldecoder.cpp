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

    // Compute cropping parameters
    setVideoParameters(config, videoParameters, 44, 620);

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
        // PAL burst is 300 mV p-p (about 43 IRE, as 100 IRE = 700 mV)
        qreal nominalBurstIre = 300 * (100.0 / 700) / 2;
        qreal tSaturation = 100 * (nominalBurstIre / burstMedianIre);

        if (config.blackAndWhite) {
            tSaturation = 0;
        }

        // Perform the PALcolour filtering
        QByteArray outputData = palColour.performDecode(firstFieldData, secondFieldData, 100, static_cast<qint32>(tSaturation));

        // The PALcolour library outputs the whole frame, so here we have to strip all the non-visible stuff to just get the
        // actual required image - it would be better if PALcolour gave back only the required RGB, but it's not my library.
        // Since PALcolour uses +-3 scan-lines to colourise, the final lines before the non-visible area may not come out quite
        // right, but we're including them here anyway.
        QByteArray croppedData = PalDecoder::cropOutputFrame(config, outputData);

        // Write the result to the output file
        if (!decoderPool.putOutputFrame(frameNumber, croppedData)) {
            abort = true;
            break;
        }
    }
}
