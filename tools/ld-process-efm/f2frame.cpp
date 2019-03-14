/************************************************************************

    f2frame.cpp

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

#include "f2frame.h"

// Note: Class for storing 'F2 frames' as defined by clause 17 of ECMA-130

F2Frame::F2Frame()
{
    dataSymbols.resize(24);
    errorSymbols.resize(24);

    dataSymbols.fill(0);
    errorSymbols.fill(0);
}

void F2Frame::setData(QByteArray dataParam, QByteArray erasuresParam)
{
    dataSymbols = dataParam;
    errorSymbols = erasuresParam;
}

// This method returns the 24 data symbols for the F3 Frame
QByteArray F2Frame::getDataSymbols(void)
{
    return dataSymbols;
}

// This method returns the 24 error symbols for the F3 Frame
QByteArray F2Frame::getErrorSymbols(void)
{
    return errorSymbols;
}
