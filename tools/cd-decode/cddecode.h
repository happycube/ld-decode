/************************************************************************

    cddecode.h

    cd-decode - Compact Disc RF to EFM converter
    Copyright (C) 2019 Simon Inns

    This file is part of ld-decode-tools.

    cd-decode is free software: you can redistribute it and/or
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

#ifndef CDDECODE_H
#define CDDECODE_H

#include <QObject>
#include <QCoreApplication>
#include <QDebug>
#include <QFile>

#include "isifilter.h"
#include "pll.h"

class CdDecode : public QObject
{
    Q_OBJECT
public:
    explicit CdDecode(QObject *parent = nullptr);

    bool process(QString inputFilename);

private:
    QFile *inputFileHandle;
    QFile *outputFileHandle;

    IsiFilter isiFilter;
    Pll pll;

    bool openInputFile(QString inputFilename);
    void closeInputFile();

    bool openOutputFile(QString outputFilename);
    void closeOutputFile();
};

#endif // CDDECODE_H
