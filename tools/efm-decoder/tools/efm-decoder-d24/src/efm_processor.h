/************************************************************************

    efm_processor.h

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

#ifndef EFM_PROCESSOR_H
#define EFM_PROCESSOR_H

#include <QString>
#include <QDebug>
#include <QFile>
#include <QElapsedTimer>

#include "decoders.h"
#include "dec_f2sectiontof1section.h"
#include "dec_f1sectiontodata24section.h"

#include "writer_data24section.h"
#include "reader_f2section.h"

class EfmProcessor
{
public:
    EfmProcessor();

    bool process(const QString &inputFilename, const QString &outputFilename);
    void setShowData(bool showData24, bool showF1);
    void setDebug(bool f1, bool data24);
    void showStatistics() const;

private:
    // Data debug options (to show data at various stages of processing)
    bool m_showData24;
    bool m_showF1;

    // IEC 60909-1999 Decoders
    F2SectionToF1Section m_f2SectionToF1Section;
    F1SectionToData24Section m_f1SectionToData24Section;

    // Input file readers
    ReaderF2Section m_readerF2Section;

    // Output file writers
    WriterData24Section m_writerData24Section;

    // Processing statistics
    struct GeneralPipelineStatistics {
        qint64 f2SectionToF1SectionTime{0};
        qint64 f1ToData24Time{0};
    } m_generalPipelineStats;

    void processGeneralPipeline();
    void showGeneralPipelineStatistics();
};

#endif // EFM_PROCESSOR_H