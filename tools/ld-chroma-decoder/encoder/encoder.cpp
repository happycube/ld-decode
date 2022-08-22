/************************************************************************

    encoder.cpp

    ld-chroma-encoder - Composite video encoder
    Copyright (C) 2019-2022 Adam Sampson
    Copyright (C) 2022 Phillip Blucas

    This file is part of ld-decode-tools.

    ld-chroma-encoder is free software: you can redistribute it and/or
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
    \class Encoder

    This is the abstract base class for video encoders. A subclass of Encoder
    implements an encoder for a particular video standard.

    References:

    [Poynton] "Digital Video and HDTV Algorithms and Interfaces" by Charles
    Poynton, 2003, first edition, ISBN 1-55860-792-7. Later editions have less
    material about analogue video standards.

    [EBU] "Specification of interfaces for 625-line digital PAL signals",
    (https://tech.ebu.ch/docs/tech/tech3280.pdf) EBU Tech. 3280-E.

    [SMPTE] "System M/NTSC Composite Video Signals Bit-Parallel Digital Interface",
    (https://ieeexplore.ieee.org/document/7290873) SMPTE 244M-2003.

    [Clarke] "Colour encoding and decoding techniques for line-locked sampled
    PAL and NTSC television signals" (https://www.bbc.co.uk/rd/publications/rdreport_1986_02),
    BBC Research Department Report 1986/02, by C.K.P. Clarke.
 */

#include "encoder.h"

Encoder::Encoder(QFile &_rgbFile, QFile &_tbcFile, LdDecodeMetaData &_metaData)
    : rgbFile(_rgbFile), tbcFile(_tbcFile), metaData(_metaData)
{
}

bool Encoder::encode()
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
qint32 Encoder::encodeFrame(qint32 frameNo)
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
    // In a TBC file, the first field is always the one that starts with the
    // half-line (i.e. frame line 44 for PAL or 39 for NTSC, counting from 0).
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
bool Encoder::encodeField(qint32 fieldNo)
{
    const qint32 lineOffset = fieldNo % 2;

    // Output from the encoder
    std::vector<double> outputC(videoParameters.fieldWidth);
    std::vector<double> outputVBS(videoParameters.fieldWidth);

    // TBC data is unsigned 16-bit values in native byte order
    std::vector<quint16> outputLine(videoParameters.fieldWidth);

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
        encodeLine(fieldNo, frameLine, rgbData, outputC, outputVBS);

        // Scale to a 16-bit output sample and limit the excursion to the
        // permitted sample values. [EBU p6] [SMPTE p6]
        //
        // With PAL line-locked sampling, some colours (e.g. the yellow
        // colourbar) can result in values outside this range because there
        // isn't enough headroom.
        for (qint32 x = 0; x < videoParameters.fieldWidth; x++) {
            const double scaled = ((outputC[x] + outputVBS[x])
                                   * (videoParameters.white16bIre - videoParameters.black16bIre)) + videoParameters.black16bIre;
            outputLine[x] = qBound(static_cast<double>(0x0100), scaled, static_cast<double>(0xFEFF));
        }

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
    getFieldMetadata(fieldNo, fieldData);
    metaData.appendField(fieldData);

    return true;
}
