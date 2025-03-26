/************************************************************************

    f2_stacker.cpp

    efm-stacker-f2 - EFM F2 Section stacker
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

#include "f2_stacker.h"

F2Stacker::F2Stacker() :
    m_goodBytes(0),
    m_noValidValueForByte(0),
    m_errorFreeFrames(0),
    m_errorFrames(0),
    m_validValueForByte(0),
    m_usedMostCommonValue(0),
    m_paddedFrames(0)
{}

bool F2Stacker::process(const QVector<QString> &inputFilenames, const QString &outputFilename)
{
    // Prepare the source differences statistics
    m_sourceDifferences.resize(inputFilenames.size());
    m_sourceDifferences.fill(0);

    // Start by opening all the input F2 section files
    for (int index = 0; index < inputFilenames.size(); index++) {
        ReaderF2Section* reader = new ReaderF2Section();
        if (!reader->open(inputFilenames[index])) {
            qCritical() << "F2Stacker::process() - Could not open input file" << inputFilenames[index];
            delete reader;
            return false;
        }
        m_inputFiles.append(reader);
        qDebug() << "Opened input file" << inputFilenames[index];
    }

    // Figure out the time range covered by the input files
    // Note: This is assuming that the input files are in chronological order...
    QVector<SectionTime> m_startTimes;
    QVector<SectionTime> m_endTimes;

    qInfo() << "Scanning input files to get time range of data from each...";
    for (int inputFileIdx = 0; inputFileIdx < m_inputFiles.size(); inputFileIdx++) {
        m_inputFiles[inputFileIdx]->seekToSection(0);
        SectionTime startTime = m_inputFiles[inputFileIdx]->read().metadata.absoluteSectionTime();
        m_inputFiles[inputFileIdx]->seekToSection(m_inputFiles[inputFileIdx]->size() - 1);
        SectionTime endTime = m_inputFiles[inputFileIdx]->read().metadata.absoluteSectionTime();
        m_startTimes.append(startTime);
        m_endTimes.append(endTime);
        
        // Seek back to the start of the file
        m_inputFiles[inputFileIdx]->seekToSection(0);
        qInfo().noquote() << "Input File" << inputFilenames[inputFileIdx] << "- Start:" << startTime.toString() << "- End:" << endTime.toString();
    }

    // The start time (for the stacking) is the earliest start time of all the input files
    // The end time (for the stacking) is the latest end time of all the input files
    SectionTime stackStartTime(59,59,74);
    SectionTime stackEndTime(0,0,0);
    for (int index = 0; index < m_startTimes.size(); index++) {
        if (m_startTimes[index] < stackStartTime) {
            stackStartTime = m_startTimes[index];
        }
        if (m_endTimes[index] > stackEndTime) {
            stackEndTime = m_endTimes[index];
        }
    }
    qInfo().noquote() << "Stacking Start Time:" << stackStartTime.toString() << "End Time:" << stackEndTime.toString();

    // Open the output file
    if (!m_outputFile.open(outputFilename)) {
        qCritical() << "F2Stacker::process() - Could not open output file" << outputFilename;
        return false;
    }

    // Process
    for (int address = stackStartTime.frames(); address <= stackEndTime.frames(); address++) {
        // Make a list of the input files that have data for this frame
        QVector<ReaderF2Section*> inputReaderList;
        for (int inputFileIdx = 0; inputFileIdx < m_inputFiles.size(); inputFileIdx++) {
            if (m_startTimes[inputFileIdx].frames() <= address && m_endTimes[inputFileIdx].frames() >= address) {
                inputReaderList.append(m_inputFiles[inputFileIdx]);
            }
        }

        QVector<F2Section> sectionList;
        for (int inputFileIdx = 0; inputFileIdx < inputReaderList.size(); inputFileIdx++) {
            sectionList.append(inputReaderList[inputFileIdx]->read());
        }

        qDebug().noquote() << "F2Stacker::process() - Stacking section" << sectionList.at(0).metadata.absoluteSectionTime().toString();

        F2Section stackedF2Section = stackSections(sectionList);

        // Write the output F2 Section
        m_outputFile.write(stackedF2Section);

        // Every 2500 Sections, show progress
        if (address % 2500 == 0) {
            float percentageComplete = (static_cast<float>(address) - static_cast<float>(stackStartTime.frames())) *
                100.0 / (static_cast<float>(stackEndTime.frames()) - static_cast<float>(stackStartTime.frames()));
            qInfo().noquote().nospace() << "Processed " << address << " sections of " << (stackEndTime.frames() - stackStartTime.frames() + 1)
                << " " << QString::number(percentageComplete, 'f', 2) << "%";
        }
    }

    // Close the input files
    for (int index = 0; index < m_inputFiles.size(); index++) {
        m_inputFiles[index]->close();
        delete m_inputFiles[index];
    }
    m_inputFiles.clear();
    
    // Close the output file
    m_outputFile.close();

    // Statistics
    qInfo() << "Stacking results:";
    qInfo().noquote() << "  Sections stacked:" << stackEndTime.frames() - stackStartTime.frames() + 1;
    qInfo().noquote() << "  Frames stacked:" << (stackEndTime.frames() - stackStartTime.frames() + 1) * 98;
    qInfo().noquote() << "";
    qInfo().noquote() << "  Error free frames:" << m_errorFreeFrames;
    qInfo().noquote() << "  Error frames:" << m_errorFrames;
    qInfo().noquote().nospace() << "  Padded frames: " << m_paddedFrames << " (" << m_paddedFrames / 98 << " sections)";
    qInfo().noquote() << "  Total frames:" << m_errorFreeFrames + m_errorFrames + m_paddedFrames;
    qInfo().noquote() << "";
    qInfo().noquote() << "  Valid bytes common to all sources:" << m_validValueForByte;
    qInfo().noquote() << "  Valid bytes that differed in value between sources:" << m_usedMostCommonValue;
    qInfo().noquote() << "  Invalid byte in all sources:" << m_noValidValueForByte;
    qInfo().noquote() << "";
    qInfo().noquote() << "  Source differences:";
    qInfo().noquote() << "    Source 0" << inputFilenames[0];
    for (int sourceIndex = 1; sourceIndex < m_sourceDifferences.size(); sourceIndex++) {
        qInfo().noquote() << "    Source" << sourceIndex << inputFilenames[sourceIndex] << ":" << m_sourceDifferences[sourceIndex];
    }

    return true;
}

F2Section F2Stacker::stackSections(const QVector<F2Section> &f2Sections)
{
    F2Section stackedSection;
    SectionMetadata stackedMetadata;
    
    // Pick the first section from the list with valid metadata
    bool gotValidMetadata = false;
    for (int sectionIndex = 0; sectionIndex < f2Sections.size(); sectionIndex++) {
        if (f2Sections[sectionIndex].metadata.isValid() && !f2Sections[sectionIndex].metadata.isRepaired()) {
            stackedMetadata = f2Sections[sectionIndex].metadata;
            gotValidMetadata = true;
            break;
        }
    }

    // If we didn't get anything valid, try again and include repaired metadata
    if (!gotValidMetadata) {
        for (int sectionIndex = 0; sectionIndex < f2Sections.size(); sectionIndex++) {
            if (f2Sections[sectionIndex].metadata.isValid()) {
                stackedMetadata = f2Sections[sectionIndex].metadata;
                gotValidMetadata = true;
                break;
            }
        }
    }

    if (!gotValidMetadata) {
        qFatal("F2Stacker::stackSections - No valid metadata found in the input sections");
    }

    // Check if the section's frames contain only padding rather than valid data
    // and Remove any sections that are just padding
    QVector<F2Section> validF2Sections;
    for (int sectionIndex = 0; sectionIndex < f2Sections.size(); sectionIndex++) {
        bool isPadding = true;
        for (int frameIndex = 0; frameIndex < 98; frameIndex++) {
            if (f2Sections[sectionIndex].frame(frameIndex).paddedData().contains(false)) {
                isPadding = false;
                break;
            }
        }

        if (isPadding) {
            qDebug().noquote() << "F2Stacker::stackSections - Section" << sectionIndex << "is just padding";
        } else {
            validF2Sections.append(f2Sections[sectionIndex]);
        }
    }

    // Do we have at least 2 sections to stack?
    if (validF2Sections.size() < 2) {
        // Just pass through the first padded section
        stackedSection = f2Sections[0];
        m_paddedFrames += 98;
    } else {
        // Each section contains 98 F2Frames
        for (int frameIndex = 0; frameIndex < 98; frameIndex++) {
            // Make a list of the frames to stack
            QVector<F2Frame> frameList;
            for (int sectionIndex = 0; sectionIndex < validF2Sections.size(); sectionIndex++) {
                frameList.append(validF2Sections[sectionIndex].frame(frameIndex));
            }

            // Stack the frames
            F2Frame stackedFrame = stackFrames(frameList);
            stackedSection.pushFrame(stackedFrame);

            // Does the stacked frame have any errors?
            if (stackedFrame.errorData().contains(1)) {
                m_errorFrames++;
            } else {
                m_errorFreeFrames++;
            }
        }
    }

    stackedSection.metadata = stackedMetadata;
    return stackedSection;
}

F2Frame F2Stacker::stackFrames(QVector<F2Frame> &f2Frames)
{
    F2Frame stackedFrame;

    // Process one byte at a time
    QVector<quint8> stackedFrameData;
    QVector<bool> stackedFrameErrorData;
    for (int byteIndex = 0; byteIndex < 32; byteIndex++) {
        // Make a list of the bytes to stack (i.e. those without error flags)
        QVector<quint8> validBytes;
        for (int listIndex = 0; listIndex < f2Frames.size(); ++listIndex) {
            if (f2Frames.at(listIndex).errorData().at(byteIndex) == false) {
                validBytes.append(f2Frames.at(listIndex).data().at(byteIndex));
            }
        }

        if (validBytes.size() == 0) {
            // All bytes are errors - can't correct
            stackedFrameData.append(f2Frames.at(0).data().at(byteIndex));
            stackedFrameErrorData.append(true);
            qDebug() << "F2Stacker::stackFrames - No valid byte value for index" << byteIndex;
            m_noValidValueForByte++;
        } else {
            // Are all the valid bytes the same value?
            bool allBytesSame = true;
            for (int byteIndex = 1; byteIndex < validBytes.size(); byteIndex++) {
                if (validBytes.at(byteIndex) != validBytes.at(0)) {
                    allBytesSame = false;
                    continue;
                }
            }

            // If all valid bytes are the same, use that value or, if there are only
            // two sources, use the value from the first source
            if (allBytesSame || validBytes.size() == 2) {
                stackedFrameData.append(validBytes.at(0));
                stackedFrameErrorData.append(false);
                m_validValueForByte++;
                continue;
            } else {
                // If all valid bytes aren't the same, calculate the most common
                // byte value from the available valid bytes and use that value
                QHash<quint8, int> byteCounts;
                for (int byteIndex = 0; byteIndex < validBytes.size(); byteIndex++) {
                    byteCounts[validBytes.at(byteIndex)]++;
                }

                // Find the most common byte value
                int maxCount = 0;
                quint8 mostCommonByte = 0;
                for (auto it = byteCounts.begin(); it != byteCounts.end(); ++it) {
                    if (it.value() > maxCount) {
                        maxCount = it.value();
                        mostCommonByte = it.key();
                    }
                }
                m_usedMostCommonValue++;

                QString validBytesString;
                for (int byteIndex = 0; byteIndex < validBytes.size(); byteIndex++) {
                    validBytesString.append(QString("%1 ").arg(validBytes.at(byteIndex), 2, 16, QChar('0')).toUpper());
                }
                QString mostCommonByteString = QString("%1").arg(mostCommonByte, 2, 16, QChar('0')).toUpper();
                qDebug().noquote() << "F2Stacker::stackFrames - Valid byte values differ - using"
                    << mostCommonByteString << "from" << validBytesString;

                stackedFrameData.append(mostCommonByte);
                stackedFrameErrorData.append(false);                
            }
        }

        // Update the source differences statistics for this byte
        quint8 expectedValue = f2Frames.at(0).data().at(byteIndex);
        for (int sourceIndex = 0; sourceIndex < f2Frames.size(); sourceIndex++) {
            if (f2Frames.at(sourceIndex).data().at(byteIndex) != expectedValue) {
                m_sourceDifferences[sourceIndex]++;
            }
        }
    }

    // Set the data for the stacked frame
    stackedFrame.setData(stackedFrameData);
    stackedFrame.setErrorData(stackedFrameErrorData);

    return stackedFrame;
}