/************************************************************************

    dec_tvaluestochannel.h

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

#ifndef DEC_TVALUESTOCHANNEL_H
#define DEC_TVALUESTOCHANNEL_H

#include "decoders.h"
#include "tvalues.h"

class TvaluesToChannel : public Decoder
{
public:
    TvaluesToChannel();
    void pushFrame(const QByteArray &data);
    QByteArray popFrame();
    bool isReady() const;

    void showStatistics();

private:
    void processStateMachine();
    void attemptToFixOvershootFrame(QByteArray &frameData);
    void attemptToFixUndershootFrame(quint32 startIndex, quint32 endIndex, QByteArray &frameData);
    quint32 countBits(const QByteArray &data, qint32 startPosition = 0, qint32 endPosition = -1);

    // State machine states
    enum State { ExpectingInitialSync, ExpectingSync, HandleOvershoot, HandleUndershoot };

    // Statistics
    quint32 m_consumedTValues;
    quint32 m_discardedTValues;
    quint32 m_channelFrameCount;

    quint32 m_perfectFrames;
    quint32 m_longFrames;
    quint32 m_shortFrames;

    quint32 m_overshootSyncs;
    quint32 m_undershootSyncs;
    quint32 m_perfectSyncs;

    State m_currentState;
    QByteArray m_internalBuffer;
    QByteArray m_frameData;

    QQueue<QByteArray> m_inputBuffer;
    QQueue<QByteArray> m_outputBuffer;

    Tvalues m_tvalues;
    quint32 m_tvalueDiscardCount;

    State expectingInitialSync();
    State expectingSync();
    State handleUndershoot();
    State handleOvershoot();
};

#endif // DEC_TVALUESTOCHANNEL_H