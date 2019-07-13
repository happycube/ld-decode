/************************************************************************

    sourceframe.cpp

    ld-decode-tools shared library
    Copyright (C) 2018 Simon Inns

    This file is part of ld-decode-tools.

    ld-decode-tools is free software: you can redistribute it and/or
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

#include "sourcefield.h"

SourceField::SourceField(QByteArray fieldGrayScaleData, QObject *parent) : QObject (parent)
{
    setFieldData(fieldGrayScaleData);
}

// Public method to set the frame's greyscale data
void SourceField::setFieldData(QByteArray fieldGreyscaleData)
{
    greyScaleData = QByteArray(fieldGreyscaleData, fieldGreyscaleData.size());
}

// Public method to get the frame's greyscale data
QByteArray SourceField::getFieldData(void)
{
    return greyScaleData;
}
