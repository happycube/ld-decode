/************************************************************************

    dec_channeltof3frame.h

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

#ifndef DEC_CHANNELTOF3FRAME_H
#define DEC_CHANNELTOF3FRAME_H

#include "decoders.h"
#include "efm.h"

class ChannelToF3Frame : public Decoder
{
public:
    ChannelToF3Frame();
    void pushFrame(const QByteArray &data);
    F3Frame popFrame();
    bool isReady() const;

    void showStatistics();

private:
    void processQueue();
    F3Frame createF3Frame(const QByteArray &data);

    QByteArray tvaluesToData(const QByteArray &tvalues);
    quint16 getBits(const QByteArray &data, int startBit, int endBit);

    Efm m_efm;

    QQueue<QByteArray> m_inputBuffer;
    QQueue<F3Frame> m_outputBuffer;

    // Statistics
    quint32 m_goodFrames;
    quint32 m_undershootFrames;
    quint32 m_overshootFrames;
    quint32 m_validEfmSymbols;
    quint32 m_invalidEfmSymbols;
    quint32 m_validSubcodeSymbols;
    quint32 m_invalidSubcodeSymbols;
};

#endif // DEC_CHANNELTOF3FRAME_H