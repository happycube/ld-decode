/************************************************************************

    dec_rawsectortosector.h

    efm-decoder-data - EFM Data24 to data decoder
    Copyright (C) 2025 Simon Inns

    This file is part of ld-decode-tools.

    This application is free software: you can redistribute it and/or
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

#ifndef DEC_RAWSECTORTOSECTOR_H
#define DEC_RAWSECTORTOSECTOR_H

#include "decoders.h"
#include "sector.h"
#include "rspc.h"

class RawSectorToSector : public Decoder
{
public:
    RawSectorToSector();
    void pushSector(const RawSector &rawSector);
    Sector popSector();
    bool isReady() const;

    void showStatistics();

private:
    void processQueue();
    quint8 bcdToInt(quint8 bcd);
    quint32 crc32(const QByteArray &src, qint32 size);

    QQueue<RawSector> m_inputBuffer;
    QQueue<Sector> m_outputBuffer;

    // Statistics
    quint32 m_validSectors;
    quint32 m_invalidSectors;
    quint32 m_correctedSectors;

    quint32 m_mode0Sectors;
    quint32 m_mode1Sectors;
    quint32 m_mode2Sectors;
    quint32 m_invalidModeSectors;

    // This table is the CRC32 look-up for the EDC data
    const quint32 m_crc32Lut[256] = {
        0x00000000, 0x90910101, 0x91210201, 0x01B00300, 0x92410401, 0x02D00500, 0x03600600, 0x93F10701,
        0x94810801, 0x04100900, 0x05A00A00, 0x95310B01, 0x06C00C00, 0x96510D01, 0x97E10E01, 0x07700F00,
        0x99011001, 0x09901100, 0x08201200, 0x98B11301, 0x0B401400, 0x9BD11501, 0x9A611601, 0x0AF01700,
        0x0D801800, 0x9D111901, 0x9CA11A01, 0x0C301B00, 0x9FC11C01, 0x0F501D00, 0x0EE01E00, 0x9E711F01,
        0x82012001, 0x12902100, 0x13202200, 0x83B12301, 0x10402400, 0x80D12501, 0x81612601, 0x11F02700,
        0x16802800, 0x86112901, 0x87A12A01, 0x17302B00, 0x84C12C01, 0x14502D00, 0x15E02E00, 0x85712F01,
        0x1B003000, 0x8B913101, 0x8A213201, 0x1AB03300, 0x89413401, 0x19D03500, 0x18603600, 0x88F13701,
        0x8F813801, 0x1F103900, 0x1EA03A00, 0x8E313B01, 0x1DC03C00, 0x8D513D01, 0x8CE13E01, 0x1C703F00,
        0xB4014001, 0x24904100, 0x25204200, 0xB5B14301, 0x26404400, 0xB6D14501, 0xB7614601, 0x27F04700,
        0x20804800, 0xB0114901, 0xB1A14A01, 0x21304B00, 0xB2C14C01, 0x22504D00, 0x23E04E00, 0xB3714F01,
        0x2D005000, 0xBD915101, 0xBC215201, 0x2CB05300, 0xBF415401, 0x2FD05500, 0x2E605600, 0xBEF15701,
        0xB9815801, 0x29105900, 0x28A05A00, 0xB8315B01, 0x2BC05C00, 0xBB515D01, 0xBAE15E01, 0x2A705F00,
        0x36006000, 0xA6916101, 0xA7216201, 0x37B06300, 0xA4416401, 0x34D06500, 0x35606600, 0xA5F16701,
        0xA2816801, 0x32106900, 0x33A06A00, 0xA3316B01, 0x30C06C00, 0xA0516D01, 0xA1E16E01, 0x31706F00,
        0xAF017001, 0x3F907100, 0x3E207200, 0xAEB17301, 0x3D407400, 0xADD17501, 0xAC617601, 0x3CF07700,
        0x3B807800, 0xAB117901, 0xAAA17A01, 0x3A307B00, 0xA9C17C01, 0x39507D00, 0x38E07E00, 0xA8717F01,
        0xD8018001, 0x48908100, 0x49208200, 0xD9B18301, 0x4A408400, 0xDAD18501, 0xDB618601, 0x4BF08700,
        0x4C808800, 0xDC118901, 0xDDA18A01, 0x4D308B00, 0xDEC18C01, 0x4E508D00, 0x4FE08E00, 0xDF718F01,
        0x41009000, 0xD1919101, 0xD0219201, 0x40B09300, 0xD3419401, 0x43D09500, 0x42609600, 0xD2F19701,
        0xD5819801, 0x45109900, 0x44A09A00, 0xD4319B01, 0x47C09C00, 0xD7519D01, 0xD6E19E01, 0x46709F00,
        0x5A00A000, 0xCA91A101, 0xCB21A201, 0x5BB0A300, 0xC841A401, 0x58D0A500, 0x5960A600, 0xC9F1A701,
        0xCE81A801, 0x5E10A900, 0x5FA0AA00, 0xCF31AB01, 0x5CC0AC00, 0xCC51AD01, 0xCDE1AE01, 0x5D70AF00,
        0xC301B001, 0x5390B100, 0x5220B200, 0xC2B1B301, 0x5140B400, 0xC1D1B501, 0xC061B601, 0x50F0B700,
        0x5780B800, 0xC711B901, 0xC6A1BA01, 0x5630BB00, 0xC5C1BC01, 0x5550BD00, 0x54E0BE00, 0xC471BF01,
        0x6C00C000, 0xFC91C101, 0xFD21C201, 0x6DB0C300, 0xFE41C401, 0x6ED0C500, 0x6F60C600, 0xFFF1C701,
        0xF881C801, 0x6810C900, 0x69A0CA00, 0xF931CB01, 0x6AC0CC00, 0xFA51CD01, 0xFBE1CE01, 0x6B70CF00,
        0xF501D001, 0x6590D100, 0x6420D200, 0xF4B1D301, 0x6740D400, 0xF7D1D501, 0xF661D601, 0x66F0D700,
        0x6180D800, 0xF111D901, 0xF0A1DA01, 0x6030DB00, 0xF3C1DC01, 0x6350DD00, 0x62E0DE00, 0xF271DF01,
        0xEE01E001, 0x7E90E100, 0x7F20E200, 0xEFB1E301, 0x7C40E400, 0xECD1E501, 0xED61E601, 0x7DF0E700,
        0x7A80E800, 0xEA11E901, 0xEBA1EA01, 0x7B30EB00, 0xE8C1EC01, 0x7850ED00, 0x79E0EE00, 0xE971EF01,
        0x7700F000, 0xE791F101, 0xE621F201, 0x76B0F300, 0xE541F401, 0x75D0F500, 0x7460F600, 0xE4F1F701,
        0xE381F801, 0x7310F900, 0x72A0FA00, 0xE231FB01, 0x71C0FC00, 0xE151FD01, 0xE0E1FE01, 0x7070FF00
    };
};

#endif // DEC_RAWSECTORTOSECTOR_H