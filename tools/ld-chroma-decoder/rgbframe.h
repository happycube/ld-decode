/************************************************************************

    rgbframe.h

    ld-chroma-decoder - Colourisation filter for ld-decode
    Copyright (C) 2020 Adam Sampson

    This file is part of ld-decode-tools.

    ld-chroma-decoder is free software: you can redistribute it and/or
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

#ifndef RGBFRAME_H
#define RGBFRAME_H

#include <QtGlobal>
#include <QVector>

// A decoded frame, containing triples of (R, G, B) samples
using RGBFrame = QVector<quint16>;

#endif // RGBFRAME_H
