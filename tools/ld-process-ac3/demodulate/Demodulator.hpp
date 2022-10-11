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

#include <algorithm>

template<class DATA_SRC>
struct Demodulator {
    static constexpr int compareIntervalSize = 16;
    static constexpr int cyclesPerSymbol = 10;
    static constexpr int samplesBetweenSymbols = compareIntervalSize * cyclesPerSymbol;

    static constexpr int buffer_size = 1024;
    static constexpr int bufferPreload = samplesBetweenSymbols * 2;
    static_assert(buffer_size > bufferPreload, "buffer_size too small");

    int buffer[buffer_size];
    int buffer_pos;
    DATA_SRC &source;

    explicit Demodulator(DATA_SRC &source) : source(source) {
        // Load bufferPreload samples into buffer
        for (int i = 0; i < bufferPreload; i++)
            buffer[i] = source.next();
        buffer_pos = bufferPreload;
    }

    // Votes on the value of a symbol from a window of samples
    char next() {
        buffer[buffer_pos] = source.next();

        int sums[4] {0, 0, 0, 0};
        for (int ph = 0; ph < 4; ph++) {
            const int phase = ph * (samplesPerCarrierCycle / 4);
            int sum = 0;
            for (int j = 0; j < compareIntervalSize; j++) {
                sum += buffer[buffer_pos - j] ^ buffer[buffer_pos - j - samplesBetweenSymbols - phase];
            }
            sums[ph] = sum;
        }

        const int a = sums[2] - sums[0];
        const int b = sums[3] - sums[1];
        const char winner = (abs(a) > abs(b)) ? (a > 0 ? 0 : 3) : (b > 0 ? 1 : 2);

        buffer_pos++;

        // If the buffer is full, throw away all but the last bufferPreload samples
        if (buffer_pos == buffer_size) {
            std::copy(&buffer[buffer_size - bufferPreload], &buffer[buffer_size], buffer);
            buffer_pos = bufferPreload;
        }

        return winner;
    }
};
