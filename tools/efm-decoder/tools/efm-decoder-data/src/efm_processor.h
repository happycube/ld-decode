/************************************************************************

    efm_processor.h

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

#ifndef EFM_PROCESSOR_H
#define EFM_PROCESSOR_H

#include <QString>
#include <QDebug>
#include <QFile>
#include <QElapsedTimer>

#include "decoders.h"
#include "dec_data24torawsector.h"
#include "dec_rawsectortosector.h"
#include "dec_sectorcorrection.h"

#include "writer_sector.h"
#include "writer_sector_metadata.h"

#include "reader_data24section.h"

class EfmProcessor
{
public:
    EfmProcessor();

    bool process(const QString &inputFilename, const QString &outputFilename);
    void setShowData(bool showRawSector);
    void setOutputType(bool outputDataMetadata);
    void setDebug(bool rawSector, bool sector, bool sectorCorrection);
    void showStatistics() const;

private:
    // Data debug options (to show data at various stages of processing)
    bool m_showRawSector;

    // Output options
    bool m_outputDataMetadata;

    // ECMA-130 Decoders
    Data24ToRawSector m_data24ToRawSector;
    RawSectorToSector m_rawSectorToSector;
    SectorCorrection m_sectorCorrection;

    // Input file readers
    ReaderData24Section m_readerData24Section;

    // Output file writers
    WriterSector m_writerSector;
    WriterSectorMetadata m_writerSectorMetadata;

    // Processing statistics
    struct DataPipelineStatistics {
        qint64 data24ToRawSectorTime{0};
        qint64 rawSectorToSectorTime{0};
    } m_dataPipelineStats;

    void processDataPipeline();
    void showDataPipelineStatistics();
};

#endif // EFM_PROCESSOR_H