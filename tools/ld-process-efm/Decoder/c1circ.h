/************************************************************************

    c1circ.h

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

#ifndef C1CIRC_H
#define C1CIRC_H

#include <QCoreApplication>
#include <QDebug>

#include <ezpwd/rs_base>
#include <ezpwd/rs>

// CD-ROM specific CIRC configuration for Reed-Solomon forward error correction
template < size_t SYMBOLS, size_t PAYLOAD > struct C1RS;
template < size_t PAYLOAD > struct C1RS<255, PAYLOAD> : public __RS(C1RS, uint8_t, 255, PAYLOAD, 0x11d, 0,  1);

#include "Datatypes/f3frame.h"

class C1Circ
{
public:
    C1Circ();

    // Statistics data structure
    struct Statistics {
        qint32 c1Passed;
        qint32 c1Corrected;
        qint32 c1Failed;
        qint32 c1flushed;
    };

    void reset(void);
    void resetStatistics(void);
    Statistics getStatistics(void);
    void reportStatus(void);
    void pushF3Frame(F3Frame f3Frame);
    QByteArray getDataSymbols(void);
    QByteArray getErrorSymbols(void);
    void flush(void);

private:
    QByteArray currentF3Data;
    QByteArray previousF3Data;
    QByteArray currentF3Errors;
    QByteArray previousF3Errors;

    QByteArray interleavedC1Data;
    QByteArray interleavedC1Errors;

    QByteArray outputC1Data;
    QByteArray outputC1Errors;

    qint32 c1BufferLevel;    
    Statistics statistics;

    void interleave(void);
    void errorCorrect(void);
};

#endif // C1CIRC_H
