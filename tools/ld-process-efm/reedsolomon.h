/************************************************************************

    reedsolomon.cpp

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

#ifndef REEDSOLOMON_H
#define REEDSOLOMON_H

#include <QCoreApplication>
#include <QDebug>

class ReedSolomon
{
public:
    ReedSolomon();

    bool decodeC1(uchar *inData, bool *inErasures);
    bool decodeC2(uchar *inData, bool *inErasures);

private:
    QString dataToString(std::vector<uint8_t> data);

    qint32 c1Passed;
    qint32 c1Corrected;
    qint32 c1Failed;

    qint32 c2Passed;
    qint32 c2Corrected;
    qint32 c2Failed;
};

#endif // REEDSOLOMON_H
