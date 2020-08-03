/************************************************************************

    yiq.h

    ld-chroma-decoder - Colourisation filter for ld-decode
    Copyright (C) 2018 Chad Page
    Copyright (C) 2018-2019 Simon Inns

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

#ifndef YIQ_H
#define YIQ_H

#include <QCoreApplication>

class YIQ
{
public:
    double y, i, q;

    YIQ(double y_ = 0.0, double i_ = 0.0, double q_ = 0.0)
        : y(y_), i(i_), q(q_) {}

    YIQ operator*=(double x) const {
        YIQ o;

        o.y = this->y * x;
        o.i = this->i * x;
        o.q = this->q * x;

        return o;
    }

    YIQ operator+=(const YIQ &p) const {
        YIQ o;

        o.y = this->y + p.y;
        o.i = this->i + p.i;
        o.q = this->q + p.q;

        return o;
    }
};

#endif // YIQ_H
