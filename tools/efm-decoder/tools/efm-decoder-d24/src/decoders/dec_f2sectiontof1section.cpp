/************************************************************************

    dec_f2sectiontof1section.cpp

    ld-efm-decoder - EFM data decoder
    Copyright (C) 2025 Simon Inns

    This file is part of ld-decode-tools.

    ld-efm-decoder is free software: you can redistribute it and/or
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

#include "dec_f2sectiontof1section.h"

F2SectionToF1Section::F2SectionToF1Section() :
    m_delayLine1({ 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1,
        0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1 }),
    m_delayLine2({ 0, 0, 0, 0, 2, 2, 2, 2, 0, 0, 0, 0, 2, 2, 2, 2, 0, 0, 0, 0, 2, 2, 2, 2 }),
    m_delayLineM({ 108, 104, 100, 96, 92, 88, 84, 80, 76, 72, 68, 64, 60, 56,
        52,  48,  44,  40, 36, 32, 28, 24, 20, 16, 12, 8,  4,  0 }),
    m_validInputF2FramesCount(0),
    m_invalidInputF2FramesCount(0),
    m_invalidOutputF1FramesCount(0),
    m_validOutputF1FramesCount(0),
    m_inputByteErrors(0),
    m_outputByteErrors(0),
    m_dlLostFramesCount(0),
    m_lastFrameNumber(-1),
    m_continuityErrorCount(0),
    m_invalidPaddedF1FramesCount(0),
    m_invalidNonPaddedF1FramesCount(0)
{}

void F2SectionToF1Section::pushSection(const F2Section &f2Section)
{
    // Add the data to the input buffer
    m_inputBuffer.enqueue(f2Section);

    // Process the queue
    processQueue();
}

F1Section F2SectionToF1Section::popSection()
{
    // Return the first item in the output buffer
    return m_outputBuffer.dequeue();
}

bool F2SectionToF1Section::isReady() const
{
    // Return true if the output buffer is not empty
    return !m_outputBuffer.isEmpty();
}

// Note: The F2 frames will not be correct until the delay lines are full
// So lead-in is required to prevent loss of the input date.  For now we will
// just discard the data until the delay lines are full.
void F2SectionToF1Section::processQueue()
{
    // Process the input buffer
    while (!m_inputBuffer.isEmpty()) {
        F2Section f2Section = m_inputBuffer.dequeue();
        F1Section f1Section;

        // Sanity check the F2 section
        if (!f2Section.isComplete()) {
            qFatal("F2SectionToF1Section::processQueue - F2 Section is not complete");
        }

        // Check section continuity
        if (m_lastFrameNumber != -1) {
            if (f2Section.metadata.absoluteSectionTime().frames()
                != m_lastFrameNumber + 1) {
                qWarning() << "F2 Section continuity error last frame:" << m_lastFrameNumber
                           << "current frame:"
                           << f2Section.metadata.absoluteSectionTime().frames();
                qWarning() << "Last section time:"
                           << f2Section.metadata.absoluteSectionTime().toString();
                qWarning() << "This is a bug in the F2 Metadata correction and should be reported";
                m_continuityErrorCount++;
            }
            m_lastFrameNumber = f2Section.metadata.absoluteSectionTime().frames();
        } else {
            m_lastFrameNumber = f2Section.metadata.absoluteSectionTime().frames();
        }

        for (int index = 0; index < 98; index++) {
            QVector<quint8> data = f2Section.frame(index).data();
            QVector<bool> errorData = f2Section.frame(index).errorData();
            QVector<bool> paddedData = f2Section.frame(index).paddedData();

            // Check F2 frame for errors (counts only when errorData = 1)
            quint32 inFrameErrors = f2Section.frame(index).countErrors();
            if (inFrameErrors == 0)
                m_validInputF2FramesCount++;
            else {
                m_invalidInputF2FramesCount++;
                m_inputByteErrors += inFrameErrors;
            }

            m_delayLine1.push(data, errorData, paddedData);
            if (data.isEmpty()) {
                // Output an empty F1 frame (ensures the section is complete)
                // Note: This isn't an error frame, it's just an empty frame
                F1Frame f1Frame;
                f1Frame.setData(QVector<quint8>(24, 0));
                f1Frame.setErrorData(QVector<bool>(24, false));
                f1Frame.setPaddedData(QVector<bool>(24, false));
                f1Section.pushFrame(f1Frame);
                m_dlLostFramesCount++;
                continue;
            }

            // Process the data
            // Note: We will only get valid data if the delay lines are all full
            m_inverter.invertParity(data);

            m_circ.c1Decode(data, errorData, paddedData, m_showDebug);

            m_delayLineM.push(data, errorData, paddedData);
            if (data.isEmpty()) {
                // Output an empty F1 frame (ensures the section is complete)
                // Note: This isn't an error frame, it's just an empty frame
                F1Frame f1Frame;
                f1Frame.setData(QVector<quint8>(24, 0));
                f1Frame.setErrorData(QVector<bool>(24, false));
                f1Frame.setPaddedData(QVector<bool>(24, false));
                f1Section.pushFrame(f1Frame);
                m_dlLostFramesCount++;
                continue;
            }

            // Only perform C2 decode if delay line 1 is full and delay line M is full
            m_circ.c2Decode(data, errorData, paddedData, m_showDebug);

            if (m_showDebug && errorData.contains(true)) {
                qDebug().noquote().nospace() << "F2SectionToF1Section - F2 Frame [" << index << "]: C2 Failed in section " << f2Section.metadata.absoluteSectionTime().toString();
            }

            m_interleave.deinterleave(data, errorData, paddedData);

            m_delayLine2.push(data, errorData, paddedData);
            if (data.isEmpty()) {
                // Output an empty F1 frame (ensures the section is complete)
                // Note: This isn't an error frame, it's just an empty frame
                F1Frame f1Frame;
                f1Frame.setData(QVector<quint8>(24, 0));
                f1Frame.setErrorData(QVector<bool>(24, false));
                f1Frame.setPaddedData(QVector<bool>(24, false));
                f1Section.pushFrame(f1Frame);
                m_dlLostFramesCount++;
                continue;
            }

            // Put the resulting data (and error data) into an F1 frame and
            // push it to the output buffer
            F1Frame f1Frame;
            f1Frame.setData(data);
            f1Frame.setErrorData(errorData);
            f1Frame.setPaddedData(paddedData);

            // Check F1 frame for errors
            // Note: The error C2 count will differ from the overall error F1 count
            // due to the the interleaving which will distribute the errors over more
            // than on frame (potentially)
            quint32 outFrameErrors = f1Frame.countErrors();
            quint32 outFramePadding = f1Frame.countPadded();

            if (outFrameErrors == 0 && outFramePadding == 0)
                m_validOutputF1FramesCount++;
            else {
                m_invalidOutputF1FramesCount++;
                m_outputByteErrors += outFrameErrors;

                // Invalid with or without padding?
                if (outFramePadding > 0) m_invalidPaddedF1FramesCount++;
                else m_invalidNonPaddedF1FramesCount++;
            }

            f1Section.pushFrame(f1Frame);
        }

        // All frames in the section are processed
        f1Section.metadata = f2Section.metadata;

        // Add the section to the output buffer
        m_outputBuffer.enqueue(f1Section);
    }
}

void F2SectionToF1Section::showData(const QString &description, qint32 index, const QString &timeString,
                                    QVector<quint8> &data, QVector<quint8> &dataError)
{
    // Early return if no errors to avoid string processing
    bool hasError = false;
    for (const quint8 error : dataError) {
        if (error != 0) {
            hasError = true;
            break;
        }
    }
    if (!hasError) return;

    // Pre-allocate string with approximate size needed
    QString dataString;
    dataString.reserve(data.size() * 3);

    // Process data only if we know we need to display it
    for (int i = 0; i < data.size(); ++i) {
        if (dataError[i] == 0) {
            // Faster than QString::arg for hex conversion
            if (data[i] < 0x10) dataString.append('0');
            dataString.append(QString::number(data[i], 16));
            dataString.append(' ');
        } else {
            dataString.append(QStringLiteral("XX "));
        }
    }

    qDebug().nospace().noquote() << "F2SectionToF1Section - " << description << "["
                                 << QString::number(index).rightJustified(2, '0') << "]: ("
                                 << timeString << ") " << dataString << "XX=ERROR";
}

void F2SectionToF1Section::showStatistics()
{
    qInfo() << "F2 Section to F1 Section statistics:";
    qInfo() << "  Input F2 Frames:";
    qInfo() << "    Valid frames:" << m_validInputF2FramesCount;
    qInfo() << "    Corrupt frames:" << m_invalidInputF2FramesCount << "frames containing"
            << m_inputByteErrors << "byte errors";
    qInfo() << "    Delay line lost frames:" << m_dlLostFramesCount;
    qInfo() << "    Continuity errors:" << m_continuityErrorCount;

    qInfo() << "  Output F1 Frames (after CIRC):";
    qInfo() << "    Valid frames:" << m_validOutputF1FramesCount;
    qInfo() << "    Invalid frames due to padding:" << m_invalidPaddedF1FramesCount;
    qInfo() << "    Invalid frames without padding:" << m_invalidNonPaddedF1FramesCount;
    qInfo() << "    Invalid frames (total):" << m_invalidOutputF1FramesCount;
    qInfo() << "    Output byte errors:" << m_outputByteErrors;

    qInfo() << "  C1 decoder:";
    qInfo() << "    Valid C1s:" << m_circ.validC1s();
    qInfo() << "    Fixed C1s:" << m_circ.fixedC1s();
    qInfo() << "    Error C1s:" << m_circ.errorC1s();

    qInfo() << "  C2 decoder:";
    qInfo() << "    Valid C2s:" << m_circ.validC2s();
    qInfo() << "    Fixed C2s:" << m_circ.fixedC2s();
    qInfo() << "    Error C2s:" << m_circ.errorC2s();
}