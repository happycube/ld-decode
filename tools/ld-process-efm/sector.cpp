/************************************************************************

    sector.cpp

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

#include "sector.h"

Sector::Sector()
{
    valid = false;
}

// Method to set the sector's data from a F1 frame
void Sector::setData(F1Frame f1Frame)
{
    // Get the f1 data symbols and represent as unsigned 8-bit
    QByteArray f1Data = f1Frame.getDataSymbols();
    uchar* uF1Data = reinterpret_cast<uchar*>(f1Data.data());

    // Set the sector's address
    address.setTime(
        bcdToInteger(static_cast<uchar>(uF1Data[12])),
        bcdToInteger(static_cast<uchar>(uF1Data[13])),
        bcdToInteger(static_cast<uchar>(uF1Data[14]))
        );

    // Set the sector's mode
    mode = uF1Data[15];

    // Range check the mode and default to 1 if out of range
    if (mode < 0 || mode > 2) {
        qDebug() << "Sector::setData(): Invalid mode of" << mode << "defaulting to 1";
        mode = 1;
    }

    // Process the sector depending on the mode
    if (mode == 0) {
        // Mode 0 sector
        // This is an empty sector filled with 2336 zeros
        userData.fill(0, 2336);
        valid = true;
    } else if (mode == 1) {
        // Mode 1 sector
        // This is a data sector with error correction

        // Perform CRC - since ECC is expensive on processing, we only
        // error correct sector data if the CRC fails

        // Get the 32-bit EDC word from the F1 data
        edcWord =
            ((static_cast<quint32>(uF1Data[2064])) <<  0) |
            ((static_cast<quint32>(uF1Data[2065])) <<  8) |
            ((static_cast<quint32>(uF1Data[2066])) << 16) |
            ((static_cast<quint32>(uF1Data[2067])) << 24);

        // Perform a CRC32 on bytes 0 to 2063 of the F1 frame
        if (edcWord != crc32(uF1Data, 2064)) {
            //qDebug() << "Sector::setData(): CRC32 failed";

            // Attempt error correction on sector
            // TO-DO
        } else {
            // EDC passed, data is valid.  Copy to sector user data (2048 bytes)
            userData = f1Data.mid(16, 2048);
            valid = true;
        }
    } else if (mode == 2) {
        // Mode 2 sector
        // This is a 2336 byte data sector without error correction
        userData = f1Data.mid(16, 2336);
        valid = true;
    }
}

// Method to get the sector's mode
qint32 Sector::getMode(void)
{
    return mode;
}

// Method to get the sector's address
TrackTime Sector::getAddress(void)
{
    return address;
}

// Method to get the sector's user data
QByteArray Sector::getUserData(void)
{
    return userData;
}

// Method to get the sector's validity
bool Sector::isValid(void)
{
    return valid;
}

// Private methods ----------------------------------------------------------------------------------------------------

// Method to convert 2 digit BCD byte to an integer
qint32 Sector::bcdToInteger(uchar bcd)
{
   return (((bcd>>4)*10) + (bcd & 0xF));
}

// This method is for debug and outputs an array of 8-bit unsigned data as a hex string
QString Sector::dataToString(QByteArray data)
{
    QString output;

    for (qint32 count = 0; count < data.length(); count++) {
        output += QString("%1").arg(static_cast<uchar>(data[count]), 2, 16, QChar('0'));
    }

    return output;
}

// CRC code adapted and used under GPLv3 from:
// https://github.com/claunia/edccchk/blob/master/edccchk.c
quint32 Sector::crc32(uchar *src, qint32 size)
{
    quint32 crc = 0;

    while(size--) {
        crc = (crc >> 8) ^ crc32LUT[(crc ^ (*src++)) & 0xFF];
    }

    return crc;
}
