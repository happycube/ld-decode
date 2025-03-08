/************************************************************************

    dec_f1sectiontodata24section.cpp

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

#include "dec_f1sectiontodata24section.h"

F1SectionToData24Section::F1SectionToData24Section() :
    m_invalidF1FramesCount(0),
    m_validF1FramesCount(0),
    m_corruptBytesCount(0),
    m_paddedBytesCount(0),
    m_unpaddedF1FramesCount(0),
    m_paddedF1FramesCount(0)
{}

void F1SectionToData24Section::pushSection(const F1Section &f1Section)
{
    // Add the data to the input buffer
    m_inputBuffer.enqueue(f1Section);

    // Process the queue
    processQueue();
}

Data24Section F1SectionToData24Section::popSection()
{
    // Return the first item in the output buffer
    return m_outputBuffer.dequeue();
}

bool F1SectionToData24Section::isReady() const
{
    // Return true if the output buffer is not empty
    return !m_outputBuffer.isEmpty();
}

void F1SectionToData24Section::processQueue()
{
    // Process the input buffer
    while (!m_inputBuffer.isEmpty()) {
        F1Section f1Section = m_inputBuffer.dequeue();
        Data24Section data24Section;

        // Sanity check the F1 section
        if (!f1Section.isComplete()) {
            qFatal("F1SectionToData24Section::processQueue - F1 Section is not complete");
        }

        for (int index = 0; index < 98; ++index) {
            QVector<quint8> data = f1Section.frame(index).data();
            QVector<bool> errorData = f1Section.frame(index).errorData();
            QVector<bool> paddedData = f1Section.frame(index).paddedData();

            // ECMA-130 issue 2 page 16 - Clause 16
            // All byte pairs are swapped by the F1 Frame encoder
            if (data.size() == errorData.size()) {
                for (int i = 0; i < data.size() - 1; i += 2) {
                    qSwap(data[i], data[i + 1]);
                    qSwap(errorData[i], errorData[i + 1]);
                    qSwap(paddedData[i], paddedData[i + 1]);
                }
            } else {
                qFatal("Data and error data size mismatch in F1 frame %d", index);
            }

            // Check the error data (and count any flagged errors)
            quint32 errorCount = f1Section.frame(index).countErrors();

            m_corruptBytesCount += errorCount;

            if (errorCount > 0)
                ++m_invalidF1FramesCount;
            else
                ++m_validF1FramesCount;

            // Check the error data (and count any flagged padding)
            quint32 paddingCount = f1Section.frame(index).countPadded();
            m_paddedBytesCount += paddingCount;

            if (paddingCount > 0)
                ++m_paddedF1FramesCount;
            else
                ++m_unpaddedF1FramesCount;

            // Put the resulting data into a Data24 frame and push it to the output buffer
            Data24 data24;
            data24.setData(data);
            data24.setErrorData(errorData);
            data24.setPaddedData(paddedData);

            data24Section.pushFrame(data24);
        }

        // Transfer the metadata
        data24Section.metadata = f1Section.metadata;

        // Add the section to the output buffer
        m_outputBuffer.enqueue(data24Section);
    }
}

void F1SectionToData24Section::showStatistics()
{
    qInfo() << "F1 Section to Data24 Section statistics:";

    qInfo() << "  Frames:";
    qInfo() << "    Total F1 frames:" << m_validF1FramesCount + m_invalidF1FramesCount;
    qInfo() << "    Error-free F1 frames:" << m_validF1FramesCount;
    qInfo() << "    F1 frames containing errors:" << m_invalidF1FramesCount;
    qInfo() << "    Padded F1 frames:" << m_paddedF1FramesCount;
    qInfo() << "    Unpadded F1 frames:" << m_unpaddedF1FramesCount;

    qInfo() << "  Data:";
    quint32 validBytes = (m_validF1FramesCount + m_invalidF1FramesCount) * 24;
    double totalSize = validBytes + m_corruptBytesCount;

    if (totalSize < 1024) {
        // Show in bytes if less than 1KB
        qInfo().nospace().noquote() << "    Total bytes: " << validBytes + m_corruptBytesCount;
        qInfo().nospace().noquote() << "    Valid bytes: " << validBytes;
        qInfo().nospace().noquote() << "    Corrupt bytes: " << m_corruptBytesCount;
        qInfo().nospace().noquote() << "    Padded bytes: " << m_paddedBytesCount;
    } else if (totalSize < 1024 * 1024) {
        // Show in KB if less than 1MB
        double validKBytes = static_cast<double>(validBytes + m_corruptBytesCount) / 1024.0;
        double validOnlyKBytes = static_cast<double>(validBytes) / 1024.0;
        double corruptKBytes = static_cast<double>(m_corruptBytesCount) / 1024.0;
        double paddedKBytes = static_cast<double>(m_paddedBytesCount) / 1024.0;
        qInfo().nospace().noquote() << "    Total KBytes: " << QString::number(validKBytes, 'f', 2);
        qInfo().nospace().noquote() << "    Valid KBytes: " << QString::number(validOnlyKBytes, 'f', 2);
        qInfo().nospace().noquote() << "    Corrupt KBytes: " << QString::number(corruptKBytes, 'f', 2);
        qInfo().nospace().noquote() << "    Padded KBytes: " << QString::number(paddedKBytes, 'f', 2);
    } else {
        // Show in MB if 1MB or larger
        double validMBytes = static_cast<double>(validBytes + m_corruptBytesCount) / (1024.0 * 1024.0);
        double validOnlyMBytes = static_cast<double>(validBytes) / (1024.0 * 1024.0);
        double corruptMBytes = static_cast<double>(m_corruptBytesCount) / (1024.0 * 1024.0);
        double paddedMBytes = static_cast<double>(m_paddedBytesCount) / (1024.0 * 1024.0);
        qInfo().nospace().noquote() << "    Total MBytes: " << QString::number(validMBytes, 'f', 2);
        qInfo().nospace().noquote() << "    Valid MBytes: " << QString::number(validOnlyMBytes, 'f', 2);
        qInfo().nospace().noquote() << "    Corrupt MBytes: " << QString::number(corruptMBytes, 'f', 2);
        qInfo().nospace().noquote() << "    Padded MBytes: " << QString::number(paddedMBytes, 'f', 2);
    }

    qInfo().nospace().noquote() << "    Data loss: "
                               << QString::number((m_corruptBytesCount * 100.0) / validBytes, 'f', 3)
                               << "%";
}