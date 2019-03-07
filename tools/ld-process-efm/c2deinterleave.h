/************************************************************************

    c2deinterleave.h

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

#ifndef C2DEINTERLEAVE_H
#define C2DEINTERLEAVE_H

#include <QCoreApplication>
#include <QDebug>

class C2Deinterleave
{
public:
    C2Deinterleave();

    void reportStatus(void);
    void pushC2(QByteArray dataSymbols, QByteArray errorSymbols);
    QByteArray getDataSymbols(void);
    QByteArray getErrorSymbols(void);
    void flush(void);

private:
    struct C2Element {
        QByteArray c2Data;
        QByteArray c2Error;
    };
    QVector<C2Element> c2DelayBuffer;

    QByteArray outputC2Data;
    QByteArray outputC2Errors;

    qint32 c2flushed;
    qint32 validDeinterleavedC2s;
    qint32 invalidDeinterleavedC2s;

    void deinterleave(void);
};

#endif // C2DEINTERLEAVE_H
