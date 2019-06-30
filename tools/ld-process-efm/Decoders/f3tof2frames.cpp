/************************************************************************

    f3tof2frames.cpp

    ld-process-efm - EFM data decoder
    Copyright (C) 2019 Simon Inns

    This file is part of ld-decode-tools.

    ld-process-efm is free software: you can redistribute it and/or
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

#include "f3tof2frames.h"

F3ToF2Frames::F3ToF2Frames()
{
    debugOn = false;
    abort = false;
}

// Public methods -----------------------------------------------------------------------------------------------------

void F3ToF2Frames::startProcessing(QFile *inputFileHandle, QFile *outputFileHandle)
{
    abort = false;

    // Clear the statistic counters
    clearStatistics();

    // Define an input data stream
    QDataStream inputDataStream(inputFileHandle);

    // Define an output data stream
    QDataStream outputDataStream(outputFileHandle);

    if (debugOn) qDebug() << "F3ToF2Frames::startProcessing(): Initial input file size of" << inputFileHandle->bytesAvailable() << "bytes";

    // Initialise variables to track the disc time
    bool initialDiscTimeSet = false;
    TrackTime lastDiscTime;
    lastDiscTime.setTime(0, 0, 0);

    // Since metadata is out-of-sync with F2 data, we need to buffer it
    // across the sections of 98 F3 frames
    QVector<Section> sectionBuffer;
    QVector<TrackTime> sectionDiscTimes;

    QVector<F2Frame> f2FrameBuffer;

    while (inputFileHandle->bytesAvailable() != 0 && !abort) {
        // Input data will be available in sections of 98 F3 frames, synchronised with a section
        // read in the 98 F3 Frames
        QVector<F3Frame> f3FrameBuffer;
        F3Frame f3Frame;
        QByteArray sectionData;
        for (qint32 i = 0; i < 98; i++) {
            // Get the incoming F3 frame and place it in the F3 frame buffer
            inputDataStream >> f3Frame;
            f3FrameBuffer.append(f3Frame);
            statistics.totalF3Frames++;

            // Collect the 98 subcode data symbols
            sectionData.append(static_cast<char>(f3FrameBuffer[i].getSubcodeSymbol()));
        }

        // Process the subcode data into a section
        Section section;
        section.setData(sectionData);

        // Display some debug about the section metadata contents
        if (section.getQMode() == 1 || section.getQMode() == 4) {
            // if (debugOn) qDebug() << "F3ToF2Frames::startProcessing(): Q Mode is" << section.getQMode()<< "disc time:" << section.getQMetadata().qMode1And4.discTime.getTimeAsQString();
        } else if (section.getQMode() == 2) {
            // if (debugOn) qDebug() << "F3ToF2Frames::startProcessing(): Q Mode is 2 (ID):" << section.getQMetadata().qMode2.catalogueNumber << "with AFrame of" << section.getQMetadata().qMode2.aFrame;
        } else {
            // if (debugOn) qDebug() << "F3ToF2Frames::startProcessing(): Subcode corrupt, qMode unknown";
        }

        // Keep track of the disc time
        TrackTime currentDiscTime;
        if (!initialDiscTimeSet) {
            // Get the initial disc time if available
            if (section.getQMode() == 1 || section.getQMode() == 4) {
                statistics.initialDiscTime = section.getQMetadata().qMode1And4.discTime;
                lastDiscTime = section.getQMetadata().qMode1And4.discTime;
                currentDiscTime = lastDiscTime;
                if (debugOn) qDebug().noquote() << "F3ToF2Frames::startProcessing(): Initial disc time is" << statistics.initialDiscTime.getTimeAsQString();
                initialDiscTimeSet = true;
            } else {
                // If initial disc time isn't set and the first section isn't Q Mode 1 or 4, we could have
                // a problem here... it might be smart to simply drop the section of F3 frames until we get a
                // valid point; otherwise the decoded audio could be really messy?
                if (debugOn) qDebug() << "F3ToF2Frames::startProcessing(): No available disc time in the first section of F3 Frames!";
            }
        } else {
            // Last disc time is known, compare to current
            if (section.getQMode() == 1 || section.getQMode() == 4) {
                // Current section has a valid disc time
                currentDiscTime = section.getQMetadata().qMode1And4.discTime;
            } else {
                // Current section does not have a valid disc time, estimate it
                currentDiscTime = lastDiscTime;
                currentDiscTime.addFrames(1); // We assume this section is contiguous
                //if (debugOn) qDebug().noquote() << "F3ToF2Frames::startProcessing(): Disc time not available, setting current disc time to" << currentDiscTime.getTimeAsQString();
            }

            // Check that this section is one frame difference from the previous
            qint32 sectionFrameGap = currentDiscTime.getDifference(lastDiscTime.getTime());

            if (sectionFrameGap > 1) {
                // The incoming F3 section isn't contiguous with the previous F3 section
                // this means the C1, C2 and deinterleave buffers are full of the wrong
                // data... so here we flush them to speed up the recovery time
                if (debugOn) qDebug() << "F3ToF2Frames::startProcessing(): Non-contiguous F3 section with" << sectionFrameGap << "frames missing - Last disc time was" <<
                            lastDiscTime.getTimeAsQString() << "current disc time is" << currentDiscTime.getTimeAsQString();
                statistics.sequenceInterruptions++;
                statistics.missingF3Frames += (sectionFrameGap - 1) * 98;
                c1Circ.flush();
                c2Circ.flush();
                c2Deinterleave.flush();

                // Also flush the metadata as it's now out of sync
                sectionBuffer.clear();
            }
        }

        // Store the current disc time as last
        lastDiscTime = currentDiscTime;
        statistics.currentDiscTime = currentDiscTime;

        // Add the new section to our section buffer
        sectionBuffer.append(section);
        sectionDiscTimes.append(currentDiscTime);

        // Process the F3 frames into F2 frames (payload data)
        for (qint32 i = 0; i < 98; i++) {
            // Process C1 CIRC
            c1Circ.pushF3Frame(f3FrameBuffer[i]);

            // Get C1 results (if available)
            QByteArray c1DataSymbols = c1Circ.getDataSymbols();
            QByteArray c1ErrorSymbols = c1Circ.getErrorSymbols();

            // If we have C1 results, process C2
            if (!c1DataSymbols.isEmpty()) {
                // Process C2 CIRC
                c2Circ.pushC1(c1DataSymbols, c1ErrorSymbols);

                // Get C2 results (if available)
                QByteArray c2DataSymbols = c2Circ.getDataSymbols();
                QByteArray c2ErrorSymbols = c2Circ.getErrorSymbols();
                bool c2DataValid = c2Circ.getDataValid();

                // Only process the F2 frames if we received data
                if (!c2DataSymbols.isEmpty()) {
                    // Deinterleave the C2
                    c2Deinterleave.pushC2(c2DataSymbols, c2ErrorSymbols, c2DataValid);

                    QByteArray c2DeinterleavedData = c2Deinterleave.getDataSymbols();
                    QByteArray c2DeinterleavedErrors = c2Deinterleave.getErrorSymbols();
                    bool c2DeinterleavedDataValid = c2Deinterleave.getDataValid();

                    // If we have deinterleaved C2s, create an F2 frame
                    if (!c2DeinterleavedData.isEmpty()) {
                        F2Frame newF2Frame;
                        newF2Frame.setData(c2DeinterleavedData, c2DeinterleavedErrors, c2DeinterleavedDataValid);
                        f2FrameBuffer.append(newF2Frame);
                    }
                }
            }
        }

        // Apply the section metadata to the available F2 frames
        // Note: There will be 98 F2 frames to each section of metadata
        if (f2FrameBuffer.size() >= 98) {
            // How many sections should be processed?
            qint32 sectionsToProcess = f2FrameBuffer.size() / 98;

            // Ensure we have enough section data to cover the waiting F2 frames
            if (sectionsToProcess > sectionBuffer.size()) {
                qWarning() << "F3ToF2Frames::startProcessing(): There are more waiting F2 frames than section data - This is a bug!";
            } else {
                qint32 currentF2Frame = 0;
                // Apply the metadata to the F2 frames
                for (qint32 currentSection = 0; currentSection < sectionsToProcess; currentSection++) {
                    // Process F2 Frames for the current section
                    for (qint32 i = 0; i < 98; i++) {
                        // Always output the disc time from the corrected local version
                        f2FrameBuffer[currentF2Frame].setDiscTime(sectionDiscTimes[currentSection]);

                        // Only use the real metadata if it is valid and available
                        if (sectionBuffer[currentSection].getQMode() == 1 || sectionBuffer[currentSection].getQMode() == 4) {
                            f2FrameBuffer[currentF2Frame].setTrackTime(sectionBuffer[currentSection].getQMetadata().qMode1And4.trackTime);
                            f2FrameBuffer[currentF2Frame].setTrackNumber(sectionBuffer[currentSection].getQMetadata().qMode1And4.trackNumber);
                            f2FrameBuffer[currentF2Frame].setIsEncoderRunning(sectionBuffer[currentSection].getQMetadata().qMode1And4.isEncoderRunning);
                        } else {
                            TrackTime dummyTime;
                            dummyTime.setTime(0, 0, 0);
                            f2FrameBuffer[currentF2Frame].setTrackTime(dummyTime);
                            f2FrameBuffer[currentF2Frame].setTrackNumber(1);
                            f2FrameBuffer[currentF2Frame].setIsEncoderRunning(true);
                        }

                        // Output the F2Frame
                        outputDataStream << f2FrameBuffer[currentF2Frame];
                        statistics.totalF2Frames++;
                        currentF2Frame++;
                    }
                }

                // Remove the consumed frames and sections
                sectionBuffer.remove(0, sectionsToProcess);
                sectionDiscTimes.remove(0, sectionsToProcess);
                f2FrameBuffer.remove(0, sectionsToProcess * 98);
            }
        }
    }

    if (debugOn) qDebug() << "F3ToF2Frames::startProcessing(): No more data to processes";
}

void F3ToF2Frames::stopProcessing(void)
{
    abort = true;
}

F3ToF2Frames::Statistics F3ToF2Frames::getStatistics(void)
{
    // Ensure sub-class statistics are updated
    statistics.c1Circ_statistics = c1Circ.getStatistics();
    statistics.c2Circ_statistics = c2Circ.getStatistics();
    statistics.c2Deinterleave_statistics = c2Deinterleave.getStatistics();

    return statistics;
}

void F3ToF2Frames::reportStatistics(void)
{
    qInfo() << "";
    qInfo() << "F3 Frame to F2 Frame decode:";
    qInfo() << "      Total input F3 Frames:" << statistics.totalF3Frames;
    qInfo() << "     Total output F2 Frames:" << statistics.totalF2Frames;
    qInfo() << "  F3 Sequence Interruptions:" << statistics.sequenceInterruptions;
    qInfo() << "          Missing F3 Frames:" << statistics.missingF3Frames;
    qInfo().noquote() << "          Initial disc time:" << statistics.initialDiscTime.getTimeAsQString();
    qInfo().noquote() << "            Final disc time:" << statistics.currentDiscTime.getTimeAsQString();

    // Show C1 CIRC statistics
    c1Circ.reportStatistics();

    // Show C2 CIRC statistics
    c2Circ.reportStatistics();

    // Show C2 Deinterleave statistics
    c2Deinterleave.reportStatistics();
}

// Private methods ----------------------------------------------------------------------------------------------------

void F3ToF2Frames::clearStatistics(void)
{
    statistics.totalF3Frames = 0;
    statistics.totalF2Frames = 0;

    c1Circ.resetStatistics();
    c2Circ.resetStatistics();
    c2Deinterleave.resetStatistics();

    statistics.initialDiscTime.setTime(0, 0, 0);
    statistics.currentDiscTime.setTime(0, 0, 0);

    statistics.sequenceInterruptions = 0;
    statistics.missingF3Frames = 0;
}
