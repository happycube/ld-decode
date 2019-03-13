/************************************************************************

    decodeaudio.h

    ld-process-efm - EFM data decoder
    Copyright (C) 2019 Simon Inns

    This file is part of ld-decode-tools.

    ld-process-efm is free software: you can redistribute it and/or
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

#ifndef DECODEAUDIO_H
#define DECODEAUDIO_H

#include <QCoreApplication>
#include <QDebug>
#include <QFile>
#include <QDataStream>

#include "subcodeblock.h"
#include "f3frame.h"
#include "c1circ.h"
#include "c2circ.h"
#include "c2deinterleave.h"

class DecodeAudio
{
public:
    DecodeAudio();
    ~DecodeAudio();

    void reportStatus(void);
    bool openOutputFile(QString filename);
    void closeOutputFile(void);
    void flush(void);
    void process(SubcodeBlock subcodeBlock);

private:
    C1Circ c1Circ;
    C2Circ c2Circ;
    C2Deinterleave c2Deinterleave;

    QFile *outputFileHandle;
    QDataStream *outputStream;

    void writeAudioData(QByteArray audioData);
};

#endif // DECODEAUDIO_H
