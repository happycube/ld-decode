/************************************************************************

    inverter.cpp

    EFM-library - Parity inversion functions
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

#include "inverter.h"

Inverter::Inverter() { }

// Invert the P and Q parity bytes in accordance with
// ECMA-130 issue 2 page 35/36
void Inverter::invertParity(QVector<quint8> &inputData)
{
    if (inputData.size() != 32) {
        qFatal("Inverter::invertParity(): Data must be a QVector of 32 integers.");
    }

    for (int i = 12; i < 16; ++i) {
        inputData[i] = ~inputData[i] & 0xFF;
    }
    for (int i = 28; i < 32; ++i) {
        inputData[i] = ~inputData[i] & 0xFF;
    }
}