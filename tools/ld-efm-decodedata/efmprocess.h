/************************************************************************

    efmprocess.cpp

    ld-efm-decodedata - EFM data decoder for ld-decode
    Copyright (C) 2019 Simon Inns

    This file is part of ld-decode-tools.

    ld-efm-decodedata is free software: you can redistribute it and/or
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

#include "decodesubcode.h"
#include "decodeaudio.h"

class EfmProcess
{
public:
    EfmProcess();

    bool process(QString inputFilename, QString outputFilename);

private:
    QFile* inputFile;
    QFile* outputFile;

    DecodeSubcode decodeSubcode;
    DecodeAudio decodeAudio;



    bool openInputF3File(QString filename);
    void closeInputF3File(void);
    QByteArray readF3Frames(qint32 numberOfFrames);
    bool openOutputDataFile(QString filename);
    void closeOutputDataFile(void);


};

#endif // EFMPROCESS_H
