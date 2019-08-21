/************************************************************************

    ldsprocess.h

    ld-ldstoefm - LDS sample to EFM data processing
    Copyright (C) 2019 Simon Inns

    This file is part of ld-decode-tools.

    ld-ldstoefm is free software: you can redistribute it and/or
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

#ifndef LDSPROCESS_H
#define LDSPROCESS_H

#include <QCoreApplication>
#include <QDebug>
#include <QFile>

#include "pll.h"

class LdsProcess
{
public:
    LdsProcess();
    bool process(QString outputFilename);

private:
    QFile stdinFileHandle;
    QFile *outputFileHandle;
    Pll pll;

    bool openInputFile();
    void closeInputFile(void);

    bool openOutputFile(QString outputFileName);
    void closeOutputFile(void);
};

#endif // LDSPROCESS_H
