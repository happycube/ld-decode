/************************************************************************

    efm_processor.h

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

#ifndef EFM_PROCESSOR_H
#define EFM_PROCESSOR_H

#include <QString>
#include <QDebug>
#include <QFile>
#include <QElapsedTimer>

#include "decoders.h"
#include "dec_tvaluestochannel.h"
#include "dec_channeltof3frame.h"
#include "dec_f3frametof2section.h"
#include "dec_f2sectioncorrection.h"

#include "writer_f2section.h"
#include "reader_data.h"

class EfmProcessor
{
public:
    EfmProcessor();

    bool process(const QString &inputFilename, const QString &outputFilename);
    void setShowData(bool showF2, bool showF3);
    void setDebug(bool tvalue, bool channel, bool f3, bool f2);
    void showStatistics() const;

private:
    // Data debug options (to show data at various stages of processing)
    bool m_showF2;
    bool m_showF3;

    // IEC 60909-1999 Decoders
    TvaluesToChannel m_tValuesToChannel;
    ChannelToF3Frame m_channelToF3;
    F3FrameToF2Section m_f3FrameToF2Section;
    F2SectionCorrection m_f2SectionCorrection;

    // Input file readers
    ReaderData m_readerData;

    // Output file writers
    WriterF2Section m_writerF2Section;

    // Processing statistics
    struct GeneralPipelineStatistics {
        qint64 channelToF3Time{0};
        qint64 f3ToF2Time{0};
        qint64 f2CorrectionTime{0};
    } m_generalPipelineStats;

    void processGeneralPipeline();
    void showGeneralPipelineStatistics();
};

#endif // EFM_PROCESSOR_H