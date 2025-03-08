/************************************************************************

    efm_processor.cpp

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

#include "efm_processor.h"

EfmProcessor::EfmProcessor() : 
    m_showF2(false),
    m_showF3(false)
{}

bool EfmProcessor::process(const QString &inputFilename, const QString &outputFilename)
{
    qDebug() << "EfmProcessor::process(): Decoding EFM from file:" << inputFilename
             << "to file:" << outputFilename;

    // Prepare the input file reader
    if (!m_readerData.open(inputFilename)) {
        qDebug() << "EfmProcessor::process(): Failed to open input file:" << inputFilename;
        return false;
    }

    // Prepare the output file writer
    m_writerF2Section.open(outputFilename);

    // Get the total size of the input file for progress reporting
    qint64 totalSize = m_readerData.size();
    qint64 processedSize = 0;
    int lastProgress = 0;

    // Process the EFM data in chunks of 1024 T-values
    bool endOfData = false;
    while (!endOfData) {
        // Read 1024 T-values from the input file
        QByteArray tValues = m_readerData.read(1024);
        processedSize += tValues.size();

        int progress = static_cast<int>((processedSize * 100) / totalSize);
        if (progress >= lastProgress + 5) { // Show progress every 5%
            qInfo() << "Progress:" << progress << "%";
            lastProgress = progress;
        }

        if (tValues.isEmpty()) {
            endOfData = true;
        } else {
            m_tValuesToChannel.pushFrame(tValues);
        }

        processGeneralPipeline();
    }

    // We are out of data flush the pipeline and process it one last time
    qInfo() << "Flushing decoding pipelines";
    m_f2SectionCorrection.flush();

    qInfo() << "Processing final pipeline data";
    processGeneralPipeline();

    // Show summary
    qInfo() << "Decoding complete";

    m_tValuesToChannel.showStatistics();
    qInfo() << "";
    m_channelToF3.showStatistics();
    qInfo() << "";
    m_f3FrameToF2Section.showStatistics();
    qInfo() << "";
    m_f2SectionCorrection.showStatistics();
    qInfo() << "";

    showGeneralPipelineStatistics();

    // Close the input file
    m_readerData.close();

    // Close the output files
    if (m_writerF2Section.isOpen()) m_writerF2Section.close();

    qInfo() << "Encoding complete";
    return true;
}

void EfmProcessor::processGeneralPipeline()
{
    QElapsedTimer pipelineTimer;

    // T-values to Channel processing
    pipelineTimer.start();
    while (m_tValuesToChannel.isReady()) {
        QByteArray channelData = m_tValuesToChannel.popFrame();
        m_channelToF3.pushFrame(channelData);
    }
    m_generalPipelineStats.channelToF3Time += pipelineTimer.nsecsElapsed();

    // Channel to F3 processing
    pipelineTimer.restart();
    while (m_channelToF3.isReady()) {
        F3Frame f3Frame = m_channelToF3.popFrame();
        if (m_showF3)
            f3Frame.showData();
        m_f3FrameToF2Section.pushFrame(f3Frame);
    }
    m_generalPipelineStats.f3ToF2Time += pipelineTimer.nsecsElapsed();

    // F3 to F2 section processing
    pipelineTimer.restart();
    while (m_f3FrameToF2Section.isReady()) {
        F2Section section = m_f3FrameToF2Section.popSection();
        m_f2SectionCorrection.pushSection(section);
    }
    m_generalPipelineStats.f2CorrectionTime += pipelineTimer.nsecsElapsed();

    // F2 correction processing
    while (m_f2SectionCorrection.isReady()) {
        F2Section f2Section = m_f2SectionCorrection.popSection();
        if (m_showF2)
            f2Section.showData();
        // Write the F2 section to the output file
        m_writerF2Section.write(f2Section);
    }
}

void EfmProcessor::showGeneralPipelineStatistics()
{
    qInfo() << "Decoder processing summary (general):";

    qInfo() << "  Channel to F3 processing time:" << m_generalPipelineStats.channelToF3Time / 1000000 << "ms";
    qInfo() << "  F3 to F2 section processing time:" << m_generalPipelineStats.f3ToF2Time / 1000000 << "ms";
    qInfo() << "  F2 correction processing time:" << m_generalPipelineStats.f2CorrectionTime / 1000000 << "ms";

    qint64 totalProcessingTime = m_generalPipelineStats.channelToF3Time +
                                 m_generalPipelineStats.f3ToF2Time + m_generalPipelineStats.f2CorrectionTime;
    float totalProcessingTimeSeconds = totalProcessingTime / 1000000000.0;
    qInfo().nospace() << "  Total processing time: " << totalProcessingTime / 1000000 << " ms ("
            << Qt::fixed << qSetRealNumberPrecision(2) << totalProcessingTimeSeconds << " seconds)";

    qInfo() << "";
}

void EfmProcessor::setShowData(bool showF2, bool showF3)
{
    m_showF2 = showF2;
    m_showF3 = showF3;
}

void EfmProcessor::setDebug(bool tvalue, bool channel, bool f3, bool f2)
{
    // Set the debug flags
    m_tValuesToChannel.setShowDebug(tvalue);
    m_channelToF3.setShowDebug(channel);
    m_f3FrameToF2Section.setShowDebug(f3);
    m_f2SectionCorrection.setShowDebug(f2);
}