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

    This is a simplistic PAL encoder for decoder testing.

    The output includes the colourburst and encoded active region, with the
    reference carrier phase progressing appropriately over the 4-frame
    sequence. It doesn't include sync pulses or colourburst suppression
    (because ld-chroma-decoder doesn't currently need them), and the code aims
    to be accurate rather than fast.

    References below are to "Digital Video and HDTV Algorithms and Interfaces"
    by Charles Poynton, 2003, first edition, ISBN 1-55860-792-7. Later editions
    have less material about analogue video standards.
 */

#include "palencoder.h"

#include <cmath>

PALEncoder::PALEncoder(QFile &_rgbFile, QFile &_tbcFile, LdDecodeMetaData &_metaData)
    : rgbFile(_rgbFile), tbcFile(_tbcFile), metaData(_metaData)
{
    // PAL subcarrier frequency [Poynton p529]
    fSC = 4433618.75;

    // Initialise video parameters based on ld-decode's usual output.
    // numberOfSequentialFields will be computed automatically.
    videoParameters.isSourcePal = true;
    videoParameters.colourBurstStart = 98;
    videoParameters.colourBurstEnd = 138;
    videoParameters.activeVideoStart = 185;
    videoParameters.activeVideoEnd = 1107;
    videoParameters.white16bIre = 54016;
    videoParameters.black16bIre = 16384;
    videoParameters.fieldWidth = 1135;
    videoParameters.fieldHeight = 313;
    // If you change the sample rate, you will also need to recompute the
    // filter coefficients below.
    videoParameters.sampleRate = 17734375;
    // fsc in this struct is an integer, so it's not precise for PAL; the code
    // below uses fSC instead.
    videoParameters.fsc = 4433618;
    videoParameters.isMapped = false;

    // Initialise active region dimensions, based on ld-chroma-decoder's usual output.
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

    // Store video parameters, now we've generated all the fields
    metaData.setVideoParameters(videoParameters);

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
    QVector<quint16> outputLine(videoParameters.fieldWidth);

    for (qint32 frameLine = 0; frameLine < 2 * videoParameters.fieldHeight; frameLine++) {
        // Skip lines that aren't in this field
        if ((frameLine % 2) != lineOffset) {
            continue;
        }

        // Fill the line with black
        outputLine.fill(videoParameters.black16bIre);

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

// Apply a FIR filter
static void applyFIRFilter(QVector<double> &data, qint32 filterSize, const double filter[])
{
    const qint32 dataSize = data.size();
    QVector<double> tmp(dataSize);

    for (qint32 i = 0; i < dataSize; i++) {
        double v = 0.0;
        for (qint32 j = 0, k = i - (filterSize / 2); j < filterSize; j++, k++) {
            // Assume data is 0 outside the vector bounds
            if (k >= 0 && k < dataSize) {
                v += filter[j] * data[k];
            }
        }
        tmp[i] = v;
    }

    data = tmp;
}

// 1.3 MHz low-pass FIR filter.
// Generated by: scipy.signal.firwin(9, [1.3e6/17734375], window='hamming')
static constexpr qint32 UV_FILTER_SIZE = 9;
static constexpr double UV_FILTER[UV_FILTER_SIZE] = {
    0.01611319, 0.04614531, 0.12141641, 0.19982705, 0.23299608,
    0.19982705, 0.12141641, 0.04614531, 0.01611319
};

void PALEncoder::encodeLine(qint32 fieldNo, qint32 frameLine, const quint16 *rgbData, QVector<quint16> &outputLine)
{
    // Compute the subcarrier phase at the start of the line. [Poynton p529]
    // How many complete lines have gone by since the start of the 4-frame sequence?
    const qint32 fieldID = fieldNo % 8; 
    const qint32 prevLines = ((fieldID / 2) * 625) + ((fieldID % 2) * 312) + (frameLine / 2);
    // So how many cycles of the subcarrier have gone by?
    const double prevCycles = prevLines * 283.7516;

    // Compute the V-switch state and colourburst phase on this line [Poynton p530]
    const double Vsw = (prevLines % 2) == 0 ? 1.0 : -1.0;
    const double burstOffset = Vsw * 135.0 * M_PI / 180.0;

    // Compute colourburst gating profile [Poynton p530]
    const double halfBurstRiseTime = 300.0e-9 / 2.0;
    const double burstStartTime = (1.0 * videoParameters.colourBurstStart) / videoParameters.sampleRate;
    const double burstEndTime = (1.0 * videoParameters.colourBurstEnd) / videoParameters.sampleRate;

    // Compute luma/chroma gating profiles to avoid sharp transitions at the
    // edge of the active region. The rise times are as suggested in
    // [Poynton p323], timed so that the video reaches full amplitude at the
    // start/end of the active region.
    const double halfLumaRiseTime = 2.0 / (4.0 * fSC);
    const double halfChromaRiseTime = 3.0 / (4.0 * fSC);
    const double activeStartTime = ((1.0 * videoParameters.activeVideoStart) / videoParameters.sampleRate) - (2.0 * halfChromaRiseTime);
    const double activeEndTime = (1.0 * videoParameters.activeVideoEnd) / videoParameters.sampleRate + (2.0 * halfChromaRiseTime);

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

            const qint32 x = activeLeft + i;
            Y[x] = (R * 0.299)     + (G * 0.587)     + (B * 0.114);
            U[x] = (R * -0.147141) + (G * -0.288869) + (B * 0.436010);
            V[x] = (R * 0.614975)  + (G * -0.514965) + (B * -0.100010);
        }

        // Low-pass filter U and V to 1.3 MHz [Poynton p342]
        applyFIRFilter(U, UV_FILTER_SIZE, UV_FILTER);
        applyFIRFilter(V, UV_FILTER_SIZE, UV_FILTER);
    }

    for (qint32 x = 0; x < videoParameters.fieldWidth; x++) {
        // For this sample, compute time relative to start of line, and subcarrier phase
        const double t = (1.0 * x) / videoParameters.sampleRate;
        const double a = 2.0 * M_PI * ((fSC * t) + prevCycles);

        // Generate colourburst.
        // Burst peak-to-peak amplitude is 3/7 of black-white range. [Poynton p532 eq 44.3]
        const double burst = sin(a + burstOffset) * (3.0 / 7.0) / 2.0;

        // Encode the chroma signal [Poynton p338]
        const double chroma = (U[x] * sin(a)) + (V[x] * cos(a) * Vsw);

        // Combine everything to make up the composite signal
        const double burstGate = raisedCosineGate(t, burstStartTime, burstEndTime, halfBurstRiseTime);
        const double lumaGate = raisedCosineGate(t, activeStartTime, activeEndTime, halfLumaRiseTime);
        const double chromaGate = raisedCosineGate(t, activeStartTime, activeEndTime, halfChromaRiseTime);
        const double composite = (burst * burstGate) + qBound(-lumaGate, Y[x], lumaGate) + qBound(-chromaGate, chroma, chromaGate);

        // Scale to a 16-bit output sample and limit the excursion. Some RGB
        // colours (e.g. strongly saturated yellows) can go outside ld-decode's
        // usual range.
        const double scaled = (composite * (videoParameters.white16bIre - videoParameters.black16bIre)) + videoParameters.black16bIre;
        outputLine[x] = qBound(0.0, scaled, 65535.0);
    }
}
