/************************************************************************

    yiq.cpp

    ld-comb-ntsc - NTSC colourisation filter for ld-decode
    Copyright (C) 2018 Chad Page
    Copyright (C) 2018 Simon Inns

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

#include "yiq.h"

YIQ::YIQ(double _y, double _i, double _q)
{
    y = _y; i = _i; q = _q;
}

YIQ YIQ::operator*=(double x)
{
    YIQ o;

    o.y = this->y * x;
    o.i = this->i * x;
    o.q = this->q * x;

    return o;
}

YIQ YIQ::operator+=(YIQ p)
{
    YIQ o;

    o.y = this->y + p.y;
    o.i = this->i + p.i;
    o.q = this->q + p.q;

    return o;
}
