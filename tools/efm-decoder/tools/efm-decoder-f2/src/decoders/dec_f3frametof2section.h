/************************************************************************

    dec_f3frametof2section.h

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

#ifndef DEC_F3FRAMETOF2SECTION_H
#define DEC_F3FRAMETOF2SECTION_H

#include "decoders.h"
#include "section.h"
#include "subcode.h"

class F3FrameToF2Section : public Decoder
{
public:
    F3FrameToF2Section();
    void pushFrame(const F3Frame &data);
    F2Section popSection();
    bool isReady() const;

    void showStatistics();

private:
    void processStateMachine();
    void outputSection(bool showAddress);

    QQueue<F3Frame> m_inputBuffer;
    QQueue<F2Section> m_outputBuffer;

    QVector<F3Frame> m_internalBuffer;
    QVector<F3Frame> m_sectionFrames;

    qint32 m_badSyncCounter;
    SectionMetadata m_lastSectionMetadata;

    // State machine states
    enum State { ExpectingInitialSync, ExpectingSync, HandleValid, HandleOvershoot, HandleUndershoot, LostSync };

    State m_currentState;

    // State machine state processing functions
    State expectingInitialSync();
    State expectingSync();
    State handleValid();
    State handleUndershoot();
    State handleOvershoot();
    State lostSync();

    // Statistics
    quint64 m_inputF3Frames;
    quint64 m_presyncDiscardedF3Frames;
    quint64 m_goodSync0;
    quint64 m_missingSync0;
    quint64 m_undershootSync0;
    quint64 m_overshootSync0;
    quint64 m_discardedF3Frames;
    quint64 m_paddedF3Frames;
    quint64 m_lostSyncCounter;
};

#endif // DEC_F3FRAMETOF2SECTION_H