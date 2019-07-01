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
    // Get the default configuration for the comb filter
    // FIXME It'd be nice not to have to create a Comb for this
    Comb comb;
    config.combConfig = comb.getConfiguration();

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

    // Calculate the frame height
    qint32 frameHeight = (videoParameters.fieldHeight * 2) - 1;

    // Set the first and last active scan line
    config.firstActiveScanLine = 40;
    config.lastActiveScanLine = 525;

    // Default to standard output size
    config.fieldWidth = videoParameters.fieldWidth;
    config.videoStart = videoParameters.activeVideoStart;
    config.videoEnd = videoParameters.activeVideoEnd;
    config.outputHeight = 488;

    // Make sure output width is divisible by 8 (better for ffmpeg processing)
    while (((config.videoEnd - config.videoStart) % 8) != 0) {
        config.videoEnd++;
    }

    // Show output information to the user
    qInfo() << "Input video of" << videoParameters.fieldWidth << "x" << frameHeight <<
               "will be colourised and trimmed to" << config.videoEnd - config.videoStart <<
               "x" << config.outputHeight << "RGB 16-16-16 frames";

    // Set the input buffer dimensions configuration
    config.combConfig.fieldWidth = videoParameters.fieldWidth;
    config.combConfig.fieldHeight = videoParameters.fieldHeight;

    // Set the active video range
    config.combConfig.activeVideoStart = videoParameters.activeVideoStart;
    config.combConfig.activeVideoEnd = videoParameters.activeVideoEnd;

    // Set the first frame scan line which contains active video
    config.combConfig.firstVisibleFrameLine = config.firstActiveScanLine;

    // Set the IRE levels
    config.combConfig.blackIre = videoParameters.black16bIre;
    config.combConfig.whiteIre = videoParameters.white16bIre;

    return true;
}

QThread *NtscDecoder::makeThread(QAtomicInt& abort, DecoderPool& decoderPool)
{
    return new NtscThread(abort, decoderPool, config);
}

NtscThread::NtscThread(QAtomicInt& abortParam, DecoderPool &decoderPoolParam,
                       const NtscDecoder::Configuration &configParam, QObject *parent)
    : QThread(parent), abort(abortParam), decoderPool(decoderPoolParam), config(configParam)
{
}

void NtscThread::run()
{
    qint32 frameNumber;

    // Input data buffers
    QByteArray firstFieldData;
    QByteArray secondFieldData;

    // Frame metadata
    qint32 firstFieldPhaseID;
    qint32 secondFieldPhaseID;
    qreal burstMedianIre;

    // Create the comb filter object with the precomputed configuration
    Comb comb;
    comb.setConfiguration(config.combConfig);

    while(!abort) {
        // Get the next frame to process from the input file
        if (!decoderPool.getInputFrame(frameNumber, firstFieldData, secondFieldData,
                                       firstFieldPhaseID, secondFieldPhaseID, burstMedianIre)) {
            // No more input frames -- exit
            break;
        }

        // Filter the frame
        QByteArray rgbOutputData = comb.process(firstFieldData, secondFieldData, burstMedianIre,
                                                firstFieldPhaseID, secondFieldPhaseID);

        // The NTSC filter outputs the whole frame, so here we crop it to the required dimensions
        QByteArray croppedOutputData;

        // Add additional output lines to ensure the output height is 488 lines
        QByteArray blankLine;
        blankLine.resize((config.videoEnd - config.videoStart) * 6 );
        blankLine.fill(0);
        for (qint32 y = 0; y < config.outputHeight - (config.lastActiveScanLine - config.firstActiveScanLine); y++) {
            croppedOutputData.append(blankLine);
        }

        for (qint32 y = static_cast<qint32>(config.firstActiveScanLine); y < static_cast<qint32>(config.lastActiveScanLine); y++) {
            croppedOutputData.append(rgbOutputData.mid((y * config.fieldWidth * 6) + (static_cast<qint32>(config.videoStart) * 6),
                                                       ((static_cast<qint32>(config.videoEnd) - static_cast<qint32>(config.videoStart)) * 6)));
        }

        // Write the result to the output file
        if (!decoderPool.putOutputFrame(frameNumber, croppedOutputData)) {
            abort = true;
            break;
        }
    }
}
