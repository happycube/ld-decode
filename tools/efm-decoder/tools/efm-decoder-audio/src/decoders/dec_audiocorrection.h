/************************************************************************

    dec_audiocorrection.h

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

#ifndef DEC_AUDIOCORRECTION_H
#define DEC_AUDIOCORRECTION_H

#include "decoders.h"
#include "section.h"

class AudioCorrection : public Decoder
{
public:
    AudioCorrection();
    void pushSection(const AudioSection &audioSection);
    AudioSection popSection();
    bool isReady() const;

    void showStatistics();

private:
    void processQueue();
    QString convertToAudacityTimestamp(qint32 minutes, qint32 seconds, qint32 frames, qint32 subsection, qint32 sample);

    QQueue<AudioSection> m_inputBuffer;
    QQueue<AudioSection> m_outputBuffer;

    QVector<AudioSection> m_correctionBuffer;

    bool m_firstSectionFlag;

    // Statistics
    quint32 m_concealedSamplesCount;
    quint32 m_silencedSamplesCount;
    quint32 m_validSamplesCount;
};

#endif // DEC_AUDIOCORRECTION_H