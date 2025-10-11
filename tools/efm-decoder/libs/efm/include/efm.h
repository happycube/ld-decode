/************************************************************************

    efm.h

    EFM-library - EFM conversion functions
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

#ifndef EFM_H
#define EFM_H

#include <cstdint>
#include <QDebug>
#include <QHash>

class Efm
{
public:
    Efm() noexcept;
    ~Efm() = default;

    // Delete copy operations to prevent accidental copies
    Efm(const Efm&) = delete;
    Efm& operator=(const Efm&) = delete;

    // Make move operations default
    Efm(Efm&&) = default;
    Efm& operator=(Efm&&) = default;

    // Convert methods made const as they don't modify state
    quint16 fourteenToEight(quint16 efm) const noexcept;
    QString eightToFourteen(quint16 value) const;

private:
    static constexpr size_t EFM_LUT_SIZE = 258; // 256 + 2 sync symbols
    static constexpr quint16 INVALID_EFM = 300;
    QHash<quint16, quint16> m_efmHash;
};

#endif // EFM_H