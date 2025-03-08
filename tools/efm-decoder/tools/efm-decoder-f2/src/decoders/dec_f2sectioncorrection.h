/************************************************************************

    dec_f2sectioncorrection.h

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

#ifndef DEC_F2SECTIONCORRECTION_H
#define DEC_F2SECTIONCORRECTION_H

#include <QQueue>
#include <QVector>
#include "decoders.h"
#include "section_metadata.h"

class F2SectionCorrection : public Decoder
{
public:
    F2SectionCorrection();
    void pushSection(const F2Section &data);
    F2Section popSection();
    bool isReady() const;
    void flush();

    void showStatistics() const;

private:
    void processQueue();

    void waitForInputToSettle(F2Section &f2Section);
    void waitingForSection(F2Section &f2Section);
    SectionTime getExpectedAbsoluteTime() const;

    void processInternalBuffer();
    void outputSections();

    QQueue<F2Section> m_inputBuffer;
    QQueue<F2Section> m_leadinBuffer;
    QQueue<F2Section> m_outputBuffer;

    QQueue<F2Section> m_internalBuffer;

    bool m_leadinComplete;

    QQueue<F2Section> m_window;
    quint32 m_maximumGapSize;
    quint32 m_paddingWatermark;

    // Statistics
    quint32 m_totalSections;
    quint32 m_correctedSections;
    quint32 m_uncorrectableSections;
    quint32 m_preLeadinSections;
    quint32 m_missingSections;
    quint32 m_paddingSections;
    quint32 m_outOfOrderSections;

    quint32 m_qmode1Sections;
    quint32 m_qmode2Sections;
    quint32 m_qmode3Sections;
    quint32 m_qmode4Sections;

    // Time statistics
    SectionTime m_absoluteStartTime;
    SectionTime m_absoluteEndTime;
    QVector<quint8> m_trackNumbers;
    QVector<SectionTime> m_trackStartTimes;
    QVector<SectionTime> m_trackEndTimes;
};

#endif // DEC_F2SECTIONCORRECTION_H