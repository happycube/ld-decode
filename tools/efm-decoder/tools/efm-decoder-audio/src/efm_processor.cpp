/************************************************************************

    efm_processor.cpp

    efm-decoder-audio - EFM Data24 to Audio decoder
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
    m_showAudio(false),
    m_outputWavMetadata(false),
    m_noAudioConcealment(false)
{}

bool EfmProcessor::process(const QString &inputFilename, const QString &outputFilename)
{
    qDebug() << "EfmProcessor::process(): Decoding Data24 Sections from file:" << inputFilename
             << "to wav file:" << outputFilename;

    // Prepare the input file reader
    if (!m_readerData24Section.open(inputFilename)) {
        qDebug() << "EfmProcessor::process(): Failed to open input Data24 Section file:" << inputFilename;
        return false;
    }

    // Prepare the output writers
    m_writerWav.open(outputFilename);
    if (m_outputWavMetadata) {
        QString metadataFilename = outputFilename;
        if (metadataFilename.endsWith(".wav")) {
            metadataFilename.replace(".wav", ".txt");
        } else {
            metadataFilename.append(".txt");
        }
        m_writerWavMetadata.open(metadataFilename, m_noAudioConcealment);
    }

    // Get the first section
    Data24Section currentSection = m_readerData24Section.read();

    // If zero padding is required, perform it
    if (m_zeroPad) {
        qint32 requiredPadding = currentSection.metadata.absoluteSectionTime().frames();
        if (requiredPadding > 0) {
            qInfo() << "Zero padding enabled, start time is" << currentSection.metadata.absoluteSectionTime().toString() << 
                "and requires" << requiredPadding << "frames of padding";

            SectionTime currentTime = SectionTime(0, 0, 0);
            Data24Section zeroSection;
            zeroSection.metadata = currentSection.metadata;
            zeroSection.metadata.setAbsoluteSectionTime(currentTime);
            zeroSection.metadata.setSectionTime(currentTime);

            for (int j = 0; j < 98; ++j) {
                Data24 data24Zero;
                data24Zero.setData(QVector<quint8>(24, 0));
                data24Zero.setErrorData(QVector<bool>(24, false));
                data24Zero.setPaddedData(QVector<bool>(24, true));
                zeroSection.pushFrame(data24Zero);
            }

            for (int i = 0; i < requiredPadding; ++i) {
                zeroSection.metadata.setAbsoluteSectionTime(currentTime);
                zeroSection.metadata.setSectionTime(currentTime);
                m_data24ToAudio.pushSection(zeroSection);
                processAudioPipeline();
                currentTime++;
            }
        }
    }

    // Process the Data24 Section data
    QElapsedTimer audioPipelineTimer;
    for (int index = 0; index < m_readerData24Section.size(); ++index) {
        audioPipelineTimer.restart();
        m_data24ToAudio.pushSection(currentSection);
        m_audioPipelineStats.data24ToAudioTime += audioPipelineTimer.nsecsElapsed();
        processAudioPipeline();

        // Every 500 sections show progress
        if (index % 500 == 0) {
            // Calculate the percentage complete
            float percentageComplete = (index / static_cast<float>(m_readerData24Section.size())) * 100.0;
            qInfo().nospace().noquote() << "Decoding Data24 Section " << index << " of " << m_readerData24Section.size() << " (" << QString::number(percentageComplete, 'f', 2) << "%)";
        }

        currentSection = m_readerData24Section.read();
    }

    // We are out of data flush the pipeline and process it one last time
    qInfo() << "Flushing decoding pipelines";
    // Nothing to do here at the moment...

    qInfo() << "Processing final pipeline data";
    processAudioPipeline();

    // Show summary
    qInfo() << "Decoding complete";

    // Show statistics
    m_data24ToAudio.showStatistics();
    qInfo() << "";
    
    if (!m_noAudioConcealment) {
        m_audioCorrection.showStatistics();
        qInfo() << "";
    }

    showAudioPipelineStatistics();

    // Close the input file
    m_readerData24Section.close();

    // Close the output files
    if (m_writerWav.isOpen()) m_writerWav.close();
    if (m_writerWavMetadata.isOpen()) m_writerWavMetadata.close();

    qInfo() << "Encoding complete";
    return true;
}

void EfmProcessor::processAudioPipeline()
{
    QElapsedTimer audioPipelineTimer;

    // Audio processing
    if (m_noAudioConcealment) {
        while (m_data24ToAudio.isReady()) {
            AudioSection audioSection = m_data24ToAudio.popSection();
            m_writerWav.write(audioSection);
            if (m_outputWavMetadata)
                m_writerWavMetadata.write(audioSection);
        }
    } else {
        audioPipelineTimer.restart();
        while (m_data24ToAudio.isReady()) {
            AudioSection audioSection = m_data24ToAudio.popSection();
            m_audioCorrection.pushSection(audioSection);
        }
        m_audioPipelineStats.audioCorrectionTime += audioPipelineTimer.nsecsElapsed();

        while (m_audioCorrection.isReady()) {
            AudioSection audioSection = m_audioCorrection.popSection();
            m_writerWav.write(audioSection);
            if (m_outputWavMetadata)
                m_writerWavMetadata.write(audioSection);
        }
    }
}

void EfmProcessor::showAudioPipelineStatistics()
{
    qInfo() << "Decoder processing summary (audio):";
    qInfo() << "  Data24 to Audio processing time:" << m_audioPipelineStats.data24ToAudioTime / 1000000 << "ms";
    qInfo() << "  Audio correction processing time:" << m_audioPipelineStats.audioCorrectionTime / 1000000 << "ms";

    qint64 totalProcessingTime = m_audioPipelineStats.data24ToAudioTime + m_audioPipelineStats.audioCorrectionTime;
    float totalProcessingTimeSeconds = totalProcessingTime / 1000000000.0;
    qInfo().nospace() << "  Total processing time: " << totalProcessingTime / 1000000 << " ms ("
            << Qt::fixed << qSetRealNumberPrecision(2) << totalProcessingTimeSeconds << " seconds)";
}

void EfmProcessor::setShowData(bool showAudio)
{
    m_showAudio = showAudio;
}

// Set the output data type (true for WAV, false for raw)
void EfmProcessor::setOutputType(bool outputWavMetadata, bool noAudioConcealment, bool zeroPad)
{
    m_outputWavMetadata = outputWavMetadata;
    m_noAudioConcealment = noAudioConcealment;
    m_zeroPad = zeroPad;
}

void EfmProcessor::setDebug(bool audio, bool audioCorrection)
{
    // Set the debug flags
    m_data24ToAudio.setShowDebug(audio);
    m_audioCorrection.setShowDebug(audioCorrection);
}