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

    // The following table provides the 10-bit EFM code (padded with leading
    // zeros to 16-bit) corresponding to 0 to 255.  The represented number is
    // given by the position in the array (i.e. position 0 = EFM code for
    // decimal 0 and so on).  Symbols 256 and 257 are the sync symbols sync0
    // and sync1 respectively.
    const quint16 efmLut[256 + 2] = {
        0x1220, 0x2100, 0x2420, 0x2220, 0x1100, 0x0110, 0x0420, 0x0900, //   8 (7)
        0x1240, 0x2040, 0x2440, 0x2240, 0x1040, 0x0040, 0x0440, 0x0840, //  16
        0x2020, 0x2080, 0x2480, 0x0820, 0x1080, 0x0080, 0x0480, 0x0880, //  24
        0x1210, 0x2010, 0x2410, 0x2210, 0x1010, 0x0210, 0x0410, 0x0810, //  32
        0x0020, 0x2108, 0x0220, 0x0920, 0x1108, 0x0108, 0x1020, 0x0908, //  40
        0x1248, 0x2048, 0x2448, 0x2248, 0x1048, 0x0048, 0x0448, 0x0848, //  48
        0x0100, 0x2088, 0x2488, 0x2110, 0x1088, 0x0088, 0x0488, 0x0888, //  56
        0x1208, 0x2008, 0x2408, 0x2208, 0x1008, 0x0208, 0x0408, 0x0808, //  64
        0x1224, 0x2124, 0x2424, 0x2224, 0x1124, 0x0024, 0x0424, 0x0924, //  72
        0x1244, 0x2044, 0x2444, 0x2244, 0x1044, 0x0044, 0x0444, 0x0844, //  80
        0x2024, 0x2084, 0x2484, 0x0824, 0x1084, 0x0084, 0x0484, 0x0884, //  88
        0x1204, 0x2004, 0x2404, 0x2204, 0x1004, 0x0204, 0x0404, 0x0804, //  96
        0x1222, 0x2122, 0x2422, 0x2222, 0x1122, 0x0022, 0x1024, 0x0922, // 104
        0x1242, 0x2042, 0x2442, 0x2242, 0x1042, 0x0042, 0x0442, 0x0842, // 112
        0x2022, 0x2082, 0x2482, 0x0822, 0x1082, 0x0082, 0x0482, 0x0882, // 120
        0x1202, 0x0248, 0x2402, 0x2202, 0x1002, 0x0202, 0x0402, 0x0802, // 128
        0x1221, 0x2121, 0x2421, 0x2221, 0x1121, 0x0021, 0x0421, 0x0921, // 136
        0x1241, 0x2041, 0x2441, 0x2241, 0x1041, 0x0041, 0x0441, 0x0841, // 144
        0x2021, 0x2081, 0x2481, 0x0821, 0x1081, 0x0081, 0x0481, 0x0881, // 152
        0x1201, 0x2090, 0x2401, 0x2201, 0x1090, 0x0201, 0x0401, 0x0890, // 160
        0x0221, 0x2109, 0x1110, 0x0121, 0x1109, 0x0109, 0x1021, 0x0909, // 168
        0x1249, 0x2049, 0x2449, 0x2249, 0x1049, 0x0049, 0x0449, 0x0849, // 176
        0x0120, 0x2089, 0x2489, 0x0910, 0x1089, 0x0089, 0x0489, 0x0889, // 184
        0x1209, 0x2009, 0x2409, 0x2209, 0x1009, 0x0209, 0x0409, 0x0809, // 192
        0x1120, 0x2111, 0x2490, 0x0224, 0x1111, 0x0111, 0x0490, 0x0911, // 200
        0x0241, 0x2101, 0x0244, 0x0240, 0x1101, 0x0101, 0x0090, 0x0901, // 208
        0x0124, 0x2091, 0x2491, 0x2120, 0x1091, 0x0091, 0x0491, 0x0891, // 216
        0x1211, 0x2011, 0x2411, 0x2211, 0x1011, 0x0211, 0x0411, 0x0811, // 224
        0x1102, 0x0102, 0x2112, 0x0902, 0x1112, 0x0112, 0x1022, 0x0912, // 232
        0x2102, 0x2104, 0x0249, 0x0242, 0x1104, 0x0104, 0x0422, 0x0904, // 240
        0x0122, 0x2092, 0x2492, 0x0222, 0x1092, 0x0092, 0x0492, 0x0892, // 248
        0x1212, 0x2012, 0x2412, 0x2212, 0x1012, 0x0212, 0x0412, 0x0812, // 256 (255)
        0x0801, 0x0012 // sync0 (256), sync1 (257)
    };
};

#endif // EFM_H