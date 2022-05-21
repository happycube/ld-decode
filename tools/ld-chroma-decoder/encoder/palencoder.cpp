/************************************************************************

    palencoder.cpp

    ld-chroma-encoder - PAL encoder for testing
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

/*!
    \class PALEncoder

    This is a simplistic PAL encoder for decoder testing. The code aims to be
    accurate rather than fast.

    References:

    [Poynton] "Digital Video and HDTV Algorithms and Interfaces" by Charles
    Poynton, 2003, first edition, ISBN 1-55860-792-7. Later editions have less
    material about analogue video standards.

    [EBU] "Specification of interfaces for 625-line digital PAL signals",
    (https://tech.ebu.ch/docs/tech/tech3280.pdf) EBU Tech. 3280-E.

    [Clarke] "Colour encoding and decoding techniques for line-locked sampled
    PAL and NTSC television signals" (https://www.bbc.co.uk/rd/publications/rdreport_1986_02),
    BBC Research Department Report 1986/02, by C.K.P. Clarke.
 */

#include "palencoder.h"

#include "firfilter.h"

#include <array>
#include <cmath>

PALEncoder::PALEncoder(QFile &_rgbFile, QFile &_tbcFile, LdDecodeMetaData &_metaData, bool _scLocked)
    : rgbFile(_rgbFile), tbcFile(_tbcFile), metaData(_metaData), scLocked(_scLocked)
{
    // PAL subcarrier frequency [Poynton p529] [EBU p5]
    fSC = 4433618.75;

    if (scLocked) {
        // Parameters for 4fSC subcarrier-locked sampling:
        //
        // Each frame in the TBC file contains (1135 * 625) + 4 samples,
        // followed by dummy samples to fill out the rest of the "626th" line.
        // For horizontal alignment between the two fields, we treat this as:
        // - field 1: 1135 x 313 lines, plus 2 extra samples
        // - field 2: 1135 x 312 lines, plus 2 extra samples
        // - 1131 padding samples
        //
        // Each 64 usec line is 1135 + (4 / 625) samples long, so everything
        // moves to the right by (4 / 625) samples on each line. The values
        // in this struct represent the sample numbers *on the first line*.
        //
        // The first sample in the TBC frame is the first blanking sample of
        // field 1 line 1, sample 948 of 1135. 0H occurs midway between samples
        // 957 and 958. [EBU p7]
        const double zeroH = 957.5 - 948;

        sampleRate = 4 * fSC;

        // Burst gate opens 5.6 usec after 0H, and closes 10 cycles later.
        // [Poynton p530]
        const double burstStartPos = zeroH + (5.6e-6 * sampleRate);
        const double burstEndPos = burstStartPos + (10 * 4);
        videoParameters.colourBurstStart = static_cast<qint32>(lrint(burstStartPos));
        videoParameters.colourBurstEnd = static_cast<qint32>(lrint(burstEndPos));
        // The colourburst is sampled at 0, 90, 180 and 270 degrees, so the
        // sample values are [95.5, 64, 32.5, 64] * 0x100. [Poynton p532]

        // Centre the 922 samples for 4:3 in the 948-sample digital active area
        // [Poynton p532]
        videoParameters.activeVideoStart = (1135 - 948) + ((948 - 922) / 2);
        videoParameters.activeVideoEnd = videoParameters.activeVideoStart + 922;
    } else {
        // Parameters for line-locked sampling, based on ld-decode's usual output:

        sampleRate = 1135 / 64.0e-6;

        videoParameters.colourBurstStart = 98;
        videoParameters.colourBurstEnd = 138;

        videoParameters.activeVideoStart = 185;
        videoParameters.activeVideoEnd = 1107;
    }

    // Parameters that are common for subcarrier- and line-locked output:
    videoParameters.numberOfSequentialFields = 0;
    videoParameters.isSourcePal = true;
    videoParameters.isSubcarrierLocked = scLocked;
    // White level and blanking level, extended to 16 bits [EBU p6]
    videoParameters.white16bIre = 0xD300;
    videoParameters.black16bIre = 0x4000;
    videoParameters.fieldWidth = 1135;
    videoParameters.fieldHeight = 313;
    // sampleRate and fsc are integers in this struct, so they're not precise;
    // the code below uses fSC and sampleRate instead
    videoParameters.sampleRate = static_cast<qint32>(lrint(sampleRate));
    videoParameters.fsc = static_cast<qint32>(lrint(fSC));
    videoParameters.isMapped = false;

    // Compute the location of the input image within the PAL frame, based on
    // the parameters above. For a 4:3 picture, there should really be 922
    // horizontal samples at 4fSC, but ld-chroma-decoder expands both sides to
    // make the width a multiple of 8 -- so centre the input across the active
    // area.
    activeWidth = 928;
    activeLeft = ((videoParameters.activeVideoStart + videoParameters.activeVideoEnd) / 2) - (activeWidth / 2);
    activeTop = 44;
    activeHeight = 620 - activeTop;

    // Resize the input buffer.
    // The RGB data is triples of 16-bit unsigned numbers in native byte order.
    rgbFrame.resize(activeWidth * activeHeight * 3 * 2);

    // Resize the output buffers.
    Y.resize(videoParameters.fieldWidth);
    U.resize(videoParameters.fieldWidth);
    V.resize(videoParameters.fieldWidth);
}

bool PALEncoder::encode()
{
    // Store video parameters
    metaData.setVideoParameters(videoParameters);

    // Process frames until EOF
    qint32 numFrames = 0;
    while (true) {
        qint32 result = encodeFrame(numFrames);
        if (result == -1) {
            return false;
        } else if (result == 0) {
            break;
        }
        numFrames++;
    }

    return true;
}

// Read one frame from the input, and write two fields to the output.
// Returns 0 on EOF, 1 on success; on failure, prints an error and returns -1.
qint32 PALEncoder::encodeFrame(qint32 frameNo)
{
    // Read the input frame
    qint64 remainBytes = rgbFrame.size();
    qint64 posBytes = 0;
    while (remainBytes > 0) {
        qint64 count = rgbFile.read(rgbFrame.data() + posBytes, remainBytes);
        if (count == 0 && remainBytes == rgbFrame.size()) {
            // EOF at the start of a frame
            return 0;
        } else if (count == 0) {
            qCritical() << "Unexpected end of input file";
            return -1;
        } else if (count < 0) {
            qCritical() << "Error reading from input file";
            return -1;
        }
        remainBytes -= count;
        posBytes += count;
    }

    // Write the two fields -- even-numbered lines, then odd-numbered lines.
    // In a PAL TBC file, the first field is the one that starts with the
    // half-line (i.e. frame line 44, when counting from 0).
    if (!encodeField(frameNo * 2)) {
        return -1;
    }
    if (!encodeField((frameNo * 2) + 1)) {
        return -1;
    }

    return 1;
}

// Encode one field from rgbFrame to the output.
// Returns true on success; on failure, prints an error and returns false.
bool PALEncoder::encodeField(qint32 fieldNo)
{
    const qint32 lineOffset = fieldNo % 2;

    // TBC data is unsigned 16-bit values in native byte order
    QVector<quint16> outputLine;

    for (qint32 frameLine = 0; frameLine < 2 * videoParameters.fieldHeight; frameLine++) {
        // Skip lines that aren't in this field
        if ((frameLine % 2) != lineOffset) {
            continue;
        }

        // Encode the line
        const quint16 *rgbData = nullptr;
        if (frameLine >= activeTop && frameLine < (activeTop + activeHeight)) {
            rgbData = reinterpret_cast<const quint16 *>(rgbFrame.data()) + ((frameLine - activeTop) * activeWidth * 3);
        }
        encodeLine(fieldNo, frameLine, rgbData, outputLine);

        // Write the line to the TBC file
        const char *outputData = reinterpret_cast<const char *>(outputLine.data());
        qint64 remainBytes = outputLine.size() * 2;
        qint64 posBytes = 0;
        while (remainBytes > 0) {
            qint64 count = tbcFile.write(outputData + posBytes, remainBytes);
            if (count < 0) {
                qCritical() << "Error writing to output file";
                return false;
            }
            remainBytes -= count;
            posBytes += count;
        }
    }

    // Generate field metadata
    LdDecodeMetaData::Field fieldData;
    fieldData.seqNo = fieldNo;
    fieldData.isFirstField = (fieldNo % 2) == 0;
    fieldData.syncConf = 100;
    // Burst peak-to-peak amplitude is 3/7 of black-white range
    fieldData.medianBurstIRE = 100.0 * (3.0 / 7.0) / 2.0;
    fieldData.fieldPhaseID = 0;
    fieldData.audioSamples = 0;
    metaData.appendField(fieldData);

    return true;
}

// Generate a gate waveform with raised-cosine transitions, with 50% points at given start and end times
static double raisedCosineGate(double t, double startTime, double endTime, double halfRiseTime)
{
    if (t < startTime - halfRiseTime) {
        return 0.0;
    } else if (t < startTime + halfRiseTime) {
        return 0.5 + (0.5 * sin((M_PI / 2.0) * ((t - startTime) / halfRiseTime)));
    } else if (t < endTime - halfRiseTime) {
        return 1.0;
    } else if (t < endTime + halfRiseTime) {
        return 0.5 - (0.5 * sin((M_PI / 2.0) * ((t - endTime) / halfRiseTime)));
    } else {
        return 0.0;
    }
}

// Types of sync pulse [Poynton p521]
enum SyncPulseType {
    NONE = 0,
    NORMAL,
    EQUALISATION,
    BROAD
};

// Generate a gate waveform for a sync pulse in one half of a line
static double syncPulseGate(double t, double startTime, SyncPulseType type)
{
    // Timings from [Poynton p521]
    double length;
    switch (type) {
    case NONE:
        return 0.0;
    case NORMAL:
        length = 4.7e-6;
        break;
    case EQUALISATION:
        length = 4.7e-6 / 2.0;
        break;
    case BROAD:
        length = (64.0e-6 / 2.0) - 4.7e-6;
        break;
    }

    return raisedCosineGate(t, startTime, startTime + length, 200.0e-9 / 2.0);
}

// 1.3 MHz low-pass Gaussian filter, as used in pyctools-pal's coder.
// Generated by: c = scipy.signal.gaussian(13, 1.49); c / sum(c)
//
// The UV filter should be 0 dB at 0 Hz, >= -3 dB at 1.3 MHz, <= -20 dB at
// 4.0 MHz. [Clarke p8]
static constexpr std::array<double, 13> uvFilterCoeffs {
    8.06454142158873e-05, 0.0009604748783110286, 0.007290763490157312, 0.035272860169480155, 0.10876496139131472,
    0.21375585039760908, 0.2677488885178237, 0.21375585039760908, 0.10876496139131472, 0.035272860169480155,
    0.007290763490157312, 0.0009604748783110286, 8.06454142158873e-05
};
static constexpr auto uvFilter = makeFIRFilter(uvFilterCoeffs);

void PALEncoder::encodeLine(qint32 fieldNo, qint32 frameLine, const quint16 *rgbData, QVector<quint16> &outputLine)
{
    // Resize the output line and fill with black
    qint32 lineLen = videoParameters.fieldWidth;
    if (!videoParameters.isSubcarrierLocked) {
        // Line-locked -- all lines are the same length
    } else if (frameLine == 625) {
        lineLen -= 4;
    } else if (frameLine == 623 || frameLine == 624) {
        lineLen += 2;
    }
    outputLine.resize(videoParameters.fieldWidth);
    outputLine.fill(videoParameters.black16bIre);
    if (frameLine == 625) {
        // Dummy last line
        return;
    }

    // How many complete lines have gone by since the start of the 4-frame sequence?
    const qint32 fieldID = fieldNo % 8; 
    const qint32 prevLines = ((fieldID / 2) * 625) + ((fieldID % 2) * 313) + (frameLine / 2);

    // Compute the time at which 0H occurs within the line (see above)
    double zeroH;
    if (videoParameters.isSubcarrierLocked) {
        zeroH = ((957.5 - 948) + ((prevLines % 625) * (4.0 / 625))) / sampleRate;
    } else {
        zeroH = 0.0;
    }

    // How many cycles of the subcarrier have gone by at 0H? [Poynton p529]
    const double prevCycles = prevLines * 283.7516;

    // Compute the V-switch state and colourburst phase on this line [Poynton p530]
    const double Vsw = (prevLines % 2) == 0 ? 1.0 : -1.0;
    const double burstOffset = Vsw * 135.0 * M_PI / 180.0;

    // Burst peak-to-peak amplitude is 3/7 of black-white range [Poynton p532 eq 44.3]
    double burstAmplitude = 3.0 / 7.0;

    // Compute colourburst gating times, relative to 0H [Poynton p530]
    const double halfBurstRiseTime = 300.0e-9 / 2.0;
    const double burstStartTime = 5.6e-6;
    const double burstEndTime = burstStartTime + (10.0 / fSC);

    // Compute luma/chroma gating times, relative to 0H, to avoid sharp
    // transitions at the edge of the active region. The rise times are as
    // suggested in [Poynton p323], timed so that the video reaches full
    // amplitude at the start/end of the active region.
    const double halfLumaRiseTime = 2.0 / (4.0 * fSC);
    const double halfChromaRiseTime = 3.0 / (4.0 * fSC);
    double activeStartTime = (videoParameters.activeVideoStart / sampleRate) - zeroH - (2.0 * halfChromaRiseTime);
    double activeEndTime = (videoParameters.activeVideoEnd / sampleRate) - zeroH + (2.0 * halfChromaRiseTime);

    // Adjust gating for half-lines [Poynton p525]
    if (frameLine == 44) {
        activeStartTime = 42.5e-6;
    }
    if (frameLine == 619) {
        activeEndTime = 30.35e-6;
    }

    // Compute sync pulse times and pattern, relative to 0H [Poynton p520]
    // Sync level is -300mV, or 0x0100 [EBU p6]
    const double syncLevel = -0.3 / 0.7;
    const double leftSyncStartTime = 0.0;
    const double rightSyncStartTime = 64.0e-6 / 2.0;
    SyncPulseType leftSyncType = NORMAL;
    if (frameLine < 5) {
        leftSyncType = BROAD;
    } else if (frameLine >= 5 && frameLine < 10) {
        leftSyncType = EQUALISATION;
    } else if (frameLine >= 620) {
        leftSyncType = EQUALISATION;
    }
    SyncPulseType rightSyncType = NONE;
    if (frameLine < 4) {
        rightSyncType = BROAD;
    } else if (frameLine >= 4 && frameLine < 9) {
        rightSyncType = EQUALISATION;
    } else if (frameLine >= 619 && frameLine < 624) {
        rightSyncType = EQUALISATION;
    } else if (frameLine == 624) {
        rightSyncType = BROAD;
    }

    // Burst suppression [Poynton p520]
    if (leftSyncType != NORMAL) {
        burstAmplitude = 0.0;
    } else if (frameLine == 619) {
        burstAmplitude = 0.0;
    } else if (Vsw < 0 && (frameLine == 10 || frameLine == 11 || frameLine == 618)) {
        burstAmplitude = 0.0;
    }

    // Clear Y'UV buffers. Values in these are scaled so that 0.0 is black and
    // 1.0 is white.
    Y.fill(0.0);
    U.fill(0.0);
    V.fill(0.0);

    if (rgbData != nullptr) {
        // Convert the R'G'B' data to Y'UV form [Poynton p337 eq 28.5]
        for (qint32 i = 0; i < activeWidth; i++) {
            const double R = rgbData[i * 3]       / 65535.0;
            const double G = rgbData[(i * 3) + 1] / 65535.0;
            const double B = rgbData[(i * 3) + 2] / 65535.0;

            qint32 x = activeLeft + i;
            if (videoParameters.isSubcarrierLocked && (fieldNo % 2) == 1) {
                x += 2;
            }
            Y[x] = (R * 0.299)     + (G * 0.587)     + (B * 0.114);
            U[x] = (R * -0.147141) + (G * -0.288869) + (B * 0.436010);
            V[x] = (R * 0.614975)  + (G * -0.514965) + (B * -0.100010);
        }

        // Low-pass filter U and V to 1.3 MHz [Poynton p342]
        uvFilter.apply(U);
        uvFilter.apply(V);
    }

    for (qint32 x = 0; x < outputLine.size(); x++) {
        // For this sample, compute time relative to 0H, and subcarrier phase
        const double t = (x / sampleRate) - zeroH;
        const double a = 2.0 * M_PI * ((fSC * t) + prevCycles);

        // Generate colourburst
        const double burst = sin(a + burstOffset) * burstAmplitude / 2.0;

        // Encode the chroma signal [Poynton p338]
        const double chroma = (U[x] * sin(a)) + (V[x] * cos(a) * Vsw);

        // Combine everything to make up the composite signal
        const double burstGate = raisedCosineGate(t, burstStartTime, burstEndTime, halfBurstRiseTime);
        const double lumaGate = raisedCosineGate(t, activeStartTime, activeEndTime, halfLumaRiseTime);
        const double chromaGate = raisedCosineGate(t, activeStartTime, activeEndTime, halfChromaRiseTime);
        const double leftSyncGate = syncPulseGate(t, leftSyncStartTime, leftSyncType);
        const double rightSyncGate = syncPulseGate(t, rightSyncStartTime, rightSyncType);
        const double composite = (burst * burstGate)
                                 + qBound(-lumaGate, Y[x], lumaGate)
                                 + qBound(-chromaGate, chroma, chromaGate)
                                 + (syncLevel * (leftSyncGate + rightSyncGate));

        // Scale to a 16-bit output sample and limit the excursion to the
        // permitted sample values. [EBU p6]
        //
        // With line-locked sampling, some colours (e.g. the yellow colourbar)
        // can result in values outside this range because there isn't enough
        // headroom.
        const double scaled = (composite * (videoParameters.white16bIre - videoParameters.black16bIre)) + videoParameters.black16bIre;
        outputLine[x] = qBound(static_cast<double>(0x0100), scaled, static_cast<double>(0xFEFF));
    }
}
