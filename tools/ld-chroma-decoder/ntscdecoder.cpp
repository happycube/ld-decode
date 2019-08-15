/************************************************************************

    ntscdecoder.cpp

    ld-chroma-decoder - Colourisation filter for ld-decode
    Copyright (C) 2018 Chad Page
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

#include "ntscdecoder.h"

#include "decoderpool.h"

NtscDecoder::NtscDecoder(bool blackAndWhite, bool whitePoint, bool use3D, bool showOpticalFlowMap) {
    // Set the comb filter configuration
    config.combConfig.blackAndWhite = blackAndWhite;
    config.combConfig.whitePoint100 = whitePoint;

    // Set the filter type
    config.combConfig.use3D = use3D;
    config.combConfig.showOpticalFlowMap = showOpticalFlowMap;
}

bool NtscDecoder::configure(const LdDecodeMetaData::VideoParameters &videoParameters) {
    // Ensure the source video is NTSC
    if (videoParameters.isSourcePal) {
        qCritical() << "This decoder is for NTSC video sources only";
        return false;
    }

    // Compute cropping parameters
    setVideoParameters(config, videoParameters, config.combConfig.firstActiveLine, config.combConfig.lastActiveLine);

    return true;
}

QThread *NtscDecoder::makeThread(QAtomicInt& abort, DecoderPool& decoderPool)
{
    return new NtscThread(abort, decoderPool, config);
}

NtscThread::NtscThread(QAtomicInt& _abort, DecoderPool &_decoderPool,
                       const NtscDecoder::Configuration &_config, QObject *parent)
    : QThread(parent), abort(_abort), decoderPool(_decoderPool), config(_config)
{
    // Configure NTSC decoder
    comb.updateConfiguration(config.videoParameters, config.combConfig);
}

void NtscThread::run()
{
    qint32 frameNumber;

    // Input field metadata and data
    LdDecodeMetaData::Field firstField;
    QByteArray firstFieldData;
    LdDecodeMetaData::Field secondField;
    QByteArray secondFieldData;

    while(!abort) {
        // Get the next frame to process from the input file
        if (!decoderPool.getInputFrame(frameNumber, firstField, firstFieldData, secondField, secondFieldData)) {
            // No more input frames -- exit
            break;
        }

        // Filter the frame
        QByteArray outputData = comb.decodeFrame(firstField, firstFieldData, secondField, secondFieldData);

        // The NTSC filter outputs the whole frame, so here we crop it to the required dimensions
        QByteArray croppedData = NtscDecoder::cropOutputFrame(config, outputData);

        // Write the result to the output file
        if (!decoderPool.putOutputFrame(frameNumber, croppedData)) {
            abort = true;
            break;
        }
    }
}
