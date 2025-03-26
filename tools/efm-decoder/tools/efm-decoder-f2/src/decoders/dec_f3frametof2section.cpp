/************************************************************************

    dec_f3frametof2section.cpp

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

#include "dec_f3frametof2section.h"

F3FrameToF2Section::F3FrameToF2Section() :
    m_currentState(ExpectingInitialSync),
    m_inputF3Frames(0),
    m_presyncDiscardedF3Frames(0),
    m_goodSync0(0),
    m_undershootSync0(0),
    m_overshootSync0(0),
    m_discardedF3Frames(0),
    m_paddedF3Frames(0),
    m_missingSync0(0),
    m_badSyncCounter(0),
    m_lostSyncCounter(0),
    m_lastSectionMetadata(SectionMetadata())
{}

void F3FrameToF2Section::pushFrame(const F3Frame &data)
{
    m_internalBuffer.append(data);
    m_inputF3Frames++;
    processStateMachine();
}

F2Section F3FrameToF2Section::popSection()
{
    return m_outputBuffer.dequeue();
}

bool F3FrameToF2Section::isReady() const
{
    return !m_outputBuffer.isEmpty();
}

void F3FrameToF2Section::processStateMachine()
{
    if (m_internalBuffer.size() > 1) {
        switch (m_currentState) {
        case ExpectingInitialSync:
            m_currentState = expectingInitialSync();
            break;
        case ExpectingSync:
            m_currentState = expectingSync();
            break;
        case HandleValid:
            m_currentState = handleValid();
            break;
        case HandleUndershoot:
            m_currentState = handleUndershoot();
            break;
        case HandleOvershoot:
            m_currentState = handleOvershoot();
            break;
        case LostSync:
            m_currentState = lostSync();
            break;
        }
    }
}

F3FrameToF2Section::State F3FrameToF2Section::expectingInitialSync()
{
    State nextState = ExpectingInitialSync;

    // Does the internal buffer contain a sync0 frame?
    // Note: For the initial sync we are only using sync0 frames
    bool foundSync0 = false;
    for (int i = 0; i < m_internalBuffer.size(); ++i) {
        if (m_internalBuffer.at(i).f3FrameType() == F3Frame::Sync0) {
            m_presyncDiscardedF3Frames += i;
            // Discard all frames before the sync0 frame
            m_internalBuffer = m_internalBuffer.mid(i);
            foundSync0 = true;
            break;
        }
    }

    if (foundSync0) {
        qDebug() << "F3FrameToF2Section::expectingInitialSync - Found sync0 frame after discarding" << m_presyncDiscardedF3Frames << "frames";
        m_presyncDiscardedF3Frames = 0;
        nextState = ExpectingSync;
    } else {
        m_presyncDiscardedF3Frames += m_internalBuffer.size();
        m_internalBuffer.clear();
    }

    return nextState;
}

F3FrameToF2Section::State F3FrameToF2Section::expectingSync()
{
    State nextState = ExpectingSync;

    // Did we receive a sync0 frame?
    if (m_internalBuffer.last().f3FrameType() == F3Frame::Sync0) {
        // Extract the section frames and remove them from the internal buffer
        m_sectionFrames = m_internalBuffer.mid(0,  m_internalBuffer.size() - 1);
        m_internalBuffer = m_internalBuffer.mid(m_internalBuffer.size() - 1, 1);
    } else if (m_internalBuffer.last().f3FrameType() == F3Frame::Sync1) {
        // Is the previous frame a sync0 frame?
        if (m_internalBuffer.size() > 1 && m_internalBuffer.at(m_internalBuffer.size() - 2).f3FrameType() == F3Frame::Sync0) {
            // Keep waiting for a sync0 frame
            nextState = ExpectingSync;
            return nextState;
        } else {
            // Looks like we got a sync1 frame without a sync0 frame - make the previous
            // frame sync0 and process
            m_missingSync0++;
            m_internalBuffer[m_internalBuffer.size() - 2].setFrameTypeAsSync0();

            // Extract the section frames and remove them from the internal buffer
            m_sectionFrames = m_internalBuffer.mid(0,  m_internalBuffer.size() - 2);
            m_internalBuffer = m_internalBuffer.mid(m_internalBuffer.size() - 2, 1);
            if (m_showDebug) qDebug() << "F3FrameToF2Section::expectingSync - Got sync1 frame without a sync0 frame - section frame size is" << m_sectionFrames.size();
        }
    } else {
        // Keep waiting for a sync0 frame
        nextState = ExpectingSync;
        return nextState;
    }

    // Do we have a valid number of frames in the section?
    // Or do we have overshoot or undershoot?
    if (m_sectionFrames.size() == 98) {
        m_goodSync0++;
        nextState = HandleValid;
    } else if (m_sectionFrames.size() < 98) {
        m_undershootSync0++;
        nextState = HandleUndershoot;
    } else if (m_sectionFrames.size() > 98) {
        m_overshootSync0++;
        nextState = HandleOvershoot;
    }

    // Have we hit the bad sync limit?
    if (m_badSyncCounter > 3) {
        nextState = LostSync;
    }

    return nextState;
}

F3FrameToF2Section::State F3FrameToF2Section::handleValid()
{
    State nextState = ExpectingSync;

    // Output the section
    outputSection(false);

    // Reset the bad sync counter
    m_badSyncCounter = 0;

    nextState = ExpectingSync;
    return nextState;
}

F3FrameToF2Section::State F3FrameToF2Section::handleUndershoot()
{
    State nextState = HandleUndershoot;
    m_badSyncCounter++;

    // How much undershoot do we have?
    int padding = 98 - m_sectionFrames.size();

    if (padding > 4) {
        if (m_showDebug) qDebug() << "F3FrameToF2Section::handleUndershoot - Undershoot is" << padding << "frames; ignoring sync0 frame";
        // Put the section frames back into the internal buffer
        m_internalBuffer.append(m_sectionFrames);
        m_sectionFrames.clear();
        nextState = ExpectingSync;
    } else {
        m_paddedF3Frames += padding;
        if (m_showDebug) qDebug() << "F3FrameToF2Section::handleUndershoot - Padding section with" << padding << "frames";

        // If we are padding, we are introducing errors... The CIRC can correct these
        // provided they are distributed across the section; so the best policy here
        // is to interleave the padding with the (hopefully) valid section frames

        F3Frame emptyFrame;
        emptyFrame.setData(QVector<quint8>(32, 0));
        emptyFrame.setErrorData(QVector<bool>(32, true));
        emptyFrame.setPaddedData(QVector<bool>(32, false));
        emptyFrame.setFrameTypeAsSubcode(0);

        // The padding is interleaved with the section frames start
        // at position 4 (to avoid the sync0 and sync1 frames)
        for (int i = 0; i < padding; ++i) {
            m_sectionFrames.insert(4 + i, emptyFrame);
        }

        outputSection(true);
    }

    nextState = ExpectingSync;
    return nextState;
}

F3FrameToF2Section::State F3FrameToF2Section::handleOvershoot()
{
    State nextState = HandleOvershoot;

    // How many sections worth of data do we have?
    int frameCount = m_sectionFrames.size() / 98;
    int remainder = m_sectionFrames.size() % 98;
    if (m_showDebug) qDebug() << "F3FrameToF2Section::handleOvershoot - Got" << m_sectionFrames.size()
        << "frames, which is" << frameCount << "sections with a remainder of" << remainder << "frames";

    if (frameCount == 1) {
        // Delete frames from the start of the section buffer to make it 98 frames
        m_discardedF3Frames += remainder;
        m_sectionFrames = m_sectionFrames.mid(remainder);
        outputSection(true);
    } else {
        // Remove any frames that are not part of a complete section from the beginning of the section buffer
        m_discardedF3Frames += remainder;
        m_sectionFrames = m_sectionFrames.mid(remainder);

        // Break the section buffer into 98 frame sections and output them
        QVector<F3Frame> tempSectionFrames = m_sectionFrames;
        for (int i = 0; i < frameCount; ++i) {
            m_sectionFrames = tempSectionFrames.mid(0, 98);
            tempSectionFrames = tempSectionFrames.mid(98);
            outputSection(true);
        }
    }

    // Each missed sync is a bad sync
    m_badSyncCounter += frameCount;

    nextState = ExpectingSync;
    return nextState;
}

F3FrameToF2Section::State F3FrameToF2Section::lostSync()
{
    State nextState = ExpectingInitialSync;
    if (m_showDebug) qDebug() << "F3FrameToF2Section::lostSync - Lost section sync";
    m_lostSyncCounter++;
    m_badSyncCounter = 0;
    m_internalBuffer.clear();
    m_sectionFrames.clear();
    return nextState;
}

void F3FrameToF2Section::outputSection(bool showAddress)
{
    if (m_sectionFrames.size() != 98) {
        qFatal("F3FrameToF2Section::outputSection - Section size is not 98");
    }

    Subcode subcode;
    if (m_showDebug)
        subcode.setShowDebug(true);

    QByteArray subcodeData;
    for (int i = 0; i < 98; ++i) {
        subcodeData.append(m_sectionFrames[i].subcodeByte());
    }
    SectionMetadata sectionMetadata = subcode.fromData(subcodeData);

    F2Section f2Section;
    for (quint32 index = 0; index < 98; ++index) {
        F2Frame f2Frame;
        f2Frame.setData(m_sectionFrames[index].data());
        f2Frame.setErrorData(m_sectionFrames[index].errorData());
        f2Section.pushFrame(f2Frame);
    }

    // There is an edge case where a repaired Q-channel will pass CRC, but the data is still invalid
    // This is a sanity check for that case
    if (sectionMetadata.isRepaired()) {
        // Check the absolute time is within 10 frames of the last section
        if (sectionMetadata.absoluteSectionTime().frames() - m_lastSectionMetadata.absoluteSectionTime().frames() > 10) {
            qWarning() << "F3FrameToF2Section::outputSection - Repaired section has a large time difference from the last section - marking as invalid";
            sectionMetadata.setValid(false);
        }
    }

    f2Section.metadata = sectionMetadata;
    m_lastSectionMetadata = sectionMetadata;
    m_outputBuffer.enqueue(f2Section);

    if (m_showDebug && showAddress) qDebug() << "F3FrameToF2Section::outputSection - Outputing F2 section with address"
        << sectionMetadata.absoluteSectionTime().toString();
}

void F3FrameToF2Section::showStatistics()
{
    qInfo() << "F3 Frame to F2 Section statistics:";
    qInfo() << "  F3 Frames:";
    qInfo() << "    Input frames:" << m_inputF3Frames;
    qInfo() << "    Good sync0 frames:" << m_goodSync0;
    qInfo() << "    Missing sync0 frames:" << m_missingSync0;
    qInfo() << "    Undershoot sync0 frames:" << m_undershootSync0;
    qInfo() << "    Overshoot sync0 frames:" << m_overshootSync0;
    qInfo() << "    Lost sync:" << m_lostSyncCounter;
    qInfo() << "  Frame loss:";
    qInfo() << "    Presync discarded F3 frames:" << m_presyncDiscardedF3Frames;
    qInfo() << "    Discarded F3 frames:" << m_discardedF3Frames;
    qInfo() << "    Padded F3 frames:" << m_paddedF3Frames;
}