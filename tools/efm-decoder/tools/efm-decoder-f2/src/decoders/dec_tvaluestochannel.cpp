/************************************************************************

    dec_tvaluestochannel.cpp

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

#include "dec_tvaluestochannel.h"

TvaluesToChannel::TvaluesToChannel()
{
    // Statistics
    m_consumedTValues = 0;
    m_discardedTValues = 0;
    m_channelFrameCount = 0;

    m_perfectFrames = 0;
    m_longFrames = 0;
    m_shortFrames = 0;

    m_overshootSyncs = 0;
    m_undershootSyncs = 0;
    m_perfectSyncs = 0;

    // Set the initial state
    m_currentState = ExpectingInitialSync;

    m_tvalueDiscardCount = 0;
}

void TvaluesToChannel::pushFrame(const QByteArray &data)
{
    // Add the data to the input buffer
    m_inputBuffer.enqueue(data);

    // Process the state machine
    processStateMachine();
}

QByteArray TvaluesToChannel::popFrame()
{
    // Return the first item in the output buffer
    return m_outputBuffer.dequeue();
}

bool TvaluesToChannel::isReady() const
{
    // Return true if the output buffer is not empty
    return !m_outputBuffer.isEmpty();
}

void TvaluesToChannel::processStateMachine()
{
    // Add the input data to the internal t-value buffer
    m_internalBuffer.append(m_inputBuffer.dequeue());

    // We need 588 bits to make a frame.  Every frame starts with T11+T11.
    // So the minimum number of t-values we need is 54 and
    // the maximum number of t-values we can have is 191.  This upper limit
    // is where we need to maintain the buffer size (at 382 for 2 frames).

    while (m_internalBuffer.size() > 382) {
        switch (m_currentState) {
        case ExpectingInitialSync:
            //qDebug() << "TvaluesToChannel::processStateMachine() - State: ExpectingInitialSync";
            m_currentState = expectingInitialSync();
            break;
        case ExpectingSync:
            //qDebug() << "TvaluesToChannel::processStateMachine() - State: ExpectingSync";
            m_currentState = expectingSync();
            break;
        case HandleOvershoot:
            //qDebug() << "TvaluesToChannel::processStateMachine() - State: HandleOvershoot";
            m_currentState = handleOvershoot();
            break;
        case HandleUndershoot:
            //qDebug() << "TvaluesToChannel::processStateMachine() - State: HandleUndershoot";
            m_currentState = handleUndershoot();
            break;
        }
    }
}

TvaluesToChannel::State TvaluesToChannel::expectingInitialSync()
{
    State nextState = ExpectingInitialSync;

    // Expected sync header
    QByteArray t11_t11 = QByteArray::fromHex("0B0B");

    // Does the buffer contain a T11+T11 sequence?
    int initialSyncIndex = m_internalBuffer.indexOf(t11_t11);

    if (initialSyncIndex != -1) {
        if (m_showDebug) {
            if (m_tvalueDiscardCount > 0)
                qDebug() << "TvaluesToChannel::expectingInitialSync() - Initial sync header found after" << m_tvalueDiscardCount << "discarded T-values";
            else
                qDebug() << "TvaluesToChannel::expectingInitialSync() - Initial sync header found";
        }

        m_tvalueDiscardCount = 0;
        nextState = ExpectingSync;
    } else {
        // Drop all but the last T-value in the buffer
        m_tvalueDiscardCount += m_internalBuffer.size() - 1;
        m_discardedTValues += m_internalBuffer.size() - 1;
        m_internalBuffer = m_internalBuffer.right(1);
    }

    return nextState;
}

TvaluesToChannel::State TvaluesToChannel::expectingSync()
{
    State nextState = ExpectingSync;

    // The internal buffer contains a valid sync at the start
    // Find the next sync header after it
    QByteArray t11_t11 = QByteArray::fromHex("0B0B");
    int syncIndex = m_internalBuffer.indexOf(t11_t11, 2);

    // Do we have a valid second sync header?
    if (syncIndex != -1) {
        // Extract the frame data from (and including) the first sync header until
        // (but not including) the second sync header
        QByteArray frameData = m_internalBuffer.left(syncIndex);

        // Do we have exactly 588 bits of data?  Count the T-values
        int bitCount = countBits(frameData);

        // If the frame data is 550 to 600 bits, we have a valid frame
        if (bitCount > 550 && bitCount < 600) {
            if (bitCount != 588) {
                if (m_showDebug) qDebug() << "TvaluesToChannel::expectingSync() - Got frame with" << bitCount << "bits - Treating as valid";
                if (bitCount > 588) attemptToFixOvershootFrame(frameData);
                if (bitCount < 588) attemptToFixUndershootFrame(0, syncIndex, frameData);
            }

            // We have a valid frame
            // Place the frame data into the output buffer
            m_outputBuffer.enqueue(frameData);
            
            m_consumedTValues += frameData.size();
            m_channelFrameCount++;
            m_perfectSyncs++;

            if (bitCount == 588)
                m_perfectFrames++;
            if (bitCount > 588)
                m_longFrames++;
            if (bitCount < 588)
                m_shortFrames++;

            // Remove the frame data from the internal buffer
            m_internalBuffer = m_internalBuffer.right(m_internalBuffer.size() - syncIndex);
            nextState = ExpectingSync;
        } else {
            // This is most likely a missing sync header issue rather than
            // one or more T-values being incorrect. So we'll handle that
            // separately.
            if (bitCount > 588) {
                nextState = HandleOvershoot;
            } else {
                nextState = HandleUndershoot;
            }
        }
    } else {
        // The buffer does not contain a valid second sync header, so throw it away
        
        if (m_showDebug)
            qDebug() << "TvaluesToChannel::expectingSync() - No second sync header found, sync lost - dropping" << m_internalBuffer.size() << "T-values";

        m_discardedTValues += m_internalBuffer.size();
        m_internalBuffer.clear();
        nextState = ExpectingInitialSync;
    }

    return nextState;
}

TvaluesToChannel::State TvaluesToChannel::handleUndershoot()
{
    State nextState = ExpectingSync;

    // The frame data is too short
    m_undershootSyncs++;

    // Find the second sync header
    QByteArray t11_t11 = QByteArray::fromHex("0B0B");
    int secondSyncIndex = m_internalBuffer.indexOf(t11_t11, 2);

    // Find the third sync header
    int thirdSyncIndex = m_internalBuffer.indexOf(t11_t11, secondSyncIndex + 2);

    // So, unless the data is completely corrupt we should have 588 bits between
    // the first and third sync headers (i.e. the second was a corrupt sync header) or
    // 588 bits between the second and third sync headers (i.e. the first was a corrupt sync header)
    //
    // If neither of these conditions are met, we have a corrupt frame data and we have to drop it

    if (thirdSyncIndex != -1) {
        // Value of the Ts between the first and third sync header
        int fttBitCount = countBits(m_internalBuffer, 0, thirdSyncIndex);

        // Value of the Ts between the second and third sync header
        int sttBitCount = countBits(m_internalBuffer, secondSyncIndex, thirdSyncIndex);

        if (fttBitCount > 550 && fttBitCount < 600) {
            if (m_showDebug)
                qDebug() << "TvaluesToChannel::handleUndershoot() - Undershoot frame - Value from first to third sync_header =" << fttBitCount << "bits - treating as valid";
            // Valid frame between the first and third sync headers
            QByteArray frameData = m_internalBuffer.left(thirdSyncIndex);
            qint32 bitCount = countBits(frameData);
            if (bitCount != 588) {
                if (m_showDebug) qDebug() << "TvaluesToChannel::handleUndershoot1() - Got frame with" << sttBitCount << "bits - Treating as valid";
                if (bitCount > 588) attemptToFixOvershootFrame(frameData);
                if (bitCount < 588) attemptToFixUndershootFrame(0, thirdSyncIndex, frameData);
            }
            m_outputBuffer.enqueue(frameData);
            
            m_consumedTValues += frameData.size();
            m_channelFrameCount++;

            if (fttBitCount == 588)
                m_perfectFrames++;
            if (fttBitCount > 588)
                m_longFrames++;
            if (fttBitCount < 588)
                m_shortFrames++;

            // Remove the frame data from the internal buffer
            m_internalBuffer = m_internalBuffer.right(m_internalBuffer.size() - thirdSyncIndex);
            nextState = ExpectingSync;
        } else if (sttBitCount > 550 && sttBitCount < 600) {
            if (m_showDebug)
                qDebug() << "TvaluesToChannel::handleUndershoot() - Undershoot frame - Value from second to third sync_header =" << sttBitCount << "bits - treating as valid";
            // Valid frame between the second and third sync headers
            QByteArray frameData = m_internalBuffer.mid(secondSyncIndex, thirdSyncIndex - secondSyncIndex);
            qint32 bitCount = countBits(frameData);
            if (bitCount != 588) {
                if (m_showDebug) qDebug() << "TvaluesToChannel::handleUndershoot2() - Got frame with" << sttBitCount << "bits - Treating as valid";
                if (bitCount > 588) attemptToFixOvershootFrame(frameData);
                if (bitCount < 588) attemptToFixUndershootFrame(secondSyncIndex, thirdSyncIndex, frameData);
            }
            m_outputBuffer.enqueue(frameData);

            m_consumedTValues += frameData.size();
            m_channelFrameCount++;

            if (sttBitCount == 588)
                m_perfectFrames++;
            if (sttBitCount > 588)
                m_longFrames++;
            if (sttBitCount < 588)
                m_shortFrames++;

            // Remove the frame data from the internal buffer
            m_discardedTValues += secondSyncIndex;
            m_internalBuffer = m_internalBuffer.right(m_internalBuffer.size() - thirdSyncIndex);
            nextState = ExpectingSync;
        } else {
            if (m_showDebug)
                qDebug() << "TvaluesToChannel::handleUndershoot() - First to third sync is" << fttBitCount << "bits, second to third sync is" << sttBitCount << ". Dropping (what might be a) frame.";
            nextState = ExpectingSync;

            // Remove the frame data from the internal buffer
            m_discardedTValues += secondSyncIndex;
            m_internalBuffer = m_internalBuffer.right(m_internalBuffer.size() - thirdSyncIndex);
        }
    } else {
        if (m_internalBuffer.size() <= 382) {
            if (m_showDebug)
                qDebug() << "TvaluesToChannel::handleUndershoot() - No third sync header found.  Staying in undershoot state waiting for more data.";
            nextState = HandleUndershoot;
        } else {
            if (m_showDebug)
                qDebug() << "TvaluesToChannel::handleUndershoot() - No third sync header found - Sync lost.  Dropping" << m_internalBuffer.size() - 1 << "T-values";
            
            m_discardedTValues += m_internalBuffer.size() - 1;
            m_internalBuffer = m_internalBuffer.right(1);
            nextState = ExpectingInitialSync;
        }
    }

    return nextState;
}

TvaluesToChannel::State TvaluesToChannel::handleOvershoot()
{
    State nextState = ExpectingSync;

    // The frame data is too long
    m_overshootSyncs++;

    // Is the overshoot due to a missing/corrupt sync header?
    // Count the bits between the first and second sync headers, if they are 588*2, split
    // the frame data into two frames
    QByteArray t11_t11 = QByteArray::fromHex("0B0B");

    // Find the second sync header
    int syncIndex = m_internalBuffer.indexOf(t11_t11, 2);

    // Do we have a valid second sync header?
    if (syncIndex != -1) {
        // Extract the frame data from (and including) the first sync header until
        // (but not including) the second sync header
        QByteArray frameData = m_internalBuffer.left(syncIndex);

        // Remove the frame data from the internal buffer
        m_internalBuffer = m_internalBuffer.right(m_internalBuffer.size() - syncIndex);

        // How many bits of data do we have?  Count the T-values
        int bitCount = countBits(frameData);

        // If the frame data is within the range of n frames, we have n frames
        // separated by corrupt sync headers
        const int frameSize = 588;
        const int tolerance = 11; // How close to 588 bits do we need to be?
        const int maxFrames = 10; // Define the maximum number of frames to check for
        bool validFrames = false;

        for (int n = 2; n <= maxFrames; ++n) {
            if (bitCount > frameSize * n - tolerance && bitCount < frameSize * n + tolerance) {
                validFrames = true;
                int accumulatedBits = 0;
                int endOfFrameIndex = 0;

                for (int i = 0; i < n; ++i) {
                    QByteArray singleFrameData;
                    while (accumulatedBits < frameSize && endOfFrameIndex < frameData.size()) {
                        accumulatedBits += frameData.at(endOfFrameIndex);
                        ++endOfFrameIndex;
                    }

                    singleFrameData = frameData.left(endOfFrameIndex);
                    frameData = frameData.right(frameData.size() - endOfFrameIndex);
                    accumulatedBits = 0;
                    endOfFrameIndex = 0;

                    quint32 singleFrameBitCount = countBits(singleFrameData);

                    // Place the frame into the output buffer
                    m_outputBuffer.enqueue(singleFrameData);

                    if (m_showDebug)
                        qDebug().nospace() << "TvaluesToChannel::handleOvershoot() - Overshoot frame split - " << singleFrameBitCount << " bits - frame split #" << i + 1;

                    m_consumedTValues += singleFrameData.size();
                    m_channelFrameCount++;

                    if (singleFrameBitCount == frameSize)
                    m_perfectFrames++;
                    if (singleFrameBitCount < frameSize)
                    m_longFrames++;
                    if (singleFrameBitCount > frameSize)
                    m_shortFrames++;
                }
                break;
            }
        }

        if (!validFrames) {
            if (m_showDebug) {
                qDebug() << "TvaluesToChannel::handleOvershoot() - Attempted overshoot recovery, but there were no sync headers in the data - are we processing noise?";
                qDebug() << "TvaluesToChannel::handleOvershoot() - Overshoot by " << bitCount << "bits, but no sync header found, dropping" << m_internalBuffer.size() - 1 << "T-values";
            }
            m_internalBuffer = m_internalBuffer.right(1);
            nextState = ExpectingInitialSync;
        } else {
            nextState = ExpectingSync;
        }
        } else {
        qFatal("TvaluesToChannel::handleOvershoot() - Overshoot frame detected but no second sync header found, even though it should have been there.");
    }

    return nextState;
}

// This function tries some basic tricks to fix a frame that is more than 588 bits long
void TvaluesToChannel::attemptToFixOvershootFrame(QByteArray &frameData)
{
    qint32 bitCount = countBits(frameData);

    if (bitCount > 588) {
        // We have too many bits, so we'll try to remove some
        // We'll remove the first T-value in the frame
        QByteArray lframeData = frameData.left(frameData.size() - 1);
        // ... and the last T-value in the frame
        QByteArray rframeData = frameData.right(frameData.size() - 1);
        qint32 lbitCount = countBits(lframeData);
        qint32 rbitCount = countBits(rframeData);

        if (lbitCount == 588) {
            frameData = lframeData;
            if (m_showDebug) qDebug() << "TvaluesToChannel::attemptToFixOvershootFrame() - Removed first T-value to fix frame";
        } else if (rbitCount == 588) {
            frameData = rframeData;
            if (m_showDebug) qDebug() << "TvaluesToChannel::attemptToFixOvershootFrame() - Removed last T-value to fix frame";
        }
    }
}

// This function tries some basic tricks to fix a frame that is less than 588 bits long
// Note: the start and end indexes refer to m_internalBuffer
void TvaluesToChannel::attemptToFixUndershootFrame(quint32 startIndex, quint32 endIndex, QByteArray &frameData)
{
    qint32 bitCount = countBits(frameData);

    if (bitCount < 588) {
        QByteArray lframeData = m_internalBuffer.mid(startIndex, endIndex + 1);     
        qint32 lbitCount = countBits(lframeData);

        if (lbitCount == 588) {
            frameData = lframeData;
            if (m_showDebug) qDebug() << "TvaluesToChannel::attemptToFixUndershootFrame() - Added additional last T-value to fix frame";
            return;
        }

        if (startIndex > 0) {
            QByteArray rframeData = m_internalBuffer.mid(startIndex -1, endIndex);          
            qint32 rbitCount = countBits(rframeData);

            if (rbitCount == 588) {
                frameData = rframeData;
                if (m_showDebug) qDebug() << "TvaluesToChannel::attemptToFixUndershootFrame() - Added additional first T-value to fix frame";
            }
        }
    }
}

// Count the number of bits in the array of T-values
quint32 TvaluesToChannel::countBits(const QByteArray &data, qint32 startPosition, qint32 endPosition)
{
    if (endPosition == -1)
        endPosition = data.size();

    quint32 bitCount = 0;
    for (int i = startPosition; i < endPosition; i++) {
        bitCount += data.at(i);
    }
    return bitCount;
}

void TvaluesToChannel::showStatistics()
{
    qInfo() << "T-values to Channel Frame statistics:";
    qInfo() << "  T-Values:";
    qInfo() << "    Consumed:" << m_consumedTValues;
    qInfo() << "    Discarded:" << m_discardedTValues;
    qInfo() << "  Channel frames:";
    qInfo() << "    Total:" << m_channelFrameCount;
    qInfo() << "    588 bits:" << m_perfectFrames;
    qInfo() << "    >588 bits:" << m_longFrames;
    qInfo() << "    <588 bits:" << m_shortFrames;
    qInfo() << "  Sync headers:";
    qInfo() << "    Good syncs:" << m_perfectSyncs;
    qInfo() << "    Overshoots:" << m_overshootSyncs;
    qInfo() << "    Undershoots:" << m_undershootSyncs;

    // When we overshoot and split the frame, we are guessing the sync header...
    qInfo() << "    Guessed:" << m_channelFrameCount - m_perfectSyncs - m_overshootSyncs - m_undershootSyncs;
}