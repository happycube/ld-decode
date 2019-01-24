/************************************************************************

    filter.h

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

#ifndef FILTER_H
#define FILTER_H

#include <QCoreApplication>
#include <QDebug>

#include <vector>

using namespace std;

class Filter
{
public:
    Filter(int _order, const double *_a, const double *_b);
    Filter(vector<double> _b, vector<double> _a);
    Filter(Filter *orig);
    void clear(double val = 0);
    void dump();
    double feed(double val);
    double val();

private:
    unsigned long order;
    bool isIIR;
    vector<double> a, b;
    vector<double> y, x;
};

#endif // FILTER_H
