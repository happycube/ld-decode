/************************************************************************

    ntscencoder.cpp

    ld-chroma-encoder - NTSC encoder for testing
    Copyright (C) 2019 Adam Sampson
    Copyright (C) 2022 Phillip Blucas

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
    \class NTSCEncoder

    This is a simplistic NTSC encoder for decoder testing. The code aims to be
    accurate rather than fast.

    References:

    [Poynton] "Digital Video and HDTV Algorithms and Interfaces" by Charles
    Poynton, 2003, first edition, ISBN 1-55860-792-7. Later editions have less
    material about analog video standards.

    [SMPTE] "System M/NTSC Composite Video Signals Bit-Parallel Digital Interface",
    (https://ieeexplore.ieee.org/document/7290873) SMPTE 244M-2003.

    [Clarke] "Colour encoding and decoding techniques for line-locked sampled
    PAL and NTSC television signals" (https://www.bbc.co.uk/rd/publications/rdreport_1986_02),
    BBC Research Department Report 1986/02, by C.K.P. Clarke.
 */

#include "ntscencoder.h"

#include "firfilter.h"

#include <array>
#include <cmath>

NTSCEncoder::NTSCEncoder(QFile &_rgbFile, QFile &_tbcFile, LdDecodeMetaData &_metaData)
    : rgbFile(_rgbFile), tbcFile(_tbcFile), metaData(_metaData)
{
    // NTSC subcarrier frequency [Poynton p511]
    videoParameters.fSC = 315.0e6 / 88.0;

    videoParameters.sampleRate = 4 * videoParameters.fSC;

    // Parameters for 4fSC subcarrier-locked sampling:
    //
    // Each frame in the TBC file contains (910 * 526) samples.
    // The last line is ignored.
    //
    // Each 63.555 usec line is 910 samples long. The values
    // in this struct represent the sample numbers *on the first line*.
    //
    // The first sample in the TBC frame is the first blanking sample of
    // field 1 line 1, sample 768 of 910. 0H occurs 33/90 between samples
    // 784 and 785. [SMPTE p4]

    // Subcarrier is co-incident with 0H, i.e. SCH phase is 0. [Poynton p511]
    const double zeroH = 784 + 33.0 / 90.0 - 768;

    // Burst gate opens 19 cycles after 0H, and closes 9 cycles later.
    // [Poynton p512]
    const double burstStartPos = zeroH + (19 * 4);
    const double burstEndPos = burstStartPos + (9 * 4);
    videoParameters.colourBurstStart = static_cast<qint32>(lrint(burstStartPos));
    videoParameters.colourBurstEnd = static_cast<qint32>(lrint(burstEndPos));
    // The colorburst is sampled at -33, 57, 123 and 213 degrees, so the
    // sample values are [46, 83, 74, 37] * 0x100. [Poynton p517]

    // Center the 757+ analog active samples in the 768-sample digital active
    // area. [Poynton p517-518]
    videoParameters.activeVideoStart = (910 - 768) + ((768 - 758) / 2);
    videoParameters.activeVideoEnd = videoParameters.activeVideoStart + 758;

    videoParameters.numberOfSequentialFields = 0;
    videoParameters.system = NTSC;
    videoParameters.isSubcarrierLocked = true;

    // White level, black level, and blanking level, extended to 16 bits
    // [SMPTE p2, Poynton p517]
    videoParameters.white16bIre = 0xC800;
    const qint32 blankingIre = 0x3C00;
    const qint32 ntscSetup = 0x0A80;  // 10.5 * 256
    videoParameters.black16bIre = blankingIre + ntscSetup;  // (60 + 10.5) * 256
    videoParameters.fieldWidth = 910;
    videoParameters.fieldHeight = 263;
    videoParameters.isMapped = false;

    // Compute the location of the input image within the NTSC frame, based on
    // the parameters above.
    activeWidth = 758;
    activeLeft = ((videoParameters.activeVideoStart + videoParameters.activeVideoEnd) / 2) - (activeWidth / 2);
    activeTop = 39;
    activeHeight = 525 - activeTop;

    // Resize the input buffer.
    // The RGB data is triples of 16-bit unsigned numbers in native byte order.
    rgbFrame.resize(activeWidth * activeHeight * 3 * 2);

    // Resize the output buffers.
    Y.resize(videoParameters.fieldWidth);
    I.resize(videoParameters.fieldWidth);
    Q.resize(videoParameters.fieldWidth);
}

bool NTSCEncoder::encode()
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
qint32 NTSCEncoder::encodeFrame(qint32 frameNo)
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
    // In an NTSC TBC file, the first field is the one that starts with the
    // half-line (i.e. frame line 39, when counting from 0).
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
bool NTSCEncoder::encodeField(qint32 fieldNo)
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
    fieldData.medianBurstIRE = 20;
    fieldData.fieldPhaseID = fieldNo % 4;
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

// Types of sync pulse [Poynton p502]
enum SyncPulseType {
    NONE = 0,
    NORMAL,
    EQUALIZATION,
    BROAD
};

// Generate a gate waveform for a sync pulse in one half of a line
static double syncPulseGate(double t, double startTime, SyncPulseType type)
{
    // Timings from [Poynton p502]
    double length;
    switch (type) {
    case NONE:
        return 0.0;
    case NORMAL:
        length = 4.7e-6;
        break;
    case EQUALIZATION:
        length = 4.7e-6 / 2.0;
        break;
    case BROAD:
        length = ((63 + 5.0/9.0) / 2.0) * 1e-6 - 4.7e-6;
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

void NTSCEncoder::encodeLine(qint32 fieldNo, qint32 frameLine, const quint16 *rgbData, QVector<quint16> &outputLine)
{
    // Resize the output line and fill with black
    outputLine.resize(videoParameters.fieldWidth);
    outputLine.fill(videoParameters.black16bIre - 0x0A80);

    // Skip encoding the last (dummy) frameLine
    if (frameLine == 525)
        return;

    // How many complete lines have gone by since the start of the 4-field
    // sequence? Subcarrier is positive going at line 10, so adjust for
    // that here. [SMPTE p3]
    const qint32 fieldID = fieldNo % 4;
    qint32 prevLines = ((fieldID / 2) * 525) + ((fieldID % 2) * 263) + (frameLine / 2) - 10;
    // XXX The third field shouldn't be special like this. If anything,
    // colorframe B needs something, but prevLines seems correct.
    if (fieldID == 2)
        prevLines--;

    // Subcarrier is co-incident with 0H which is 33/90 after sample 784
    // [SMPTE p5] [Poynton p511]
    const double zeroH = (784 + 33.0 / 90.0 - 768) / videoParameters.sampleRate;

    // How many cycles of the subcarrier have gone by at 0H? [Poynton p511]
    // There are 227.5 cycles per lines (910/4). 0H is offset 33/90 of one
    // sample, which is 33/360 of one 4-sample cycle.
    const double prevCycles = prevLines * 227.5 + 33.0 / 360.0;

    // The colorburst is inverted from subcarrier [SMPTE p4] [Poynton p512]
    const double burstOffset = 227.5 * M_PI / 180.0;

    // Burst peak-to-peak amplitude is 2/5 of black-white range
    // [Poynton p516 eq 42.6]
    double burstAmplitude = 2.0 / 5.0;

    // Compute colorburst gating times, relative to 0H [Poynton p512]
    const double halfBurstRiseTime = 300.0e-9 / 2.0;
    const double burstStartTime = 19.0 / videoParameters.fSC;
    const double burstEndTime = burstStartTime + (9.0 / videoParameters.fSC);

    // Compute luma/chroma gating times, relative to 0H, to avoid sharp
    // transitions at the edge of the active region. The rise times are as
    // suggested in [Poynton p323], timed so that the video reaches full
    // amplitude at the start/end of the active region.
    const double halfLumaRiseTime = 2.0 / (4.0 * videoParameters.fSC);
    const double halfChromaRiseTime = 3.0 / (4.0 * videoParameters.fSC);
    double activeStartTime = (videoParameters.activeVideoStart / videoParameters.sampleRate) - zeroH - (2.0 * halfChromaRiseTime);
    double activeEndTime = (videoParameters.activeVideoEnd / videoParameters.sampleRate) - zeroH + (2.0 * halfChromaRiseTime);

    // Adjust gating for half-lines [Poynton p506]
    if (frameLine == 39) {
        activeStartTime = 41.259e-6;
    }
    if (frameLine == 524) {
        activeEndTime = 30.593e-6;
    }

    // Compute sync pulse times and pattern, relative to 0H [Poynton p520]
    // Sync level is -285.7mV, or 0x1000 [SMPTE p2]
    const double syncLevel = -285.7 / 714.3;
    const double leftSyncStartTime = 0.0;
    const double rightSyncStartTime = (63 + 5.0/9.0) / 2.0 * 1e-6;
    SyncPulseType leftSyncType = NORMAL;
    if (frameLine < 6) {
        leftSyncType = EQUALIZATION;
    } else if (frameLine >= 6 && frameLine < 12) {
        leftSyncType = BROAD;
    } else if (frameLine < 18) {
        leftSyncType = EQUALIZATION;
    }
    SyncPulseType rightSyncType = NONE;
    if (frameLine < 5) {
        rightSyncType = EQUALIZATION;
    } else if (frameLine >= 5 && frameLine < 11) {
        rightSyncType = BROAD;
    } else if (frameLine < 17) {
        rightSyncType = EQUALIZATION;
    } else if (frameLine == 524) {
        rightSyncType = EQUALIZATION;
    }

    // Burst suppression in VBI [SMPTE 170M p9]
    if (frameLine < 18) {
        burstAmplitude = 0.0;
    }

    // Clear Y'IQ buffers. Values in these are scaled so that 0.0 is black and
    // 1.0 is white.
    Y.fill(0.0);
    I.fill(0.0);
    Q.fill(0.0);

    if (rgbData != nullptr) {
        // Convert the R'G'B' data to Y'IQ form [Poynton p367 eq 30.2]
        for (qint32 i = 0; i < activeWidth; i++) {
            const double R = rgbData[i * 3]       / 65535.0;
            const double G = rgbData[(i * 3) + 1] / 65535.0;
            const double B = rgbData[(i * 3) + 2] / 65535.0;
            qint32 x = activeLeft + i;
            Y[x] = (R * 0.299)    + (G * 0.587)     + (B * 0.114);
            I[x] = (R * 0.595901) + (G * -0.274557) + (B * -0.321344);
            Q[x] = (R * 0.211537) + (G * -0.522736) + (B * 0.311200);
        }

        // Low-pass filter I and Q to 1.3 MHz [Poynton p342]
        uvFilter.apply(I);
        uvFilter.apply(Q);
    }

    for (qint32 x = 0; x < outputLine.size(); x++) {
        // For this sample, compute time relative to 0H, and subcarrier phase
        const double t = (x / videoParameters.sampleRate) - zeroH;
        const double a = 2.0 * M_PI * ((videoParameters.fSC * t) + prevCycles);

        // Generate colorburst
        const double burst = sin(a + burstOffset) * burstAmplitude / 2.0;

        // Encode the chroma signal [Poynton p368]
        const double chroma = Q[x] * sin(a + 33.0) + I[x] * cos(a + 33.0);

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
        // permitted sample values. [SMPTE p6]
        const double scaled = (composite * (videoParameters.white16bIre - videoParameters.black16bIre)) + videoParameters.black16bIre;
        outputLine[x] = qBound(static_cast<double>(0x0100), scaled, static_cast<double>(0xFEFF));
    }
}
