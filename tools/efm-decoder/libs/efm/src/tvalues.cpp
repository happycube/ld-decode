/************************************************************************

    tvalues.cpp

    EFM-library - T-values to bit string conversion
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

#include "tvalues.h"

Tvalues::Tvalues()
    : m_invalidHighTValuesCount(0),
      m_invalidLowTValuesCount(0),
      m_validTValuesCount(0)
{
}

QString Tvalues::tvaluesToBitString(const QByteArray &tvalues)
{
    QString bitString;

    // For every T-value in the input array reserve 11 bits in the output bit string
    // Note: This is just to increase speed
    bitString.reserve(tvalues.size() * 11);

    for (qint32 i = 0; i < tvalues.size(); ++i) {
        // Convert the T-value to a bit string

        // Range check
        qint32 tValue = static_cast<qint32>(tvalues[i]);
        if (tValue > 11) {
            m_invalidHighTValuesCount++;
            tValue = 11;
        } else if (tValue < 3) {
            m_invalidLowTValuesCount++;
            tValue = 3;
        } else {
            m_validTValuesCount++;
        }

        // T3 = 100, T4 = 1000, ... , T11 = 10000000000
        bitString += '1';
        bitString += QString(tValue - 1, '0');
    }

    return bitString;
}
