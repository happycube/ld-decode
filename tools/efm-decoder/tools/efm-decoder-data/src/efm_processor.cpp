/************************************************************************

    efm_processor.cpp

    efm-decoder-data - EFM Data24 to data decoder
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
    m_outputDataMetadata(false)
{}

bool EfmProcessor::process(const QString &inputFilename, const QString &outputFilename)
{
    qDebug() << "EfmProcessor::process(): Decoding Data24 Sections from file:" << inputFilename
             << "to file:" << outputFilename;

    // Prepare the input file reader
    if (!m_readerData24Section.open(inputFilename)) {
        qDebug() << "EfmProcessor::process(): Failed to open input Data24 Section file:" << inputFilename;
        return false;
    }

    // Prepare the output file writers
    m_writerSector.open(outputFilename);
    if (m_outputDataMetadata) {
        QString metadataFilename = outputFilename;
        if (metadataFilename.endsWith(".dat")) {
            metadataFilename.replace(".dat", ".bsm"); // Bad Sector Map
        } else {
            metadataFilename.append(".bsm");
        }
        m_writerSectorMetadata.open(metadataFilename);
    }

    // Process the Data24 Section data
    QElapsedTimer dataPipelineTimer;
    for (int index = 0; index < m_readerData24Section.size(); ++index) {
        dataPipelineTimer.restart();
        m_data24ToRawSector.pushSection(m_readerData24Section.read());
        m_dataPipelineStats.data24ToRawSectorTime += dataPipelineTimer.nsecsElapsed();
        processDataPipeline();

        // Every 500 sections show progress
        if (index % 500 == 0) {
            // Calculate the percentage complete
            float percentageComplete = (index / static_cast<float>(m_readerData24Section.size())) * 100.0;
            qInfo().nospace().noquote() << "Decoding Data24 Section " << index << " of " << m_readerData24Section.size() << " (" << QString::number(percentageComplete, 'f', 2) << "%)";
        }
    }

    // We are out of data flush the pipeline and process it one last time
    qInfo() << "Flushing decoding pipelines";
    // Nothing to do here at the moment...

    qInfo() << "Processing final pipeline data";
    processDataPipeline();

    // Show summary
    qInfo() << "Decoding complete";

    // Show statistics
    m_data24ToRawSector.showStatistics();
    qInfo() << "";
    m_rawSectorToSector.showStatistics();
    qInfo() << "";
    m_sectorCorrection.showStatistics();
    qInfo() << "";

    showDataPipelineStatistics();

    // Close the input file
    m_readerData24Section.close();

    // Close the output files
    if (m_writerSector.isOpen()) m_writerSector.close();
    if (m_writerSectorMetadata.isOpen()) m_writerSectorMetadata.close();

    qInfo() << "Encoding complete";
    return true;
}

void EfmProcessor::processDataPipeline()
{
    QElapsedTimer dataPipelineTimer;

    // Raw sector to sector processing
    dataPipelineTimer.restart();
    while (m_data24ToRawSector.isReady()) {
        RawSector rawSector = m_data24ToRawSector.popSector();
        m_rawSectorToSector.pushSector(rawSector);
        if (m_showRawSector)
            rawSector.showData();
    }
    m_dataPipelineStats.rawSectorToSectorTime += dataPipelineTimer.nsecsElapsed();

    // Sector correction processing
    while (m_rawSectorToSector.isReady()) {
        Sector sector = m_rawSectorToSector.popSector();
        m_sectorCorrection.pushSector(sector);
    }

    // Write out the sector data
    while (m_sectorCorrection.isReady()) {
        Sector sector = m_sectorCorrection.popSector();
        m_writerSector.write(sector);
        if (m_outputDataMetadata)
            m_writerSectorMetadata.write(sector);
    }
}

void EfmProcessor::showDataPipelineStatistics()
{
    qInfo() << "Decoder processing summary (data):";
    qInfo() << "  Data24 to Raw Sector processing time:" << m_dataPipelineStats.data24ToRawSectorTime / 1000000 << "ms";
    qInfo() << "  Raw Sector to Sector processing time:" << m_dataPipelineStats.rawSectorToSectorTime / 1000000 << "ms";

    qint64 totalProcessingTime = m_dataPipelineStats.data24ToRawSectorTime + m_dataPipelineStats.rawSectorToSectorTime;
    float totalProcessingTimeSeconds = totalProcessingTime / 1000000000.0;
    qInfo().nospace() << "  Total processing time: " << totalProcessingTime / 1000000 << " ms ("
            << Qt::fixed << qSetRealNumberPrecision(2) << totalProcessingTimeSeconds << " seconds)";

    qInfo() << "";
}

void EfmProcessor::setShowData(bool showRawSector)
{
    m_showRawSector = showRawSector;
}

// Set the output data type (true for WAV, false for raw)
void EfmProcessor::setOutputType(bool outputDataMetadata)
{
    m_outputDataMetadata = outputDataMetadata;
}

void EfmProcessor::setDebug(bool rawSector, bool sector, bool sectorCorrection)
{
    // Set the debug flags

    m_data24ToRawSector.setShowDebug(rawSector);
    m_rawSectorToSector.setShowDebug(sector);
    m_sectorCorrection.setShowDebug(sectorCorrection);
}