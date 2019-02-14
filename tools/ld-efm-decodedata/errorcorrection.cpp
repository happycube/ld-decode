/************************************************************************

    errorcorrection.cpp

    ld-efm-decodedata - EFM data decoder for ld-decode
    Copyright (C) 2019 Simon Inns

    This file is part of ld-decode-tools.

    ld-efm-decodedata is free software: you can redistribute it and/or
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

#include "errorcorrection.h"

ErrorCorrection::ErrorCorrection()
{
    // Initialise the rscode library
    // This is configured (via ecc.h to support 4
    // parity bytes)
    initialize_ecc();
}

// Method to perform CIRC error checking and correction of P values
void ErrorCorrection::checkP(qint32 data[])
{
    (void)data;
}

// Method to perform CIRC error checking and correction of P values
void ErrorCorrection::checkQ(qint32 data[])
{
    (void)data;
}
