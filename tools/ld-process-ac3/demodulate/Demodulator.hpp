/*******************************************************************************
 * Demodulator.hpp
 *
 * ld-process-ac3 - AC3-RF decoder
 * Copyright (C) 2022-2022 Leighton Smallshire & Ian Smallshire
 *
 * Derived from prior work by Staffan Ulfberg with feedback
 * to original author. (Copyright (C) 2021-2022)
 * https://bitbucket.org/staffanulfberg/ldaudio/src/master/
 *
 * This file is part of ld-decode-tools.
 *
 * ld-process-ac3 is free software: you can redistribute it and/or
 * modify it under the terms of the GNU General Public License as
 * published by the Free Software Foundation, either version 3 of the
 * License, or (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with this program.  If not, see <http://www.gnu.org/licenses/>.
 ******************************************************************************/

#pragma once

#include "Resampler.hpp"


template<class DATA_SRC>
struct Demodulator {
    static constexpr int compareIntervalSize = 16;
    static constexpr int cyclesPerSymbol = 10;
    static constexpr int samplesBetweenSymbols = compareIntervalSize * cyclesPerSymbol;
    static constexpr short buffer_size = (compareIntervalSize + samplesBetweenSymbols + samplesPerCarrierCycle) * 2;

    bool buffer[buffer_size]{};
    short buffer_pos = 0;
    DATA_SRC &source;

    explicit Demodulator(DATA_SRC &source) : source(source) {
        for (bool &i: buffer)
            i = source.next();
    }

    // ~90% of runtime spent here
    // __attribute__((optimize("unroll-loops")))

    // Votes on the value of a symbol from a window of samples
    char next() {
        int votes[2]{0, 0};
        buffer[buffer_pos] = source.next();
        buffer_pos = (buffer_pos + 1) % buffer_size;

        for (int j = 0; j < compareIntervalSize; ++j) {
            int ptmp = 320 - 1 + buffer_pos - j;
            const int p0 = ptmp % buffer_size;
            ptmp -= samplesBetweenSymbols;
            const int p1 = (ptmp - +0) % buffer_size;
            const int p2 = (ptmp - +4) % buffer_size;
            const int p3 = (ptmp - +8) % buffer_size;
            const int p4 = (ptmp - 12) % buffer_size;

            auto d0 = buffer[p0];
            votes[0] -= d0 ^ buffer[p1];
            votes[1] -= d0 ^ buffer[p2];
            votes[0] += d0 ^ buffer[p3];
            votes[1] += d0 ^ buffer[p4];
        }
        int &a = votes[0], &b = votes[1];

        char winner = (abs(a) > abs(b)) ? (a > 0 ? 0 : 3) : (b > 0 ? 1 : 2);
        return winner;
    }
};
