/************************************************************************

    dec_channeltof3frame.cpp

    efm-decoder-f2 - EFM T-values to F2 Section decoder
    Copyright (C) 2025 Simon Inns

    This file is part of ld-decode-tools.

    This application is free software: you can redistribute it and/or
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

#include "dec_channeltof3frame.h"

ChannelToF3Frame::ChannelToF3Frame()
{
    // Statistics
    m_goodFrames = 0;
    m_undershootFrames = 0;
    m_overshootFrames = 0;

    m_validEfmSymbols = 0;
    m_invalidEfmSymbols = 0;

    m_validSubcodeSymbols = 0;
    m_invalidSubcodeSymbols = 0;
}

void ChannelToF3Frame::pushFrame(const QByteArray &data)
{
    // Add the data to the input buffer
    m_inputBuffer.enqueue(data);

    // Process queue
    processQueue();
}

F3Frame ChannelToF3Frame::popFrame()
{
    // Return the first item in the output buffer
    return m_outputBuffer.dequeue();
}

bool ChannelToF3Frame::isReady() const
{
    // Return true if the output buffer is not empty
    return !m_outputBuffer.isEmpty();
}

void ChannelToF3Frame::processQueue()
{
    while (!m_inputBuffer.isEmpty()) {
        // Extract the first item in the input buffer
        QByteArray frameData = m_inputBuffer.dequeue();

        // Count the number of bits in the frame
        int bitCount = 0;
        for (int i = 0; i < frameData.size(); ++i) {
            bitCount += frameData.at(i);
        }

        // Generate statistics
        if (bitCount != 588 && m_showDebug)
            qDebug() << "ChannelToF3Frame::processQueue() - Frame data is" << bitCount
                     << "bits (should be 588)";
        if (bitCount == 588)
            m_goodFrames++;
        if (bitCount < 588)
            m_undershootFrames++;
        if (bitCount > 588)
            m_overshootFrames++;

        // Create an F3 frame
        F3Frame f3Frame = createF3Frame(frameData);

        // Place the frame into the output buffer
        m_outputBuffer.enqueue(f3Frame);
    }
}

F3Frame ChannelToF3Frame::createF3Frame(const QByteArray &tValues)
{
    F3Frame f3Frame;

    // The channel frame data is:
    //   Sync Header: 24 bits (bits 0-23)
    //   Merging bits: 3 bits (bits 24-26)
    //   Subcode: 14 bits (bits 27-40)
    //   Merging bits: 3 bits (bits 41-43)
    //   Then 32x 17-bit data values (bits 44-587)
    //     Data: 14 bits
    //     Merging bits: 3 bits
    //
    // Giving a total of 588 bits

    // Convert the T-values to data
    QByteArray frameData = tvaluesToData(tValues);

    // Extract the subcode in bits 27-40
    quint16 subcode = m_efm.fourteenToEight(getBits(frameData, 27, 40));
    if (subcode == 300) {
        subcode = 0;
        m_invalidSubcodeSymbols++;
    } else {
        m_validSubcodeSymbols++;
    }

    // Extract the data values in bits 44-587 ignoring the merging bits
    QVector<quint8> dataValues;
    QVector<bool> errorValues;
    for (int i = 44; i < (frameData.size() * 8) - 13; i += 17) {
        quint16 dataValue = m_efm.fourteenToEight(getBits(frameData, i, i + 13));

        if (dataValue < 256) {
            dataValues.append(dataValue);
            errorValues.append(false);
            m_validEfmSymbols++;
        } else {
            dataValues.append(0);
            errorValues.append(true);
            m_invalidEfmSymbols++;
        }
    }

    // If the data values are not a multiple of 32 (due to undershoot), pad with zeros
    while (dataValues.size() < 32) {
        dataValues.append(0);
        errorValues.append(true);
    }

    // Create an F3 frame...

    // Determine the frame type
    if (subcode == 256)
        f3Frame.setFrameTypeAsSync0();
    else if (subcode == 257)
        f3Frame.setFrameTypeAsSync1();
    else
        f3Frame.setFrameTypeAsSubcode(subcode);

    // Set the frame data
    f3Frame.setData(dataValues);
    f3Frame.setErrorData(errorValues);

    return f3Frame;
}

QByteArray ChannelToF3Frame::tvaluesToData(const QByteArray &tValues)
{
    // Pre-allocate output buffer (each T-value generates at least 1 bit)
    QByteArray outputData;
    outputData.reserve((tValues.size() + 7) / 8);
    
    quint32 bitBuffer = 0;  // Use 32-bit buffer to avoid frequent byte writes
    int bitsInBuffer = 0;

    for (quint8 tValue : tValues) {
        // Validate T-value
        if (Q_UNLIKELY(tValue < 3 || tValue > 11)) {
            qFatal("ChannelToF3Frame::tvaluesToData(): T-value must be in the range 3 to 11.");
        }

        // Shift in 1 followed by (tValue-1) zeros
        bitBuffer = (bitBuffer << tValue) | (1U << (tValue - 1));
        bitsInBuffer += tValue;

        // Write complete bytes when we have 8 or more bits
        while (bitsInBuffer >= 8) {
            outputData.append(static_cast<char>(bitBuffer >> (bitsInBuffer - 8)));
            bitsInBuffer -= 8;
        }
    }

    // Handle remaining bits
    if (bitsInBuffer > 0) {
        bitBuffer <<= (8 - bitsInBuffer);
        outputData.append(static_cast<char>(bitBuffer));
    }

    return outputData;
}

quint16 ChannelToF3Frame::getBits(const QByteArray &data, int startBit, int endBit)
{
    // Validate input
    if (Q_UNLIKELY(startBit < 0 || startBit > 587 || endBit < 0 || endBit > 587 || startBit > endBit)) {
        qFatal("ChannelToF3Frame::getBits(): Invalid bit range (%d, %d)", startBit, endBit);
    }

    int startByte = startBit / 8;
    int endByte = endBit / 8;
    
    if (Q_UNLIKELY(endByte >= data.size())) {
        qFatal("ChannelToF3Frame::getBits(): Byte index %d exceeds data size %d", endByte, data.size());
    }

    // Fast path for bits within a single byte
    if (startByte == endByte) {
        quint8 mask = (0xFF >> (startBit % 8)) & (0xFF << (7 - (endBit % 8)));
        return (data[startByte] & mask) >> (7 - (endBit % 8));
    }

    // Handle multi-byte case
    quint16 result = 0;
    int bitsRemaining = endBit - startBit + 1;
    
    // Handle first byte
    int firstByteBits = 8 - (startBit % 8);
    quint8 mask = 0xFF >> (startBit % 8);
    result = (data[startByte] & mask) << (bitsRemaining - firstByteBits);
    
    // Handle middle bytes
    for (int i = startByte + 1; i < endByte; i++) {
        result |= (data[i] & 0xFF) << (bitsRemaining - firstByteBits - 8 * (i - startByte));
    }
    
    // Handle last byte
    int lastByteBits = (endBit % 8) + 1;
    mask = 0xFF << (8 - lastByteBits);
    result |= (data[endByte] & mask) >> (8 - lastByteBits);

    return result;
}

void ChannelToF3Frame::showStatistics()
{
    qInfo() << "Channel to F3 Frame statistics:";
    qInfo() << "  Channel Frames:";
    qInfo() << "    Total:" << m_goodFrames + m_undershootFrames + m_overshootFrames;
    qInfo() << "    Good:" << m_goodFrames;
    qInfo() << "    Undershoot:" << m_undershootFrames;
    qInfo() << "    Overshoot:" << m_overshootFrames;
    qInfo() << "  EFM symbols:";
    qInfo() << "    Valid:" << m_validEfmSymbols;
    qInfo() << "    Invalid:" << m_invalidEfmSymbols;
    qInfo() << "  Subcode symbols:";
    qInfo() << "    Valid:" << m_validSubcodeSymbols;
    qInfo() << "    Invalid:" << m_invalidSubcodeSymbols;
}