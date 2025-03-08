/************************************************************************

    efm.cpp

    EFM-library - EFM Frame type classes
    Copyright (C) 2025 Simon Inns

    This file is part of ld-decode-tools.

    ld-efm-decoder is free software: you can redistribute it and/or
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

#include "efm.h"

Efm::Efm() noexcept
{
    // Pre-allocate hash table to avoid rehashing
    m_efmHash.reserve(EFM_LUT_SIZE);
    
    // Initialise the hash table
    for (quint16 i = 0; i < EFM_LUT_SIZE; ++i) {
        m_efmHash.insert(efmLut[i], i);
    }
}

// Note: There are 257 EFM symbols: 0 to 255 and two additional sync0 and sync1 symbols
// A value of 300 is returned for an invalid EFM symbol
quint16 Efm::fourteenToEight(quint16 efm) const noexcept
{
    // Use hash table for O(1) lookup instead of linear search
    auto it = m_efmHash.find(efm);
    return it != m_efmHash.end() ? it.value() : INVALID_EFM;
}

QString Efm::eightToFourteen(quint16 value) const
{
    if (value >= EFM_LUT_SIZE) {
        throw std::out_of_range("EFM value out of valid range");
    }

    quint16 efm = efmLut[value];
    QString efmString;
    efmString.reserve(14); // Pre-allocate string space

    // Convert the 14-bit EFM code to a 14-bit string
    for (int i = 13; i >= 0; --i) {
        efmString.append((efm & (1 << i)) ? '1' : '0');
    }

    return efmString;
}