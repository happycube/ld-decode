/************************************************************************

    efmprocess.cpp

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

#ifndef EFMPROCESS_H
#define EFMPROCESS_H

#include <QCoreApplication>
#include <QDebug>
#include <QFile>
#include <QDataStream>

#include "f3framer.h"
#include "subcodeblock.h"

#include "decodesubcode.h"
#include "decodeaudio.h"

class EfmProcess
{
public:
    EfmProcess();

    bool process(QString inputFilename, QString outputFilename, bool frameDebug);

private:
    QFile *inputFileHandle;
    QFile *outputFileHandle;

    F3Framer f3Framer;
    SubcodeBlock subcodeBlock;

    DecodeSubcode decodeSubcode;
    DecodeAudio decodeAudio;

    void saveAudioData(QDataStream &outStream);

    bool openInputFile(QString inputFileName);
    void closeInputFile(void);
    QByteArray readEfmData(qint32 bufferSize);

    bool openOutputDataFile(QString filename);
    void closeOutputDataFile(void);
};

#endif // EFMPROCESS_H
