/************************************************************************

    dec_f1sectiontodata24section.h

    ld-efm-decoder - EFM data decoder
    Copyright (C) 2025 Simon Inns

    This file is part of ld-decode-tools.

    ld-efm-decoder is free software: you can redistribute it and/or
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

#ifndef DEC_F1SECTIONTODATA24SECTION_H
#define DEC_F1SECTIONTODATA24SECTION_H

#include "decoders.h"
#include "section.h"

class F1SectionToData24Section : public Decoder
{
public:
    F1SectionToData24Section();
    void pushSection(const F1Section &f1Section);
    Data24Section popSection();
    bool isReady() const;

    void showStatistics();

private:
    void processQueue();

    QQueue<F1Section> m_inputBuffer;
    QQueue<Data24Section> m_outputBuffer;

    quint64 m_invalidF1FramesCount;
    quint64 m_validF1FramesCount;
    quint64 m_corruptBytesCount;

    quint64 m_paddedBytesCount;
    quint64 m_unpaddedF1FramesCount;
    quint64 m_paddedF1FramesCount;
};

#endif // DEC_F1SECTIONTODATA24SECTION_H