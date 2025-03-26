/************************************************************************

    reedsolomon.h

    EFM-library - Reed-Solomon CIRC functions
    Copyright (C) 2025 Simon Inns

    This file is part of EFM-Tools.

    This is free software: you can redistribute it and/or
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

#include <QDebug>

// ezpwd configuration is:
// NAME, TYPE, SYMBOLS, PAYLOAD, POLY, INIT, FCR, AGR

// To find the integer representation of the polynomial P(x)=x^8+x^4+x^3+x^2+1
// treat the coefficients as binary digits, where each coefficient corresponds to a power of x,
// starting from x^0 on the rightmost side. If there is no term for a specific power of x, its
// coefficient is 0.
//
// Steps:
//     Write the polynomial in terms of its binary representation:
//     P(x)=x^8+x^4+x^3+x^2+1
//
//     The coefficients from x^8 down to x^0 are: 1,0,0,0,1,1,1,0,1.
//
//     Form the binary number from the coefficients:
//     Binary representation: 100011101

//     Convert the binary number to its decimal (integer) equivalent:
//     0b100011101 = 0x11D = 285

class ReedSolomon
{
public:
    ReedSolomon();
    void c1Decode(QVector<quint8> &inputData, QVector<bool> &errorData,
        QVector<bool> &paddedData, bool m_showDebug);
    void c2Decode(QVector<quint8> &inputData, QVector<bool> &errorData,
        QVector<bool> &paddedData, bool m_showDebug);

    qint32 validC1s();
    qint32 fixedC1s();
    qint32 errorC1s();

    qint32 validC2s();
    qint32 fixedC2s();
    qint32 errorC2s();

private:
    qint32 m_validC1s;
    qint32 m_fixedC1s;
    qint32 m_errorC1s;

    qint32 m_validC2s;
    qint32 m_fixedC2s;
    qint32 m_errorC2s;
};

#endif // REEDSOLOMON_H