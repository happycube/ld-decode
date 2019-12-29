/************************************************************************

    iirfilter.h

    ld-decode-tools filter library
    Copyright (C) 2018 Chad Page
    Copyright (C) 2018-2019 Simon Inns
    Copyright (C) 2019 Adam Sampson

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

#ifndef IIRFILTER_H
#define IIRFILTER_H

#include <cassert>
#include <array>
#include <vector>

// IIR or FIR filter
// b is feedforward (input), a is feedback (output -- 1 for a FIR filter).
template <unsigned bOrder, unsigned aOrder>
class IIRFilter
{
public:
    // Construct a filter from coefficients.
    template <typename BSrc, typename ASrc>
    IIRFilter(const BSrc &_b, const ASrc &_a) {
        assert(_a.size() == aOrder);
        assert(_b.size() == bOrder);

        // Normalise the coefficients against a[0]
        for (unsigned i = 0; i < aOrder; i++) {
            a[i] = _a[i] / _a[0];
        }
        for (unsigned i = 0; i < bOrder; i++) {
            b[i] = _b[i] / _a[0];
        }

        clear();
    }

    // Construct a filter as a copy of an existing one.
    // This is slightly cheaper than constructing it from scratch,
    // but note that it also copies the history of the filter.
    IIRFilter(const IIRFilter &) = default;

    void clear(double val = 0) {
        x.fill(val);
        y.fill(val);
    }

    // Feed a new input value into the filter, returning the new output value
    double feed(double val) {
        double y0 = b[0] * val;
        for (int i = bOrder - 1; i >= 1; i--) {
            x[i] = x[i - 1];
            y0 += b[i] * x[i];
        }
        x[0] = val;
        for (int i = aOrder - 1; i >= 1; i--) {
            y[i] = y[i - 1];
            y0 -= a[i] * y[i];
        }
        y[0] = y0;
        return y[0];
    }

private:
    // Feedforward (input) coefficients
    std::array<double, bOrder> b;
    // Feedback (output) coefficients
    std::array<double, aOrder> a;
    // History of input values
    std::array<double, bOrder> x;
    // History of output values
    std::array<double, aOrder> y;
};

#endif // IIRFILTER_H
