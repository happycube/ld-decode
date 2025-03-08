/************************************************************************

    efm_processor.h

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

#ifndef EFM_PROCESSOR_H
#define EFM_PROCESSOR_H

#include <QString>
#include <QDebug>
#include <QFile>
#include <QElapsedTimer>

#include "decoders.h"
#include "dec_data24toaudio.h"
#include "dec_audiocorrection.h"

#include "writer_wav.h"
#include "writer_wav_metadata.h"

#include "reader_data24section.h"

class EfmProcessor
{
public:
    EfmProcessor();

    bool process(const QString &inputFilename, const QString &outputFilename);
    void setShowData(bool showAudio);
    void setOutputType(bool outputWavMetadata, bool noAudioConcealment, bool zeroPad);
    void setDebug(bool audio, bool audioCorrection);
    void showStatistics() const;

private:
    // Data debug options (to show data at various stages of processing)
    bool m_showAudio;

    // Output options
    bool m_outputWavMetadata;
    bool m_noAudioConcealment;
    bool m_zeroPad;

    // IEC 60909-1999 Decoders
    Data24ToAudio m_data24ToAudio;
    AudioCorrection m_audioCorrection;

    // Input file readers
    ReaderData24Section m_readerData24Section;

    // Output file writers
    WriterWav m_writerWav;
    WriterWavMetadata m_writerWavMetadata;

    // Processing statistics
    struct AudioPipelineStatistics {
        qint64 data24ToAudioTime{0};
        qint64 audioCorrectionTime{0};
    } m_audioPipelineStats;

    void processAudioPipeline();
    void showAudioPipelineStatistics();
};

#endif // EFM_PROCESSOR_H