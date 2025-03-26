/************************************************************************

    efm_processor.cpp

    efm-decoder-d24 - EFM F2Section to Data24 Section decoder
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
    m_showData24(false),
    m_showF1(false)
{}

bool EfmProcessor::process(const QString &inputFilename, const QString &outputFilename)
{
    qDebug() << "EfmProcessor::process(): Decoding F2 Sections from file:" << inputFilename
             << "to file:" << outputFilename;

    // Prepare the input file reader
    if (!m_readerF2Section.open(inputFilename)) {
        qDebug() << "EfmProcessor::process(): Failed to open input F2 Section file:" << inputFilename;
        return false;
    }

    // Prepare the output file writer
    m_writerData24Section.open(outputFilename);

    // Process the F2 Section data
    QElapsedTimer pipelineTimer;
    for (int index = 0; index < m_readerF2Section.size(); ++index) {
        pipelineTimer.restart();
        m_f2SectionToF1Section.pushSection(m_readerF2Section.read());
        m_generalPipelineStats.f2SectionToF1SectionTime += pipelineTimer.nsecsElapsed();
        processGeneralPipeline();

        // Every 1000 sections show progress
        if (index % 1000 == 0) {
            // Calculate the percentage complete
            float percentageComplete = (index / static_cast<float>(m_readerF2Section.size())) * 100.0;
            qInfo().nospace().noquote() << "Decoding F2 Section " << index << " of " << m_readerF2Section.size() << " (" << QString::number(percentageComplete, 'f', 2) << "%)";
        }
    }

    // We are out of data flush the pipeline and process it one last time
    qInfo() << "Flushing decoding pipelines";
    // Nothing to do here at the moment...

    qInfo() << "Processing final pipeline data";
    processGeneralPipeline();

    // Show summary
    qInfo() << "Decoding complete";

    // Show statistics
    m_f2SectionToF1Section.showStatistics();
    qInfo() << "";
    m_f1SectionToData24Section.showStatistics();
    qInfo() << "";

    showGeneralPipelineStatistics();

    // Close the input file
    m_readerF2Section.close();

    // Close the output files
    if (m_writerData24Section.isOpen()) m_writerData24Section.close();

    qInfo() << "Encoding complete";
    return true;
}

void EfmProcessor::processGeneralPipeline()
{
    QElapsedTimer pipelineTimer;

    // F2 to F1 processing
    pipelineTimer.restart();
    while (m_f2SectionToF1Section.isReady()) {
        F1Section f1Section = m_f2SectionToF1Section.popSection();
        if (m_showF1)
            f1Section.showData();
        m_f1SectionToData24Section.pushSection(f1Section);
    }
    m_generalPipelineStats.f1ToData24Time += pipelineTimer.nsecsElapsed();

    // Data24 output writer
    while (m_f1SectionToData24Section.isReady()) {
        Data24Section data24Section = m_f1SectionToData24Section.popSection();
        m_writerData24Section.write(data24Section);
        if (m_showData24) {
            data24Section.showData();
        }
    }
}

void EfmProcessor::showGeneralPipelineStatistics()
{
    qInfo() << "Decoder processing summary (general):";

    qInfo() << "  F2 to F1 processing time:" << m_generalPipelineStats.f2SectionToF1SectionTime / 1000000 << "ms";
    qInfo() << "  F1 to Data24 processing time:" << m_generalPipelineStats.f1ToData24Time / 1000000 << "ms";

    qint64 totalProcessingTime = m_generalPipelineStats.f2SectionToF1SectionTime +
                                 m_generalPipelineStats.f1ToData24Time;
    float totalProcessingTimeSeconds = totalProcessingTime / 1000000000.0;
    qInfo().nospace() << "  Total processing time: " << totalProcessingTime / 1000000 << " ms ("
            << Qt::fixed << qSetRealNumberPrecision(2) << totalProcessingTimeSeconds << " seconds)";

    qInfo() << "";
}

void EfmProcessor::setShowData(bool showData24, bool showF1)
{
    m_showData24 = showData24;
    m_showF1 = showF1;
}

void EfmProcessor::setDebug(bool f1, bool data24)
{
    // Set the debug flags
    m_f2SectionToF1Section.setShowDebug(f1);
    m_f1SectionToData24Section.setShowDebug(data24);
}