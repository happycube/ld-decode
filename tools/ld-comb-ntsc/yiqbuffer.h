/************************************************************************

    yiqbuffer.h

    ld-comb-ntsc - NTSC colourisation filter for ld-decode
    Copyright (C) 2018 Chad Page
    Copyright (C) 2018-2019 Simon Inns

    This file is part of ld-decode-tools.

    ld-comb-ntsc is free software: you can redistribute it and/or
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

#ifndef YIQBUFFER_H
#define YIQBUFFER_H

#include <array>
#include <vector>

#include "yiq.h"

using YiqLine = std::array<YIQ, 910>;

// A heap-allocated 2D array of YIQ pixels
class YiqBuffer
    : public std::vector<YiqLine>
{
public:
    YiqBuffer()
        : std::vector<YiqLine>(525)
    {
    }

    // Zero all pixels in the buffer
    void clear() {
        for (YiqLine &line: *this) {
            line.fill(YIQ());
        }
    }
};

#endif // YIQBUFFER_H
