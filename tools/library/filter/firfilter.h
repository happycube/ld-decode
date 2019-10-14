/************************************************************************

    firfilter.h

    ld-decode-tools filter library
    Copyright (C) 2019 Adam Sampson

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

#ifndef FIRFILTER_H
#define FIRFILTER_H

#include <cassert>

// A FIR filter with arbitrary coefficients. The number of taps must be odd.
//
// Coeffs::value_type will be used to accumulate the results, so if you provide
// float coefficients, the filter will work at float precision internally.
template <typename Coeffs>
class FIRFilter
{
public:
    constexpr FIRFilter(const Coeffs &coeffs_)
        : coeffs(coeffs_)
    {
    }

    // Apply the filter to a range of input samples from inputData of length
    // numSamples, writing the result into outputData.
    //
    // Samples outside the range of the input are assumed to be 0.
    template <typename InputSample, typename OutputSample>
    void apply(const InputSample *inputData, OutputSample *outputData, int numSamples) const
    {
        const int numTaps = coeffs.size();

        for (int i = 0; i < numSamples; i++) {
            typename Coeffs::value_type v = 0;
            for (int j = 0, k = i - (numTaps / 2); j < numTaps; j++, k++) {
                if (k >= 0 && k < numSamples) {
                    v += coeffs[j] * inputData[k];
                }
            }
            outputData[i] = v;
        }
    }

    // Apply the filter to samples from container inputData, writing the result
    // into container outputData. The two containers must be the same size.
    template <typename InputContainer, typename OutputContainer>
    void apply(const InputContainer &inputData, OutputContainer &outputData) const
    {
        assert(inputData.size() == outputData.size());
        apply(inputData.data(), outputData.data(), inputData.size());
    }

    // Apply the filter to samples from container data, writing the result back
    // into the same container.
    template <typename Container>
    void apply(Container &data) const
    {
        Container tmp(data.size());
        apply(data, tmp);
        data = tmp;
    }

private:
    const Coeffs &coeffs;
};

// Helper for declaring FIRFilter instances with auto.
// e.g. constexpr auto myFilter = makeFIRFilter(myFilterCoeffs);
template <typename Coeffs>
constexpr FIRFilter<Coeffs> makeFIRFilter(const Coeffs &coeffs)
{
    return FIRFilter<Coeffs>(coeffs);
}

#endif
