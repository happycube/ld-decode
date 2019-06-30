/************************************************************************

    testfilter.cpp

    ld-comb-ntsc - NTSC colourisation filter for ld-decode
    Copyright (C) 2019 Adam Sampson

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

#include <cmath>
#include <cstdlib>
#include <iostream>

using std::cerr;

#include "iirfilter.h"
#include "filter.h"

#include "../../deemp.h"

// Check that two filters produce the same output given the same input.
template <typename FN, typename FO>
void test_filter(const char *name, FN& fn, FO& fo) {
    cerr << "Comparing filters: " << name << "\n";    

    for (int i = 0; i < 100; ++i) {
        double input = i - 40;
        double out_n = fn.feed(input);
        double out_o = fo.feed(input);
        if (fabs(out_n - out_o) > 0.000001) {
            cerr << "Mismatch on " << name << ": " << input << " -> " << out_n << ", " << out_o << "\n";
            exit(1);
        }
    }
}

int main(int argc, char *argv[]) {
    // Test with the sets of coefficients used in the code.

    IIRFilter<2, 2> f0(c_colorlpi_b, c_colorlpi_a);
    Filter g0(c_colorlpi_b, c_colorlpi_a);
    test_filter("colorlpi", f0, g0);

    IIRFilter<2, 2> f1(c_colorlpq_b, c_colorlpq_a);
    Filter g1(c_colorlpq_b, c_colorlpq_a);
    test_filter("colorlpq", f1, g1);

    IIRFilter<17, 1> f2(c_nrc_b, c_nrc_a);
    Filter g2(c_nrc_b, c_nrc_a);
    test_filter("nrc", f2, g2);

    IIRFilter<25, 1> f3(c_nr_b, c_nr_a);
    Filter g3(c_nr_b, c_nr_a);
    test_filter("nr", f3, g3);

    IIRFilter<5, 5> f4(c_a500_48k_b, c_a500_48k_a);
    Filter g4(c_a500_48k_b, c_a500_48k_a);
    test_filter("a500_48k", f4, g4);

    IIRFilter<5, 5> f5(c_a40h_48k_b, c_a40h_48k_a);
    Filter g5(c_a40h_48k_b, c_a40h_48k_a);
    test_filter("a40h_48k", f5, g5);

    return 0;
}
